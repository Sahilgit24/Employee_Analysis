import logging
import time
import threading
from urllib.parse import urlparse


logger = logging.getLogger(__name__)
_OSRM_REQUEST_LOCK = threading.Lock()
_OSRM_LAST_REQUEST_BY_HOST = {}
_OSRM_PREFERRED_BASE_URL = None


def _osrm_base_urls():
    import os

    configured_url = os.environ.get("OSRM_BASE_URL")
    if configured_url:
        return [configured_url.rstrip("/")]
    return [
        "https://router.project-osrm.org",
        "https://routing.openstreetmap.de/routed-car",
    ]


def _summarize_osrm_error(error):
    response = getattr(error, "response", None)
    if response is not None:
        return f"HTTP {response.status_code} {response.reason}"
    message = str(error)
    if "WinError 10013" in message:
        return "Windows blocked the outbound connection (WinError 10013)"
    if "timed out" in message.lower() or "timeout" in message.lower():
        return "Connection timed out"
    if "ssl" in message.lower() or "tls" in message.lower() or "handshake" in message.lower():
        return "TLS handshake failed"
    return f"{type(error).__name__} while connecting"


def _request_osrm_json(urls, params, requests, timeout, user_agent):
    global _OSRM_PREFERRED_BASE_URL
    last_error = None
    rate_limit_seconds = 1.05 if len(_osrm_base_urls()) > 1 else 0
    ordered_urls = list(urls)
    if _OSRM_PREFERRED_BASE_URL:
        ordered_urls.sort(key=lambda item: item[0] != _OSRM_PREFERRED_BASE_URL)

    for attempt in range(3):
        for base_url, url in ordered_urls:
            host = urlparse(base_url).netloc
            with _OSRM_REQUEST_LOCK:
                previous_request = _OSRM_LAST_REQUEST_BY_HOST.get(host)
                if previous_request is not None and rate_limit_seconds:
                    wait_seconds = rate_limit_seconds - (time.monotonic() - previous_request)
                    if wait_seconds > 0:
                        time.sleep(wait_seconds)
                _OSRM_LAST_REQUEST_BY_HOST[host] = time.monotonic()
            try:
                response = requests.get(
                    url,
                    params=params,
                    timeout=timeout,
                    headers={"User-Agent": user_agent},
                )
                response.raise_for_status()
                _OSRM_PREFERRED_BASE_URL = base_url
                return response
            except requests.exceptions.RequestException as error:
                last_error = error
                logger.warning("OSRM request to %s failed: %s", base_url, _summarize_osrm_error(error))
        if attempt < 2:
            time.sleep(2 ** (attempt + 1))

    endpoints = ", ".join(base_url for base_url, _ in ordered_urls)
    if ordered_urls and all(
        urlparse(base_url).hostname in {"127.0.0.1", "localhost"}
        for base_url, _ in ordered_urls
    ):
        raise RuntimeError(
            f"Could not connect to local OSRM at {endpoints}. Start Docker Desktop, then run "
            "`.\\setup-osrm.ps1` from the backend's `osrm` directory in PowerShell. "
            "Wait until the setup script reports that OSRM is ready, then retry. "
            "The first setup downloads OpenStreetMap road data and needs several GB of disk "
            "space and memory. No public routing fallback is enabled, so house and vehicle "
            "coordinates are not sent to an external routing service."
        ) from last_error
    raise RuntimeError(
        f"All OSRM endpoints failed ({endpoints}). Last error: {_summarize_osrm_error(last_error)}. "
        "Check backend internet access or set OSRM_BASE_URL to a reachable OSRM server. "
        "For private local routing, start Docker Desktop and run `osrm\\setup-osrm.ps1`, "
        "then set OSRM_BASE_URL=http://127.0.0.1:5000 before starting Flask."
    ) from last_error


def _download_drive_graph(polygon, ox):
    max_attempts = 4
    for attempt in range(max_attempts):
        try:
            return ox.graph_from_polygon(polygon, network_type="drive")
        except Exception as error:
            message = str(error).lower()
            transient_status = any(
                marker in message
                for marker in ("502", "503", "504", "bad gateway", "gateway timeout", "at capacity")
            )
            transient_network_error = any(
                marker in message
                for marker in ("timeout", "timed out", "connection error", "connection reset")
            )
            if attempt == max_attempts - 1 or not (transient_status or transient_network_error):
                raise

            delay_seconds = 5 * (2 ** attempt)
            logger.warning(
                "OpenStreetMap road data request failed; retrying in %s seconds (attempt %s/%s): %s",
                delay_seconds,
                attempt + 1,
                max_attempts,
                error,
            )
            time.sleep(delay_seconds)


