# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

## Employee Route Planner

The Employee Route Planner tab can import one or more local JSON files. Each file should contain an array of daily records in this format:

```json
[
  {
    "date": "2026-10-18",
    "emproute": [
      {
        "datetime": "2026-10-18T08:00:00",
        "lat": 12.97,
        "lon": 77.59
      }
    ]
  }
]
```

The file name is used as the employee label because this response format does not include an employee identifier. Empty `emproute` arrays are accepted and shown as dates with no GPS data. Each coordinate in a non-empty `emproute` is treated as a timestamped garbage-vehicle GPS track point, not a house. Points are sorted by time and connected in that same order using drivable-road routes. The employee view shows the start truck marker, end flag, route map, per-segment "from → to" coordinates and times, and a streets/satellite layer selector.

This only maps the recorded route; it does not collect houses or reorder the GPS points. The employee route viewer sorts the supplied timestamped points and routes them through OSRM in the same order. It also compares Valhalla results when `VALHALLA_BASE_URL` is explicitly configured. OSRM is asked for full GeoJSON road geometry and per-step geometry; the backend verifies there is a road leg and geometry for each consecutive point pair. Large tracks are split into overlapping waypoint chunks; the shared snapped waypoint hint is reused to keep chunk endpoints aligned, and any remaining seam is explicitly routed over roads rather than drawn as a straight line. Valhalla route requests are chunked into ordered waypoints and its encoded polyline6 leg shapes are decoded into road geometry. The backend logs unroutable chunks/segments and GPS points snapped over 50 metres from their original coordinates. Either configured engine can be unavailable or return fewer viable alternatives.

By default, the backend uses the public OSRM demo and routing.openstreetmap.de as a fallback. House and vehicle coordinates are sent to the configured routing service. To keep routing local, explicitly set `OSRM_BASE_URL=http://127.0.0.1:5000` and start the self-hosted OSRM service described below. To add a Valhalla comparison, explicitly set `VALHALLA_BASE_URL` to a reachable Valhalla-compatible service. OSM road extracts can differ from the basemap, so a road shown on the map is not guaranteed to be routable. The employee map shows only the selected road alternative as a prominent blue line with a white outline. Raw GPS fixes are shown as small dots only; the app does not draw a straight line between them or stack every route on top of one another. OSRM geometry uses `[longitude, latitude]` in the API and is converted to Leaflet's `[latitude, longitude]` order. Valhalla geometry is decoded from encoded polyline6 in latitude/longitude order. The existing house-trip optimizer remains unchanged and continues to use its Overpass-backed graph logic.

The employee route viewer and Beat House Route Planner use OSRM and OpenStreetMap driving data; mapped residential and service roads are routable when present in the selected OSM extract. The public services are best-effort and may throttle or reject large route-matrix requests.

On Windows with Docker Desktop, prepare and start the local router with:

```powershell
cd D:\Agent\project_trajectory-main\Route_optimisation_backend\osrm
.\setup-osrm.ps1
```

The script downloads Geofabrik's Central Zone OSM extract (about 335 MB), prepares the OSRM road graph, starts the router container at `http://127.0.0.1:5000`, and checks that it is responding. This extract covers Nagpur and nearby central India. OSRM preprocessing may take several minutes and needs several GB of free disk space and memory. Keep Docker Desktop running while using the self-hosted router. The data files are kept in `Route_optimisation_backend\osrm\data` and are excluded from source control. OSM data is © OpenStreetMap contributors and is available under the ODbL. To stop the service, run `docker compose -f D:\Agent\project_trajectory-main\Route_optimisation_backend\osrm\docker-compose.yml down`.

To use the prepared local server instead of the public default, set `$env:OSRM_BASE_URL = "http://127.0.0.1:5000"` in the same PowerShell terminal before starting Flask. To explicitly use another OSRM-compatible service, set `OSRM_BASE_URL` to its base URL. To add a Valhalla comparison, explicitly set `VALHALLA_BASE_URL` to a reachable Valhalla-compatible service. Remote routing services receive the GPS/house coordinates used in their requests.

## Beat House Route Planner

