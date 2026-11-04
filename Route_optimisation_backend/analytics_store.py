import hashlib
import json
import logging
import math
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


logger = logging.getLogger(__name__)
UNASSIGNED_SAMPLE_VEHICLE_ID = "unassigned-sample"


def _database_path():
    configured = os.environ.get("ANALYTICS_DB_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parent / "data" / "operational_analytics.sqlite3"


@contextmanager
def _connect():
    path = _database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_analytics_store():
    with _connect() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS analytics_beats (
                beat_id TEXT PRIMARY KEY,
                beat_name TEXT,
                state TEXT,
                municipal_corporation TEXT,
                zone TEXT,
                ward TEXT,
                geofence TEXT
            );
            CREATE TABLE IF NOT EXISTS analytics_houses (
                beat_id TEXT NOT NULL,
                house_id TEXT NOT NULL,
                lat REAL,
                lon REAL,
                PRIMARY KEY (beat_id, house_id)
            );
            CREATE TABLE IF NOT EXISTS analytics_vehicles (
                vehicle_id TEXT PRIMARY KEY,
                vehicle_name TEXT,
                capacity_kg REAL
            );
            CREATE TABLE IF NOT EXISTS analytics_collections (
                collection_date TEXT NOT NULL,
                beat_id TEXT NOT NULL,
                house_id TEXT NOT NULL,
                vehicle_id TEXT,
                trip_id TEXT,
                covered INTEGER NOT NULL CHECK (covered IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS analytics_gps_points (
                point_id TEXT PRIMARY KEY,
                point_date TEXT NOT NULL,
                vehicle_id TEXT NOT NULL,
                beat_id TEXT,
                trip_id TEXT,
                timestamp TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS analytics_dump_weights (
                record_id TEXT PRIMARY KEY,
                dump_date TEXT NOT NULL,
                vehicle_id TEXT NOT NULL,
                beat_id TEXT,
                trip_id TEXT,
                weight_kg REAL NOT NULL CHECK (weight_kg >= 0),
                wet_weight_kg REAL CHECK (wet_weight_kg IS NULL OR wet_weight_kg > 0),
                dry_weight_kg REAL CHECK (dry_weight_kg IS NULL OR dry_weight_kg > 0),
                allocation_method TEXT NOT NULL CHECK (
                    allocation_method IN ('unknown', 'beat_direct', 'trip_total')
                )
            );
            CREATE TABLE IF NOT EXISTS analytics_collection_scans (
                scan_id TEXT PRIMARY KEY,
                scan_date TEXT NOT NULL,
                vehicle_id TEXT NOT NULL,
                trip_id TEXT,
                reference_id TEXT,
                timestamp TEXT,
                lat REAL,
                lon REAL
            );
            CREATE TABLE IF NOT EXISTS analytics_dump_events (
                dump_id TEXT PRIMARY KEY,
                dump_date TEXT NOT NULL,
                vehicle_id TEXT NOT NULL,
                trip_id TEXT,
                reference_id TEXT,
                timestamp TEXT,
                lat REAL,
                lon REAL,
                total_weight_raw REAL,
                wet_weight_raw REAL,
                dry_weight_raw REAL,
                weight_unit TEXT
            );
            CREATE TABLE IF NOT EXISTS analytics_house_locations (
                location_id TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                imported_at TEXT NOT NULL,
                UNIQUE(dataset_id, lat, lon)
            );
            CREATE INDEX IF NOT EXISTS idx_analytics_beats_location
                ON analytics_beats(state, municipal_corporation, zone, ward, beat_id);
            CREATE INDEX IF NOT EXISTS idx_analytics_collections_date
                ON analytics_collections(collection_date, beat_id, vehicle_id);
            CREATE INDEX IF NOT EXISTS idx_analytics_gps_date_vehicle
                ON analytics_gps_points(point_date, vehicle_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_analytics_weights_date_vehicle
                ON analytics_dump_weights(dump_date, vehicle_id, beat_id);
        """)
        columns = {
            row["name"] for row in connection.execute(
                "PRAGMA table_info(analytics_dump_weights)"
            ).fetchall()
        }
        for column in ("wet_weight_kg", "dry_weight_kg"):
            if column not in columns:
                connection.execute(
                    f"ALTER TABLE analytics_dump_weights ADD COLUMN {column} REAL"
                )
        collection_columns = connection.execute(
            "PRAGMA table_info(analytics_collections)"
        ).fetchall()
        collection_primary_key = [
            row["name"] for row in sorted(
                (column for column in collection_columns if column["pk"]),
                key=lambda column: column["pk"],
            )
        ]
        if collection_primary_key:
            connection.execute(
                "ALTER TABLE analytics_collections RENAME TO analytics_collections_legacy"
            )
            connection.execute("""
                CREATE TABLE analytics_collections (
                    collection_date TEXT NOT NULL,
                    beat_id TEXT NOT NULL,
                    house_id TEXT NOT NULL,
                    vehicle_id TEXT,
                    trip_id TEXT,
                    covered INTEGER NOT NULL CHECK (covered IN (0, 1))
                )
            """)
            connection.execute("""
                INSERT INTO analytics_collections
                    (collection_date, beat_id, house_id, vehicle_id, trip_id, covered)
                SELECT collection_date, beat_id, house_id, vehicle_id, trip_id, covered
                FROM analytics_collections_legacy
            """)
            connection.execute("DROP TABLE analytics_collections_legacy")
        connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_analytics_collections_identity
            ON analytics_collections(
                collection_date, beat_id, house_id, COALESCE(vehicle_id, '')
            )
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_analytics_collections_date
            ON analytics_collections(collection_date, beat_id, vehicle_id)
        """)


def _text(value):
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _parse_date(value, field):
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date in YYYY-MM-DD format.")
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date().isoformat()
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO date in YYYY-MM-DD format.") from error


def _parse_timestamp(value):
    if isinstance(value, (int, float)):
        epoch = value / 1000 if value > 10**12 else value
        return datetime.fromtimestamp(epoch).isoformat(timespec="seconds")
    if not isinstance(value, str):
        raise ValueError("GPS timestamp must be an ISO datetime or Unix timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("GPS timestamp must be an ISO datetime or Unix timestamp.") from error
    return parsed.isoformat(timespec="seconds")


def _coordinate(lat, lon, name):
    try:
        latitude = float(lat)
        longitude = float(lon)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must include numeric latitude and longitude.") from error
    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise ValueError(f"{name} has invalid latitude or longitude.")
    return latitude, longitude


def _normalize_geofence(beat):
    geofence = beat.get("geofence")
    if geofence is None:
        return None
    if not isinstance(geofence, str):
        raise ValueError("Beat geofence must be a semicolon-separated `lat,lon` string.")
    coordinates = []
    try:
        for pair in geofence.split(";"):
            lat, lon = pair.split(",")
            latitude, longitude = _coordinate(lat, lon, "Beat geofence")
            coordinates.append((latitude, longitude))
    except (ValueError, TypeError) as error:
        raise ValueError("Beat geofence must contain valid `lat,lon` coordinate pairs.") from error
    if len(coordinates) < 3:
        raise ValueError("Beat geofence must contain at least three coordinates.")
    return ";".join(f"{lat},{lon}" for lat, lon in coordinates)


def _weight_kg(weight, unit):
    try:
        value = float(weight)
    except (TypeError, ValueError) as error:
        raise ValueError("Dump weight must be a non-negative number.") from error
    if not math.isfinite(value) or value < 0:
        raise ValueError("Dump weight must be a non-negative number.")
    normalized_unit = str(unit or "").strip().lower()
    if normalized_unit in {"kg", "kilogram", "kilograms"}:
        return value
    if normalized_unit in {"tonne", "tonnes", "metric_ton", "metric_tons", "t"}:
        return value * 1000
    raise ValueError("Dump weight unit must be `kg` or `tonnes`.")


def _stable_id(record):
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def import_operational_records(payload):
    if not isinstance(payload, dict):
        raise ValueError("Upload a JSON object containing operational record arrays.")
    if (
        isinstance(payload.get("geofence"), str)
        and isinstance(payload.get("houses"), list)
        and isinstance(payload.get("routes"), list)
    ):
        return _import_combined_route_export(payload)
    allowed = {
        "beats", "houses", "vehicles", "collection_records",
        "gps_points", "gps_routes", "dumping_weights", "collection_scans",
        "dump_events", "house_coordinates",
    }
    if not any(key in payload for key in allowed):
        raise ValueError("No supported operational record arrays were supplied.")
    records = {}
    rejected = {key: 0 for key in allowed}
    for key in allowed:
        value = payload.get(key, [])
        if not isinstance(value, list):
            raise ValueError(f"`{key}` must be an array.")
        records[key] = value
    if not any(records.values()):
        raise ValueError("The uploaded operational record arrays are empty.")
    counts = {key: 0 for key in allowed}
    initialize_analytics_store()

    with _connect() as connection:
        for record in records["beats"]:
            if not isinstance(record, dict):
                rejected["beats"] += 1
                continue
            beat_id = _text(record.get("beat_id"))
            if not beat_id:
                rejected["beats"] += 1
                continue
            geofence = _normalize_geofence(record)
            connection.execute(
                """INSERT INTO analytics_beats
                   (beat_id, beat_name, state, municipal_corporation, zone, ward, geofence)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(beat_id) DO UPDATE SET
                    beat_name=COALESCE(excluded.beat_name, analytics_beats.beat_name),
                    state=COALESCE(excluded.state, analytics_beats.state),
                    municipal_corporation=COALESCE(excluded.municipal_corporation, analytics_beats.municipal_corporation),
                    zone=COALESCE(excluded.zone, analytics_beats.zone),
                    ward=COALESCE(excluded.ward, analytics_beats.ward),
                    geofence=COALESCE(excluded.geofence, analytics_beats.geofence)""",
                (
                    beat_id, _text(record.get("beat_name")), _text(record.get("state")),
                    _text(record.get("municipal_corporation")), _text(record.get("zone")),
                    _text(record.get("ward")), geofence,
                ),
            )
            counts["beats"] += 1

        for record in records["houses"]:
            if not isinstance(record, dict):
                rejected["houses"] += 1
                continue
            beat_id = _text(record.get("beat_id"))
            house_id = _text(record.get("house_id"))
            if not beat_id or not house_id:
                rejected["houses"] += 1
                continue
            if record.get("lat") is None and record.get("lon") is None:
                lat = lon = None
            else:
                lat, lon = _coordinate(record.get("lat"), record.get("lon"), "House")
            connection.execute(
                """INSERT INTO analytics_houses (beat_id, house_id, lat, lon)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(beat_id, house_id) DO UPDATE SET
                    lat=COALESCE(excluded.lat, analytics_houses.lat),
                    lon=COALESCE(excluded.lon, analytics_houses.lon)""",
                (beat_id, house_id, lat, lon),
            )
            counts["houses"] += 1

        for record in records["vehicles"]:
            if not isinstance(record, dict):
                rejected["vehicles"] += 1
                continue
            vehicle_id = _text(record.get("vehicle_id"))
            if not vehicle_id:
                rejected["vehicles"] += 1
                continue
            capacity = record.get("capacity_kg")
            if capacity is not None:
                try:
                    capacity = float(capacity)
                except (TypeError, ValueError) as error:
                    raise ValueError("Vehicle capacity must be a positive number or unknown.") from error
                if not math.isfinite(capacity) or capacity <= 0:
                    raise ValueError("Vehicle capacity must be a positive number or unknown.")
            connection.execute(
                """INSERT INTO analytics_vehicles (vehicle_id, vehicle_name, capacity_kg)
                   VALUES (?, ?, ?)
                   ON CONFLICT(vehicle_id) DO UPDATE SET
                    vehicle_name=COALESCE(excluded.vehicle_name, analytics_vehicles.vehicle_name),
                    capacity_kg=COALESCE(excluded.capacity_kg, analytics_vehicles.capacity_kg)""",
                (vehicle_id, _text(record.get("vehicle_name")), capacity),
            )
            counts["vehicles"] += 1

        for record in records["collection_records"]:
            if not isinstance(record, dict):
                rejected["collection_records"] += 1
                continue
            beat_id = _text(record.get("beat_id"))
            house_id = _text(record.get("house_id"))
            vehicle_id = _text(record.get("vehicle_id"))
            if not beat_id or not house_id or not record.get("date"):
                rejected["collection_records"] += 1
                continue
            date = _parse_date(record["date"], "Collection date")
            covered = record.get("covered")
            if not isinstance(covered, bool):
                rejected["collection_records"] += 1
                continue
            connection.execute(
                """INSERT INTO analytics_collections
                   (collection_date, beat_id, house_id, vehicle_id, trip_id, covered)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT DO UPDATE SET
                    vehicle_id=COALESCE(excluded.vehicle_id, analytics_collections.vehicle_id),
                    trip_id=COALESCE(excluded.trip_id, analytics_collections.trip_id),
                    covered=excluded.covered""",
                (
                    date, beat_id, house_id, vehicle_id, _text(record.get("trip_id")),
                    int(covered),
                ),
            )
            counts["collection_records"] += 1

        gps_records = list(records["gps_points"])
        for route in records["gps_routes"]:
            if not isinstance(route, dict):
                rejected["gps_routes"] += 1
                continue
            points = route.get("emproute", route.get("track_points"))
            if not isinstance(points, list):
                rejected["gps_routes"] += 1
                continue
            for point in points:
                if not isinstance(point, dict):
                    rejected["gps_points"] += 1
                    continue
                gps_records.append({
                    **point,
                    "vehicle_id": route.get("vehicle_id"),
                    "beat_id": route.get("beat_id"),
                    "trip_id": route.get("trip_id"),
                })
        for record in gps_records:
            if not isinstance(record, dict):
                rejected["gps_points"] += 1
                continue
            vehicle_id = _text(record.get("vehicle_id"))
            timestamp_value = record.get("timestamp", record.get("datetime"))
            if not vehicle_id or timestamp_value is None:
                rejected["gps_points"] += 1
                continue
            timestamp = _parse_timestamp(timestamp_value)
            lat, lon = _coordinate(record.get("lat"), record.get("lon", record.get("lng")), "GPS point")
            point_date = timestamp[:10]
            identity = {
                "vehicle_id": vehicle_id,
                "beat_id": _text(record.get("beat_id")),
                "timestamp": timestamp,
                "lat": round(lat, 7),
                "lon": round(lon, 7),
                "trip_id": _text(record.get("trip_id")),
            }
            inserted = connection.execute(
                """INSERT OR IGNORE INTO analytics_gps_points
                   (point_id, point_date, vehicle_id, beat_id, trip_id, timestamp, lat, lon)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    _stable_id(identity), point_date, vehicle_id, _text(record.get("beat_id")),
                    _text(record.get("trip_id")), timestamp, lat, lon,
                ),
            )
            counts["gps_points"] += inserted.rowcount

        for record in records["dumping_weights"]:
            if not isinstance(record, dict):
                rejected["dumping_weights"] += 1
                continue
            vehicle_id = _text(record.get("vehicle_id"))
            if not vehicle_id or not record.get("date"):
                rejected["dumping_weights"] += 1
                continue
            date = _parse_date(record["date"], "Dump date")
            unit = record.get("unit")
            wet_raw = record.get("wet_weight")
            dry_raw = record.get("dry_weight")
            wet_weight = (
                _weight_kg(wet_raw, record.get("wet_unit") or unit)
                if wet_raw not in (None, "")
                else None
            )
            dry_weight = (
                _weight_kg(dry_raw, record.get("dry_unit") or unit)
                if dry_raw not in (None, "")
                else None
            )
            # Zero values are not evidence of collected waste.
            wet_weight = wet_weight if wet_weight and wet_weight > 0 else None
            dry_weight = dry_weight if dry_weight and dry_weight > 0 else None
            total_raw = record.get("weight", record.get("total_weight"))
            if total_raw in (None, ""):
                if wet_weight is None or dry_weight is None:
                    rejected["dumping_weights"] += 1
                    continue
                weight = wet_weight + dry_weight
            else:
                weight = _weight_kg(total_raw, unit)
            if weight <= 0:
                rejected["dumping_weights"] += 1
                continue
            method = _text(record.get("allocation_method")) or "unknown"
            if method not in {"unknown", "beat_direct", "trip_total"}:
                raise ValueError("Weight allocation_method must be unknown, beat_direct, or trip_total.")
            identity = {
                "date": date,
                "vehicle_id": vehicle_id,
                "beat_id": _text(record.get("beat_id")),
                "trip_id": _text(record.get("trip_id")),
                "weight_kg": round(weight, 6),
                "wet_weight_kg": round(wet_weight, 6) if wet_weight is not None else None,
                "dry_weight_kg": round(dry_weight, 6) if dry_weight is not None else None,
                "method": method,
            }
            record_id = _text(record.get("record_id") or record.get("dumping_id"))
            if not record_id:
                record_id = _stable_id(identity)
            connection.execute(
                """INSERT INTO analytics_dump_weights
                   (record_id, dump_date, vehicle_id, beat_id, trip_id, weight_kg,
                    wet_weight_kg, dry_weight_kg, allocation_method)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(record_id) DO UPDATE SET
                    dump_date=excluded.dump_date, vehicle_id=excluded.vehicle_id,
                    beat_id=excluded.beat_id, trip_id=excluded.trip_id,
                    weight_kg=excluded.weight_kg, wet_weight_kg=excluded.wet_weight_kg,
                    dry_weight_kg=excluded.dry_weight_kg,
                    allocation_method=excluded.allocation_method""",
                (
                    record_id, date, vehicle_id, identity["beat_id"],
                    identity["trip_id"], weight, wet_weight, dry_weight, method,
                ),
            )
            counts["dumping_weights"] += 1

        for record in records["collection_scans"]:
            if not isinstance(record, dict):
                rejected["collection_scans"] += 1
                continue
            vehicle_id = _text(record.get("vehicle_id"))
            date_value = record.get("date")
            if not vehicle_id or not date_value:
                rejected["collection_scans"] += 1
                continue
            date = _parse_date(date_value, "Collection scan date")
            reference_id = _text(record.get("reference_id"))
            timestamp = (
                _parse_timestamp(record["timestamp"])
                if record.get("timestamp") else None
            )
            lat = lon = None
            if record.get("lat") is not None or record.get("lon") is not None:
                lat, lon = _coordinate(record.get("lat"), record.get("lon"), "Collection scan")
            if not reference_id and lat is None:
                rejected["collection_scans"] += 1
                continue
            identity = {
                "date": date,
                "vehicle_id": vehicle_id,
                "trip_id": _text(record.get("trip_id")),
                "reference_id": reference_id,
                "timestamp": timestamp,
                "lat": lat,
                "lon": lon,
            }
            scan_id = _text(record.get("scan_id")) or _stable_id(identity)
            connection.execute(
                """INSERT INTO analytics_collection_scans
                   (scan_id, scan_date, vehicle_id, trip_id, reference_id, timestamp, lat, lon)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(scan_id) DO UPDATE SET
                    scan_date=excluded.scan_date, vehicle_id=excluded.vehicle_id,
                    trip_id=excluded.trip_id, reference_id=excluded.reference_id,
                    timestamp=excluded.timestamp, lat=excluded.lat, lon=excluded.lon""",
                (
                    scan_id, date, vehicle_id, identity["trip_id"], reference_id,
                    timestamp, lat, lon,
                ),
            )
            counts["collection_scans"] += 1

        for record in records["dump_events"]:
            if not isinstance(record, dict):
                rejected["dump_events"] += 1
                continue
            vehicle_id = _text(record.get("vehicle_id"))
            date_value = record.get("date")
            if not vehicle_id or not date_value:
                rejected["dump_events"] += 1
                continue
            timestamp = (
                _parse_timestamp(record["timestamp"])
                if record.get("timestamp") else None
            )
            date = _parse_date(
                timestamp[:10] if timestamp else date_value,
                "Dump date",
            )
            lat = lon = None
            if record.get("lat") is not None or record.get("lon") is not None:
                lat, lon = _coordinate(record.get("lat"), record.get("lon"), "Dump location")
            raw_weights = []
            for field in ("total_weight", "wet_weight", "dry_weight"):
                value = record.get(field)
                try:
                    value = float(value) if value not in (None, "") else None
                except (TypeError, ValueError):
                    value = None
                if value is not None and not math.isfinite(value):
                    value = None
                raw_weights.append(value)
            identity = {
                "date": date,
                "vehicle_id": vehicle_id,
                "trip_id": _text(record.get("trip_id")),
                "reference_id": _text(record.get("reference_id")),
                "timestamp": timestamp,
                "lat": lat,
                "lon": lon,
                "weights": raw_weights,
                "unit": _text(record.get("weight_unit")),
            }
            dump_id = _text(record.get("dump_id")) or _stable_id(identity)
            connection.execute(
                """INSERT INTO analytics_dump_events
                   (dump_id, dump_date, vehicle_id, trip_id, reference_id, timestamp,
                    lat, lon, total_weight_raw, wet_weight_raw, dry_weight_raw, weight_unit)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(dump_id) DO UPDATE SET
                    dump_date=excluded.dump_date, vehicle_id=excluded.vehicle_id,
                    trip_id=excluded.trip_id, reference_id=excluded.reference_id,
                    timestamp=excluded.timestamp, lat=excluded.lat, lon=excluded.lon,
                    total_weight_raw=excluded.total_weight_raw,
                    wet_weight_raw=excluded.wet_weight_raw,
                    dry_weight_raw=excluded.dry_weight_raw,
                    weight_unit=excluded.weight_unit""",
                (
                    dump_id, date, vehicle_id, identity["trip_id"],
                    identity["reference_id"], timestamp, lat, lon,
                    *raw_weights, identity["unit"],
                ),
            )
            counts["dump_events"] += 1

        for record in records["house_coordinates"]:
            if not isinstance(record, dict):
                rejected["house_coordinates"] += 1
                continue
            dataset_id = _text(record.get("dataset_id"))
            if not dataset_id:
                rejected["house_coordinates"] += 1
                continue
            lat, lon = _coordinate(record.get("lat"), record.get("lon"), "House coordinate")
            coordinate = (round(lat, 7), round(lon, 7))
            location_id = _stable_id({
                "dataset_id": dataset_id,
                "lat": coordinate[0],
                "lon": coordinate[1],
            })
            connection.execute(
                """INSERT INTO analytics_house_locations
                   (location_id, dataset_id, lat, lon, imported_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(dataset_id, lat, lon) DO UPDATE SET
                    imported_at=excluded.imported_at""",
                (
                    location_id, dataset_id, *coordinate,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            counts["house_coordinates"] += 1

    return {
        "status": "success",
        "upserted": counts,
        "rejected": rejected,
        "message": "Valid operational records were merged into the analytics database; no sample records were created.",
    }


def _import_combined_route_export(payload):
    vehicle_id = _text(payload.get("vehicle_id")) or UNASSIGNED_SAMPLE_VEHICLE_ID
    routes = payload["routes"]
    if not all(isinstance(route, dict) for route in routes):
        raise ValueError("Every combined route entry must be an object.")

    gps_routes = []
    collection_scans = []
    dump_events = []
    for route_index, route in enumerate(routes):
        date = route.get("date")
        if not date:
            raise ValueError(f"Combined route {route_index + 1} has no date.")
        points = route.get("emproute", [])
        if not isinstance(points, list):
            raise ValueError(f"Combined route {route_index + 1} has invalid emproute data.")
        gps_routes.append({
            "date": date,
            "vehicle_id": vehicle_id,
            "trip_id": str(date),
            "emproute": points,
        })
        scans = route.get("Collectionlist", route.get("collectionList", []))
        if not isinstance(scans, list):
            raise ValueError(f"Combined route {route_index + 1} has invalid Collectionlist data.")
        for scan_index, scan in enumerate(scans):
            if not isinstance(scan, dict):
                collection_scans.append(scan)
                continue
            timestamp = scan.get("datetime")
            collection_scans.append({
                "scan_id": _stable_id({
                    "employee_id": vehicle_id,
                    "route_date": date,
                    "route_index": route_index,
                    "scan_index": scan_index,
                    "scan": scan,
                }),
                "date": str(timestamp)[:10] if timestamp else date,
                "vehicle_id": vehicle_id,
                "trip_id": str(date),
                "reference_id": scan.get("referanceId", scan.get("referenceId")),
                "timestamp": timestamp,
                "lat": scan.get("lat"),
                "lon": scan.get("lon", scan.get("lng")),
            })
        dumps = route.get("dumplist", [])
        if not isinstance(dumps, list):
            raise ValueError(f"Combined route {route_index + 1} has invalid dumplist data.")
        for dump_index, dump in enumerate(dumps):
            if not isinstance(dump, dict):
                dump_events.append(dump)
                continue
            timestamp = dump.get("datetime")
            dump_events.append({
                "dump_id": _stable_id({
                    "employee_id": vehicle_id,
                    "route_date": date,
                    "route_index": route_index,
                    "dump_index": dump_index,
                    "dump": dump,
                }),
                "date": str(timestamp)[:10] if timestamp else date,
                "vehicle_id": vehicle_id,
                "trip_id": str(date),
                "reference_id": dump.get("referanceId", dump.get("referenceId")),
                "timestamp": timestamp,
                "lat": dump.get("lat"),
                "lon": dump.get("lon", dump.get("lng")),
                "total_weight": dump.get("totalGcWeight"),
                "wet_weight": dump.get("totalWetWeight"),
                "dry_weight": dump.get("totalDryWeight"),
                "weight_unit": dump.get("weightUnit", dump.get("unit", payload.get("weight_unit"))),
            })

    geofence = payload["geofence"]
    dataset_id = _stable_id({"geofence": geofence})
    beat_id = f"combined-{dataset_id[:24]}"
    house_coordinates = [
        {
            "dataset_id": dataset_id,
            "lat": house.get("lat"),
            "lon": house.get("lon"),
        }
        for house in payload["houses"]
        if isinstance(house, dict)
    ]
    identified_house_locations = {}
    for house in payload["houses"]:
        if not isinstance(house, dict):
            continue
        house_id = _text(
            house.get("house_id") or house.get("House_Id") or house.get("houseId")
        )
        if not house_id or house.get("lat") is None or house.get("lon") is None:
            continue
        lat, lon = _coordinate(house.get("lat"), house.get("lon"), "House")
        identified_house_locations.setdefault(house_id, set()).add(
            (round(lat, 7), round(lon, 7))
        )
    identified_houses = [
        {
            "beat_id": beat_id,
            "house_id": house_id,
            "lat": next(iter(coordinates))[0],
            "lon": next(iter(coordinates))[1],
        }
        for house_id, coordinates in identified_house_locations.items()
        if len(coordinates) == 1
    ]

    canonical = import_operational_records({
        "beats": [{
            "beat_id": beat_id,
            "beat_name": _text(payload.get("beat_name")) or "Imported beat boundary",
            "geofence": geofence,
        }],
        "houses": identified_houses,
        "gps_routes": gps_routes,
        "collection_scans": collection_scans,
        "dump_events": dump_events,
        "house_coordinates": house_coordinates,
    })
    house_ids = sum(
        1 for house in payload["houses"]
        if isinstance(house, dict) and _text(
            house.get("house_id") or house.get("houseId") or house.get("House_Id")
        )
    )
    nonzero_dump_weights = 0
    for record in dump_events:
        if not isinstance(record, dict):
            continue
        values = (record.get("wet_weight"), record.get("dry_weight"), record.get("total_weight"))
        try:
            if any(value not in (None, "") and float(value) > 0 for value in values):
                nonzero_dump_weights += 1
        except (TypeError, ValueError):
            continue
    canonical["format"] = "combined_route_export"
    date_mismatches = {"gps_points": 0, "collection_scans": 0, "dump_records": 0}
    for route in routes:
        route_date = str(route["date"])[:10]
        for records, key in (
            (route.get("emproute", []), "gps_points"),
            (route.get("Collectionlist", route.get("collectionList", [])), "collection_scans"),
            (route.get("dumplist", []), "dump_records"),
        ):
            for record in records or []:
                timestamp = record.get("datetime") if isinstance(record, dict) else None
                if timestamp and str(timestamp)[:10] != route_date:
                    date_mismatches[key] += 1
    canonical["source_summary"] = {
        "house_coordinates": len(payload["houses"]),
        "houses_with_explicit_ids": house_ids,
        "houses_linked_to_ids_and_coordinates": len(identified_houses),
        "houses_with_ambiguous_id_coordinates": sum(
            1 for coordinates in identified_house_locations.values()
            if len(coordinates) > 1
        ),
        "gps_points": sum(len(route["emproute"]) for route in gps_routes),
        "collection_scans": len(collection_scans),
        "dump_records": len(dump_events),
        "dump_records_with_positive_weights": nonzero_dump_weights,
        "house_coordinates_imported_as_identified_houses": len(identified_houses),
        "unique_house_coordinates": len({
            (round(float(house["lat"]), 7), round(float(house["lon"]), 7))
            for house in house_coordinates
            if house["lat"] is not None and house["lon"] is not None
        }),
        "vehicle_id_provided": vehicle_id != UNASSIGNED_SAMPLE_VEHICLE_ID,
        "timestamp_date_mismatches": date_mismatches,
    }
    vehicle_note = (
        " The data is grouped under 'Unassigned (sample/testing)', not a real vehicle."
        if vehicle_id == UNASSIGNED_SAMPLE_VEHICLE_ID else ""
    )
    canonical["message"] = (
        "Combined route data imported: GPS points and raw collection scan observations were saved. "
        "Coordinate-only houses were not assigned invented house IDs; collection scans were not counted as house collections. "
        "Dump weights were not added because this file's weight units/values are not verified."
        f"{vehicle_note}"
    )
    return canonical


def _filters(connection):
    def values(column, table="analytics_beats"):
        return [
            row[0] for row in connection.execute(
                f"SELECT DISTINCT {column} FROM {table} "
                f"WHERE {column} IS NOT NULL AND TRIM({column}) != '' ORDER BY {column}"
            ).fetchall()
        ]

    vehicles = {row[0] for row in connection.execute(
        "SELECT vehicle_id FROM analytics_vehicles"
    ).fetchall()}
    for table in (
        "analytics_collections",
        "analytics_gps_points",
        "analytics_dump_weights",
        "analytics_collection_scans",
        "analytics_dump_events",
    ):
        vehicles.update(row[0] for row in connection.execute(
            f"SELECT DISTINCT vehicle_id FROM {table} WHERE vehicle_id IS NOT NULL"
        ).fetchall())
    return {
        "state": values("state"),
        "municipal_corporation": values("municipal_corporation"),
        "zone": values("zone"),
        "ward": values("ward"),
        "beat_id": values("beat_id"),
        "vehicle_id": sorted(vehicles),
    }


def _date_clause(column, start_date, end_date):
    clause = []
    params = []
    if start_date:
        clause.append(f"{column} >= ?")
        params.append(start_date)
    if end_date:
        clause.append(f"{column} <= ?")
        params.append(end_date)
    return (" AND ".join(clause) if clause else "1=1"), params


def _scope_clause(filters, alias="b"):
    clauses = []
    params = []
    for key, column in (
        ("state", "state"),
        ("municipal_corporation", "municipal_corporation"),
        ("zone", "zone"),
        ("ward", "ward"),
        ("beat_id", "beat_id"),
    ):
        value = filters.get(key)
        if value:
            clauses.append(f"{alias}.{column} = ?")
            params.append(value)
    return (" AND ".join(clauses) if clauses else "1=1"), params


def _haversine_m(first, second):
    from math import asin, cos, radians, sin, sqrt

    lat1, lon1 = first
    lat2, lon2 = second
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    value = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 12742000 * asin(sqrt(min(1, value)))


def _elapsed_seconds(first_timestamp, second_timestamp):
    first = datetime.fromisoformat(first_timestamp)
    second = datetime.fromisoformat(second_timestamp)
    if first.tzinfo is None and second.tzinfo is not None:
        first = first.replace(tzinfo=second.tzinfo)
    elif first.tzinfo is not None and second.tzinfo is None:
        second = second.replace(tzinfo=first.tzinfo)
    return (second - first).total_seconds()


def _gps_vehicle_metrics(connection, date_where, date_params, filters):
    sql = f"""
        SELECT g.point_date, g.vehicle_id, g.beat_id, g.trip_id, g.timestamp, g.lat, g.lon
        FROM analytics_gps_points g
        LEFT JOIN analytics_beats b ON b.beat_id = g.beat_id
        WHERE {date_where}
    """
    params = list(date_params)
    for key, column in (
        ("state", "state"),
        ("municipal_corporation", "municipal_corporation"),
        ("zone", "zone"),
        ("ward", "ward"),
        ("beat_id", "beat_id"),
    ):
        if filters.get(key):
            sql += f" AND b.{column} = ?"
            params.append(filters[key])
    if filters.get("vehicle_id"):
        sql += " AND g.vehicle_id = ?"
        params.append(filters["vehicle_id"])
    sql += " ORDER BY g.vehicle_id, g.point_date, COALESCE(g.trip_id, ''), g.timestamp"
    grouped = {}
    invalid_intervals = 0
    cursor = connection.execute(sql, params)
    active_key = None
    previous = None

    def start_group(row):
        key = (row["vehicle_id"], row["point_date"], row["trip_id"] or "")
        grouped.setdefault(key[0], {"distance_m": 0.0, "operating_seconds": 0, "gps_points": 0})
        return key

    for row in cursor:
        key = start_group(row)
        grouped[key[0]]["gps_points"] += 1
        if key != active_key:
            active_key = key
            previous = row
            continue
        elapsed = _elapsed_seconds(previous["timestamp"], row["timestamp"])
        distance = _haversine_m((previous["lat"], previous["lon"]), (row["lat"], row["lon"]))
        if elapsed <= 0 or elapsed > 900 or distance / elapsed * 3.6 > 120:
            invalid_intervals += 1
            previous = row
            continue
        grouped[key[0]]["distance_m"] += distance
        grouped[key[0]]["operating_seconds"] += elapsed
        previous = row
    return grouped, invalid_intervals


def _daily_gps_metrics(connection, start_date, end_date, filters):
    date_where, params = _date_clause("point_date", start_date, end_date)
    sql = f"""
        SELECT point_date, vehicle_id, trip_id, timestamp, lat, lon
        FROM analytics_gps_points
        WHERE {date_where}
    """
    if filters.get("vehicle_id"):
        sql += " AND vehicle_id = ?"
        params.append(filters["vehicle_id"])
    sql += " ORDER BY point_date, vehicle_id, COALESCE(trip_id, ''), timestamp"
    trips = {}
    for row in connection.execute(sql, params).fetchall():
        key = (row["point_date"], row["vehicle_id"], row["trip_id"] or "")
        trips.setdefault(key, []).append(row)

    daily = {}
    invalid_intervals = 0
    for (date, _, _), points in trips.items():
        seen = set()
        distinct_points = []
        for point in points:
            identity = (
                point["timestamp"],
                round(float(point["lat"]), 7),
                round(float(point["lon"]), 7),
            )
            if identity in seen:
                continue
            seen.add(identity)
            distinct_points.append(point)
        item = daily.setdefault(date, {
            "distance_m": 0.0,
            "valid_intervals": 0,
            "operating_seconds": 0,
            "gps_points": 0,
        })
        item["gps_points"] += len(distinct_points)
        for previous, current in zip(distinct_points, distinct_points[1:]):
            elapsed = _elapsed_seconds(previous["timestamp"], current["timestamp"])
            distance = _haversine_m(
                (previous["lat"], previous["lon"]),
                (current["lat"], current["lon"]),
            )
            if elapsed <= 0 or elapsed > 900 or distance / elapsed * 3.6 > 120:
                invalid_intervals += 1
                continue
            item["distance_m"] += distance
            item["valid_intervals"] += 1
            item["operating_seconds"] += elapsed
    return daily, invalid_intervals


def _daily_time_metrics(connection, start_date, end_date, filters):
    vehicle_id = filters.get("vehicle_id")
    gps_where, gps_params = _date_clause("point_date", start_date, end_date)
    gps_sql = f"""
        SELECT point_date, vehicle_id, trip_id, timestamp, lat, lon
        FROM analytics_gps_points
        WHERE {gps_where}
    """
    if vehicle_id:
        gps_sql += " AND vehicle_id = ?"
        gps_params.append(vehicle_id)
    gps_rows = connection.execute(
        gps_sql + " ORDER BY point_date, vehicle_id, COALESCE(trip_id, ''), timestamp",
        gps_params,
    ).fetchall()
    gps_by_day_employee = {}
    seen_gps = set()
    for row in gps_rows:
        identity = (
            row["point_date"], row["vehicle_id"], row["trip_id"],
            row["timestamp"], round(float(row["lat"]), 7), round(float(row["lon"]), 7),
        )
        if identity in seen_gps:
            continue
        seen_gps.add(identity)
        key = (row["point_date"], row["vehicle_id"], row["trip_id"])
        gps_by_day_employee.setdefault(key, []).append(row)

    gps_distance_by_day = {}
    for (date, employee, _), points in gps_by_day_employee.items():
        points.sort(key=lambda point: datetime.fromisoformat(
            point["timestamp"]
        ).timestamp())
        key = (date, employee)
        distance_m, valid_intervals = gps_distance_by_day.get(key, (0.0, 0))
        for previous, current in zip(points, points[1:]):
            elapsed = _elapsed_seconds(previous["timestamp"], current["timestamp"])
            distance = _haversine_m(
                (float(previous["lat"]), float(previous["lon"])),
                (float(current["lat"]), float(current["lon"])),
            )
            if elapsed > 0 and elapsed <= 900 and distance / elapsed * 3.6 <= 120:
                distance_m += distance
                valid_intervals += 1
        gps_distance_by_day[key] = (distance_m, valid_intervals)

    scan_where, scan_params = _date_clause("scan_date", start_date, end_date)
    scan_sql = f"""
        SELECT scan_date, vehicle_id, reference_id, timestamp
        FROM analytics_collection_scans
        WHERE {scan_where}
    """
    if vehicle_id:
        scan_sql += " AND vehicle_id = ?"
        scan_params.append(vehicle_id)
    scan_rows = connection.execute(
        scan_sql + " ORDER BY scan_date, vehicle_id, COALESCE(timestamp, ''), reference_id",
        scan_params,
    ).fetchall()
    collections_by_day_employee = {}
    for row in scan_rows:
        if not row["reference_id"]:
            continue
        key = (row["scan_date"], row["vehicle_id"])
        references = collections_by_day_employee.setdefault(key, {})
        timestamp = row["timestamp"]
        previous = references.get(row["reference_id"])
        if previous is None or (
            timestamp and (
                not previous or _elapsed_seconds(timestamp, previous) > 0
            )
        ):
            references[row["reference_id"]] = timestamp

    house_ids_by_day_employee = {
        key: set(references) for key, references in collections_by_day_employee.items()
    }
    collection_where, collection_params = _date_clause(
        "collection_date", start_date, end_date
    )
    collection_sql = f"""
        SELECT collection_date, vehicle_id, house_id
        FROM analytics_collections
        WHERE {collection_where} AND covered = 1
    """
    if vehicle_id:
        collection_sql += " AND vehicle_id = ?"
        collection_params.append(vehicle_id)
    for row in connection.execute(collection_sql, collection_params):
        key = (row["collection_date"], row["vehicle_id"])
        house_ids_by_day_employee.setdefault(key, set()).add(row["house_id"])

    gps_by_day = {}
    gps_observed_by_day = {}
    for (date, employee, _), points in gps_by_day_employee.items():
        key = (date, employee)
        gps_by_day.setdefault(key, []).extend(points)
        points.sort(key=lambda point: datetime.fromisoformat(
            point["timestamp"]
        ).timestamp())
        observed_seconds, valid_intervals = gps_observed_by_day.get(key, (0, 0))
        for previous, current in zip(points, points[1:]):
            elapsed = _elapsed_seconds(previous["timestamp"], current["timestamp"])
            distance = _haversine_m(
                (float(previous["lat"]), float(previous["lon"])),
                (float(current["lat"]), float(current["lon"])),
            )
            if elapsed > 0 and elapsed <= 900 and distance / elapsed * 3.6 <= 120:
                observed_seconds += elapsed
                valid_intervals += 1
        gps_observed_by_day[key] = (observed_seconds, valid_intervals)

    rows = []
    all_intervals = []
    for date, employee in sorted(set(gps_by_day) | set(collections_by_day_employee)):
        gps_points = gps_by_day.get((date, employee), [])
        gps_points.sort(key=lambda point: datetime.fromisoformat(
            point["timestamp"]
        ).timestamp())
        gps_first = gps_points[0]["timestamp"] if gps_points else None
        gps_last = gps_points[-1]["timestamp"] if gps_points else None
        gps_span_seconds = (
            max(0, _elapsed_seconds(gps_first, gps_last))
            if len(gps_points) > 1 else None
        )
        gps_observed_seconds, valid_gps_intervals = gps_observed_by_day.get(
            (date, employee), (0, 0)
        )

        reference_times = collections_by_day_employee.get((date, employee), {})
        timed_references = []
        for reference_id, timestamp in reference_times.items():
            if not timestamp:
                continue
            timed_references.append((datetime.fromisoformat(timestamp).timestamp(),
                                    reference_id, timestamp))
        timed_references.sort()
        intervals = []
        for previous, current in zip(timed_references, timed_references[1:]):
            duration_seconds = max(0, current[0] - previous[0])
            intervals.append({
                "date": date,
                "vehicle_id": employee,
                "from_house_id": previous[1],
                "to_house_id": current[1],
                "from_timestamp": previous[2],
                "to_timestamp": current[2],
                "duration_seconds": round(duration_seconds),
            })
        all_intervals.extend(intervals)
        collection_timestamps = [item[2] for item in timed_references]
        collection_span_seconds = (
            round(max(0, timed_references[-1][0] - timed_references[0][0]))
            if len(timed_references) > 1 else None
        )
        rows.append({
            "date": date,
            "vehicle_id": employee,
            "gps_points": len(gps_points) if gps_points else None,
            "gps_first_timestamp": gps_first,
            "gps_last_timestamp": gps_last,
            "gps_span_seconds": round(gps_span_seconds)
                if gps_span_seconds is not None else None,
            "gps_observed_seconds": gps_observed_seconds
                if valid_gps_intervals else None,
            "distance_m": gps_distance_by_day.get(
                (date, employee), (None, 0)
            )[0] if gps_distance_by_day.get((date, employee), (None, 0))[1] else None,
            "unique_house_ids": len(
                house_ids_by_day_employee.get((date, employee), set())
            ),
            "collection_ids_with_timestamps": len(timed_references),
            "collection_ids_without_timestamps": sum(
                1 for timestamp in reference_times.values() if not timestamp
            ),
            "collection_first_timestamp": collection_timestamps[0]
                if collection_timestamps else None,
            "collection_last_timestamp": collection_timestamps[-1]
                if collection_timestamps else None,
            "collection_span_seconds": collection_span_seconds,
            "between_collection_interval_count": len(intervals),
            "average_between_collection_seconds": round(
                sum(item["duration_seconds"] for item in intervals) / len(intervals)
            ) if intervals else None,
        })

    by_employee = {}
    for row in rows:
        by_employee.setdefault(row["vehicle_id"], []).append(row)
    for employee_rows in by_employee.values():
        for row in employee_rows:
            row["comparable_day_count"] = 0
            row["benchmark_time_seconds"] = None
            row["benchmark_date"] = None
            row["time_difference_from_benchmark_seconds"] = None
            distance_m = row["distance_m"]
            house_count = row["unique_house_ids"]
            actual_time = row["gps_observed_seconds"]
            if distance_m is None or distance_m <= 0 or house_count <= 0 \
                    or actual_time is None:
                continue
            comparable = [
                candidate for candidate in employee_rows
                if candidate["date"] != row["date"]
                and candidate["distance_m"] is not None
                and candidate["distance_m"] > 0
                and candidate["unique_house_ids"] > 0
                and candidate["gps_observed_seconds"] is not None
                and abs(candidate["distance_m"] - distance_m)
                    <= max(candidate["distance_m"], distance_m) * 0.2
                and abs(candidate["unique_house_ids"] - house_count)
                    <= max(candidate["unique_house_ids"], house_count) * 0.2
            ]
            row["comparable_day_count"] = len(comparable)
            if len(comparable) < 2:
                continue
            fastest = min(
                comparable,
                key=lambda candidate: (
                    candidate["gps_observed_seconds"],
                    candidate["date"],
                ),
            )
            row["benchmark_time_seconds"] = fastest["gps_observed_seconds"]
            row["benchmark_date"] = fastest["date"]
            row["time_difference_from_benchmark_seconds"] = (
                actual_time - fastest["gps_observed_seconds"]
            )

    return {
        "daily": rows,
        "intervals": all_intervals[:2000],
        "total_interval_count": len(all_intervals),
        "intervals_truncated": len(all_intervals) > 2000,
    }


def _dated_rows(connection, table, date_column, start_date, end_date, vehicle_id=None):
    where, params = _date_clause(date_column, start_date, end_date)
    sql = f"SELECT * FROM {table} WHERE {where}"
    if vehicle_id:
        sql += " AND vehicle_id = ?"
        params.append(vehicle_id)
    return connection.execute(sql, params).fetchall()


def _optional_weight_kg(value, unit):
    if value is None:
        return None
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(raw) or raw <= 0:
        return None
    try:
        return _weight_kg(raw, unit)
    except ValueError:
        return None


def _historical_analytics(connection, start_date, end_date, filters):
    vehicle_id = filters.get("vehicle_id")
    history_all_dates = str(filters.get("history_all_dates", "")).lower() in {
        "1", "true", "yes",
    }
    history_start = None if history_all_dates else start_date
    history_end = None if history_all_dates else end_date
    gps_by_date, invalid_gps_intervals = _daily_gps_metrics(
        connection, start_date, end_date, filters
    )
    daily_time_performance = _daily_time_metrics(
        connection, start_date, end_date, filters
    )
    scans = _dated_rows(
        connection, "analytics_collection_scans", "scan_date",
        start_date, end_date, vehicle_id,
    )
    dumps = _dated_rows(
        connection, "analytics_dump_events", "dump_date",
        start_date, end_date, vehicle_id,
    )
    weighted_records = _dated_rows(
        connection, "analytics_dump_weights", "dump_date",
        start_date, end_date, vehicle_id,
    )

    collection_where, collection_date_params = _date_clause(
        "c.collection_date", start_date, end_date
    )
    collection_sql = f"""
        SELECT c.collection_date, c.beat_id, c.house_id, c.covered,
               h.lat, h.lon, b.beat_name, b.zone, b.ward
        FROM analytics_collections c
        JOIN analytics_houses h
          ON h.beat_id = c.beat_id AND h.house_id = c.house_id
        LEFT JOIN analytics_beats b ON b.beat_id = c.beat_id
        WHERE {collection_where}
    """
    collection_params = list(collection_date_params)
    if vehicle_id:
        collection_sql += " AND c.vehicle_id = ?"
        collection_params.append(vehicle_id)
    scope_where, scope_params = _scope_clause(filters, "b")
    if scope_params:
        collection_sql += f" AND ({scope_where})"
        collection_params.extend(scope_params)
    collection_rows = connection.execute(
        collection_sql + " ORDER BY c.collection_date, c.beat_id, c.house_id",
        collection_params,
    ).fetchall()
    house_collection_days = {
        row[0] for row in connection.execute(
            f"""
            SELECT DISTINCT c.collection_date
            FROM analytics_collections c
            JOIN analytics_houses h
              ON h.beat_id = c.beat_id AND h.house_id = c.house_id
            LEFT JOIN analytics_beats b ON b.beat_id = c.beat_id
            WHERE {collection_where}
            """ +
            (" AND c.vehicle_id = ?" if vehicle_id else "") +
            (f" AND ({scope_where})" if scope_params else ""),
            collection_params,
        ).fetchall()
    }

    scan_ids_by_date = {}
    scan_events_by_date = {}
    scan_ids_by_zone = {}
    scan_events_by_zone = {}
    for scan in scans:
        date = scan["scan_date"]
        scan_events_by_date[date] = scan_events_by_date.get(date, 0) + 1
        reference_id = scan["reference_id"]
        if reference_id:
            scan_ids_by_date.setdefault(date, set()).add(reference_id)

    history_scans = _dated_rows(
        connection, "analytics_collection_scans", "scan_date",
        start_date, end_date, vehicle_id,
    )
    all_history_scans = _dated_rows(
        connection, "analytics_collection_scans", "scan_date",
        None, None, vehicle_id,
    )
    reference_history = {}
    for scan in all_history_scans:
        reference_id = scan["reference_id"]
        if not reference_id:
            continue
        history = reference_history.setdefault(reference_id, {
            "dates": set(), "coordinates": set(), "scan_events": 0,
        })
        history["dates"].add(scan["scan_date"])
        history["scan_events"] += 1
        if scan["lat"] is not None and scan["lon"] is not None:
            history["coordinates"].add((
                round(float(scan["lat"]), 6),
                round(float(scan["lon"]), 6),
            ))

    all_collection_sql = """
        SELECT c.collection_date, c.beat_id, c.house_id, c.covered,
               h.lat, h.lon, b.beat_name
        FROM analytics_collections c
        JOIN analytics_houses h
          ON h.beat_id = c.beat_id AND h.house_id = c.house_id
        LEFT JOIN analytics_beats b ON b.beat_id = c.beat_id
        WHERE 1=1
    """
    all_collection_params = []
    if vehicle_id:
        all_collection_sql += " AND c.vehicle_id = ?"
        all_collection_params.append(vehicle_id)
    if scope_params:
        all_collection_sql += f" AND ({scope_where})"
        all_collection_params.extend(scope_params)
    all_collection_rows = connection.execute(
        all_collection_sql, all_collection_params
    ).fetchall()
    for row in all_collection_rows:
        if not row["covered"]:
            continue
        history = reference_history.setdefault(row["house_id"], {
            "dates": set(), "coordinates": set(), "scan_events": 0,
            "beat_id": row["beat_id"], "beat_name": row["beat_name"],
        })
        history["dates"].add(row["collection_date"])
        if row["lat"] is not None and row["lon"] is not None:
            history["coordinates"].add((
                round(float(row["lat"]), 6),
                round(float(row["lon"]), 6),
            ))
    for history in reference_history.values():
        history.setdefault("beat_id", None)
        history.setdefault("beat_name", None)

    house_ids_by_date = {
        date: set(reference_ids)
        for date, reference_ids in scan_ids_by_date.items()
    }
    for row in collection_rows:
        if row["covered"]:
            house_ids_by_date.setdefault(row["collection_date"], set()).add(row["house_id"])
    house_visit_days = set(house_ids_by_date) | house_collection_days

    dump_by_date = {}
    for dump in dumps:
        item = dump_by_date.setdefault(dump["dump_date"], {
            "trips": 0,
            "total_weights": [],
            "wet_weights": [],
            "dry_weights": [],
            "invalid_total_weights": 0,
            "invalid_wet_weights": 0,
            "invalid_dry_weights": 0,
        })
        item["trips"] += 1
        for column, key, invalid_key in (
            ("total_weight_raw", "total_weights", "invalid_total_weights"),
            ("wet_weight_raw", "wet_weights", "invalid_wet_weights"),
            ("dry_weight_raw", "dry_weights", "invalid_dry_weights"),
        ):
            weight = _optional_weight_kg(dump[column], dump["weight_unit"])
            if weight is None:
                item[invalid_key] += 1
            else:
                item[key].append(weight)
    for dump in weighted_records:
        item = dump_by_date.setdefault(dump["dump_date"], {
            "trips": 0,
            "total_weights": [],
            "wet_weights": [],
            "dry_weights": [],
            "invalid_total_weights": 0,
            "invalid_wet_weights": 0,
            "invalid_dry_weights": 0,
        })
        item["trips"] += 1
        item["total_weights"].append(float(dump["weight_kg"]))
        if dump["wet_weight_kg"] is None:
            item["invalid_wet_weights"] += 1
        else:
            item["wet_weights"].append(float(dump["wet_weight_kg"]))
        if dump["dry_weight_kg"] is None:
            item["invalid_dry_weights"] += 1
        else:
            item["dry_weights"].append(float(dump["dry_weight_kg"]))

    if vehicle_id:
        all_dates = set()
        for table, date_column in (
            ("analytics_gps_points", "point_date"),
            ("analytics_collection_scans", "scan_date"),
            ("analytics_dump_events", "dump_date"),
            ("analytics_dump_weights", "dump_date"),
            ("analytics_collections", "collection_date"),
        ):
            all_dates.update(
                row[0] for row in connection.execute(
                    f"SELECT DISTINCT {date_column} FROM {table} WHERE vehicle_id = ?",
                    (vehicle_id,),
                ).fetchall()
            )
    else:
        all_dates = {
            row[0] for row in connection.execute("""
                SELECT point_date FROM analytics_gps_points
                UNION SELECT scan_date FROM analytics_collection_scans
                UNION SELECT dump_date FROM analytics_dump_events
                UNION SELECT dump_date FROM analytics_dump_weights
                UNION SELECT collection_date FROM analytics_collections
            """).fetchall()
        }
    available_dates = sorted(all_dates)
    selected_dates = [
        date for date in available_dates
        if (not start_date or date >= start_date)
        and (not end_date or date <= end_date)
    ]
    dates_with_data = (
        set(gps_by_date) | set(scan_events_by_date) | set(dump_by_date)
        | house_collection_days | house_visit_days
    )
    dates = [date for date in selected_dates if date in dates_with_data]

    daily_rows = []
    for date in dates:
        gps = gps_by_date.get(date, {})
        dump = dump_by_date.get(date)
        total_weight = None
        wet_weight = None
        dry_weight = None
        if dump and dump["trips"] and len(dump["total_weights"]) == dump["trips"]:
            total_weight = round(sum(dump["total_weights"]), 2)
        if dump and dump["trips"] and len(dump["wet_weights"]) == dump["trips"]:
            wet_weight = round(sum(dump["wet_weights"]), 2)
        if dump and dump["trips"] and len(dump["dry_weights"]) == dump["trips"]:
            dry_weight = round(sum(dump["dry_weights"]), 2)
        daily_rows.append({
            "date": date,
            "distance_km": round(gps["distance_m"] / 1000, 2)
                if gps.get("valid_intervals", 0) else None,
            "gps_observed_seconds": gps.get("operating_seconds", 0)
                if gps.get("valid_intervals", 0) else None,
            "gps_points": gps.get("gps_points", 0),
            "unique_collection_references": len(scan_ids_by_date.get(date, set())),
            "collection_scan_events": scan_events_by_date.get(date, 0),
            "houses_recorded_visited": len(house_ids_by_date.get(date, set()))
                if date in house_visit_days else None,
            "dumping_trips": dump["trips"] if dump else 0,
            "garbage_weight_kg": total_weight,
            "wet_weight_kg": wet_weight,
            "dry_weight_kg": dry_weight,
            "weighted_dump_trips": len(dump["total_weights"]) if dump else 0,
            "dump_weights_complete": bool(
                dump and dump["trips"] and total_weight is not None
            ),
        })

    def average(values):
        return round(sum(values) / len(values), 2) if values else None

    distance_days = [row for row in daily_rows if row["distance_km"] is not None]
    collection_days = [
        row for row in daily_rows if row["unique_collection_references"] > 0
    ]
    verified_collection_days = [
        row for row in daily_rows if row["date"] in house_visit_days
    ]
    daily_house_counts = [
        row["houses_recorded_visited"] for row in verified_collection_days
    ]
    unique_visited_houses = set().union(*house_ids_by_date.values()) \
        if house_ids_by_date else set()
    multiple_day_house_history = []
    for house_id, history in reference_history.items():
        dates_for_house = sorted(
            date for date in history["dates"]
            if date in selected_dates
        )
        if len(dates_for_house) > 1:
            multiple_day_house_history.append({
                "beat_id": history.get("beat_id"),
                "beat_name": history.get("beat_name") or history.get("beat_id"),
                "house_id": house_id,
                "visit_days": len(dates_for_house),
                "visit_dates": dates_for_house,
                "lat": (
                    next(iter(history["coordinates"]))[0]
                    if len(history["coordinates"]) == 1 else None
                ),
                "lon": (
                    next(iter(history["coordinates"]))[1]
                    if len(history["coordinates"]) == 1 else None
                ),
            })
    multiple_day_house_history.sort(
        key=lambda row: (-row["visit_days"], row["house_id"])
    )

    recorded_beat_ids = {row["beat_id"] for row in collection_rows}
    all_recorded_beat_ids = {row["beat_id"] for row in all_collection_rows}
    all_houses_sql = """
        SELECT h.beat_id, h.house_id, h.lat, h.lon, b.beat_name
        FROM analytics_houses h
        LEFT JOIN analytics_beats b ON b.beat_id = h.beat_id
        WHERE 1=1
    """
    all_houses_params = []
    if all_recorded_beat_ids:
        placeholders = ",".join("?" for _ in all_recorded_beat_ids)
        all_houses_sql += f" AND h.beat_id IN ({placeholders})"
        all_houses_params.extend(sorted(all_recorded_beat_ids))
    else:
        all_houses_sql += " AND 1=0"
    registered_houses = connection.execute(
        all_houses_sql + " ORDER BY h.beat_id, h.house_id",
        all_houses_params,
    ).fetchall()
    coordinate_house_rows = connection.execute("""
        SELECT h.beat_id, h.house_id, h.lat, h.lon
        FROM analytics_houses h
        LEFT JOIN analytics_beats b ON b.beat_id = h.beat_id
        WHERE h.lat IS NOT NULL AND h.lon IS NOT NULL
    """ + (f" AND ({scope_where})" if scope_where else ""),
        scope_params,
    ).fetchall()
    coordinate_houses = {}
    reference_house_candidates = {}
    all_house_rows = connection.execute("""
        SELECT h.beat_id, h.house_id, h.lat, h.lon
        FROM analytics_houses h
        LEFT JOIN analytics_beats b ON b.beat_id = h.beat_id
    """ + (f" WHERE ({scope_where})" if scope_where else ""),
        scope_params,
    ).fetchall()
    for row in all_house_rows:
        key = (row["beat_id"], row["house_id"])
        reference_house_candidates.setdefault(row["house_id"], set()).add(key)

    house_grid_performance = {
        "available": False,
        "zones": [],
        "matched_reference_ids": 0,
        "unmatched_reference_ids": 0,
        "ambiguous_reference_ids": 0,
        "note": (
            "Grid performance uses House ID coordinates from the house master. "
            "Only collection-list IDs that match a house with a known location are counted."
        ),
    }
    if coordinate_house_rows:
        min_lat = min(float(row["lat"]) for row in coordinate_house_rows)
        max_lat = max(float(row["lat"]) for row in coordinate_house_rows)
        min_lon = min(float(row["lon"]) for row in coordinate_house_rows)
        max_lon = max(float(row["lon"]) for row in coordinate_house_rows)
        lat_span = max(max_lat - min_lat, 0.0001)
        lon_span = max(max_lon - min_lon, 0.0001)

        def house_grid_key(lat, lon):
            row_index = min(3, max(0, int((max_lat - lat) / lat_span * 4)))
            column_index = min(3, max(0, int((lon - min_lon) / lon_span * 4)))
            return f"Grid R{row_index + 1}C{column_index + 1}"

        grid_members = {}
        for row in coordinate_house_rows:
            key = (row["beat_id"], row["house_id"])
            grid = house_grid_key(float(row["lat"]), float(row["lon"]))
            coordinate_houses[key] = grid
            grid_members.setdefault(grid, set()).add(key)

        visited_by_grid = {grid: set() for grid in grid_members}
        matched_reference_ids = set()
        unmatched_reference_ids = set()
        ambiguous_reference_ids = set()
        for scan in scans:
            reference_id = scan["reference_id"]
            if not reference_id:
                continue
            candidates = reference_house_candidates.get(reference_id, set())
            if len(candidates) != 1:
                unmatched_reference_ids.add(reference_id)
                if len(candidates) > 1:
                    ambiguous_reference_ids.add(reference_id)
                continue
            house_key = next(iter(candidates))
            grid = coordinate_houses.get(house_key)
            if grid is None:
                unmatched_reference_ids.add(reference_id)
                continue
            matched_reference_ids.add(reference_id)
            visited_by_grid[grid].add(house_key)
        for record in collection_rows:
            if not record["covered"]:
                continue
            house_key = (record["beat_id"], record["house_id"])
            grid = coordinate_houses.get(house_key)
            if grid is not None:
                visited_by_grid[grid].add(house_key)

        zones = []
        for grid, house_keys in grid_members.items():
            houses_visited = len(house_keys & visited_by_grid[grid])
            total_houses = len(house_keys)
            zones.append({
                "zone": grid,
                "registered_houses": total_houses,
                "houses_recorded_visited": houses_visited,
                "houses_without_recorded_visit": total_houses - houses_visited,
                "recorded_visit_rate_pct": round(
                    houses_visited / total_houses * 100, 1
                ) if total_houses else None,
            })
        zones.sort(
            key=lambda row: (
                row["recorded_visit_rate_pct"]
                if row["recorded_visit_rate_pct"] is not None else -1,
                row["zone"],
            )
        )
        house_grid_performance = {
            **house_grid_performance,
            "available": True,
            "zones": zones,
            "matched_reference_ids": len(matched_reference_ids),
            "unmatched_reference_ids": len(
                unmatched_reference_ids - ambiguous_reference_ids
            ),
            "ambiguous_reference_ids": len(ambiguous_reference_ids),
        }
    selected_house_ids = {
        house_id
        for ids in house_ids_by_date.values()
        for house_id in ids
    }
    not_recorded_houses = [{
        "beat_id": row["beat_id"],
        "beat_name": row["beat_name"] or row["beat_id"],
        "house_id": row["house_id"],
        "lat": row["lat"],
        "lon": row["lon"],
    } for row in registered_houses
        if row["house_id"] not in selected_house_ids]
    known_reference_houses_not_recorded = [{
        "beat_id": history.get("beat_id"),
        "beat_name": history.get("beat_name") or history.get("beat_id"),
        "house_id": house_id,
        "lat": (
            next(iter(history["coordinates"]))[0]
            if len(history["coordinates"]) == 1 else None
        ),
        "lon": (
            next(iter(history["coordinates"]))[1]
            if len(history["coordinates"]) == 1 else None
        ),
        "visit_days": 0,
        "visit_dates": [],
    } for house_id, history in reference_history.items()
        if not any(date in selected_dates for date in history["dates"])
        and not any(
            house["house_id"] == house_id for house in not_recorded_houses
        )]
    not_recorded_houses.extend(known_reference_houses_not_recorded)
    weight_days = [
        row for row in daily_rows if row["garbage_weight_kg"] is not None
    ]
    total_dump_trips = sum(row["dumping_trips"] for row in daily_rows)
    weighted_dump_trips = sum(row["weighted_dump_trips"] for row in daily_rows)
    recorded_dump_weights = [
        weight for item in dump_by_date.values() for weight in item["total_weights"]
    ]
    all_dump_trips_weighted = (
        total_dump_trips > 0
        and sum(len(item["total_weights"]) for item in dump_by_date.values())
        == total_dump_trips
    )
    valid_day_distances_m = [
        gps_by_date[row["date"]]["distance_m"]
        for row in distance_days
    ]
    valid_day_distances = [distance_m / 1000 for distance_m in valid_day_distances_m]
    high_distance = max(distance_days, key=lambda row: row["distance_km"]) if distance_days else None
    low_distance = min(distance_days, key=lambda row: row["distance_km"]) if distance_days else None
    daily_ref_totals = [row["unique_collection_references"] for row in collection_days]
    high_collections = max(collection_days, key=lambda row: row["unique_collection_references"]) if collection_days else None
    low_collections = min(collection_days, key=lambda row: row["unique_collection_references"]) if collection_days else None
    unique_references = set().union(*scan_ids_by_date.values()) if scan_ids_by_date else set()
    active_days = selected_dates
    reference_rows = []
    for reference_id, history in reference_history.items():
        dates_for_ref = sorted(history["dates"])
        if not dates_for_ref:
            continue
        in_range_dates = [date for date in dates_for_ref if date in active_days]
        coordinates = sorted(history["coordinates"])
        missing_dates = [date for date in active_days if date not in in_range_dates]
        reference_rows.append({
            "reference_id": reference_id,
            "house_id": reference_id,
            "beat_id": history.get("beat_id"),
            "beat_name": history.get("beat_name") or history.get("beat_id"),
            "lat": coordinates[0][0] if len(coordinates) == 1 else None,
            "lon": coordinates[0][1] if len(coordinates) == 1 else None,
            "coordinate_status": (
                "one observed coordinate" if len(coordinates) == 1
                else "no scan coordinate" if len(coordinates) == 0
                else f"{len(coordinates)} different scan coordinates; ambiguous"
            ),
            "coordinate_samples": [
                {"lat": lat, "lon": lon} for lat, lon in coordinates[:3]
            ],
            "collection_count": len(in_range_dates),
            "visit_days": len(in_range_dates),
            "collection_dates": in_range_dates,
            "visit_dates": in_range_dates,
            "not_recorded_dates": missing_dates,
            "scan_events": history["scan_events"],
        })
    reference_rows.sort(
        key=lambda row: (-row["collection_count"], row["reference_id"])
    )
    repeatedly_unrecorded = [
        row for row in reference_rows if len(row["not_recorded_dates"]) >= 2
    ]
    multiple_day_references = [
        row for row in reference_rows if row["collection_count"] >= 2
    ]
    ambiguous_references = sum(
        1 for row in reference_rows
        if row["coordinate_status"].endswith("ambiguous")
    )
    duplicate_scan_where, duplicate_scan_params = _date_clause(
        "scan_date", start_date, end_date
    )
    duplicate_scan_sql = f"""
        SELECT COALESCE(SUM(record_count - 1), 0) FROM (
            SELECT COUNT(*) AS record_count
            FROM analytics_collection_scans
            WHERE {duplicate_scan_where}
    """
    if vehicle_id:
        duplicate_scan_sql += " AND vehicle_id = ?"
        duplicate_scan_params.append(vehicle_id)
    duplicate_scan_sql += """
            GROUP BY scan_date, vehicle_id, reference_id, timestamp, lat, lon
            HAVING COUNT(*) > 1
        )
    """
    duplicate_scan_rows = connection.execute(
        duplicate_scan_sql, duplicate_scan_params
    ).fetchone()[0]
    duplicate_gps_where, duplicate_gps_params = _date_clause(
        "point_date", start_date, end_date
    )
    duplicate_gps_sql = f"""
        SELECT COALESCE(SUM(record_count - 1), 0) FROM (
            SELECT COUNT(*) AS record_count
            FROM analytics_gps_points
            WHERE {duplicate_gps_where}
    """
    if vehicle_id:
        duplicate_gps_sql += " AND vehicle_id = ?"
        duplicate_gps_params.append(vehicle_id)
    duplicate_gps_sql += """
            GROUP BY point_date, vehicle_id, trip_id, timestamp, lat, lon
            HAVING COUNT(*) > 1
        )
    """
    duplicate_gps_rows = connection.execute(
        duplicate_gps_sql, duplicate_gps_params
    ).fetchone()[0]
    attribution_where, attribution_params = _date_clause(
        "scan_date", start_date, end_date
    )
    multi_employee_sql = f"""
        SELECT COUNT(*) FROM (
            SELECT reference_id
            FROM analytics_collection_scans
            WHERE {attribution_where} AND reference_id IS NOT NULL
            GROUP BY reference_id
            HAVING COUNT(DISTINCT vehicle_id) > 1
    """
    multi_employee_params = list(attribution_params)
    if vehicle_id:
        multi_employee_sql += """
            AND MAX(CASE WHEN vehicle_id = ? THEN 1 ELSE 0 END) = 1
        """
        multi_employee_params.append(vehicle_id)
    multi_employee_sql += ")"
    multi_employee_reference_ids = connection.execute(
        multi_employee_sql, multi_employee_params
    ).fetchone()[0]

    dataset_row = connection.execute(
        """SELECT dataset_id FROM analytics_house_locations
           GROUP BY dataset_id ORDER BY MAX(imported_at) DESC LIMIT 1"""
    ).fetchone()
    house_locations = []
    if dataset_row:
        house_locations = connection.execute(
            """SELECT lat, lon FROM analytics_house_locations
               WHERE dataset_id = ? ORDER BY lat, lon""",
            (dataset_row["dataset_id"],),
        ).fetchall()
    zones = []
    if house_locations:
        min_lat = min(float(row["lat"]) for row in house_locations)
        max_lat = max(float(row["lat"]) for row in house_locations)
        min_lon = min(float(row["lon"]) for row in house_locations)
        max_lon = max(float(row["lon"]) for row in house_locations)
        lat_span = max(max_lat - min_lat, 0.0001)
        lon_span = max(max_lon - min_lon, 0.0001)
        zone_houses = {}
        zone_scans = {}
        zone_refs = {}

        def grid_key(lat, lon):
            row_index = min(3, max(0, int((max_lat - lat) / lat_span * 4)))
            column_index = min(3, max(0, int((lon - min_lon) / lon_span * 4)))
            return f"Grid R{row_index + 1}C{column_index + 1}"

        for house in house_locations:
            key = grid_key(float(house["lat"]), float(house["lon"]))
            zone_houses[key] = zone_houses.get(key, 0) + 1
        for scan in history_scans:
            if scan["lat"] is None or scan["lon"] is None:
                continue
            if not (min_lat <= scan["lat"] <= max_lat and min_lon <= scan["lon"] <= max_lon):
                continue
            key = grid_key(float(scan["lat"]), float(scan["lon"]))
            zone_scans[key] = zone_scans.get(key, 0) + 1
            if scan["reference_id"]:
                zone_refs.setdefault(key, set()).add(scan["reference_id"])
        for key, house_count in zone_houses.items():
            scan_count = zone_scans.get(key, 0)
            zones.append({
                "zone": key,
                "house_coordinate_count": house_count,
                "scan_observation_count": scan_count,
                "unique_reference_ids": len(zone_refs.get(key, set())),
                "scan_observations_per_house_coordinate": round(
                    scan_count / house_count, 2
                ) if house_count else None,
            })
        zones.sort(
            key=lambda row: (
                row["scan_observations_per_house_coordinate"],
                row["zone"],
            )
        )
        for index, zone in enumerate(zones):
            zone["relative_activity_rank"] = index + 1

    return {
        "available_dates": available_dates,
        "daily_performance": daily_rows,
        "daily_time_performance": daily_time_performance,
        "daily_summary": {
            "total_distance_km": round(sum(valid_day_distances_m) / 1000, 2)
                if distance_days else None,
            "average_daily_distance_km": average(valid_day_distances),
            "distance_per_recorded_house_km": (
                round(sum(valid_day_distances_m) / 1000 / len(unique_visited_houses), 3)
                if distance_days and unique_visited_houses else None
            ),
            "distance_days_included": len(distance_days),
            "total_gps_observed_seconds": sum(
                row["gps_observed_seconds"] for row in distance_days
            ) if distance_days else None,
            "average_gps_observed_seconds": average(
                [row["gps_observed_seconds"] for row in distance_days]
            ),
            "highest_distance_day": high_distance,
            "lowest_distance_day": low_distance,
            "unique_collection_references": len(unique_references),
            "average_daily_collection_references": average(daily_ref_totals),
            "collection_days_included": len(collection_days),
            "total_unique_houses_recorded_visited": len(unique_visited_houses),
            "average_daily_houses_recorded_visited": average(daily_house_counts),
            "house_collection_days_included": len(verified_collection_days),
            "house_visits_available": bool(unique_visited_houses or collection_rows),
            "highest_collection_day": high_collections,
            "lowest_collection_day": low_collections,
            "dumping_trips": total_dump_trips,
            "weighted_dump_trips": weighted_dump_trips,
            "average_garbage_weight_per_dumping_trip_kg": average(recorded_dump_weights),
            "average_daily_garbage_weight_kg": average(
                [row["garbage_weight_kg"] for row in weight_days]
            ),
            "weight_days_included": len(weight_days),
            "total_garbage_weight_kg": round(sum(
                row["garbage_weight_kg"] for row in weight_days
            ), 2) if weight_days and all_dump_trips_weighted else None,
            "dump_weight_complete": bool(
                total_dump_trips and all_dump_trips_weighted
            ),
            "wet_waste_weight_kg": (
                round(sum(row["wet_weight_kg"] for row in daily_rows), 2)
                if daily_rows and all(row["wet_weight_kg"] is not None
                                      for row in daily_rows if row["dumping_trips"])
                and any(row["wet_weight_kg"] is not None for row in daily_rows)
                else None
            ),
            "dry_waste_weight_kg": (
                round(sum(row["dry_weight_kg"] for row in daily_rows), 2)
                if daily_rows and all(row["dry_weight_kg"] is not None
                                      for row in daily_rows if row["dumping_trips"])
                and any(row["dry_weight_kg"] is not None for row in daily_rows)
                else None
            ),
            "invalid_gps_intervals": invalid_gps_intervals,
        },
        "house_history": {
            "reference_ids": reference_rows,
            "repeatedly_unrecorded_references": repeatedly_unrecorded,
            "collected_on_multiple_days": multiple_day_references,
            "never_recorded_houses": [],
            "house_master_available": False,
            "ambiguous_reference_coordinates": ambiguous_references,
            "visited_on_multiple_days": multiple_day_house_history[:500],
            "houses_without_recorded_visit": not_recorded_houses[:500],
            "house_master_count": len(registered_houses),
            "visited_house_count": len(unique_visited_houses),
            "verified_collection_record_count": sum(
                1 for row in collection_rows if row["covered"]
            ),
            "collection_records_count": len(collection_rows),
            "recorded_beat_ids": sorted(recorded_beat_ids),
            "house_collection_days_included": len(verified_collection_days),
            "note": (
                "Collection-list reference IDs are treated as House IDs as confirmed by the operator. "
                "An ID absent during the selected period has no matching record in this dataset; that alone does not prove a missed visit."
            ),
        },
        "house_coordinate_locations": len(house_locations),
        "geographic_activity_zones": zones,
        "geographic_activity_note": (
            "Grid zones use the uploaded house-coordinate extent and each scan's recorded coordinates. "
            "If a House ID has scans at multiple coordinates, it can appear in more than one grid zone."
        ),
        "house_grid_performance": house_grid_performance,
        "record_quality": {
            "duplicate_collection_scan_rows": int(duplicate_scan_rows or 0),
            "duplicate_gps_point_rows": int(duplicate_gps_rows or 0),
            "reference_ids_recorded_under_multiple_employees": int(
                multi_employee_reference_ids or 0
            ),
        },
    }


def get_geographic_map(filters=None):
    initialize_analytics_store()
    filters = filters or {}
    selected_date = _parse_date(filters["date"], "Map date") if filters.get("date") else None
    if not selected_date:
        raise ValueError("Map date is required.")
    start_date = _parse_date(filters["start_date"], "Start date") if filters.get("start_date") else None
    end_date = _parse_date(filters["end_date"], "End date") if filters.get("end_date") else None
    if start_date and end_date and start_date > end_date:
        raise ValueError("Start date must be on or before end date.")
    if start_date and selected_date < start_date:
        raise ValueError("Map date must be on or after the reporting period start.")
    if end_date and selected_date > end_date:
        raise ValueError("Map date must be on or before the reporting period end.")
    with _connect() as connection:
        scope_where, scope_params = _scope_clause(filters)
        house_rows = connection.execute(
            f"""
            SELECT h.beat_id, h.house_id, h.lat, h.lon, b.beat_name
            FROM analytics_houses h
            JOIN analytics_beats b ON b.beat_id = h.beat_id
            WHERE h.lat IS NOT NULL AND h.lon IS NOT NULL AND ({scope_where})
            ORDER BY h.beat_id, h.house_id
            """,
            scope_params,
        ).fetchall()
        house_candidates = {}
        for row in house_rows:
            house_candidates.setdefault(row["house_id"], []).append(row)

        scan_params = [selected_date] if selected_date else []
        scan_sql = """
            SELECT scan_date, vehicle_id, reference_id, timestamp, lat, lon
            FROM analytics_collection_scans WHERE 1=1
        """
        if selected_date:
            scan_sql += " AND scan_date = ?"
        if filters.get("vehicle_id"):
            scan_sql += " AND vehicle_id = ?"
            scan_params.append(filters["vehicle_id"])
        scans = connection.execute(
            scan_sql + " ORDER BY COALESCE(timestamp, ''), vehicle_id, reference_id",
            scan_params,
        ).fetchall()
        visit_scan_where, visit_scan_params = _date_clause(
            "scan_date", start_date, end_date
        )
        visit_scan_sql = f"""
            SELECT reference_id, MAX(COALESCE(timestamp, scan_date)) AS last_timestamp
            FROM analytics_collection_scans
            WHERE {visit_scan_where} AND reference_id IS NOT NULL
        """
        if filters.get("vehicle_id"):
            visit_scan_sql += " AND vehicle_id = ?"
            visit_scan_params.append(filters["vehicle_id"])
        visit_scan_sql += " GROUP BY reference_id"
        visit_scan_rows = connection.execute(
            visit_scan_sql, visit_scan_params
        ).fetchall()
        coordinate_check_sql = f"""
            SELECT reference_id, lat, lon FROM analytics_collection_scans
            WHERE {visit_scan_where} AND reference_id IS NOT NULL
              AND lat IS NOT NULL AND lon IS NOT NULL
        """
        coordinate_check_params = list(_date_clause(
            "scan_date", start_date, end_date
        )[1])
        if filters.get("vehicle_id"):
            coordinate_check_sql += " AND vehicle_id = ?"
            coordinate_check_params.append(filters["vehicle_id"])
        coordinate_check_rows = connection.execute(
            coordinate_check_sql, coordinate_check_params
        ).fetchall()
        coordinate_mismatch_house_keys = set()
        max_coordinate_difference_by_house = {}
        for scan_row in coordinate_check_rows:
            candidates = house_candidates.get(scan_row["reference_id"], [])
            if len(candidates) != 1:
                continue
            house = candidates[0]
            house_key = (house["beat_id"], house["house_id"])
            scan_lat = float(scan_row["lat"])
            scan_lon = float(scan_row["lon"])
            if (
                round(scan_lat, 6) != round(float(house["lat"]), 6)
                or round(scan_lon, 6) != round(float(house["lon"]), 6)
            ):
                coordinate_mismatch_house_keys.add(house_key)
            difference_m = _haversine_m(
                (float(house["lat"]), float(house["lon"])),
                (scan_lat, scan_lon),
            )
            max_coordinate_difference_by_house[house_key] = max(
                difference_m,
                max_coordinate_difference_by_house.get(house_key, 0),
            )
        # A collection-list ID is linked only when exactly one House ID master row matches.
        visited_house_keys = set()
        collection_timestamps_by_house = {}
        for scan_row in visit_scan_rows:
            reference_id = scan_row["reference_id"]
            candidates = house_candidates.get(reference_id, [])
            if len(candidates) == 1:
                row = candidates[0]
                house_key = (row["beat_id"], row["house_id"])
                visited_house_keys.add(house_key)
                collection_timestamps_by_house[house_key] = scan_row["last_timestamp"]

        collection_where, collection_date_params = _date_clause(
            "c.collection_date", start_date, end_date
        )
        collection_sql = f"""
            SELECT c.beat_id, c.house_id, MAX(c.collection_date) AS last_collection_date
            FROM analytics_collections c
            JOIN analytics_beats b ON b.beat_id = c.beat_id
            WHERE c.covered = 1 AND ({scope_where}) AND {collection_where}
        """
        collection_params = list(scope_params) + collection_date_params
        if filters.get("vehicle_id"):
            collection_sql += " AND c.vehicle_id = ?"
            collection_params.append(filters["vehicle_id"])
        collection_sql += " GROUP BY c.beat_id, c.house_id"
        collection_records = connection.execute(collection_sql, collection_params).fetchall()
        for record in collection_records:
            house_key = (record["beat_id"], record["house_id"])
            visited_house_keys.add(house_key)
            previous_timestamp = collection_timestamps_by_house.get(house_key)
            record_date = record["last_collection_date"]
            if previous_timestamp is None or record_date > previous_timestamp:
                collection_timestamps_by_house[house_key] = record_date
        houses = [{
            "house_id": row["house_id"],
            "beat_id": row["beat_id"],
            "beat_name": row["beat_name"] or row["beat_id"],
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "collection_link_ambiguous": len(
                house_candidates.get(row["house_id"], [])
            ) > 1,
            "scan_coordinate_mismatch": (
                row["beat_id"], row["house_id"]
            ) in coordinate_mismatch_house_keys,
            "max_scan_coordinate_difference_m": (
                round(max_coordinate_difference_by_house[
                    (row["beat_id"], row["house_id"])
                ], 1)
                if (row["beat_id"], row["house_id"])
                in max_coordinate_difference_by_house else None
            ),
            "has_recorded_collection": (
                row["beat_id"], row["house_id"]
            ) in visited_house_keys,
            "last_collection_timestamp": collection_timestamps_by_house.get(
                (row["beat_id"], row["house_id"])
            ),
        } for row in house_rows]

        beat_rows = connection.execute(
            f"""
            SELECT beat_id, beat_name, geofence FROM analytics_beats
            WHERE geofence IS NOT NULL AND ({scope_where})
            ORDER BY beat_name, beat_id
            """,
            scope_params,
        ).fetchall()
        beats = []
        for row in beat_rows:
            polygon = []
            for pair in row["geofence"].split(";"):
                lat, lon = pair.split(",")
                polygon.append([float(lat), float(lon)])
            beats.append({
                "beat_id": row["beat_id"],
                "beat_name": row["beat_name"] or row["beat_id"],
                "polygon": polygon,
            })

        gps_params = [selected_date] if selected_date else []
        gps_sql = """
            SELECT point_date, vehicle_id, beat_id, trip_id, timestamp, lat, lon
            FROM analytics_gps_points
        """
        gps_clauses = []
        if selected_date:
            gps_clauses.append("point_date = ?")
        if filters.get("vehicle_id"):
            gps_clauses.append("vehicle_id = ?")
            gps_params.append(filters["vehicle_id"])
        if gps_clauses:
            gps_sql += " WHERE " + " AND ".join(gps_clauses)
        gps_rows = connection.execute(
            gps_sql + " ORDER BY vehicle_id, COALESCE(trip_id, ''), timestamp",
            gps_params,
        ).fetchall()
        gps_groups = {}
        seen_gps = set()
        for row in gps_rows:
            identity = (
                row["point_date"], row["vehicle_id"], row["trip_id"],
                row["beat_id"], row["timestamp"], float(row["lat"]), float(row["lon"]),
            )
            if identity in seen_gps:
                continue
            seen_gps.add(identity)
            key = (row["vehicle_id"], row["trip_id"] or "", row["beat_id"] or "")
            gps_groups.setdefault(key, []).append({
                "date": row["point_date"],
                "vehicle_id": row["vehicle_id"],
                "beat_id": row["beat_id"],
                "trip_id": row["trip_id"],
                "timestamp": row["timestamp"],
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
            })
        gps_point_count = sum(len(points) for points in gps_groups.values())
        route_segments = []
        for (employee, trip_id, beat_id), points in gps_groups.items():
            points.sort(key=lambda point: datetime.fromisoformat(
                point["timestamp"]
            ).timestamp())
            route_segments.append({
                "vehicle_id": employee,
                "beat_id": beat_id or None,
                "trip_id": trip_id,
                "points": points,
            })
        if gps_point_count > 6000:
            stride = math.ceil(gps_point_count / 6000)
            for segment in route_segments:
                sampled = segment["points"][::stride]
                if segment["points"] and sampled[-1] != segment["points"][-1]:
                    sampled.append(segment["points"][-1])
                segment["points"] = sampled
        route_segments.sort(key=lambda segment: (
            segment["points"][0]["timestamp"] if segment["points"] else "",
            segment["vehicle_id"],
            segment["beat_id"] or "",
            segment["trip_id"],
        ))

        collection_locations = []
        for row in scans:
            if row["lat"] is None or row["lon"] is None:
                continue
            scan_location = {
                "reference_id": row["reference_id"],
                "vehicle_id": row["vehicle_id"],
                "timestamp": row["timestamp"],
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "distance_from_house_m": None,
            }
            candidates = house_candidates.get(row["reference_id"], [])
            if len(candidates) == 1:
                house = candidates[0]
                scan_location["distance_from_house_m"] = round(_haversine_m(
                    (float(house["lat"]), float(house["lon"])),
                    (float(row["lat"]), float(row["lon"])),
                ), 1)
            collection_locations.append(scan_location)
        collection_location_count = len(collection_locations)
        if collection_location_count > 1500:
            stride = math.ceil(collection_location_count / 1500)
            collection_locations = collection_locations[::stride]

        identified_coordinates = {
            (round(house["lat"], 7), round(house["lon"], 7)) for house in houses
        }
        location_query = """
            SELECT lat, lon FROM analytics_house_locations
            WHERE dataset_id = (
                SELECT dataset_id FROM analytics_house_locations
                GROUP BY dataset_id ORDER BY MAX(imported_at) DESC LIMIT 1
            )
            ORDER BY lat, lon
        """
        anonymous_locations = [{
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
        } for row in connection.execute(location_query).fetchall()
            if (round(float(row["lat"]), 7), round(float(row["lon"]), 7))
            not in identified_coordinates]
        anonymous_location_count = len(anonymous_locations)
        if anonymous_location_count > 2000:
            stride = math.ceil(anonymous_location_count / 2000)
            anonymous_locations = anonymous_locations[::stride]

        unlocated_scans = sum(
            1 for row in scans if row["lat"] is None or row["lon"] is None
        )
        unvisited_houses = sum(
            1 for house in houses
            if not house["has_recorded_collection"]
            and not house["collection_link_ambiguous"]
        )
        ambiguous_house_count = sum(
            1 for house in houses if house["collection_link_ambiguous"]
        )
        return {
            "date": selected_date,
            "houses": houses[:2500],
            "house_count": len(houses),
            "unvisited_house_count": unvisited_houses,
            "ambiguous_house_count": ambiguous_house_count,
            "collection_house_coordinate_mismatches": len(
                coordinate_mismatch_house_keys
            ),
            "house_markers_truncated": len(houses) > 2500,
            "anonymous_house_locations": anonymous_locations,
            "anonymous_house_location_count": anonymous_location_count,
            "anonymous_house_markers_truncated": anonymous_location_count > len(anonymous_locations),
            "collection_locations": collection_locations,
            "collection_location_count": collection_location_count,
            "collection_markers_truncated": collection_location_count > len(collection_locations),
            "unlocated_collection_count": unlocated_scans,
            "route_segments": route_segments,
            "gps_point_count": gps_point_count,
            "gps_points_truncated": gps_point_count > sum(
                len(segment["points"]) for segment in route_segments
            ),
            "beats": beats,
            "note": (
                "House collection status uses an exact House ID match with a unique House ID master record, "
                "or an explicit covered collection record during the selected reporting period. "
                "GPS proximity never confirms a collection. The map date filters displayed GPS and scan locations."
            ),
        }


def _weight_allocations(connection, start_date, end_date, filters):
    date_where, date_params = _date_clause("dump_date", start_date, end_date)
    sql = f"""
        SELECT record_id, dump_date, vehicle_id, beat_id, trip_id,
               weight_kg, wet_weight_kg, dry_weight_kg, allocation_method
        FROM analytics_dump_weights WHERE {date_where}
    """
    params = list(date_params)
    if filters.get("vehicle_id"):
        sql += " AND vehicle_id = ?"
        params.append(filters["vehicle_id"])
    dumps = connection.execute(sql, params).fetchall()

    collection_where, collection_params = _date_clause("collection_date", start_date, end_date)
    collection_sql = f"""
        SELECT c.collection_date, c.vehicle_id, c.trip_id, c.beat_id,
               COUNT(DISTINCT c.house_id) AS covered_houses
        FROM analytics_collections c
        JOIN analytics_houses h ON h.beat_id = c.beat_id AND h.house_id = c.house_id
        WHERE {collection_where} AND c.covered = 1 AND c.vehicle_id IS NOT NULL
    """
    if filters.get("vehicle_id"):
        collection_sql += " AND c.vehicle_id = ?"
        collection_params.append(filters["vehicle_id"])
    collection_sql += " GROUP BY c.collection_date, c.vehicle_id, c.trip_id, c.beat_id"
    coverage = connection.execute(collection_sql, collection_params).fetchall()
    trip_beats = {}
    day_beats = {}
    for row in coverage:
        count = int(row["covered_houses"])
        trip_key = (row["collection_date"], row["vehicle_id"], row["trip_id"])
        day_key = (row["collection_date"], row["vehicle_id"])
        if row["trip_id"]:
            trip_beats.setdefault(trip_key, {})[row["beat_id"]] = count
        day_beats.setdefault(day_key, {})[row["beat_id"]] = (
            day_beats.setdefault(day_key, {}).get(row["beat_id"], 0) + count
        )

    allocations = []
    unallocated_kg = 0.0
    allocation_counts = {"direct": 0, "estimated_pro_rata": 0, "unallocated": 0}
    known_beats = {
        row[0] for row in connection.execute(
            "SELECT beat_id FROM analytics_beats"
        ).fetchall()
    }
    for dump in dumps:
        weight = float(dump["weight_kg"])
        beat_counts = {}
        if dump["trip_id"]:
            beat_counts = trip_beats.get(
                (dump["dump_date"], dump["vehicle_id"], dump["trip_id"]), {}
            )
        else:
            beat_counts = day_beats.get((dump["dump_date"], dump["vehicle_id"]), {})
        beat_ids = set(beat_counts)
        assignments = []
        method = dump["allocation_method"]

        if method == "beat_direct":
            if dump["beat_id"]:
                assignments = [(dump["beat_id"], weight, "direct")]
        elif method == "trip_total" and dump["trip_id"] and beat_counts:
            total_houses = sum(beat_counts.values())
            if len(beat_counts) == 1:
                assignments = [(next(iter(beat_counts)), weight, "direct")]
            elif total_houses:
                assignments = [
                    (beat_id, weight * count / total_houses, "estimated_pro_rata")
                    for beat_id, count in beat_counts.items()
                ]
        elif method == "unknown":
            if len(beat_ids) == 1:
                only_beat = next(iter(beat_ids))
                if dump["beat_id"] in (None, only_beat):
                    assignments = [(only_beat, weight, "direct")]
            elif not beat_ids and dump["beat_id"]:
                assignments = [(dump["beat_id"], weight, "direct")]

        valid_assignments = [
            assignment for assignment in assignments
            if assignment[0] in known_beats
        ]
        if valid_assignments:
            assigned_weight = sum(assignment[1] for assignment in valid_assignments)
            for beat_id, amount, allocation_type in valid_assignments:
                allocations.append({
                    "record_id": dump["record_id"],
                    "date": dump["dump_date"],
                    "vehicle_id": dump["vehicle_id"],
                    "trip_id": dump["trip_id"],
                    "beat_id": beat_id,
                    "weight_kg": amount,
                    "method": allocation_type,
                })
                allocation_counts[allocation_type] += 1
            remainder = max(0.0, weight - assigned_weight)
            if remainder > 0.000001:
                unallocated_kg += remainder
                allocation_counts["unallocated"] += 1
        else:
            unallocated_kg += weight
            allocation_counts["unallocated"] += 1
    return dumps, allocations, unallocated_kg, allocation_counts


def get_dashboard(filters=None):
    initialize_analytics_store()
    filters = filters or {}
    start_date = _parse_date(filters["start_date"], "Start date") if filters.get("start_date") else None
    end_date = _parse_date(filters["end_date"], "End date") if filters.get("end_date") else None
    if start_date and end_date and start_date > end_date:
        raise ValueError("Start date must be on or before end date.")
    with _connect() as connection:
        filter_options = _filters(connection)
        scope_where, scope_params = _scope_clause(filters)
        beats = connection.execute(
            f"SELECT b.* FROM analytics_beats b WHERE {scope_where} ORDER BY b.beat_name, b.beat_id",
            scope_params,
        ).fetchall()
        scoped_beat_ids = {row["beat_id"] for row in beats}
        house_count = connection.execute(
            f"""SELECT COUNT(*) FROM analytics_houses h
                JOIN analytics_beats b ON b.beat_id = h.beat_id
                WHERE {scope_where}""",
            scope_params,
        ).fetchone()[0]

        collection_where, collection_params = _date_clause("collection_date", start_date, end_date)
        collection_sql = f"""
            SELECT c.beat_id, COUNT(DISTINCT CASE WHEN c.covered = 1 THEN c.house_id END) AS covered
            FROM analytics_collections c
            JOIN analytics_houses h ON h.beat_id = c.beat_id AND h.house_id = c.house_id
            JOIN analytics_beats b ON b.beat_id = c.beat_id
            WHERE {collection_where} AND ({scope_where})
        """
        params = collection_params + scope_params
        if filters.get("vehicle_id"):
            collection_sql += " AND c.vehicle_id = ?"
            params.append(filters["vehicle_id"])
        collection_sql += " GROUP BY c.beat_id"
        coverage_rows = connection.execute(collection_sql, params).fetchall()
        covered_by_beat = {row["beat_id"]: int(row["covered"] or 0) for row in coverage_rows}
        houses_by_beat = {row["beat_id"]: 0 for row in beats}
        house_rows = connection.execute(
            f"""SELECT h.beat_id, COUNT(*) AS total FROM analytics_houses h
                JOIN analytics_beats b ON b.beat_id = h.beat_id
                WHERE {scope_where} GROUP BY h.beat_id""",
            scope_params,
        ).fetchall()
        houses_by_beat.update({row["beat_id"]: int(row["total"]) for row in house_rows})
        beat_summary = []
        for beat in beats:
            total = houses_by_beat[beat["beat_id"]]
            covered = min(total, covered_by_beat.get(beat["beat_id"], 0))
            beat_summary.append({
                "beat_id": beat["beat_id"],
                "beat_name": beat["beat_name"] or beat["beat_id"],
                "total_houses": total,
                "covered_houses": covered,
                "missed_houses": max(0, total - covered),
                "coverage_pct": round(covered * 100 / total, 1) if total else None,
                "geofence": beat["geofence"],
            })
        total_houses = sum(row["total_houses"] for row in beat_summary)
        covered_houses = sum(row["covered_houses"] for row in beat_summary)
        missed_houses = max(0, total_houses - covered_houses)

        dumps, allocations, unallocated_kg, allocation_counts = _weight_allocations(
            connection, start_date, end_date, filters
        )
        has_geo_filter = any(filters.get(key) for key in (
            "state", "municipal_corporation", "zone", "ward", "beat_id"
        ))
        scoped_allocations = [
            item for item in allocations if item["beat_id"] in scoped_beat_ids
        ]
        if has_geo_filter:
            total_weight_kg = sum(item["weight_kg"] for item in scoped_allocations)
            scoped_unallocated_kg = unallocated_kg
        else:
            total_weight_kg = sum(float(row["weight_kg"]) for row in dumps)
            scoped_unallocated_kg = unallocated_kg
        component_dumps = dumps
        if has_geo_filter:
            component_dumps = [
                row for row in dumps
                if row["beat_id"] in scoped_beat_ids
                and row["allocation_method"] != "trip_total"
            ]
        wet_weight_values = [
            float(row["wet_weight_kg"]) for row in component_dumps
            if row["wet_weight_kg"] is not None
        ]
        dry_weight_values = [
            float(row["dry_weight_kg"]) for row in component_dumps
            if row["dry_weight_kg"] is not None
        ]
        wet_weight_total = sum(wet_weight_values) if wet_weight_values else None
        dry_weight_total = sum(dry_weight_values) if dry_weight_values else None
        beat_weight = {}
        for allocation in scoped_allocations:
            entry = beat_weight.setdefault(allocation["beat_id"], {
                "weight_kg": 0.0, "direct_weight_kg": 0.0,
                "estimated_weight_kg": 0.0,
            })
            entry["weight_kg"] += allocation["weight_kg"]
            if allocation["method"] == "direct":
                entry["direct_weight_kg"] += allocation["weight_kg"]
            else:
                entry["estimated_weight_kg"] += allocation["weight_kg"]
        for beat_row in beat_summary:
            weight = beat_weight.get(beat_row["beat_id"], {})
            has_weight = beat_row["beat_id"] in beat_weight
            beat_row["weight_kg"] = round(weight["weight_kg"], 2) if has_weight else None
            beat_row["direct_weight_kg"] = round(weight["direct_weight_kg"], 2) if has_weight else None
            beat_row["estimated_weight_kg"] = round(weight["estimated_weight_kg"], 2) if has_weight else None
            beat_row["weight_per_covered_house_kg"] = (
                round(beat_row["weight_kg"] / beat_row["covered_houses"], 2)
                if beat_row["covered_houses"] and has_weight else None
            )

        missed_where, missed_params = _date_clause(
            "c.collection_date", start_date, end_date
        )
        missed_sql = f"""
            SELECT c.beat_id, c.house_id, b.beat_name,
                   COUNT(DISTINCT c.collection_date) AS missed_days,
                   MAX(c.collection_date) AS last_missed_date
            FROM analytics_collections c
            JOIN analytics_houses h ON h.beat_id = c.beat_id AND h.house_id = c.house_id
            JOIN analytics_beats b ON b.beat_id = c.beat_id
            WHERE {missed_where} AND ({scope_where}) AND c.covered = 0
        """
        missed_query_params = missed_params + scope_params
        if filters.get("vehicle_id"):
            missed_sql += " AND c.vehicle_id = ?"
            missed_query_params.append(filters["vehicle_id"])
        missed_sql += """
            GROUP BY c.beat_id, c.house_id, b.beat_name
            HAVING COUNT(DISTINCT c.collection_date) > 1
            ORDER BY missed_days DESC, last_missed_date DESC
            LIMIT 200
        """
        repeatedly_missed = [{
            "beat_id": row["beat_id"],
            "beat_name": row["beat_name"] or row["beat_id"],
            "house_id": row["house_id"],
            "missed_days": int(row["missed_days"]),
            "last_missed_date": row["last_missed_date"],
        } for row in connection.execute(missed_sql, missed_query_params).fetchall()]

        gps_where, gps_params = _date_clause("g.point_date", start_date, end_date)
        vehicle_gps, invalid_gps_intervals = _gps_vehicle_metrics(
            connection, gps_where, gps_params, filters
        )
        scan_where, scan_params = _date_clause("scan_date", start_date, end_date)
        scan_sql = f"""
            SELECT reference_id, lat, lon
            FROM analytics_collection_scans
            WHERE {scan_where}
        """
        if filters.get("vehicle_id"):
            scan_sql += " AND vehicle_id = ?"
            scan_params.append(filters["vehicle_id"])
        scan_rows = connection.execute(scan_sql, scan_params).fetchall()
        scan_coordinates_by_reference = {}
        for row in scan_rows:
            if not row["reference_id"]:
                continue
            coordinates = scan_coordinates_by_reference.setdefault(row["reference_id"], set())
            if row["lat"] is not None and row["lon"] is not None:
                coordinates.add((round(float(row["lat"]), 6), round(float(row["lon"]), 6)))
        ambiguous_scan_references = sum(
            1 for coordinates in scan_coordinates_by_reference.values()
            if len(coordinates) > 1
        )
        historical_analytics = _historical_analytics(
            connection, start_date, end_date, filters
        )
        collection_vehicle_sql = f"""
            SELECT vehicle_id, COUNT(*) AS houses
            FROM (
                SELECT DISTINCT c.vehicle_id, c.beat_id, c.house_id
                FROM analytics_collections c
                JOIN analytics_houses h ON h.beat_id = c.beat_id AND h.house_id = c.house_id
                JOIN analytics_beats b ON b.beat_id = c.beat_id
                WHERE {collection_where} AND ({scope_where}) AND c.covered = 1
        """
        collection_vehicle_params = collection_params + scope_params
        if filters.get("vehicle_id"):
            collection_vehicle_sql += " AND c.vehicle_id = ?"
            collection_vehicle_params.append(filters["vehicle_id"])
        collection_vehicle_sql += """
            ) AS covered_houses_by_vehicle
            GROUP BY vehicle_id
        """
        vehicle_house_rows = connection.execute(
            collection_vehicle_sql, collection_vehicle_params
        ).fetchall()
        vehicle_houses = {
            row["vehicle_id"]: int(row["houses"])
            for row in vehicle_house_rows if row["vehicle_id"]
        }

        vehicle_weight = {}
        for allocation in scoped_allocations:
            vehicle_weight[allocation["vehicle_id"]] = (
                vehicle_weight.get(allocation["vehicle_id"], 0) + allocation["weight_kg"]
            )
        # Vehicle totals are the recorded weighments; each dumping record is counted once.
        if not has_geo_filter:
            vehicle_weight = {}
            for dump in dumps:
                vehicle_weight[dump["vehicle_id"]] = (
                    vehicle_weight.get(dump["vehicle_id"], 0) + float(dump["weight_kg"])
                )

        vehicles = set(vehicle_gps) | set(vehicle_houses) | set(vehicle_weight)
        vehicle_rows = connection.execute(
            "SELECT vehicle_id, vehicle_name, capacity_kg FROM analytics_vehicles"
        ).fetchall()
        vehicle_metadata = {row["vehicle_id"]: row for row in vehicle_rows}
        vehicle_summary = []
        for vehicle_id in sorted(vehicles):
            gps = vehicle_gps.get(vehicle_id, {})
            weight = vehicle_weight.get(vehicle_id)
            capacity = vehicle_metadata.get(vehicle_id)
            capacity = capacity["capacity_kg"] if capacity else None
            trip_weights = {}
            for dump in dumps:
                if dump["vehicle_id"] == vehicle_id and dump["trip_id"]:
                    trip_key = (dump["dump_date"], dump["trip_id"])
                    if not has_geo_filter:
                        trip_weights[trip_key] = (
                            trip_weights.get(trip_key, 0) + float(dump["weight_kg"])
                        )
            if has_geo_filter:
                for allocation in scoped_allocations:
                    if allocation["vehicle_id"] == vehicle_id and allocation["trip_id"]:
                        trip_key = (allocation["date"], allocation["trip_id"])
                        trip_weights[trip_key] = (
                            trip_weights.get(trip_key, 0) + allocation["weight_kg"]
                        )
            utilization = (
                [trip_weight * 100 / capacity for trip_weight in trip_weights.values()]
                if capacity else []
            )
            vehicle_summary.append({
                "vehicle_id": vehicle_id,
                "vehicle_name": (
                    "Unassigned (sample/testing)"
                    if vehicle_id == UNASSIGNED_SAMPLE_VEHICLE_ID
                    else vehicle_metadata[vehicle_id]["vehicle_name"]
                    if vehicle_id in vehicle_metadata else None
                ),
                "houses_covered": vehicle_houses.get(vehicle_id, 0),
                "weight_kg": round(weight, 2) if weight is not None else None,
                "distance_km": round(gps.get("distance_m", 0) / 1000, 2),
                "gps_observed_operating_hours": round(gps.get("operating_seconds", 0) / 3600, 2),
                "gps_points": gps.get("gps_points", 0),
                "weight_per_km_kg": round(weight / (gps["distance_m"] / 1000), 2)
                    if weight is not None and gps.get("distance_m", 0) > 0 else None,
                "capacity_kg": capacity,
                "capacity_utilization_pct": round(sum(utilization) / len(utilization), 1)
                    if utilization else None,
                "capacity_observed_trips": len(utilization),
            })

        trend_unit = filters.get("interval", "daily")
        if trend_unit not in {"daily", "weekly", "monthly"}:
            raise ValueError("Interval must be daily, weekly, or monthly.")
        period_expression = {
            "daily": "substr(collection_date, 1, 10)",
            "weekly": "strftime('%Y-W%W', collection_date)",
            "monthly": "substr(collection_date, 1, 7)",
        }[trend_unit]
        trend_sql = f"""
            SELECT period, COUNT(*) AS covered_houses
            FROM (
                SELECT {period_expression} AS period, c.beat_id, c.house_id
                FROM analytics_collections c
                JOIN analytics_houses h ON h.beat_id = c.beat_id AND h.house_id = c.house_id
                JOIN analytics_beats b ON b.beat_id = c.beat_id
                WHERE {collection_where} AND ({scope_where}) AND c.covered = 1
        """
        trend_params = collection_params + scope_params
        if filters.get("vehicle_id"):
            trend_sql += " AND c.vehicle_id = ?"
            trend_params.append(filters["vehicle_id"])
        trend_sql += """
                GROUP BY period, c.beat_id, c.house_id
            ) AS covered_houses_by_period
            GROUP BY period ORDER BY period
        """
        coverage_trends = [
            {"period": row["period"], "covered_houses": int(row["covered_houses"] or 0)}
            for row in connection.execute(trend_sql, trend_params).fetchall()
        ]

        def period_for_date(date_value):
            if trend_unit == "monthly":
                return date_value[:7]
            if trend_unit == "weekly":
                value = datetime.strptime(date_value, "%Y-%m-%d").date()
                return f"{value.strftime('%Y')}-W{int(value.strftime('%W')):02d}"
            return date_value

        weight_trends = {}
        wet_weight_trends = {}
        dry_weight_trends = {}
        for item in scoped_allocations:
            period = period_for_date(item["date"])
            weight_trends[period] = weight_trends.get(period, 0.0) + item["weight_kg"]
        if not has_geo_filter:
            weight_trends = {}
            for dump in dumps:
                period = period_for_date(dump["dump_date"])
                weight_trends[period] = weight_trends.get(period, 0.0) + float(dump["weight_kg"])
                if dump["wet_weight_kg"] is not None:
                    wet_weight_trends[period] = (
                        wet_weight_trends.get(period, 0.0) + float(dump["wet_weight_kg"])
                    )
                if dump["dry_weight_kg"] is not None:
                    dry_weight_trends[period] = (
                        dry_weight_trends.get(period, 0.0) + float(dump["dry_weight_kg"])
                    )
        else:
            for dump in component_dumps:
                period = period_for_date(dump["dump_date"])
                if dump["wet_weight_kg"] is not None:
                    wet_weight_trends[period] = (
                        wet_weight_trends.get(period, 0.0) + float(dump["wet_weight_kg"])
                    )
                if dump["dry_weight_kg"] is not None:
                    dry_weight_trends[period] = (
                        dry_weight_trends.get(period, 0.0) + float(dump["dry_weight_kg"])
                    )
        all_periods = sorted(
            {row["period"] for row in coverage_trends} | set(weight_trends)
        )
        coverage_by_period = {row["period"]: row["covered_houses"] for row in coverage_trends}
        trends = [{
            "period": period,
            "covered_houses": coverage_by_period.get(period, 0),
            "weight_kg": round(weight_trends[period], 2) if period in weight_trends else None,
            "wet_weight_kg": round(wet_weight_trends[period], 2)
                if period in wet_weight_trends else None,
            "dry_weight_kg": round(dry_weight_trends[period], 2)
                if period in dry_weight_trends else None,
        } for period in all_periods]

        map_beats = []
        for beat in beats:
            if beat["geofence"]:
                try:
                    polygon = [
                        [float(pair.split(",")[0]), float(pair.split(",")[1])]
                        for pair in beat["geofence"].split(";")
                    ]
                except (ValueError, IndexError):
                    polygon = []
                if len(polygon) >= 3:
                    map_beats.append({
                        "beat_id": beat["beat_id"],
                        "beat_name": beat["beat_name"] or beat["beat_id"],
                        "polygon": polygon,
                        "coverage_pct": next(
                            row["coverage_pct"] for row in beat_summary
                            if row["beat_id"] == beat["beat_id"]
                        ),
                        "total_houses": next(
                            row["total_houses"] for row in beat_summary
                            if row["beat_id"] == beat["beat_id"]
                        ),
                        "visited_houses": next(
                            row["covered_houses"] for row in beat_summary
                            if row["beat_id"] == beat["beat_id"]
                        ),
                        "weight_kg": next(
                            row["weight_kg"] for row in beat_summary
                            if row["beat_id"] == beat["beat_id"]
                        ),
                    })

        return {
            "status": "success",
            "data_available": bool(
                total_houses or covered_houses or dumps or vehicle_gps or scan_rows
                or historical_analytics["daily_performance"]
            ),
            "filters": filter_options,
            "selected_filters": filters,
            "kpis": {
                "total_houses": total_houses,
                "covered_houses": covered_houses,
                "missed_houses": missed_houses,
                "coverage_pct": round(covered_houses * 100 / total_houses, 1) if total_houses else None,
                "total_weight_kg": round(total_weight_kg, 2)
                    if dumps and (not has_geo_filter or scoped_allocations) else None,
                "wet_weight_kg": round(wet_weight_total, 2)
                    if wet_weight_total is not None else None,
                "dry_weight_kg": round(dry_weight_total, 2)
                    if dry_weight_total is not None else None,
                "weight_per_covered_house_kg": round(total_weight_kg / covered_houses, 2)
                    if covered_houses and dumps
                    and (not has_geo_filter or scoped_allocations) else None,
                "gps_distance_km": round(sum(item.get("distance_m", 0) for item in vehicle_gps.values()) / 1000, 2),
                "gps_observed_operating_hours": round(sum(item.get("operating_seconds", 0) for item in vehicle_gps.values()) / 3600, 2),
                "vehicle_count": len(vehicles),
                "unallocated_weight_kg": round(scoped_unallocated_kg, 2),
                "unallocated_weight_records": allocation_counts["unallocated"],
            },
            "weight_allocation": {
                **allocation_counts,
                "method": "Trip totals spanning multiple beats are allocated in proportion to recorded covered houses only when allocation_method is `trip_total`; otherwise ambiguous weights remain unallocated.",
            },
            "beats": beat_summary,
            "repeatedly_missed_houses": repeatedly_missed,
            "vehicles": vehicle_summary,
            "trends": trends,
            "map_beats": map_beats,
            "gps_quality": {
                "excluded_intervals": invalid_gps_intervals,
                "distance_note": "GPS-derived point-to-point distance; suspicious jumps and intervals over 15 minutes are excluded. It is not road-matched distance.",
                "operating_time_note": "Sum of timestamp intervals with gaps up to 15 minutes and plausible speed; it is not an engine-on measurement.",
            },
            "weight_note": "Weight per covered house is collected disposal weight divided by covered houses; it is not household waste generation.",
            "collection_scan_quality": {
                "scan_records": len(scan_rows),
                "unique_reference_ids": len(scan_coordinates_by_reference),
                "references_at_multiple_coordinates": ambiguous_scan_references,
                "note": "Raw scan observations are not counted as house collections unless they can be reliably matched to an identified house.",
            },
            **historical_analytics,
        }