def process_route_optimization(geofence_str, house_coords, current_location, dump_coords, batch_size, end_location):
    import pandas as pd
    import networkx as nx
    import osmnx as ox
    from shapely.geometry import Point, Polygon
    from shapely.ops import nearest_points
    from ortools.constraint_solver import routing_enums_pb2, pywrapcp

    fence_coords = [tuple(map(float, p.split(','))) for p in geofence_str.split(';')]
    polygon = Polygon([(lon, lat) for lat, lon in fence_coords])

    buffer_points = dump_coords.copy()
    if current_location:
        buffer_points.append([current_location['lat'], current_location['lon']])
    if end_location:
        buffer_points.append([end_location['lat'], end_location['lon']])

    max_dist_m = 0
    for dlat, dlon in buffer_points:
        point = Point(dlon, dlat)
        nearest_on_poly = nearest_points(polygon, point)[0]
        dist_m = point.distance(nearest_on_poly) * 111139
        max_dist_m = max(max_dist_m, dist_m)

    buffer_deg = (max_dist_m + 100) / 111139
    polygon_buffered = polygon.buffer(buffer_deg)
    G = _download_drive_graph(polygon_buffered, ox)

    df = pd.DataFrame(house_coords)
    if df.empty:
        df = pd.DataFrame(columns=['lat', 'lon', 'house_id'])

    df['inside'] = df.apply(lambda r: polygon.covers(Point(r['lon'], r['lat'])), axis=1)
    df = df[df['inside']].reset_index(drop=True)
    df['HouseID'] = df.index

    house_points = {
        row.HouseID: (row.lat, row.lon, getattr(row, 'house_id', f"House-{row.HouseID}"))
        for row in df.itertuples()
    }
    house_queue = list(house_points.items())

    depot_coord = (current_location['lat'], current_location['lon']) if current_location else (polygon.centroid.y, polygon.centroid.x)
    current_coord = depot_coord
    final_dump_coord = current_coord

    batches = []
    batch_idx = 0

    while house_queue:
        current_batch = house_queue[:batch_size]
        house_queue = house_queue[batch_size:]

        batch_nodes = [ox.nearest_nodes(G, lon, lat) for _, (lat, lon, _) in current_batch]
        start_node = ox.nearest_nodes(G, current_coord[1], current_coord[0])
        nodes = [start_node] + batch_nodes

        size = len(nodes)
        matrix = [[0]*size for _ in range(size)]
        for i in range(size):
            dists = nx.single_source_dijkstra_path_length(G, nodes[i], weight='length')
            for j in range(size):
                matrix[i][j] = int(dists.get(nodes[j], float('inf')))

        mgr = pywrapcp.RoutingIndexManager(size, 1, 0)
        tsp = pywrapcp.RoutingModel(mgr)

        def dist_cb(i, j): return matrix[mgr.IndexToNode(i)][mgr.IndexToNode(j)]
        transit = tsp.RegisterTransitCallback(dist_cb)
        tsp.SetArcCostEvaluatorOfAllVehicles(transit)

        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        params.time_limit.seconds = 5

        sol = tsp.SolveWithParameters(params)

        batch_visit_sequence = []
        if batch_idx == 0:
            batch_visit_sequence.append(('Depot', current_coord, 'Depot'))

        if sol:
            idx = tsp.Start(0)
            while not tsp.IsEnd(idx):
                node = mgr.IndexToNode(idx)
                if node > 0:
                    hid, (lat, lon, house_id) = current_batch[node - 1]
                    batch_visit_sequence.append((hid, (lat, lon), house_id))
                    current_coord = (lat, lon)
                idx = sol.Value(tsp.NextVar(idx))

        dump_coord = None
        min_dist = float('inf')
        for dlat, dlon in dump_coords:
            try:
                dnode = ox.nearest_nodes(G, dlon, dlat)
                path = nx.shortest_path(G, nodes[-1], dnode, weight='length')
                dist = sum(G[u][v][0]['length'] for u, v in zip(path[:-1], path[1:]))
                if dist < min_dist:
                    min_dist = dist
                    dump_coord = (dlat, dlon)
            except:
                continue

        if dump_coord:
            batch_visit_sequence.append((f"Dump-{batch_idx+1}", dump_coord, "Dump Yard"))
            current_coord = dump_coord
            final_dump_coord = dump_coord
        else:
            batch_visit_sequence.append((f"Dump-{batch_idx+1}", current_coord, "Dump Yard"))
            final_dump_coord = current_coord

        batch_route_path = []
        total_dist = 0
        for a, b in zip(batch_visit_sequence, batch_visit_sequence[1:]):
            coord_a, coord_b = a[1], b[1]
            try:
                na = ox.nearest_nodes(G, coord_a[1], coord_a[0])
                nb = ox.nearest_nodes(G, coord_b[1], coord_b[0])
                path = nx.shortest_path(G, na, nb, weight='length')
                seg = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in path]
                dist = sum(G[u][v][0]['length'] for u, v in zip(path[:-1], path[1:]))
                batch_route_path.extend(seg)
                total_dist += dist
            except:
                batch_route_path.extend([coord_a, coord_b])

        stops = [
            {
                "stop": idx,
                "label": label,
                "house_id": house_id,
                "lat": lat,
                "lon": lon
            }
            for idx, (label, (lat, lon), house_id) in enumerate(batch_visit_sequence)
        ]

        total_km = total_dist / 1000
        wait_time_min = 0 * sum(1 for s in batch_visit_sequence if "House" in str(s[2]))
        speed_profiles = []
        for spd in [10, 20, 30, 40]:
            drive_time = (total_km / spd) * 60
            total_time = drive_time + wait_time_min
            speed_profiles.append({
                "speed_kmph": spd,
                "distance_km": round(total_km, 2),
                "time_minutes": round(total_time, 2)
            })

        batches.append({
            "batch_index": batch_idx + 1,
            "stops": stops,
            "route_path": [{"lat": lat, "lon": lon} for lat, lon in batch_route_path],
            "speed_profiles": speed_profiles
        })

        batch_idx += 1

    try:
        garage_coord = (end_location['lat'], end_location['lon'])
        start_coord = final_dump_coord if final_dump_coord else depot_coord

        if start_coord != garage_coord:
            try:
                na = ox.nearest_nodes(G, start_coord[1], start_coord[0])
                nb = ox.nearest_nodes(G, garage_coord[1], garage_coord[0])
                path = nx.shortest_path(G, na, nb, weight='length')
                final_route_path = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in path]
                final_distance = sum(G[u][v][0]['length'] for u, v in zip(path[:-1], path[1:]))

                speed_profiles = []
                for spd in [10, 20, 30, 40]:
                    drive_time = (final_distance / 1000 / spd) * 60
                    speed_profiles.append({
                        "speed_kmph": spd,
                        "distance_km": round(final_distance / 1000, 2),
                        "time_minutes": round(drive_time, 2)
                    })

                batches.append({
                    "batch_index": batch_idx + 1,
                    "stops": [
                        {
                            "stop": 0,
                            "label": "Dump Yard",
                            "house_id": "Dump Yard",
                            "lat": start_coord[0],
                            "lon": start_coord[1]
                        },
                        {
                            "stop": 1,
                            "label": "Garage",
                            "house_id": "Garage",
                            "lat": garage_coord[0],
                            "lon": garage_coord[1]
                        }
                    ],
                    "route_path": [{"lat": lat, "lon": lon} for lat, lon in final_route_path],
                    "speed_profiles": speed_profiles
                })
            except:
                batches.append({
                    "batch_index": batch_idx + 1,
                    "stops": [
                        {
                            "stop": 0,
                            "label": "Dump Yard",
                            "house_id": "Dump Yard",
                            "lat": start_coord[0],
                            "lon": start_coord[1]
                        },
                        {
                            "stop": 1,
                            "label": "Garage",
                            "house_id": "Garage",
                            "lat": garage_coord[0],
                            "lon": garage_coord[1]
                        }
                    ],
                    "route_path": [],
                    "speed_profiles": []
                })

    except:
        pass

    return {
        "status": "success",
        "batches": batches
    }