The **Route Optimization** section contains the Beat House Route Planner. Upload one `.json` or `.txt` file containing JSON with a semicolon-separated `geofence` string (`lat,lon;lat,lon;...`), a `houses` array with `lat` and `lon` values (and optionally `house_id`), an optional `master_plate_id` on houses linked to a master plate, an optional `dumpyards` array with `lat` and `lon` values, and a `routes` array. Each route entry has a `date`, an `emproute` array of timestamped GPS points (`datetime`, `lat`, and `lon`), and optionally a `Collectionlist` array with scanned plate IDs in `referanceId` and scan coordinates in `lat` and `lon`. Collection scans are shown at their recorded coordinates even when the beat house list has no IDs. When `house_id` values are provided, a house is matched collected when its ID directly matches a scanned `referanceId`; `master_plate_id` links are only needed when a master scan represents multiple house IDs. Repeated distinct plate IDs at one scan coordinate are grouped as a master-plate scan location. Choose a day with GPS points. The planner uses that day's earliest and latest timestamped vehicle coordinates as fixed start and end locations.

The map displays only the selected day's historical GPS route and collection scan locations. Selecting another date clears the previous route result and uses only that date's GPS points as optimization endpoints and for the historical route comparison. Two playback controls let the user replay the selected day's actual GPS track and the optimized route. Planned route stops remain separate from confirmed collection records. The map button filters to ID-matched houses, or shows scan locations when house IDs are not supplied. Without house IDs, scan locations can be displayed but cannot reliably identify which beat-house markers were collected. Dumpyards are displayed as map markers and are not stops in the route.

Only houses inside the beat and within the configurable distance corridor of the selected day's timestamped GPS track are supplied to the optimizer; houses outside that corridor are excluded. Orange map markers identify these route candidates. The corridor is measured against the raw GPS trace and does not prove that a house was actually visited or collected. The selected date's earliest and latest timestamped GPS coordinates are fixed route endpoints. The selected day's road-matched GPS distance is a hard upper bound, reduced by 0.01 km so the displayed recommendation must be strictly shorter than the actual route; equal or longer candidates are discarded, and the user is told when no strictly shorter candidate is available. The backend requests a chunked OSRM distance-and-duration matrix for those endpoints and route-candidate houses, then uses Google OR-Tools guided local search with lexicographic weights: maximize houses planned within the distance limit, minimize road distance, then minimize estimated drive time. Up to four route candidates are compared in that priority order, with repeated road distance (estimated from repeated route-geometry segments) used as the final tie-breaker. The map compares the selected optimized route's distance/time with the selected day's road-matched historical trip. A planned stop is not proof of collection. Without accurate per-house service duration or live traffic, the estimate is driving time only and does not enforce a shift-time limit.

The default uses the public OSRM services described above; configure `OSRM_BASE_URL` to use the local Docker instance. A matrix for hundreds of houses can take time or be throttled. OR-Tools uses a bounded heuristic search and does not prove the global optimum. The map shows the optimized road route separately from the historical vehicle trip. Playback follows optimized road geometry. Actual and optimized road geometries are sampled at 25 m intervals against the beat polygon; detected outside sections are highlighted and their approximate distance is reported. The export currently has no approved access-connection dataset, so detected sections require review and are not claimed to be authorized. Vehicle capacity, shift-time and multi-dump-trip constraints are likewise not enforced unless their valid inputs are supplied.

## Employee Performance Analysis

The **Waste Collection Analytics** section is backed by Flask APIs at `/analytics/dashboard` and `/analytics/import`. There is no live operational database connection; uploaded records are merged/upserted into SQLite at `Route_optimisation_backend\data\operational_analytics.sqlite3`. Set `ANALYTICS_DB_PATH` to select another file and back it up with the operational source data. No sample records are seeded.

The import endpoint accepts a JSON object with any of these arrays:

