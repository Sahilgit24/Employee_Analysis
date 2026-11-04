import React, {useMemo, useState} from "react";
import L from "leaflet";
import {CircleMarker, MapContainer, Marker, Polyline, Popup, TileLayer, useMap} from "react-leaflet";
import {API_URL} from "@/config.js";

const startIcon = L.divIcon({
    className: "",
    html: '<div style="font-size:30px;line-height:34px;text-shadow:0 1px 3px #fff" title="Truck start">🚛</div>',
    iconSize: [36, 36],
    iconAnchor: [18, 30],
});
const endIcon = L.divIcon({
    className: "",
    html: '<div style="font-size:28px;line-height:34px;text-shadow:0 1px 3px #fff" title="Route end">🏁</div>',
    iconSize: [36, 36],
    iconAnchor: [18, 30],
});

function normalizeEmployeeFile(fileName, data, index) {
    if (!Array.isArray(data)) {
        throw new Error(`${fileName} must contain a JSON array of dated route records.`);
    }

    const days = data.map((record, dayIndex) => {
        if (!record || !record.date || !Array.isArray(record.emproute)) {
            throw new Error(`${fileName} has an invalid record at item ${dayIndex + 1}.`);
        }

        const trackPoints = record.emproute.map((point, pointIndex) => {
            const lat = Number(point?.lat);
            const lon = Number(point?.lon);
            const timestamp = Date.parse(point?.datetime);
            if (
                !Number.isFinite(lat) ||
                !Number.isFinite(lon) ||
                Math.abs(lat) > 90 ||
                Math.abs(lon) > 180 ||
                !Number.isFinite(timestamp)
            ) {
                throw new Error(`${fileName} has an invalid GPS coordinate or timestamp on ${record.date} (point ${pointIndex + 1}).`);
            }
            return {lat, lon, timestamp, datetime: point.datetime};
        }).sort((a, b) => a.timestamp - b.timestamp);

        return {date: String(record.date), trackPoints};
    }).sort((a, b) => a.date.localeCompare(b.date));

    return {
        id: `${fileName}-${index}`,
        name: fileName.replace(/\.[^.]+$/, "") || `Employee ${index + 1}`,
        days,
    };
}

function FitRouteBounds({points, visible}) {
    const map = useMap();
    React.useEffect(() => {
        if (!visible || points.length === 0) return;
        if (points.length === 1) {
            map.setView([points[0].lat, points[0].lon], 15);
        } else {
            map.fitBounds(points.map((point) => [point.lat, point.lon]), {padding: [24, 24]});
        }
    }, [map, points, visible]);
    return null;
}