def _coordinate_distance_meters(lat1, lon1, lat2, lon2):
    from math import asin, cos, radians, sin, sqrt

    lat1 = radians(lat1)
    lat2 = radians(lat2)
    delta_lat = lat2 - lat1
    delta_lon = radians(lon2 - lon1)
    value = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    return 2 * 6371000 * asin(sqrt(min(1.0, value)))


def _decode_valhalla_polyline(encoded_shape, precision=6):
    coordinates = []
    index = 0
    latitude = 0
    longitude = 0
    factor = 10 ** precision

    while index < len(encoded_shape):
        deltas = []
        for _ in range(2):
            result = 0
            shift = 0
            while True:
                if index >= len(encoded_shape):
                    raise ValueError("Valhalla returned a truncated encoded road geometry.")
                value = ord(encoded_shape[index]) - 63
                index += 1
                result |= (value & 0x1F) << shift
                shift += 5
                if value < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        latitude += deltas[0]
        longitude += deltas[1]
        coordinates.append({
            "lat": latitude / factor,
            "lon": longitude / factor,
        })

    if len(coordinates) < 2:
        raise ValueError("Valhalla returned incomplete road geometry.")
    return coordinates


def _request_valhalla_route(points, requests):
    import json
    import os

    max_attempts = 3
    coordinate_limit = 20
    configured_base_url = os.environ.get("VALHALLA_BASE_URL")
    if not configured_base_url:
        raise ValueError(
            "Valhalla routing is disabled unless VALHALLA_BASE_URL is explicitly configured."
        )
    routing_base_url = configured_base_url.rstrip("/")
    route_chunks = []

    for offset in range(0, len(points) - 1, coordinate_limit - 1):
        chunk = points[offset:offset + coordinate_limit]
        payload = {
            "locations": [
                {"lat": point["lat"], "lon": point["lon"], "type": "break"}
                for point in chunk
            ],
            "costing": "auto",
            "units": "kilometers",
            "shape_format": "polyline6",
        }
        last_error = None
        for attempt in range(max_attempts):
            try:
                response = requests.get(
                    f"{routing_base_url}/route",
                    params={"json": json.dumps(payload, separators=(",", ":"))},
                    timeout=(8, 60),
                    headers={"User-Agent": "RouteOptimizationProject/1.0"},
                )
                response.raise_for_status()
                data = response.json()
                trip = data.get("trip", {})
                legs = trip.get("legs", [])
                if trip.get("status") != 0 or len(legs) != len(chunk) - 1:
                    message = trip.get("status_message") or data.get("error") or "incomplete route response"
                    logger.error(
                        "Valhalla could not route ordered vehicle points %s-%s: %s. "
                        "Consecutive point pairs: %s",
                        offset + 1,
                        offset + len(chunk),
                        message,
                        [
                            {
                                "from_sequence": offset + local_index + 1,
                                "to_sequence": offset + local_index + 2,
                                "from": (chunk[local_index]["lat"], chunk[local_index]["lon"]),
                                "to": (chunk[local_index + 1]["lat"], chunk[local_index + 1]["lon"]),
                            }
                            for local_index in range(len(chunk) - 1)
                        ],
                    )
                    raise ValueError(
                        f"Valhalla could not route points {offset + 1}-{offset + len(chunk)}: {message}."
                    )

                snapped_locations = trip.get("locations", [])
                if len(snapped_locations) != len(chunk):
                    raise ValueError("Valhalla returned an incomplete snapped-waypoint list.")

                segment_results = []
                for leg_index, leg in enumerate(legs):
                    geometry = _decode_valhalla_polyline(leg.get("shape", ""))
                    segment_results.append({
                        "route_path": geometry,
                        "distance_km": float(leg.get("summary", {}).get("length", 0)),
                        "duration_minutes": float(leg.get("summary", {}).get("time", 0)) / 60,
                    })

                snaps = []
                for point, location in zip(chunk, snapped_locations):
                    snapped_lat = float(location["lat"])
                    snapped_lon = float(location["lon"])
                    snaps.append({
                        "lat": snapped_lat,
                        "lon": snapped_lon,
                        "snap_distance_meters": _coordinate_distance_meters(
                            point["lat"], point["lon"], snapped_lat, snapped_lon
                        ),
                    })
                route_chunks.append({"segments": segment_results, "snaps": snaps})
                break
            except requests.exceptions.RequestException as error:
                last_error = error
                if attempt < max_attempts - 1:
                    delay_seconds = 2 ** (attempt + 1)
                    logger.warning(
                        "Valhalla request failed; retrying in %s seconds (attempt %s/%s): %s",
                        delay_seconds,
                        attempt + 1,
                        max_attempts,
                        error,
                    )
                    time.sleep(delay_seconds)
                else:
                    logger.error(
                        "Could not connect to Valhalla at %s for ordered points %s-%s.",
                        routing_base_url,
                        offset + 1,
                        offset + len(chunk),
                    )
                    raise RuntimeError(
                        f"Could not connect to Valhalla at {routing_base_url} after 3 attempts."
                    ) from last_error

    segments = []
    snaps = []
    for chunk in route_chunks:
        segments.extend(chunk["segments"])
        snaps.extend(chunk["snaps"] if not snaps else chunk["snaps"][1:])

    for index, (point, snap) in enumerate(zip(points, snaps), start=1):
        if snap["snap_distance_meters"] > 50:
            logger.warning(
                "Valhalla snapped GPS point %s at (%s, %s), timestamp=%s, %.1f m "
                "to road (%s, %s).",
                index,
                point["lat"],
                point["lon"],
                point.get("datetime"),
                snap["snap_distance_meters"],
                snap["lat"],
                snap["lon"],
            )

    route_path = []
    for segment in segments:
        geometry = segment["route_path"]
        if route_path and _coordinate_distance_meters(
            route_path[-1]["lat"],
            route_path[-1]["lon"],
            geometry[0]["lat"],
            geometry[0]["lon"],
        ) > 1:
            raise ValueError(
                "Valhalla returned disconnected road geometry between consecutive GPS segments; "
                "no straight connector was added."
            )
        route_path.extend(geometry if not route_path else geometry[1:])
    route_path_coordinates = [
        [point["lon"], point["lat"]]
        for point in route_path
    ]

    return {
        "route_id": "valhalla-route-1",
        "label": "Valhalla route",
        "provider": "Valhalla",
        "distance_km": round(sum(segment["distance_km"] for segment in segments), 2),
        "duration_minutes": round(sum(segment["duration_minutes"] for segment in segments), 1),
        "route_path": route_path_coordinates,
        "segments": [{
            **segment,
            "route_path": [
                [point["lon"], point["lat"]]
                for point in segment["route_path"]
            ],
        } for segment in segments],
        "waypoints": snaps,
        "segment_geometries": [[
            [point["lon"], point["lat"]]
            for point in segment["route_path"]
        ] for segment in segments],
        "segment_distances_km": [segment["distance_km"] for segment in segments],
        "segment_durations_minutes": [segment["duration_minutes"] for segment in segments],
    }