```json
{
  "beats": [
    {
      "beat_id": "source-beat-id",
      "beat_name": "Source beat name",
      "state": "source state",
      "municipal_corporation": "source corporation",
      "zone": "source zone",
      "ward": "source ward",
      "geofence": "lat,lon;lat,lon;lat,lon"
    }
  ],
  "houses": [
    {"beat_id": "source-beat-id", "house_id": "source-house-id", "lat": 20.0, "lon": 78.0}
  ],
  "vehicles": [
    {"vehicle_id": "source-vehicle-id", "vehicle_name": "source name", "capacity_kg": 5000}
  ],
  "collection_records": [
    {
      "date": "2026-10-28",
      "beat_id": "source-beat-id",
      "house_id": "source-house-id",
      "vehicle_id": "source-vehicle-id",
      "trip_id": "source-trip-id",
      "covered": true
    }
  ],
  "gps_points": [
    {
      "vehicle_id": "source-vehicle-id",
      "beat_id": "source-beat-id",
      "trip_id": "source-trip-id",
      "timestamp": "2026-10-28T08:00:00",
      "lat": 20.0,
      "lon": 78.0
    }
  ],
  "dumping_weights": [
    {
      "record_id": "source-weighment-id",
      "date": "2026-10-28",
      "vehicle_id": "source-vehicle-id",
      "beat_id": "source-beat-id",
      "trip_id": "source-trip-id",
      "weight": 1250,
      "unit": "kg",
      "wet_weight": 700,
      "dry_weight": 550,
      "allocation_method": "unknown"
    }
  ]
}
```

The Employee Performance Analysis dashboard supports selecting multiple JSON/TXT operational files in one import. Select one file for each employee, enter a distinct employee ID beside every file, and select the dump-weight unit if it is not specified in the file; values are converted to kilograms. Then import; successful files are reported individually if another file fails. The ID is used to group that file's GPS, scan, dumping, and vehicle-associated records, and the **Employee** filter can show one employee or all employees. For existing schema compatibility, the employee ID is stored in the analytics vehicle grouping field; do not use this workflow when one file contains multiple employees. Re-imports for the same employee are merged into that employee's existing records.

The Analytics import also accepts the combined route-planner file directly (`.json` or `.txt` containing JSON) with root `geofence`, `houses`, and `routes`. GPS points are imported, and `Collectionlist` entries are saved as collection records. For this dataset, each collection-list `referanceId`/`referenceId` is the House ID, as confirmed by the operator. Unique reference IDs therefore count as houses recorded visited (once per day); repeated scans of one ID on the same day do not increase the house count. GPS movement alone is not counted as a visit. Combined-file house coordinates are linked to House IDs only when the house object contains an explicit ID and that ID maps consistently to one coordinate; ambiguous IDs are left unlinked. Re-import combined files after upgrading to establish these links for previously imported data. Combined-file `dumplist` events are counted as recorded dump trips. Their source total/wet/dry values are only used as measured weights when they are positive and an explicit recognized unit is supplied; zero or unitless values remain unavailable. This direct import does not infer capacity or an approved employee-to-area assignment.

The dashboard defaults to all dates and supports optional single-date and date-range filters. Its seven numbered sections cover Distance, Time, Houses Collected, Garbage Collection, Collection Efficiency, Collection Gap Analysis, and a Daily Performance Summary. The final Employee Progress & Development section requires one selected employee and compares their latest 7 calendar days with the preceding 7 days within the selected reporting period. A minimum of three recorded days in each period is required for each metric, and the overall status requires at least two independent measure groups. Trends use the employee's own history with a 10% change tolerance, not company-wide targets. House coverage remains unavailable without a verified assigned-house roster. Timeline, strengths, recurring patterns, areas to review, and recommendations are descriptive management aids, not proof of missed collections or an employee rating. Daily summary tables scroll within fixed-height areas. Houses per km and houses per GPS-observed hour are descriptive ratios, not employee-efficiency scores; GPS-observed time is not shift time. The time and gap sections calculate elapsed intervals between timestamped unique House IDs on the same employee-day. They may include travel, stops, dumping, or missing scans and do not prove wasted time. Longest and average gaps are aggregated across all intervals even when the displayed interval list is capped. Missing source data or zero denominators are shown as unavailable. Garbage weight from valid trips is shown separately from the complete total: if any recorded trip has a missing or zero weight, the complete period total and weight per trip remain unavailable, while valid measured trips can still contribute to a clearly labeled partial weight. Weight per recorded house also requires a complete valid total and unique-house count. The Geographic Collection and Movement map section is not displayed on the dashboard.