function RouteMap({trackPoints, alternatives, selectedRouteId, layer, visible}) {
    const selectedRoute = alternatives.find((route) => route.route_id === selectedRouteId);
    const points = useMemo(
        () => [...trackPoints, ...(selectedRoute?.route_path || [])],
        [trackPoints, selectedRoute]
    );
    const center = points.length ? [points[0].lat, points[0].lon] : [0, 0];
    const tileUrl = layer === "satellite"
        ? "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
        : "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
    return (
        <MapContainer center={center} zoom={13} className="h-full w-full">
            <TileLayer
                attribution={layer === "satellite"
                    ? "Tiles &copy; Esri"
                    : '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}
                url={tileUrl}
            />
            <FitRouteBounds points={points} visible={visible}/>
            {trackPoints.slice(1, -1).map((point, index) => (
                <CircleMarker
                    key={`${point.timestamp}-${index + 1}`}
                    center={[point.lat, point.lon]}
                    radius={2}
                    pathOptions={{color: "#334155", weight: 1, opacity: 0.55, fillColor: "#fff", fillOpacity: 0.7}}
                >
                    <Popup>
                        Track point {index + 2}
                        <br/>
                        {new Date(point.timestamp).toLocaleString()}
                        <br/>
                        {point.lat.toFixed(6)}, {point.lon.toFixed(6)}
                    </Popup>
                </CircleMarker>
            ))}
            {selectedRoute?.route_path?.length > 1 && (
                <>
                    <Polyline
                        positions={selectedRoute.route_path.map((point) => [point.lat, point.lon])}
                        pathOptions={{color: "#fff", weight: 10, opacity: 0.95, lineCap: "round", lineJoin: "round"}}
                        smoothFactor={0}
                    />
                    <Polyline
                        positions={selectedRoute.route_path.map((point) => [point.lat, point.lon])}
                        pathOptions={{color: "#075de8", weight: 6, opacity: 1, lineCap: "round", lineJoin: "round"}}
                        smoothFactor={0}
                    />
                </>
            )}
            {trackPoints.length > 0 && (
                <>
                    <Marker position={[trackPoints[0].lat, trackPoints[0].lon]} icon={startIcon}>
                        <Popup>
                            Truck start
                            <br/>
                            {new Date(trackPoints[0].timestamp).toLocaleString()}
                            <br/>
                            {trackPoints[0].lat.toFixed(6)}, {trackPoints[0].lon.toFixed(6)}
                        </Popup>
                    </Marker>
                    {trackPoints.length > 1 && (
                        <Marker
                            position={[trackPoints[trackPoints.length - 1].lat, trackPoints[trackPoints.length - 1].lon]}
                            icon={endIcon}
                        >
                            <Popup>
                                Route end
                                <br/>
                                {new Date(trackPoints[trackPoints.length - 1].timestamp).toLocaleString()}
                                <br/>
                                {trackPoints[trackPoints.length - 1].lat.toFixed(6)}, {trackPoints[trackPoints.length - 1].lon.toFixed(6)}
                            </Popup>
                        </Marker>
                    )}
                </>
            )}
        </MapContainer>
    );
}

export default function EmployeeHistoryPlanner({visible = true}) {
    const [employees, setEmployees] = useState([]);
    const [selectedEmployeeId, setSelectedEmployeeId] = useState("");
    const [selectedDate, setSelectedDate] = useState("");
    const [layer, setLayer] = useState("streets");
    const [alternatives, setAlternatives] = useState([]);
    const [selectedRouteId, setSelectedRouteId] = useState("");
    const [loadingFile, setLoadingFile] = useState(false);
    const [loadingRoute, setLoadingRoute] = useState(false);
    const [error, setError] = useState("");
    const [notice, setNotice] = useState("");

    const employee = employees.find((item) => item.id === selectedEmployeeId) || null;
    const day = employee?.days.find((item) => item.date === selectedDate) || null;
    const trackPoints = day?.trackPoints || [];
    const mapKey = `${selectedEmployeeId}-${selectedDate}`;
    const selectedRoute = alternatives.find((route) => route.route_id === selectedRouteId) || null;

    const handleFiles = async (event) => {
        const files = Array.from(event.target.files || []);
        if (!files.length) return;

        setLoadingFile(true);
        setError("");
        setNotice("");
        clearRoute();
        try {
            const loaded = await Promise.all(files.map(async (file, index) => {
                const data = JSON.parse(await file.text());
                return normalizeEmployeeFile(file.name, data, index);
            }));
            setEmployees(loaded);
            setSelectedEmployeeId(loaded[0]?.id || "");
            setSelectedDate(loaded[0]?.days[0]?.date || "");
            setNotice(`Loaded ${loaded.length} employee file${loaded.length === 1 ? "" : "s"}.`);
        } catch (fileError) {
            setEmployees([]);
            setSelectedEmployeeId("");
            setSelectedDate("");
            setError(fileError.message || "Could not read the selected JSON file.");
        } finally {
            setLoadingFile(false);
            event.target.value = "";
        }
    };

    const clearRoute = () => {
        setAlternatives([]);
        setSelectedRouteId("");
    };

    const handleOptimize = async () => {
        if (!day || trackPoints.length === 0) return;

        setLoadingRoute(true);
        setError("");
        setNotice("");
        clearRoute();

        try {
            const response = await fetch(`${API_URL}/optimize_employee_route`, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    track_points: trackPoints.map(({lat, lon, datetime}) => ({lat, lon, datetime})),
                }),
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.message || `Route request failed (HTTP ${response.status}).`);
            }
            if (!Array.isArray(data.track_points) || data.track_points.length !== trackPoints.length) {
                throw new Error("The routing service did not return every timestamped track point.");
            }
            if (!Array.isArray(data.alternatives) || data.alternatives.length === 0) {
                throw new Error("The routing service returned no route alternatives.");
            }
            const validAlternatives = data.alternatives.filter(
                (route) => Array.isArray(route.route_path) &&
                    route.route_path.length >= (trackPoints.length > 1 ? 2 : 1) &&
                    Array.isArray(route.segments) &&
                    route.segments.length === trackPoints.length - 1
            );
            if (validAlternatives.length === 0) {
                throw new Error("The routing service did not return full road geometry and one routed segment for every consecutive GPS-point pair.");
            }
            setAlternatives(validAlternatives);
            setSelectedRouteId(validAlternatives[0].route_id);
            const snapNotice = data.off_road_snap_count > 0
                ? ` ${data.off_road_snap_count} GPS point${data.off_road_snap_count === 1 ? " was" : "s were"} snapped more than 50 m to a road; check the backend log for coordinates.`
                : "";
            const alternativeNotice = validAlternatives.length === 1
                ? "The router returned one route."
                : `${validAlternatives.length} routes are available; select one to compare OSRM and Valhalla road geometry.`;
            const providerNotice = Array.isArray(data.routing_providers)
                ? ` Available engines: ${data.routing_providers.join(" + ")}.`
                : "";
            const providerErrorNotice = Array.isArray(data.provider_errors) && data.provider_errors.length > 0
                ? ` Some engines were unavailable: ${data.provider_errors.join("; ")}.`
                : "";
            setNotice(
                `${alternativeNotice} The map shows full-resolution drivable-road geometry; recorded GPS fixes are dots only and are not joined with straight lines.` +
                providerNotice +
                (trackPoints.length > 1
                    ? ` ${data.geometry_vertex_count} road geometry vertices across ${trackPoints.length - 1} consecutive point-to-point segments.`
                    : " Only one GPS point was supplied, so there is no road segment to draw.") +
                snapNotice +
                providerErrorNotice
            );
        } catch (routeError) {
            setError(`Could not map this route: ${routeError.message || routeError}`);
        } finally {
            setLoadingRoute(false);
        }
    };

    const handleEmployeeChange = (event) => {
        const nextEmployee = employees.find((item) => item.id === event.target.value);
        setSelectedEmployeeId(event.target.value);
        setSelectedDate(nextEmployee?.days[0]?.date || "");
        clearRoute();
        setError("");
        setNotice("");
    };

    const handleDateChange = (event) => {
        setSelectedDate(event.target.value);
        clearRoute();
        setError("");
        setNotice("");
    };

    return (
        <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-slate-50 p-4">
            <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-4">
                <section className="rounded-xl bg-white p-5 shadow-sm">
                    <h1 className="text-2xl font-bold text-slate-900">Garbage Vehicle Route Viewer</h1>
                    <p className="mt-1 text-sm text-slate-600">
                        GPS coordinates are vehicle track points, not houses. Points are kept in timestamp order and connected by shortest available drivable-road paths.
                    </p>
                    <div className="mt-4 flex flex-wrap items-end gap-4">
                        <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
                            Employee route JSON
                            <input
                                type="file"
                                accept=".json,.txt,application/json,text/plain"
                                multiple
                                onChange={handleFiles}
                                className="max-w-xs rounded border border-slate-300 p-2 text-sm"
                            />
                        </label>
                        {employees.length > 0 && (
                            <>
                                <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
                                    Employee
                                    <select
                                        value={selectedEmployeeId}
                                        onChange={handleEmployeeChange}
                                        className="rounded border border-slate-300 bg-white p-2"
                                    >
                                        {employees.map((item) => (
                                            <option key={item.id} value={item.id}>{item.name}</option>
                                        ))}
                                    </select>
                                </label>
                                <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
                                    Route date
                                    <select
                                        value={selectedDate}
                                        onChange={handleDateChange}
                                        className="rounded border border-slate-300 bg-white p-2"
                                    >
                                        {employee?.days.map((item) => (
                                            <option key={item.date} value={item.date}>{item.date}</option>
                                        ))}
                                    </select>
                                </label>
                                <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
                                    Map style
                                    <select
                                        value={layer}
                                        onChange={(event) => setLayer(event.target.value)}
                                        className="rounded border border-slate-300 bg-white p-2"
                                    >
                                        <option value="streets">Streets</option>
                                        <option value="satellite">Satellite</option>
                                    </select>
                                </label>
                                <button
                                    type="button"
                                    onClick={handleOptimize}
                                    disabled={loadingRoute || trackPoints.length === 0}
                                    className="rounded-lg bg-blue-700 px-4 py-2 font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
                                >
                                    {loadingRoute ? "Finding road routes…" : "Find road route alternatives"}
                                </button>
                            </>
                        )}
                    </div>
                    {loadingFile && <p className="mt-3 text-sm text-slate-600">Reading files…</p>}
                    {loadingRoute && (
                        <p className="mt-3 text-sm text-slate-600">
                            Requesting up to three road routes through the timestamped points in order. This can take a little while.
                        </p>
                    )}
                    {error && <p role="alert" className="mt-3 rounded bg-red-50 p-3 text-sm text-red-700">{error}</p>}
                    {notice && <p role="status" className="mt-3 rounded bg-blue-50 p-3 text-sm text-blue-800">{notice}</p>}
                </section>

                {day && (
                    <>
                        {trackPoints.length > 0 ? (
                            <>
                        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                            <div className="rounded-xl bg-white p-4 shadow-sm">
                                <div className="text-sm text-slate-500">Timestamped GPS points</div>
                                <div className="mt-1 text-2xl font-semibold">{trackPoints.length}</div>
                            </div>
                            <div className="rounded-xl bg-white p-4 shadow-sm">
                                <div className="text-sm text-slate-500">Start time</div>
                                <div className="mt-1 text-lg font-semibold">
                                    {trackPoints[0] ? new Date(trackPoints[0].timestamp).toLocaleTimeString() : "—"}
                                </div>
                            </div>
                            <div className="rounded-xl bg-white p-4 shadow-sm">
                                <div className="text-sm text-slate-500">End time</div>
                                <div className="mt-1 text-lg font-semibold">
                                    {trackPoints.at(-1) ? new Date(trackPoints.at(-1).timestamp).toLocaleTimeString() : "—"}
                                </div>
                            </div>
                            <div className="rounded-xl bg-white p-4 shadow-sm">
                                <div className="text-sm text-slate-500">Route alternatives</div>
                                <div className="mt-1 text-2xl font-semibold">{alternatives.length || "—"}</div>
                            </div>
                        </section>

                        <section className="grid min-h-[620px] flex-1 gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
                            <div className="min-h-[400px] overflow-hidden rounded-xl bg-white shadow-sm">
                                <RouteMap
                                    key={`${mapKey}-${layer}`}
                                    trackPoints={trackPoints}
                                    alternatives={alternatives}
                                    selectedRouteId={selectedRouteId}
                                    layer={layer}
                                    visible={visible}
                                />
                            </div>
                            <aside className="flex flex-col gap-3 rounded-xl bg-white p-4 text-sm text-slate-600 shadow-sm">
                                <div>
                                    <h2 className="font-semibold text-slate-900">Recorded route sequence</h2>
                                    <p className="mt-2">Truck icon: start · Checkered flag: end.</p>
                                    <p>Small gray dots: recorded GPS fixes, shown without connecting lines.</p>
                                    <p>Blue line: selected full-resolution drivable-road geometry, following points in timestamp order.</p>
                                </div>
                                {alternatives.length > 0 && (
                                    <fieldset className="space-y-2">
                                        <legend className="font-semibold text-slate-900">Compare routes</legend>
                                        {alternatives.map((route, index) => (
                                            <label
                                                key={route.route_id}
                                                className={`flex cursor-pointer items-start gap-2 rounded border p-3 ${
                                                    route.route_id === selectedRouteId
                                                        ? "border-blue-600 bg-blue-50"
                                                        : "border-slate-200"
                                                }`}
                                            >
                                                <input
                                                    type="radio"
                                                    name="employee-route-alternative"
                                                    value={route.route_id}
                                                    checked={route.route_id === selectedRouteId}
                                                    onChange={() => setSelectedRouteId(route.route_id)}
                                                />
                                                <span>
                                                    <span className="block font-medium text-slate-900">
                                                        {route.label || `Route ${index + 1}`}
                                                    </span>
                                                    <span className="text-xs text-slate-600">
                                                        {route.distance_km} km · {route.duration_minutes} min
                                                    </span>
                                                </span>
                                            </label>
                                        ))}
                                    </fieldset>
                                )}
                                {selectedRoute && (
                                    <p className="font-semibold text-slate-900">
                                        Selected: {selectedRoute.distance_km} km · {selectedRoute.duration_minutes} min
                                    </p>
                                )}
                                <div className="max-h-[520px] overflow-y-auto rounded border border-slate-200">
                                    <table className="w-full text-left text-xs">
                                        <thead className="sticky top-0 bg-slate-100 text-slate-700">
                                            <tr>
                                                <th className="p-2">From → To</th>
                                                <th className="p-2">Time</th>
                                                <th className="p-2">Road km</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {selectedRoute?.segments.map((segment) => (
                                                <tr key={`${segment.from_sequence}-${segment.to_sequence}`} className="border-t">
                                                    <td className="p-2">
                                                        <div className="font-medium">
                                                            Point {segment.from_sequence} → Point {segment.to_sequence}
                                                        </div>
                                                        <div className="mt-1 text-slate-500">
                                                            {segment.from_lat.toFixed(5)}, {segment.from_lon.toFixed(5)}
                                                            {" → "}
                                                            {segment.to_lat.toFixed(5)}, {segment.to_lon.toFixed(5)}
                                                        </div>
                                                    </td>
                                                    <td className="whitespace-nowrap p-2">
                                                        {new Date(segment.from_datetime).toLocaleTimeString()}
                                                        {" → "}
                                                        {new Date(segment.to_datetime).toLocaleTimeString()}
                                                    </td>
                                                    <td className="whitespace-nowrap p-2">{segment.distance_km}</td>
                                                </tr>
                                            ))}
                                            {!selectedRoute?.segments.length && (
                                                <tr>
                                                    <td className="p-3 text-slate-500" colSpan="3">
                                                        Select Find road route alternatives to calculate routes and segment distances.
                                                    </td>
                                                </tr>
                                            )}
                                        </tbody>
                                    </table>
                                </div>
                            </aside>
                        </section>
                            </>
                        ) : (
                            <p role="status" className="rounded-xl bg-amber-50 p-4 text-sm text-amber-800">
                                No GPS points are recorded for {day.date}. Choose another date to view or route the vehicle track.
                            </p>
                        )}
                    </>
                )}
            </div>
        </div>
    );
}