def _request_osrm_route(points, requests, max_alternatives=3):
    import math
    import os

    max_attempts = 3
    coordinate_limit = 90
    route_chunks = []
    routing_base_urls = _osrm_base_urls()
    previous_waypoint_hint = None

    for offset in range(0, len(points) - 1, coordinate_limit - 1):
        chunk = points[offset:offset + coordinate_limit]
        coordinates = ";".join(
            f"{point['lon']},{point['lat']}" for point in chunk
        )
        urls = [
            (base_url, f"{base_url}/route/v1/driving/{coordinates}")
            for base_url in routing_base_urls
        ]
        params = {
            "overview": "full",
            "geometries": "geojson",
            "steps": "true",
            "alternatives": str(max_alternatives) if max_alternatives > 1 else "false",
        }
        if previous_waypoint_hint:
            params["hints"] = ";".join(
                [previous_waypoint_hint] + [""] * (len(chunk) - 1)
            )

        for attempt in range(max_attempts):
            try:
                response = _request_osrm_json(
                    urls,
                    params,
                    requests,
                    timeout=(8, 60),
                    user_agent="EmployeeRouteViewer/1.0",
                )
                data = response.json()
                if data.get("code") != "Ok" or not data.get("routes"):
                    logger.error(
                        "OSRM could not route ordered track chunk %s-%s; code=%s; message=%s. "
                        "Candidate consecutive segments: %s",
                        offset + 1,
                        offset + len(chunk),
                        data.get("code"),
                        data.get("message"),
                        [
                            {
                                "from_sequence": offset + local_index + 1,
                                "to_sequence": offset + local_index + 2,
                                "from": (chunk[local_index]["lat"], chunk[local_index]["lon"]),
                                "to": (chunk[local_index + 1]["lat"], chunk[local_index + 1]["lon"]),
                            }
                            for local_index in range(len(chunk) - 1)
                        ],
                    )
                    raise ValueError(
                        f"Road router could not map points {offset + 1}–{offset + len(chunk)}: "
                        f"{data.get('message') or data.get('code') or 'no route found'}."
                    )

                valid_routes = []
                for route in data["routes"][:max_alternatives]:
                    legs = route.get("legs", [])
                    geometry = route.get("geometry", {}).get("coordinates", [])
                    if len(legs) != len(chunk) - 1:
                        logger.error(
                            "OSRM returned %s legs for %s ordered points in chunk %s-%s; "
                            "expected one road leg for every consecutive point pair.",
                            len(legs),
                            len(chunk),
                            offset + 1,
                            offset + len(chunk),
                        )
                        continue
                    if not geometry:
                        logger.error(
                            "OSRM returned no full route geometry for ordered track chunk %s-%s.",
                            offset + 1,
                            offset + len(chunk),
                        )
                        continue
                    if any(
                        len(coordinate) < 2 or
                        not all(math.isfinite(float(value)) for value in coordinate[:2])
                        for coordinate in geometry
                    ):
                        logger.error(
                            "OSRM returned invalid route geometry for ordered track chunk %s-%s.",
                            offset + 1,
                            offset + len(chunk),
                        )
                        continue
                    segment_geometries = []
                    for leg_index, leg in enumerate(legs):
                        segment_geometry = []
                        for step in leg.get("steps", []):
                            step_geometry = step.get("geometry", {}).get("coordinates", [])
                            if not step_geometry:
                                continue
                            if segment_geometry:
                                step_join_gap = _coordinate_distance_meters(
                                    segment_geometry[-1][1],
                                    segment_geometry[-1][0],
                                    step_geometry[0][1],
                                    step_geometry[0][0],
                                )
                                if step_join_gap > 1:
                                    logger.error(
                                        "OSRM step geometries for ordered segment %s-%s do not join "
                                        "(%.1f m gap); refusing to draw a straight connector.",
                                        offset + leg_index + 1,
                                        offset + leg_index + 2,
                                        step_join_gap,
                                    )
                                    segment_geometry = []
                                    break
                                segment_geometry.extend(step_geometry[1:])
                            else:
                                segment_geometry.extend(step_geometry)
                        if len(segment_geometry) < 2:
                            logger.error(
                                "OSRM did not provide full road geometry for segment %s-%s "
                                "(%s to %s).",
                                offset + leg_index + 1,
                                offset + leg_index + 2,
                                chunk[leg_index],
                                chunk[leg_index + 1],
                            )
                            segment_geometries = []
                            break
                        segment_geometries.append(segment_geometry)
                    if len(segment_geometries) != len(chunk) - 1:
                        continue
                    snapped_waypoints = []
                    for waypoint in data.get("waypoints", []):
                        location = waypoint.get("location", [])
                        if len(location) != 2:
                            snapped_waypoints = []
                            break
                        snap_distance = waypoint.get("distance")
                        snapped_waypoints.append({
                            "lon": float(location[0]),
                            "lat": float(location[1]),
                            "snap_distance_meters": (
                                float(snap_distance) if snap_distance is not None else None
                            ),
                            "hint": waypoint.get("hint"),
                        })
                    if len(snapped_waypoints) != len(chunk):
                        snapped_waypoints = []
                        logger.warning(
                            "OSRM returned no complete snapped-waypoint data for ordered chunk %s-%s.",
                            offset + 1,
                            offset + len(chunk),
                        )
                    valid_routes.append({
                        "distance_meters": float(route["distance"]),
                        "duration_seconds": float(route["duration"]),
                        "segment_distances": [float(leg["distance"]) for leg in legs],
                        "segment_durations": [float(leg["duration"]) for leg in legs],
                        "segment_geometries": segment_geometries,
                        "coordinates": geometry,
                        "waypoints": snapped_waypoints,
                    })
                if not valid_routes:
                    logger.error(
                        "OSRM returned no full geometry with %s legs for the %s consecutive segments "
                        "between ordered points %s-%s.",
                        len(chunk) - 1,
                        len(data.get("routes", [])),
                        offset + 1,
                        offset + len(chunk),
                    )
                    raise ValueError("Road router returned no complete routes through the supplied waypoints.")
                route_chunks.append(valid_routes)
                previous_waypoint_hint = (
                    valid_routes[0]["waypoints"][-1].get("hint")
                    if valid_routes[0]["waypoints"]
                    else None
                )
                break
            except requests.exceptions.RequestException as error:
                if attempt == max_attempts - 1:
                    logger.error(
                        "Could not request routed geometry for GPS point chunk %s-%s. "
                        "Consecutive point pairs in the failed chunk: %s",
                        offset + 1,
                        offset + len(chunk),
                        [
                            {
                                "from_sequence": offset + local_index + 1,
                                "to_sequence": offset + local_index + 2,
                                "from": (chunk[local_index]["lat"], chunk[local_index]["lon"]),
                                "from_datetime": chunk[local_index].get("datetime"),
                                "to": (chunk[local_index + 1]["lat"], chunk[local_index + 1]["lon"]),
                                "to_datetime": chunk[local_index + 1].get("datetime"),
                            }
                            for local_index in range(len(chunk) - 1)
                        ],
                    )
                    raise RuntimeError(
                        f"Could not request OSRM route geometry: {error}"
                    ) from error
                delay_seconds = 2 ** (attempt + 1)
                logger.warning(
                    "Road-routing request failed; retrying in %s seconds (attempt %s/%s): %s",
                    delay_seconds,
                    attempt + 1,
                    max_attempts,
                    error,
                )
                time.sleep(delay_seconds)

    alternatives = []
    route_count = min(max_alternatives, max(len(chunk_routes) for chunk_routes in route_chunks))
    for route_index in range(route_count):
        route_path = []
        segment_distances = []
        segment_durations = []
        snapped_waypoints = []
        segment_geometries = []
        total_distance_meters = 0.0
        total_duration_seconds = 0.0

        for chunk_routes in route_chunks:
            route = chunk_routes[min(route_index, len(chunk_routes) - 1)]
            coordinates = route["coordinates"]
            if not route_path:
                route_path.extend(coordinates)
            else:
                previous_coordinate = route_path[-1]
                next_coordinate = coordinates[0]
                seam_distance = _coordinate_distance_meters(
                    previous_coordinate[1],
                    previous_coordinate[0],
                    next_coordinate[1],
                    next_coordinate[0],
                )
                if seam_distance > 1:
                    seam_routes = _request_osrm_route(
                        [
                            {"lat": previous_coordinate[1], "lon": previous_coordinate[0]},
                            {"lat": next_coordinate[1], "lon": next_coordinate[0]},
                        ],
                        requests,
                        max_alternatives=1,
                    )
                    if not seam_routes:
                        raise RuntimeError(
                            f"OSRM chunk boundary could not be connected by road "
                            f"(snapped seam points are {seam_distance:.1f} m apart)."
                        )
                    seam_path = seam_routes[0]["route_path"]
                    start_gap = _coordinate_distance_meters(
                        previous_coordinate[1],
                        previous_coordinate[0],
                        seam_path[0]["lat"],
                        seam_path[0]["lon"],
                    )
                    end_gap = _coordinate_distance_meters(
                        seam_path[-1]["lat"],
                        seam_path[-1]["lon"],
                        next_coordinate[1],
                        next_coordinate[0],
                    )
                    if start_gap > 1 or end_gap > 1:
                        raise RuntimeError(
                            "OSRM returned a chunk-boundary connector whose road geometry does not "
                            f"meet the chunk endpoints (gaps {start_gap:.1f} m and {end_gap:.1f} m)."
                        )
                    route_path.extend([[point["lon"], point["lat"]] for point in seam_path[1:]])
                    total_distance_meters += seam_routes[0]["distance_km"] * 1000
                    total_duration_seconds += seam_routes[0]["duration_minutes"] * 60
                    if segment_distances:
                        segment_distances[-1] += seam_routes[0]["distance_km"] * 1000
                    if segment_durations:
                        segment_durations[-1] += seam_routes[0]["duration_minutes"] * 60
                    if segment_geometries and seam_routes[0]["segment_geometries"]:
                        segment_geometries[-1].extend(
                            seam_routes[0]["segment_geometries"][0][1:]
                        )
                    logger.warning(
                        "OSRM chunk boundary snaps differed by %.1f m; inserted a routed road connector.",
                        seam_distance,
                    )
                route_path.extend(coordinates[1:])
            if route["waypoints"]:
                snapped_waypoints.extend(
                    route["waypoints"] if not snapped_waypoints else route["waypoints"][1:]
                )
            segment_distances.extend(route["segment_distances"])
            segment_durations.extend(route["segment_durations"])
            segment_geometries.extend(route["segment_geometries"])
            total_distance_meters += route["distance_meters"]
            total_duration_seconds += route["duration_seconds"]

        signature = tuple((round(point[0], 6), round(point[1], 6)) for point in route_path)
        if any(route["signature"] == signature for route in alternatives):
            continue
        alternatives.append({
            "route_id": f"route-{len(alternatives) + 1}",
            "label": f"Route {len(alternatives) + 1}",
            "distance_km": round(total_distance_meters / 1000, 2),
            "duration_minutes": round(total_duration_seconds / 60, 1),
            "route_path": [{"lon": lon, "lat": lat} for lon, lat in route_path],
            "waypoints": [{
                "lon": point["lon"],
                "lat": point["lat"],
                "snap_distance_meters": point["snap_distance_meters"],
            } for point in snapped_waypoints],
            "segment_geometries": segment_geometries,
            "segment_distances_km": [distance / 1000 for distance in segment_distances],
            "segment_durations_minutes": [duration / 60 for duration in segment_durations],
            "signature": signature,
        })

    alternatives.sort(key=lambda route: (route["distance_km"], route["duration_minutes"]))
    logger.info(
        "OSRM returned %s full-geometry alternatives for %s ordered waypoints "
        "(%s road vertices, %s routed segments).",
        len(alternatives),
        len(points),
        len(alternatives[0]["route_path"]) if alternatives else 0,
        len(alternatives[0]["segment_geometries"]) if alternatives else 0,
    )
    for index, route in enumerate(alternatives, start=1):
        route.pop("signature")
        route["route_id"] = f"route-{index}"
        route["label"] = f"Route {index}"
    return alternatives