Daily collection-list comparisons show which House IDs appear on both selected days and which appear in only one day's list. Repeated House IDs are expected when a garbage vehicle revisits houses daily. Daily totals and IDs can vary with the assigned area, route, or collection load; IDs absent from a daily list do not by themselves prove a missed collection. The daily house table compares each date with House IDs already recorded on earlier selected-period dates in that calendar month. This is a list comparison, not a complete beat-house roster or missed-house count. Improvement Suggestions uses recorded patterns plus GPS coverage, duplicate/attribution checks, and weight completeness to offer review prompts; it does not label employees as poor performers or assume operational causes. Exact duplicate GPS/scan rows and IDs recorded under multiple employees are surfaced for review. House Collection History includes a collapsible grid summary. When house-master records link House IDs to coordinates, grid coverage counts distinct registered houses with a recorded collection ID. If only coordinate points without House IDs are available, the grid instead reports scan-location activity; those observations do not confirm house visits or grid coverage. House collection links require an exact unique House ID match or explicit covered collection record; GPS proximity alone is never treated as a visit. Missing coordinates and IDs remain unavailable. House-history absence means no list record, not proof of a missed visit. Dump weights require positive recorded values and known units; a missing/zero weight is unavailable, not zero waste.

For explicit collection records, provide a house master with stable IDs and dated records with `covered: true/false`. For the combined route export, the collection-list reference field is treated as the House ID according to the confirmed source format. Employee-specific GPS files containing only `date` and `emproute` can be selected with other employee files; assign each file its employee ID in the import form. Dumping weights require a vehicle, date, positive numeric total weight and `kg` or `tonnes`; `wet_weight` and `dry_weight` are optional recorded component weights (with optional `wet_unit`/`dry_unit`, otherwise they use `unit`). When both positive components are present and total weight is omitted, total is their sum. Missing or zero weights remain unavailable. Stable `record_id` values are recommended for repeat imports. `vehicles.capacity_kg` is optional and must be an actual recorded capacity.

Weight is stored in kilograms. A weighment is not assigned to a beat just because a vehicle served that beat. For a trip that spans multiple beats, set `allocation_method` to `trip_total` only when the weight is the total load for that identified trip; it is then apportioned by that trip's distinct covered-house counts and labeled estimated. Use `beat_direct` only for an explicitly measured/allocated beat weight. Ambiguous records remain visible in vehicle/overall totals and are reported as unallocated instead of being guessed into beat totals. Weight per covered house is disposal weight divided by recorded covered houses; it is not household waste generation.

Linked operational-bundle imports can additionally use beat coverage tables and maps, explicit missed-house records, and weight-allocation summaries. GPS distance is point-to-point, not road-matched. GPS-observed time is not an engine-on measurement. The original 10-day sample has 10 dates with GPS/scans and matching route dates, 2,011 coordinate records (2,008 unique locations), 8,243 GPS points, 15,748 scan events, and 9 dump events. The operator confirmed that each collection reference ID represents a House ID, so unique IDs are used for daily recorded-visit counts and history. The coordinate-only house list still has no IDs, so it cannot identify House IDs absent from all collection records or assign every scanned house to a beat. All nine dump events have zero weights, so garbage weight remains unavailable.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Babel](https://babeljs.io/) for Fast Refresh
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/) for Fast Refresh

## Expanding the ESLint configuration

If you are developing a production application, we recommend updating the configuration to enable type-aware lint rules:

```js
export default tseslint.config([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...

      // Remove tseslint.configs.recommended and replace with this
      ...tseslint.configs.recommendedTypeChecked,
      // Alternatively, use this for stricter rules
      ...tseslint.configs.strictTypeChecked,
      // Optionally, add this for stylistic rules
      ...tseslint.configs.stylisticTypeChecked,

      // Other configs...
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])
```

You can also install [eslint-plugin-react-x](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-x) and [eslint-plugin-react-dom](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-dom) for React-specific lint rules:

```js
// eslint.config.js
import reactX from 'eslint-plugin-react-x'
import reactDom from 'eslint-plugin-react-dom'

export default tseslint.config([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...
      // Enable lint rules for React
      reactX.configs['recommended-typescript'],
      // Enable lint rules for React DOM
      reactDom.configs.recommended,
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])
```
