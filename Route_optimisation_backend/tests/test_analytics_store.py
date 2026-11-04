import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from analytics_store import (
    get_dashboard,
    get_geographic_map,
    import_operational_records,
)
from flask import Flask
from routes.analytics import analytics_bp


class AnalyticsStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {
            "ANALYTICS_DB_PATH": os.path.join(
                self.temp_directory.name, "analytics.sqlite3"
            ),
        })
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp_directory.cleanup()

    def test_dashboard_uses_imported_records_and_allocates_trip_total_by_coverage(self):
        result = import_operational_records({
            "beats": [
                {
                    "beat_id": "B-1", "beat_name": "North",
                    "state": "State", "municipal_corporation": "City",
                    "zone": "Zone 1", "ward": "Ward 1",
                    "geofence": "20.0,78.0;20.0,78.1;20.1,78.1;20.1,78.0",
                },
                {
                    "beat_id": "B-2", "beat_name": "South",
                    "state": "State", "municipal_corporation": "City",
                    "zone": "Zone 1", "ward": "Ward 2",
                    "geofence": "20.1,78.0;20.1,78.1;20.2,78.1;20.2,78.0",
                },
            ],
            "houses": [
                {"beat_id": "B-1", "house_id": "H-1", "lat": 20.01, "lon": 78.01},
                {"beat_id": "B-2", "house_id": "H-2", "lat": 20.11, "lon": 78.01},
            ],
            "vehicles": [
                {"vehicle_id": "V-1", "vehicle_name": "Truck 1", "capacity_kg": 1000},
            ],
            "collection_records": [
                {
                    "date": "2026-10-28", "beat_id": "B-1", "house_id": "H-1",
                    "vehicle_id": "V-1", "trip_id": "T-1", "covered": True,
                },
                {
                    "date": "2026-10-28", "beat_id": "B-2", "house_id": "H-2",
                    "vehicle_id": "V-1", "trip_id": "T-1", "covered": True,
                },
            ],
            "gps_points": [
                {
                    "vehicle_id": "V-1", "trip_id": "T-1",
                    "timestamp": "2026-10-28T08:00:00",
                    "lat": 20.01, "lon": 78.01,
                },
                {
                    "vehicle_id": "V-1", "trip_id": "T-1",
                    "timestamp": "2026-10-28T08:05:00",
                    "lat": 20.02, "lon": 78.02,
                },
            ],
            "dumping_weights": [
                {
                    "record_id": "D-1", "date": "2026-10-28",
                    "vehicle_id": "V-1", "trip_id": "T-1",
                    "weight": 1, "unit": "tonnes",
                    "wet_weight": 650, "dry_weight": 350,
                    "wet_unit": "kg", "dry_unit": "kg",
                    "allocation_method": "trip_total",
                },
                {
                    "record_id": "D-2", "date": "2026-10-28",
                    "vehicle_id": "V-1", "weight": 300, "unit": "kg",
                },
            ],
        })
        self.assertEqual(result["status"], "success")

        dashboard = get_dashboard({
            "start_date": "2026-10-28",
            "end_date": "2026-10-28",
            "interval": "daily",
        })
        self.assertEqual(dashboard["kpis"]["total_houses"], 2)
        self.assertEqual(dashboard["kpis"]["covered_houses"], 2)
        self.assertEqual(dashboard["kpis"]["total_weight_kg"], 1300)
        self.assertEqual(dashboard["kpis"]["wet_weight_kg"], 650)
        self.assertEqual(dashboard["kpis"]["dry_weight_kg"], 350)
        self.assertEqual(dashboard["kpis"]["unallocated_weight_kg"], 300)
        self.assertEqual(dashboard["beats"][0]["weight_kg"], 500)
        self.assertEqual(dashboard["beats"][0]["estimated_weight_kg"], 500)
        self.assertEqual(dashboard["vehicles"][0]["capacity_utilization_pct"], 100)
        self.assertGreater(dashboard["kpis"]["gps_distance_km"], 0)
        self.assertEqual(dashboard["trends"][0]["period"], "2026-10-28")
        self.assertEqual(dashboard["trends"][0]["wet_weight_kg"], 650)

        filtered = get_dashboard({"beat_id": "B-1", "interval": "monthly"})
        self.assertEqual(filtered["kpis"]["total_houses"], 1)
        self.assertEqual(filtered["beats"][0]["weight_kg"], 500)

    def test_import_upserts_collection_records_without_fabricating_data(self):
        first = import_operational_records({
            "beats": [{"beat_id": "B-1", "beat_name": "Beat 1"}],
            "houses": [{"beat_id": "B-1", "house_id": "H-1"}],
            "collection_records": [{
                "date": "2026-10-28", "beat_id": "B-1",
                "house_id": "H-1", "vehicle_id": "V-1", "covered": True,
            }],
        })
        second = import_operational_records({
            "collection_records": [{
                "date": "2026-10-28", "beat_id": "B-1",
                "house_id": "H-1", "vehicle_id": "V-1", "covered": True,
            }],
        })
        dashboard = get_dashboard()
        self.assertEqual(first["upserted"]["collection_records"], 1)
        self.assertEqual(second["upserted"]["collection_records"], 1)
        self.assertEqual(dashboard["kpis"]["covered_houses"], 1)
        self.assertIsNone(dashboard["kpis"]["total_weight_kg"])
        self.assertIsNone(dashboard["kpis"]["wet_weight_kg"])
        self.assertIsNone(dashboard["kpis"]["dry_weight_kg"])
        self.assertIsNone(dashboard["vehicles"][0]["weight_kg"])

    def test_missing_and_zero_dump_weights_are_not_counted(self):
        result = import_operational_records({
            "dumping_weights": [
                {"record_id": "missing", "date": "2026-10-28", "vehicle_id": "V-1"},
                {"record_id": "zero", "date": "2026-10-28", "vehicle_id": "V-1",
                 "weight": 0, "unit": "kg"},
            ],
        })
        dashboard = get_dashboard()
        self.assertEqual(result["rejected"]["dumping_weights"], 2)
        self.assertIsNone(dashboard["kpis"]["total_weight_kg"])

    def test_combined_route_export_imports_gps_and_unmatched_scans_safely(self):
        result = import_operational_records({
            "vehicle_id": "TRUCK-7",
            "geofence": "20.0,78.0;20.0,78.1;20.1,78.1",
            "houses": [{"lat": 20.01, "lon": 78.01}, {"lat": 20.02, "lon": 78.02}],
            "routes": [{
                "date": "2026-10-28",
                "emproute": [
                    {"datetime": "2026-10-28T08:00:00", "lat": 20.01, "lon": 78.01},
                    {"datetime": "2026-10-28T08:05:00", "lat": 20.02, "lon": 78.02},
                ],
                "Collectionlist": [
                    {"datetime": "2026-10-28T08:01:00", "referanceId": "REF-1",
                     "lat": 20.01, "lon": 78.01},
                    {"datetime": "2026-10-28T08:02:00", "referanceId": "REF-1",
                     "lat": 20.02, "lon": 78.02},
                ],
                "dumplist": [{
                    "totalWetWeight": 0, "totalDryWeight": 0, "totalGcWeight": 0,
                }],
            }],
        })
        dashboard = get_dashboard()
        self.assertEqual(result["format"], "combined_route_export")
        self.assertEqual(result["source_summary"]["house_coordinates"], 2)
        self.assertEqual(result["source_summary"]["houses_with_explicit_ids"], 0)
        self.assertEqual(result["source_summary"]["gps_points"], 2)
        self.assertEqual(result["source_summary"]["dump_records"], 1)
        self.assertEqual(result["source_summary"]["dump_records_with_positive_weights"], 0)
        self.assertEqual(result["source_summary"]["timestamp_date_mismatches"], {
            "gps_points": 0, "collection_scans": 0, "dump_records": 0,
        })
        self.assertEqual(result["upserted"]["gps_points"], 2)
        self.assertEqual(result["upserted"]["collection_scans"], 2)
        self.assertEqual(result["upserted"]["dump_events"], 1)
        self.assertEqual(result["upserted"]["house_coordinates"], 2)
        self.assertEqual(dashboard["collection_scan_quality"]["scan_records"], 2)
        self.assertEqual(
            dashboard["collection_scan_quality"]["references_at_multiple_coordinates"], 1
        )
        self.assertEqual(dashboard["kpis"]["covered_houses"], 0)
        self.assertIsNone(dashboard["kpis"]["total_weight_kg"])

    def test_combined_export_links_unique_house_ids_and_map_uses_period_records(self):
        result = import_operational_records({
            "vehicle_id": "TRUCK-7",
            "geofence": "20.0,78.0;20.0,78.1;20.1,78.1",
            "houses": [
                {"house_id": "H-1", "lat": 20.01, "lon": 78.01},
                {"house_id": "H-2", "lat": 20.02, "lon": 78.02},
                {"house_id": "H-3", "lat": 20.03, "lon": 78.03},
                {"house_id": "H-3", "lat": 20.04, "lon": 78.04},
            ],
            "routes": [
                {
                    "date": "2026-10-28",
                    "emproute": [
                        {"datetime": "2026-10-28T08:00:00", "lat": 20.01, "lon": 78.01},
                        {"datetime": "2026-10-28T08:05:00", "lat": 20.02, "lon": 78.02},
                    ],
                    "Collectionlist": [{
                        "datetime": "2026-10-28T08:02:00", "referanceId": "H-1",
                        "lat": 20.011, "lon": 78.01,
                    }],
                },
                {
                    "date": "2026-10-29",
                    "emproute": [],
                    "Collectionlist": [{
                        "datetime": "2026-10-29T08:02:00", "referanceId": "H-2",
                        "lat": 20.02, "lon": 78.02,
                    }],
                },
            ],
        })
        self.assertEqual(result["source_summary"]["houses_linked_to_ids_and_coordinates"], 2)
        self.assertEqual(result["source_summary"]["houses_with_ambiguous_id_coordinates"], 1)

        map_data = get_geographic_map({
            "vehicle_id": "TRUCK-7",
            "date": "2026-10-29",
            "start_date": "2026-10-28",
            "end_date": "2026-10-29",
        })
        houses = {row["house_id"]: row for row in map_data["houses"]}
        self.assertTrue(houses["H-1"]["has_recorded_collection"])
        self.assertTrue(houses["H-1"]["scan_coordinate_mismatch"])
        self.assertGreater(houses["H-1"]["max_scan_coordinate_difference_m"], 100)
        self.assertTrue(houses["H-2"]["has_recorded_collection"])
        self.assertNotIn("H-3", houses)
        self.assertEqual(map_data["collection_location_count"], 1)
        self.assertEqual(map_data["collection_locations"][0]["reference_id"], "H-2")
        self.assertEqual(map_data["collection_locations"][0]["distance_from_house_m"], 0)
        self.assertEqual(map_data["collection_house_coordinate_mismatches"], 1)
        self.assertEqual(map_data["gps_point_count"], 0)
        self.assertEqual(len(map_data["beats"]), 1)

    def test_gps_distance_total_sums_unrounded_daily_measurements(self):
        import_operational_records({
            "gps_points": [
                {"vehicle_id": "V-1", "timestamp": "2026-10-25T08:00:00",
                 "lat": 20.0, "lon": 78.0},
                {"vehicle_id": "V-1", "timestamp": "2026-10-25T08:01:00",
                 "lat": 20.00005, "lon": 78.0},
                {"vehicle_id": "V-1", "timestamp": "2026-10-26T08:00:00",
                 "lat": 20.0, "lon": 78.0},
                {"vehicle_id": "V-1", "timestamp": "2026-10-26T08:01:00",
                 "lat": 20.00005, "lon": 78.0},
            ],
        })
        dashboard = get_dashboard()
        self.assertEqual(dashboard["daily_summary"]["total_distance_km"], 0.01)

    def test_collection_counts_are_unique_by_day_and_attribution_warnings_are_scoped(self):
        import_operational_records({
            "collection_scans": [
                {"scan_id": "S-1", "vehicle_id": "EMP-1", "date": "2026-10-25",
                 "reference_id": "H-1", "timestamp": "2026-10-25T08:00:00",
                 "lat": 20.0, "lon": 78.0},
                {"scan_id": "S-2", "vehicle_id": "EMP-1", "date": "2026-10-25",
                 "reference_id": "H-1", "timestamp": "2026-10-25T08:00:00",
                 "lat": 20.0, "lon": 78.0},
                {"scan_id": "S-3", "vehicle_id": "EMP-1", "date": "2026-10-25",
                 "reference_id": "H-1", "timestamp": "2026-10-25T08:02:00",
                 "lat": 20.001, "lon": 78.0},
                {"scan_id": "S-4", "vehicle_id": "EMP-2", "date": "2026-10-25",
                 "reference_id": "H-1", "timestamp": "2026-10-25T08:03:00",
                 "lat": 20.002, "lon": 78.0},
            ],
        })
        all_employees = get_dashboard()
        selected_employee = get_dashboard({"vehicle_id": "EMP-1"})

        self.assertEqual(
            all_employees["daily_performance"][0]["houses_recorded_visited"], 1
        )
        self.assertEqual(
            all_employees["daily_summary"]["total_unique_houses_recorded_visited"], 1
        )
        self.assertEqual(
            all_employees["daily_summary"]["average_daily_houses_recorded_visited"], 1
        )
        self.assertEqual(
            all_employees["record_quality"]["duplicate_collection_scan_rows"], 1
        )
        self.assertEqual(
            all_employees["record_quality"]["reference_ids_recorded_under_multiple_employees"], 1
        )
        self.assertEqual(
            selected_employee["record_quality"]["reference_ids_recorded_under_multiple_employees"], 1
        )

    def test_time_analysis_is_employee_day_scoped_and_uses_unique_timestamped_house_ids(self):
        import_operational_records({
            "gps_points": [
                {"vehicle_id": "EMP-1", "trip_id": "T-1",
                 "timestamp": "2026-10-25T08:00:00", "lat": 20.0, "lon": 78.0},
                {"vehicle_id": "EMP-1", "trip_id": "T-1",
                 "timestamp": "2026-10-25T08:05:00", "lat": 20.0001, "lon": 78.0},
                {"vehicle_id": "EMP-1", "trip_id": "T-2",
                 "timestamp": "2026-10-25T09:00:00", "lat": 20.0, "lon": 78.0},
                {"vehicle_id": "EMP-1", "trip_id": "T-2",
                 "timestamp": "2026-10-25T09:05:00", "lat": 20.0001, "lon": 78.0},
                {"vehicle_id": "EMP-2", "trip_id": "T-3",
                 "timestamp": "2026-10-25T08:00:00", "lat": 20.0, "lon": 78.0},
                {"vehicle_id": "EMP-2", "trip_id": "T-3",
                 "timestamp": "2026-10-25T08:05:00", "lat": 20.0001, "lon": 78.0},
            ],
            "collection_scans": [
                {"scan_id": "S-1", "vehicle_id": "EMP-1", "date": "2026-10-25",
                 "reference_id": "H-1", "timestamp": "2026-10-25T08:00:00"},
                {"scan_id": "S-2", "vehicle_id": "EMP-1", "date": "2026-10-25",
                 "reference_id": "H-1", "timestamp": "2026-10-25T08:01:00"},
                {"scan_id": "S-3", "vehicle_id": "EMP-1", "date": "2026-10-25",
                 "reference_id": "H-2", "timestamp": "2026-10-25T08:10:00"},
                {"scan_id": "S-4", "vehicle_id": "EMP-1", "date": "2026-10-25",
                 "reference_id": "H-3"},
                {"scan_id": "S-5", "vehicle_id": "EMP-2", "date": "2026-10-25",
                 "reference_id": "H-4", "timestamp": "2026-10-25T08:00:00"},
                {"scan_id": "S-6", "vehicle_id": "EMP-2", "date": "2026-10-25",
                 "reference_id": "H-5", "timestamp": "2026-10-25T08:20:00"},
            ],
        })

        dashboard = get_dashboard()
        performance = dashboard["daily_time_performance"]
        rows = {row["vehicle_id"]: row for row in performance["daily"]}
        self.assertEqual(set(rows), {"EMP-1", "EMP-2"})
        self.assertEqual(rows["EMP-1"]["gps_span_seconds"], 3900)
        self.assertEqual(rows["EMP-1"]["gps_observed_seconds"], 600)
        self.assertEqual(rows["EMP-1"]["collection_ids_with_timestamps"], 2)
        self.assertEqual(rows["EMP-1"]["collection_ids_without_timestamps"], 1)
        self.assertEqual(rows["EMP-1"]["between_collection_interval_count"], 1)
        self.assertEqual(rows["EMP-1"]["average_between_collection_seconds"], 600)
        self.assertEqual(rows["EMP-2"]["average_between_collection_seconds"], 1200)
        self.assertEqual(performance["total_interval_count"], 2)
        self.assertEqual(
            get_dashboard({"vehicle_id": "EMP-1"})["daily_time_performance"]["total_interval_count"],
            1,
        )

    def test_comparable_day_time_benchmark_uses_same_employee_and_selected_period(self):
        routes = []
        for date, end_time in (
            ("2026-10-25", "08:05:00"),
            ("2026-10-26", "08:10:00"),
            ("2026-10-27", "08:03:00"),
        ):
            routes.append({
                "date": date,
                "emproute": [
                    {"datetime": f"{date}T08:00:00", "lat": 20.0, "lon": 78.0},
                    {"datetime": f"{date}T{end_time}", "lat": 20.0001, "lon": 78.0},
                ],
                "Collectionlist": [
                    {"datetime": f"{date}T08:01:00", "referanceId": "H-1"},
                    {"datetime": f"{date}T08:02:00", "referanceId": "H-2"},
                ],
            })
        import_operational_records({
            "vehicle_id": "EMP-1",
            "geofence": "20.0,78.0;20.0,78.1;20.1,78.1",
            "houses": [{"lat": 20.01, "lon": 78.01}],
            "routes": routes,
        })

        dashboard = get_dashboard()
        days = {
            row["date"]: row
            for row in dashboard["daily_time_performance"]["daily"]
        }
        self.assertEqual(days["2026-10-25"]["benchmark_date"], "2026-10-27")
        self.assertEqual(days["2026-10-25"]["benchmark_time_seconds"], 180)
        self.assertEqual(
            days["2026-10-25"]["time_difference_from_benchmark_seconds"], 120
        )
        self.assertEqual(days["2026-10-25"]["comparable_day_count"], 2)

        single_day = get_dashboard({
            "start_date": "2026-10-25",
            "end_date": "2026-10-25",
        })["daily_time_performance"]["daily"][0]
        self.assertIsNone(single_day["benchmark_time_seconds"])
        self.assertEqual(single_day["comparable_day_count"], 0)

    def test_dashboard_returns_all_available_days_without_ten_day_truncation(self):
        gps_points = []
        for day in range(1, 31):
            date = f"2026-01-{day:02d}"
            gps_points.append({
                "vehicle_id": "EMP-30",
                "timestamp": f"{date}T08:00:00",
                "lat": 20.0,
                "lon": 78.0,
            })
        import_operational_records({"gps_points": gps_points})

        dashboard = get_dashboard({"vehicle_id": "EMP-30"})
        self.assertEqual(len(dashboard["available_dates"]), 30)
        self.assertEqual(len(dashboard["daily_performance"]), 30)
        self.assertEqual(
            dashboard["daily_performance"][0]["date"], "2026-01-01"
        )
        self.assertEqual(
            dashboard["daily_performance"][-1]["date"], "2026-01-30"
        )

    def test_combined_route_export_without_vehicle_id_uses_unassigned_testing_bucket(self):
        result = import_operational_records({
            "geofence": "20.0,78.0;20.0,78.1;20.1,78.1",
            "houses": [{"lat": 20.01, "lon": 78.01}],
            "routes": [{
                "date": "2026-10-28",
                "emproute": [{
                    "datetime": "2026-10-28T08:00:00", "lat": 20.01, "lon": 78.01,
                }],
            }],
        })
        dashboard = get_dashboard()
        self.assertFalse(result["source_summary"]["vehicle_id_provided"])
        self.assertIn("Unassigned (sample/testing)", result["message"])
        self.assertEqual(dashboard["vehicles"][0]["vehicle_name"], "Unassigned (sample/testing)")

    def test_combined_route_exports_are_separated_by_employee_id(self):
        source = {
            "geofence": "20.0,78.0;20.0,78.1;20.1,78.1",
            "houses": [{"lat": 20.01, "lon": 78.01}],
            "routes": [{
                "date": "2026-10-28",
                "emproute": [
                    {"datetime": "2026-10-28T08:00:00", "lat": 20.01, "lon": 78.01},
                    {"datetime": "2026-10-28T08:05:00", "lat": 20.02, "lon": 78.02},
                ],
                "Collectionlist": [{
                    "datetime": "2026-10-28T08:01:00",
                    "referanceId": "REF-1",
                    "lat": 20.01,
                    "lon": 78.01,
                }],
                "dumplist": [],
            }],
        }
        for employee_id in ("EMP-1", "EMP-2"):
            import_operational_records({**source, "vehicle_id": employee_id})

        first_employee = get_dashboard({"vehicle_id": "EMP-1"})
        second_employee = get_dashboard({"vehicle_id": "EMP-2"})
        all_employees = get_dashboard()

        self.assertEqual(first_employee["daily_summary"]["unique_collection_references"], 1)
        self.assertEqual(second_employee["daily_summary"]["unique_collection_references"], 1)
        self.assertEqual(first_employee["daily_performance"][0]["gps_points"], 2)
        self.assertEqual(second_employee["daily_performance"][0]["gps_points"], 2)
        self.assertEqual(
            set(all_employees["filters"]["vehicle_id"]),
            {"EMP-1", "EMP-2"},
        )

    def test_collection_records_are_preserved_per_employee_after_schema_migration(self):
        connection = sqlite3.connect(os.environ["ANALYTICS_DB_PATH"])
        connection.execute("""
            CREATE TABLE analytics_collections (
                collection_date TEXT NOT NULL,
                beat_id TEXT NOT NULL,
                house_id TEXT NOT NULL,
                vehicle_id TEXT,
                trip_id TEXT,
                covered INTEGER NOT NULL CHECK (covered IN (0, 1)),
                PRIMARY KEY (collection_date, beat_id, house_id)
            )
        """)
        connection.execute("""
            INSERT INTO analytics_collections
                (collection_date, beat_id, house_id, vehicle_id, trip_id, covered)
            VALUES ('2026-10-28', 'B-1', 'H-1', 'EMP-1', 'T-1', 1)
        """)
        connection.commit()
        connection.close()

        import_operational_records({
            "beats": [{"beat_id": "B-1", "beat_name": "Beat 1"}],
            "houses": [{"beat_id": "B-1", "house_id": "H-1"}],
            "collection_records": [
                {"date": "2026-10-28", "beat_id": "B-1", "house_id": "H-1",
                 "vehicle_id": "EMP-1", "covered": True},
                {"date": "2026-10-28", "beat_id": "B-1", "house_id": "H-1",
                 "vehicle_id": "EMP-2", "covered": True},
            ],
        })

        first_employee = get_dashboard({"vehicle_id": "EMP-1"})
        second_employee = get_dashboard({"vehicle_id": "EMP-2"})
        self.assertEqual(first_employee["kpis"]["covered_houses"], 1)
        self.assertEqual(second_employee["kpis"]["covered_houses"], 1)

    def test_employee_performance_uses_collection_reference_ids_as_house_ids(self):
        import_operational_records({
            "beats": [
                {"beat_id": "B-1", "beat_name": "North",
                 "geofence": "20.0,78.0;20.0,78.1;20.1,78.1"},
                {"beat_id": "B-2", "beat_name": "South",
                 "geofence": "20.1,78.0;20.1,78.1;20.2,78.1"},
            ],
            "houses": [
                {"beat_id": "B-1", "house_id": "H-1", "lat": 20.01, "lon": 78.01},
                {"beat_id": "B-1", "house_id": "H-2", "lat": 20.02, "lon": 78.02},
                {"beat_id": "B-2", "house_id": "H-3", "lat": 20.11, "lon": 78.01},
            ],
            "collection_records": [
                {"date": "2026-10-28", "beat_id": "B-1", "house_id": "H-1",
                 "vehicle_id": "EMP-1", "covered": True},
                {"date": "2026-10-28", "beat_id": "B-1", "house_id": "H-2",
                 "vehicle_id": "EMP-1", "covered": False},
                {"date": "2026-10-29", "beat_id": "B-1", "house_id": "H-1",
                 "vehicle_id": "EMP-1", "covered": True},
                {"date": "2026-10-28", "beat_id": "B-2", "house_id": "H-3",
                 "vehicle_id": "EMP-2", "covered": True},
            ],
            "collection_scans": [{
                "scan_id": "unverified-scan",
                "vehicle_id": "EMP-1",
                "date": "2026-10-28",
                "reference_id": "REF-ONLY",
            }],
        })

        employee = get_dashboard({"vehicle_id": "EMP-1"})
        self.assertEqual(
            [row["houses_recorded_visited"] for row in employee["daily_performance"]],
            [2, 1],
        )
        self.assertEqual(
            employee["daily_summary"]["total_unique_houses_recorded_visited"], 2
        )
        self.assertEqual(
            employee["daily_summary"]["average_daily_houses_recorded_visited"], 1.5
        )
        self.assertIn(
            "H-1",
            [row["house_id"] for row in employee["house_history"]["visited_on_multiple_days"]],
        )
        self.assertEqual(
            [row["house_id"] for row in employee["house_history"]["houses_without_recorded_visit"]],
            ["H-2"],
        )
        self.assertEqual(employee["house_history"]["recorded_beat_ids"], ["B-1"])
        beat_map = next(beat for beat in employee["map_beats"] if beat["beat_id"] == "B-1")
        self.assertEqual(beat_map["visited_houses"], 1)

        all_employees = get_dashboard()
        self.assertEqual(
            all_employees["daily_summary"]["total_unique_houses_recorded_visited"], 3
        )
        self.assertEqual(
            all_employees["daily_performance"][0]["houses_recorded_visited"], 3
        )

    def test_daily_performance_deduplicates_gps_and_collection_references(self):
        import_operational_records({
            "gps_points": [
                {"vehicle_id": "V-1", "trip_id": "T-1", "timestamp": "2026-10-25T08:00:00",
                 "lat": 20.0, "lon": 78.0},
                {"vehicle_id": "V-1", "trip_id": "T-1", "timestamp": "2026-10-25T08:00:00",
                 "lat": 20.0, "lon": 78.0},
                {"vehicle_id": "V-1", "trip_id": "T-1", "timestamp": "2026-10-25T08:05:00",
                 "lat": 20.001, "lon": 78.0},
                {"vehicle_id": "V-1", "trip_id": "T-1", "timestamp": "2026-10-25T08:10:00",
                 "lat": 20.5, "lon": 78.0},
                {"vehicle_id": "V-1", "trip_id": "T-2", "timestamp": "2026-10-26T08:00:00",
                 "lat": 20.0, "lon": 78.0},
            ],
            "collection_scans": [
                {"scan_id": "S-1", "vehicle_id": "V-1", "date": "2026-10-25",
                 "reference_id": "REF-A", "lat": 20.0, "lon": 78.0},
                {"scan_id": "S-2", "vehicle_id": "V-1", "date": "2026-10-25",
                 "reference_id": "REF-A", "lat": 20.001, "lon": 78.0},
                {"scan_id": "S-3", "vehicle_id": "V-1", "date": "2026-10-25",
                 "reference_id": "REF-B", "lat": 20.0, "lon": 78.0},
                {"scan_id": "S-4", "vehicle_id": "V-1", "date": "2026-10-26",
                 "reference_id": "REF-A", "lat": 20.0, "lon": 78.0},
                {"scan_id": "S-5", "vehicle_id": "V-1", "date": "2026-10-27",
                 "reference_id": "REF-C", "lat": 20.0, "lon": 78.0},
            ],
            "dump_events": [
                {"dump_id": "D-1", "vehicle_id": "V-1", "date": "2026-10-25",
                 "total_weight": 10, "wet_weight": 6, "dry_weight": 4,
                 "weight_unit": "kg"},
                {"dump_id": "D-2", "vehicle_id": "V-1", "date": "2026-10-26",
                 "total_weight": 0, "wet_weight": 0, "dry_weight": 0,
                 "weight_unit": "kg"},
            ],
            "house_coordinates": [
                {"dataset_id": "D-1", "lat": 20.0, "lon": 78.0},
                {"dataset_id": "D-1", "lat": 20.001, "lon": 78.0},
            ],
        })
        dashboard = get_dashboard()
        self.assertEqual(
            [row["date"] for row in dashboard["daily_performance"]],
            ["2026-10-25", "2026-10-26", "2026-10-27"],
        )
        first, second, third = dashboard["daily_performance"]
        self.assertEqual(first["gps_points"], 3)
        self.assertAlmostEqual(first["distance_km"], 0.11, places=2)
        self.assertEqual(first["gps_observed_seconds"], 300)
        self.assertEqual(
            dashboard["daily_summary"]["average_gps_observed_seconds"], 300
        )
        self.assertEqual(
            dashboard["daily_summary"]["total_gps_observed_seconds"], 300
        )
        self.assertIsNone(second["distance_km"])
        self.assertEqual(first["unique_collection_references"], 2)
        self.assertEqual(first["collection_scan_events"], 3)
        self.assertEqual(dashboard["daily_summary"]["unique_collection_references"], 3)
        self.assertEqual(dashboard["daily_summary"]["collection_days_included"], 3)
        self.assertEqual(dashboard["daily_summary"]["dumping_trips"], 2)
        self.assertEqual(dashboard["daily_summary"]["weighted_dump_trips"], 1)
        self.assertEqual(
            dashboard["daily_summary"]["average_garbage_weight_per_dumping_trip_kg"], 10
        )
        self.assertEqual(first["garbage_weight_kg"], 10)
        self.assertIsNone(second["garbage_weight_kg"])
        self.assertIsNone(dashboard["daily_summary"]["total_garbage_weight_kg"])
        self.assertEqual(dashboard["daily_summary"]["average_daily_garbage_weight_kg"], 10)
        self.assertIsNone(dashboard["daily_summary"]["wet_waste_weight_kg"])
        self.assertEqual(
            [row["houses_recorded_visited"] for row in dashboard["daily_performance"]],
            [2, 1, 1],
        )
        self.assertEqual(
            dashboard["daily_summary"]["total_unique_houses_recorded_visited"], 3
        )
        self.assertEqual(
            dashboard["daily_summary"]["average_daily_houses_recorded_visited"], 1.33
        )
        self.assertTrue(any(
            row["reference_id"] == "REF-B"
            for row in dashboard["house_history"]["repeatedly_unrecorded_references"]
        ))
        self.assertIn(
            "REF-A",
            [row["house_id"] for row in dashboard["house_history"]["visited_on_multiple_days"]],
        )
        self.assertTrue(any(
            row["reference_id"] == "REF-A"
            for row in dashboard["house_history"]["collected_on_multiple_days"]
        ))
        self.assertEqual(dashboard["house_history"]["never_recorded_houses"], [])
        self.assertTrue(dashboard["geographic_activity_zones"])
        self.assertEqual(third["unique_collection_references"], 1)

    def test_daily_date_filter_and_full_history_option_are_independent(self):
        import_operational_records({
            "collection_scans": [
                {"scan_id": "S-1", "vehicle_id": "V-1", "date": "2026-10-25",
                 "reference_id": "REF-A"},
                {"scan_id": "S-2", "vehicle_id": "V-1", "date": "2026-10-26",
                 "reference_id": "REF-B"},
            ],
        })
        selected = get_dashboard({
            "start_date": "2026-10-25", "end_date": "2026-10-25",
            "history_all_dates": "true",
        })
        self.assertEqual(len(selected["daily_performance"]), 1)
        self.assertEqual(selected["daily_summary"]["unique_collection_references"], 1)
        self.assertEqual(selected["daily_performance"][0]["houses_recorded_visited"], 1)
        self.assertEqual(
            [row["house_id"] for row in selected["house_history"]["houses_without_recorded_visit"]],
            ["REF-B"],
        )
        self.assertEqual(len(selected["house_history"]["reference_ids"]), 2)

    def test_house_grid_uses_house_master_coordinates_and_employee_filter(self):
        import_operational_records({
            "beats": [{"beat_id": "B-1"}],
            "houses": [
                {"beat_id": "B-1", "house_id": "H-1", "lat": 20.0, "lon": 78.0},
                {"beat_id": "B-1", "house_id": "H-2", "lat": 20.1, "lon": 78.1},
            ],
            "collection_scans": [
                {"scan_id": "S-1", "vehicle_id": "V-1", "date": "2026-10-25",
                 "reference_id": "H-1", "lat": 20.1, "lon": 78.1},
                {"scan_id": "S-2", "vehicle_id": "V-2", "date": "2026-10-25",
                 "reference_id": "H-2", "lat": 20.0, "lon": 78.0},
            ],
        })

        selected = get_dashboard({
            "start_date": "2026-10-25",
            "end_date": "2026-10-25",
            "vehicle_id": "V-1",
        })["house_grid_performance"]

        self.assertTrue(selected["available"])
        self.assertEqual(selected["matched_reference_ids"], 1)
        self.assertEqual(selected["unmatched_reference_ids"], 0)
        self.assertEqual(selected["ambiguous_reference_ids"], 0)
        grids = {row["zone"]: row for row in selected["zones"]}
        self.assertEqual(grids["Grid R4C1"]["houses_recorded_visited"], 1)
        self.assertEqual(grids["Grid R4C1"]["recorded_visit_rate_pct"], 100)
        self.assertEqual(grids["Grid R1C4"]["houses_recorded_visited"], 0)
        self.assertEqual(grids["Grid R1C4"]["recorded_visit_rate_pct"], 0)

    def test_trip_weight_spanning_beats_is_not_allocated_without_explicit_method(self):
        import_operational_records({
            "beats": [{"beat_id": "B-1"}, {"beat_id": "B-2"}],
            "houses": [
                {"beat_id": "B-1", "house_id": "H-1"},
                {"beat_id": "B-2", "house_id": "H-2"},
            ],
            "collection_records": [
                {"date": "2026-10-28", "beat_id": "B-1", "house_id": "H-1",
                 "vehicle_id": "V-1", "trip_id": "T-1", "covered": True},
                {"date": "2026-10-28", "beat_id": "B-2", "house_id": "H-2",
                 "vehicle_id": "V-1", "trip_id": "T-1", "covered": True},
            ],
            "dumping_weights": [{
                "record_id": "D-1", "date": "2026-10-28",
                "vehicle_id": "V-1", "trip_id": "T-1",
                "weight": 400, "unit": "kg",
            }],
        })
        dashboard = get_dashboard()
        self.assertEqual(dashboard["kpis"]["total_weight_kg"], 400)
        self.assertEqual(dashboard["kpis"]["unallocated_weight_kg"], 400)
        self.assertTrue(all(beat["weight_kg"] is None for beat in dashboard["beats"]))

    def test_repeated_misses_require_explicit_false_records(self):
        import_operational_records({
            "beats": [{"beat_id": "B-1"}],
            "houses": [{"beat_id": "B-1", "house_id": "H-1"}],
            "collection_records": [
                {"date": "2026-10-28", "beat_id": "B-1", "house_id": "H-1",
                 "covered": False},
                {"date": "2026-10-29", "beat_id": "B-1", "house_id": "H-1",
                 "covered": False},
            ],
        })
        dashboard = get_dashboard()
        self.assertEqual(dashboard["repeatedly_missed_houses"], [{
            "beat_id": "B-1",
            "beat_name": "B-1",
            "house_id": "H-1",
            "missed_days": 2,
            "last_missed_date": "2026-10-29",
        }])
        self.assertEqual(dashboard["kpis"]["missed_houses"], 1)

    def test_invalid_date_range_is_reported(self):
        with self.assertRaisesRegex(ValueError, "on or before"):
            get_dashboard({
                "start_date": "2026-11-02",
                "end_date": "2026-10-01",
            })
        with self.assertRaisesRegex(ValueError, "Map date is required"):
            get_geographic_map()
        with self.assertRaisesRegex(ValueError, "Map date must be on or after"):
            get_geographic_map({
                "date": "2026-10-28",
                "start_date": "2026-10-29",
            })

    def test_dashboard_and_import_api_use_persistent_store(self):
        app = Flask(__name__)
        app.register_blueprint(analytics_bp)
        client = app.test_client()
        empty = client.get("/analytics/dashboard")
        self.assertEqual(empty.status_code, 200)
        self.assertFalse(empty.get_json()["data_available"])

        imported = client.post("/analytics/import", json={
            "beats": [{"beat_id": "B-1", "beat_name": "Actual beat"}],
            "houses": [{"beat_id": "B-1", "house_id": "H-1",
                        "lat": 20.01, "lon": 78.01}],
            "collection_records": [{
                "date": "2026-10-28", "beat_id": "B-1", "house_id": "H-1",
                "vehicle_id": "V-1", "covered": True,
            }],
            "gps_points": [{
                "vehicle_id": "V-1", "timestamp": "2026-10-28T08:00:00",
                "lat": 20.01, "lon": 78.01,
            }],
        })
        self.assertEqual(imported.status_code, 200)
        populated = client.get("/analytics/dashboard")
        self.assertTrue(populated.get_json()["data_available"])
        self.assertEqual(populated.get_json()["kpis"]["total_houses"], 1)
        map_response = client.get(
            "/analytics/map?date=2026-10-28&start_date=2026-10-28"
            "&end_date=2026-10-28&vehicle_id=V-1"
        )
        self.assertEqual(map_response.status_code, 200)
        self.assertTrue(map_response.get_json()["houses"][0]["has_recorded_collection"])
        self.assertEqual(map_response.get_json()["gps_point_count"], 1)


if __name__ == "__main__":
    unittest.main()