def optimize_employee_track_route(track_points):
    from datetime import datetime

    import requests

    if not track_points:
        raise ValueError("At least one timestamped GPS track point is required.")

    points = []
    for index, point in enumerate(track_points):
        try:
            lat = float(point["lat"])
            lon = float(point["lon"])
            timestamp = point["datetime"]
            parsed_timestamp = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"Track point {index + 1} has invalid coordinates or timestamp.")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"Track point {index + 1} has coordinates outside valid ranges.")
        points.append({
            "lat": lat,
            "lon": lon,
            "datetime": str(timestamp),
            "_timestamp": parsed_timestamp.timestamp(),
            "_input_index": index,
        })

    points.sort(key=lambda point: (point["_timestamp"], point["_input_index"]))
    if len(points) == 1:
        point = points[0]
        ordered_point = {
            "sequence": 1,
            "lat": point["lat"],
            "lon": point["lon"],
            "datetime": point["datetime"],
        }
        single_route = {
            "route_id": "route-1",
            "label": "Route 1",
            "distance_km": 0,
            "duration_minutes": 0,
            "backtrack_distance_km": 0,
            "segments": [],
            "route_path": [{"lat": point["lat"], "lon": point["lon"]}],
        }
        return {
            "status": "success",
            "point_count": 1,
            "segment_count": 0,
            "alternative_count": 1,
            "geometry_vertex_count": 1,
            "snapped_point_count": 0,
            "off_road_snap_count": 0,
            "road_distance_km": 0,
            "track_points": [ordered_point],
            "alternatives": [single_route],
            "segments": [],
            "route_path": single_route["route_path"],
        }

    alternatives = []
    provider_errors = []
    try:
        osrm_routes = _request_osrm_route(points, requests)
        for route in osrm_routes:
            route["provider"] = "OSRM"
            route["label"] = f"OSRM route {len(alternatives) + 1}"
            route["route_id"] = f"osrm-route-{len(alternatives) + 1}"
        alternatives.extend(osrm_routes)
    except Exception as error:
        logger.exception("OSRM could not build the timestamp-ordered vehicle route.")
        provider_errors.append(f"OSRM: {error}")

    import os

    if os.environ.get("VALHALLA_BASE_URL"):
        try:
            alternatives.append(_request_valhalla_route(points, requests))
        except Exception as error:
            logger.exception("Valhalla could not build the timestamp-ordered vehicle route.")
            provider_errors.append(f"Valhalla: {error}")

    if not alternatives:
        raise ValueError(
            "Neither OSRM nor Valhalla returned a complete road route. " +
            " | ".join(provider_errors)
        )

    alternatives.sort(key=lambda route: (route["distance_km"], route["duration_minutes"]))
    for route_index, route in enumerate(alternatives, start=1):
        route["label"] = f"{route['provider']} route ({route_index})"

    for route_index, route in enumerate(alternatives):
        snapped_waypoints = route["waypoints"]
        if route_index == 0 and len(snapped_waypoints) != len(points):
            logger.error(
                "OSRM route has %s snapped waypoints for %s ordered GPS points; "
                "snap diagnostics are incomplete.",
                len(snapped_waypoints),
                len(points),
            )
        elif route_index == 0:
            for index, (point, waypoint) in enumerate(zip(points, snapped_waypoints), start=1):
                snap_distance = waypoint["snap_distance_meters"]
                if snap_distance is not None and snap_distance > 50:
                    logger.warning(
                        "GPS track point %s at (%s, %s), timestamp=%s, snapped %.1f m "
                        "to road (%s, %s).",
                        index,
                        point["lat"],
                        point["lon"],
                        point["datetime"],
                        snap_distance,
                        waypoint["lat"],
                        waypoint["lon"],
                    )
        route["segments"] = [{
            "from_sequence": index + 1,
            "to_sequence": index + 2,
            "from_datetime": points[index]["datetime"],
            "to_datetime": points[index + 1]["datetime"],
            "from_lat": points[index]["lat"],
            "from_lon": points[index]["lon"],
            "to_lat": points[index + 1]["lat"],
            "to_lon": points[index + 1]["lon"],
            "distance_km": round(route["segment_distances_km"][index], 3),
            "duration_minutes": round(route["segment_durations_minutes"][index], 1),
            "from_snap_distance_meters": (
                snapped_waypoints[index]["snap_distance_meters"]
                if len(snapped_waypoints) == len(points) else None
            ),
            "to_snap_distance_meters": (
                snapped_waypoints[index + 1]["snap_distance_meters"]
                if len(snapped_waypoints) == len(points) else None
            ),
            "route_path": [
                {"lon": coordinate[0], "lat": coordinate[1]}
                for coordinate in route["segment_geometries"][index]
            ],
        } for index in range(len(points) - 1)]
        route["backtrack_distance_km"] = round(
            _repeated_road_distance_km(route.get("route_path", [])),
            3,
        )
        route.pop("segment_distances_km")
        route.pop("segment_durations_minutes")
        route.pop("segment_geometries")

    ordered_points = [{
        "sequence": index + 1,
        "lat": point["lat"],
        "lon": point["lon"],
        "datetime": point["datetime"],
    } for index, point in enumerate(points)]

    return {
        "status": "success",
        "point_count": len(points),
        "segment_count": len(points) - 1,
        "alternative_count": len(alternatives),
        "routing_providers": sorted({route["provider"] for route in alternatives}),
        "provider_errors": provider_errors,
        "track_points": ordered_points,
        "alternatives": alternatives,
        "geometry_vertex_count": len(alternatives[0]["route_path"]),
        "snapped_point_count": sum(
            waypoint["snap_distance_meters"] is not None
            for waypoint in alternatives[0]["waypoints"]
        ),
        "off_road_snap_count": sum(
            waypoint["snap_distance_meters"] is not None and
            waypoint["snap_distance_meters"] > 50
            for waypoint in alternatives[0]["waypoints"]
        ),
        "route_path": alternatives[0]["route_path"],
        "segments": alternatives[0]["segments"],
        "road_distance_km": alternatives[0]["distance_km"],
    }


def _request_osrm_distance_matrix(points, requests):
    import math

    routing_base_urls = _osrm_base_urls()
    group_size = 90
    groups = [
        list(range(offset, min(offset + group_size, len(points))))
        for offset in range(0, len(points), group_size)
    ]
    matrix = [[None] * len(points) for _ in points]
    duration_matrix = [[None] * len(points) for _ in points]
    jobs = []

    for source_group_index, source_group in enumerate(groups):
        for destination_group_index, destination_group in enumerate(groups):
            if source_group_index == destination_group_index:
                coordinates = source_group
                source_indexes = list(range(len(source_group)))
                destination_indexes = source_indexes
            else:
                coordinates = source_group + destination_group
                source_indexes = list(range(len(source_group)))
                destination_indexes = list(range(len(source_group), len(coordinates)))

            coordinate_path = ";".join(
                f"{points[index]['lon']},{points[index]['lat']}"
                for index in coordinates
            )
            urls = [
                (base_url, f"{base_url}/table/v1/driving/{coordinate_path}")
                for base_url in routing_base_urls
            ]
            params = {
                "sources": ";".join(map(str, source_indexes)),
                "destinations": ";".join(map(str, destination_indexes)),
                "annotations": "distance,duration",
            }
            jobs.append((
                source_group,
                destination_group,
                len(source_group),
                len(destination_group),
                urls,
                params,
            ))

    def request_block(job):
        source_group, destination_group, source_size, destination_size, urls, params = job
        response = _request_osrm_json(
            urls,
            params,
            requests,
            timeout=(8, 45),
            user_agent="BeatHouseRoutePlanner/1.0",
        )
        data = response.json()
        distances = data.get("distances")
        durations = data.get("durations")
        if (
            data.get("code") != "Ok"
            or not isinstance(distances, list)
            or not isinstance(durations, list)
        ):
            raise ValueError(
                f"Road distance/time matrix request failed: "
                f"{data.get('message') or data.get('code') or 'invalid response'}."
            )
        if any(
            len(matrix_block) != source_size
            or any(not isinstance(row, list) or len(row) != destination_size for row in matrix_block)
            for matrix_block in (distances, durations)
        ):
            raise ValueError("Road-routing service returned an incomplete distance/time matrix block.")
        unavailable_pairs = 0
        for row_index, (distance_row, duration_row) in enumerate(zip(distances, durations)):
            for column_index, (distance, duration) in enumerate(zip(distance_row, duration_row)):
                for label, value in (("distance", distance), ("duration", duration)):
                    if value is not None and (
                        isinstance(value, bool) or not isinstance(value, (int, float))
                    ):
                        raise ValueError(
                            f"Road-routing service returned a non-numeric {label} for matrix "
                            f"block locations {source_group[row_index] + 1} and "
                            f"{destination_group[column_index] + 1}."
                        )

                if (
                    distance is None
                    or duration is None
                    or not math.isfinite(distance)
                    or not math.isfinite(duration)
                    or distance < 0
                    or duration < 0
                ):
                    distance_row[column_index] = None
                    duration_row[column_index] = None
                    unavailable_pairs += 1

        if unavailable_pairs:
            logger.warning(
                "OSRM returned %s unavailable road connection(s) in a matrix block; "
                "the optimizer will treat those connections as unroutable.",
                unavailable_pairs,
            )
        return source_group, destination_group, distances, durations

    for job in jobs:
        source_group, destination_group, distances, durations = request_block(job)
        for source_row, source_index in enumerate(source_group):
            for destination_column, destination_index in enumerate(destination_group):
                matrix[source_index][destination_index] = distances[source_row][destination_column]
                duration_matrix[source_index][destination_index] = durations[source_row][destination_column]

    for index in range(len(points)):
        matrix[index][index] = 0.0
        duration_matrix[index][index] = 0.0
    return matrix, duration_matrix


def _solve_beat_house_orders(
    distance_matrix,
    duration_matrix,
    route_count,
    max_distance_meters=None,
):
    import math

    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    node_count = len(distance_matrix)
    start_node = 0
    end_node = node_count - 1
    reachable_distances = [
        float(distance)
        for row in distance_matrix
        for distance in row
        if distance is not None
    ]
    reachable_durations = [
        float(duration)
        for row in duration_matrix
        for duration in row
        if duration is not None
    ]
    if not reachable_distances or not reachable_durations:
        raise ValueError("The road-routing service returned no reachable house-to-house journeys.")

    max_route_duration_seconds = (
        math.ceil(max(reachable_durations)) * max(1, node_count - 1)
    )
    distance_weight = max_route_duration_seconds + 1
    max_edge_distance = math.ceil(max(reachable_distances))
    max_route_distance_bound = (
        max_distance_meters
        if max_distance_meters is not None
        else max_edge_distance * max(1, node_count - 1)
    )
    max_route_cost = (
        max_route_distance_bound * distance_weight
        + max_route_duration_seconds
    )
    if max_route_cost >= 2**62:
        raise ValueError("The route matrix is too large to optimize safely.")
    unvisited_house_penalty = max_route_cost + 1
    strategies = [
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC,
        routing_enums_pb2.FirstSolutionStrategy.SAVINGS,
        routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION,
        routing_enums_pb2.FirstSolutionStrategy.LOCAL_CHEAPEST_INSERTION,
    ]
    candidates = []
    signatures = set()

    for candidate_index in range(route_count):
        manager = pywrapcp.RoutingIndexManager(
            node_count,
            1,
            [start_node],
            [end_node],
        )
        routing = pywrapcp.RoutingModel(manager)

        def route_cost_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            distance = distance_matrix[from_node][to_node]
            duration = duration_matrix[from_node][to_node]
            if distance is None or duration is None:
                return max_route_cost + unvisited_house_penalty
            return int(round(distance)) * distance_weight + int(round(duration))

        callback_index = routing.RegisterTransitCallback(route_cost_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(callback_index)

        def distance_constraint_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            distance = distance_matrix[from_node][to_node]
            return max_route_distance_bound + 1 if distance is None else int(round(distance))

        distance_callback_index = routing.RegisterTransitCallback(distance_constraint_callback)
        routing.AddDimension(
            distance_callback_index,
            0,
            max_route_distance_bound,
            True,
            "Distance",
        )
        for house_node in range(1, node_count - 1):
            routing.AddDisjunction(
                [manager.NodeToIndex(house_node)],
                unvisited_house_penalty,
            )
        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = strategies[candidate_index % len(strategies)]
        search_parameters.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        search_parameters.time_limit.seconds = 8
        solution = routing.SolveWithParameters(search_parameters)
        if solution is None:
            continue

        node_order = []
        index = routing.Start(0)
        while not routing.IsEnd(index):
            node_order.append(manager.IndexToNode(index))
            index = solution.Value(routing.NextVar(index))
        node_order.append(manager.IndexToNode(index))
        if any(
            distance_matrix[from_node][to_node] is None
            for from_node, to_node in zip(node_order, node_order[1:])
        ):
            continue

        signature = tuple(node_order)
        if signature in signatures:
            continue
        signatures.add(signature)
        candidates.append(node_order)

    return candidates


def _repeated_road_distance_km(route_path):
    seen_segments = set()
    repeated_distance_meters = 0.0
    for previous, current in zip(route_path, route_path[1:]):
        previous_coordinate = (round(previous["lat"], 5), round(previous["lon"], 5))
        current_coordinate = (round(current["lat"], 5), round(current["lon"], 5))
        segment = tuple(sorted((previous_coordinate, current_coordinate)))
        segment_distance = _coordinate_distance_meters(
            previous["lat"],
            previous["lon"],
            current["lat"],
            current["lon"],
        )
        if segment in seen_segments:
            repeated_distance_meters += segment_distance
        else:
            seen_segments.add(segment)
    return repeated_distance_meters / 1000


def optimize_beat_house_routes(track_points, houses, geofence_str, max_routes=4, max_distance_km=None):
    from datetime import datetime

    import requests
    from shapely.geometry import Point, Polygon

    if not track_points:
        raise ValueError("Select a vehicle route day with at least one GPS point.")
    if not houses:
        raise ValueError("The selected beat has no houses.")
    if not isinstance(geofence_str, str) or not geofence_str.strip():
        raise ValueError("A beat geofence is required.")

    fence_coordinates = []
    try:
        for pair in geofence_str.split(";"):
            lat, lon = map(float, pair.split(","))
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError
            fence_coordinates.append((lon, lat))
    except (TypeError, ValueError):
        raise ValueError("The beat geofence must contain valid 'lat,lon;lat,lon' coordinates.")

    beat = Polygon(fence_coordinates)
    if not beat.is_valid or beat.is_empty:
        raise ValueError("The beat geofence is not a valid polygon.")

    ordered_track = []
    for index, point in enumerate(track_points):
        try:
            lat = float(point["lat"])
            lon = float(point["lon"])
            timestamp = str(point["datetime"])
            parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"Vehicle track point {index + 1} has invalid coordinates or timestamp.")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"Vehicle track point {index + 1} has coordinates outside valid ranges.")
        ordered_track.append((parsed_timestamp.timestamp(), index, {"lat": lat, "lon": lon}))
    ordered_track.sort(key=lambda item: (item[0], item[1]))
    start = ordered_track[0][2]
    end = ordered_track[-1][2]

    beat_houses = []
    for index, house in enumerate(houses):
        try:
            lat = float(house["lat"])
            lon = float(house["lon"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"House {index + 1} has invalid coordinates.")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"House {index + 1} has coordinates outside valid ranges.")
        if beat.covers(Point(lon, lat)):
            beat_houses.append({
                "house_id": house.get("house_id") or house.get("House_Id") or f"House {index + 1}",
                "lat": lat,
                "lon": lon,
            })

    if not beat_houses:
        raise ValueError("No house coordinates fall inside the selected beat geofence.")

    distance_limit_meters = None
    if max_distance_km is not None:
        try:
            distance_limit_km = float(max_distance_km)
        except (TypeError, ValueError):
            raise ValueError("The maximum route distance must be a number greater than zero.")
        if not 0 < distance_limit_km <= 1000:
            raise ValueError("The maximum route distance must be between 0 and 1,000 km.")
        distance_limit_meters = int(round(distance_limit_km * 1000))

    route_points = [start] + beat_houses + [end]
    house_count = len(beat_houses)
    end_index = house_count + 1
    try:
        route_count = int(max_routes)
        if not 1 <= route_count <= 4:
            raise ValueError
    except (OverflowError, TypeError, ValueError):
        raise ValueError("The number of route suggestions must be between 1 and 4.")
    distance_matrix, duration_matrix = _request_osrm_distance_matrix(route_points, requests)
    candidates = _solve_beat_house_orders(
        distance_matrix,
        duration_matrix,
        route_count,
        distance_limit_meters,
    )
    if not candidates:
        raise ValueError(
            "The road optimizer could not find a route within the selected distance limit. "
            "Check that all house locations connect to the drivable road network."
        )

    results = []
    for candidate_order in candidates:
        ordered_stops = [
            {
                "lat": route_points[index]["lat"],
                "lon": route_points[index]["lon"],
            }
            for index in candidate_order
        ]
        routes = _request_osrm_route(ordered_stops, requests, max_alternatives=1)
        if not routes:
            continue
        route = routes[0]
        visited_house_indexes = set(candidate_order) - {0, end_index}
        route["houses_covered"] = len(visited_house_indexes)
        route["total_houses"] = house_count
        route["houses_remaining"] = house_count - len(visited_house_indexes)
        route["backtrack_distance_km"] = round(
            _repeated_road_distance_km(route.get("route_path", [])),
            3,
        )
        route["max_distance_km"] = max_distance_km
        route["unvisited_houses"] = [
            house for index, house in enumerate(beat_houses, start=1)
            if index not in visited_house_indexes
        ]
        route["stops"] = [{
            "sequence": sequence,
            "type": "start" if index == 0 else "end" if index == end_index else "house",
            "house_id": None if index in (0, end_index) else route_points[index]["house_id"],
            "lat": route_points[index]["lat"],
            "lon": route_points[index]["lon"],
            "road_lat": route["waypoints"][sequence - 1]["lat"] if len(route.get("waypoints", [])) == len(candidate_order) else None,
            "road_lon": route["waypoints"][sequence - 1]["lon"] if len(route.get("waypoints", [])) == len(candidate_order) else None,
        } for sequence, index in enumerate(candidate_order, start=1)]
        route.pop("segment_geometries", None)
        route.pop("waypoints", None)
        results.append(route)

    if not results:
        raise ValueError("The road-routing service did not return a route through the beat houses.")

    results.sort(key=lambda route: (
        -route["houses_covered"],
        route["distance_km"],
        route["duration_minutes"],
        route["backtrack_distance_km"],
    ))
    for index, route in enumerate(results, start=1):
        route["route_id"] = f"beat-route-{index}"
        route["label"] = f"Road-optimized route {index}"

    return {
        "status": "success",
        "house_count": house_count,
        "max_distance_km": max_distance_km,
        "start_inside_beat": beat.covers(Point(start["lon"], start["lat"])),
        "end_inside_beat": beat.covers(Point(end["lon"], end["lat"])),
        "routes_returned": len(results),
        "routes": results,
    }
