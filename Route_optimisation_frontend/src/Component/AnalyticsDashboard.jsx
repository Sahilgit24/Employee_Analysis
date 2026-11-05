import {useEffect, useMemo, useState} from "react";
import {CircleMarker, MapContainer, Polygon, Polyline, Popup, TileLayer, Tooltip, useMap} from "react-leaflet";
import {API_URL} from "@/config.js";

function MetricCard({label, value, detail}) {
    return (
        <article className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition-shadow hover:shadow-md">
            <p className="text-xs font-semibold tracking-wide text-slate-500">{label}</p>
            <p className="mt-2 text-2xl font-bold tracking-tight text-slate-900">{value}</p>
            {detail && <p className="mt-1 text-xs leading-5 text-slate-500">{detail}</p>}
        </article>
    );
}

function TrendChart({title, rows, valueKey, color, unit = "", emptyMessage}) {
    const maximum = Math.max(0, ...rows.map((row) => Number(row[valueKey]) || 0));
    return (
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h3 className="mb-3 text-sm font-semibold text-slate-800">{title}</h3>
            {!rows.length ? (
                <p className="py-8 text-center text-sm text-slate-500">{emptyMessage}</p>
            ) : (
                <div className="flex h-44 items-end gap-2 overflow-x-auto border-b border-l px-2">
                    {rows.map((row) => {
                        const value = Number(row[valueKey]) || 0;
                        const period = row.period || row.date;
                        const hasValue = row[valueKey] != null;
                        const height = maximum > 0 ? Math.max(value > 0 ? 3 : 0, value / maximum * 100) : 0;
                        return (
                            <div key={period} className="flex h-full min-w-8 flex-1 flex-col items-center justify-end gap-1">
                                <span className="max-w-20 truncate text-[10px] text-slate-500">
                                    {hasValue ? `${formatNumber(value)}${unit}` : "—"}
                                </span>
                                <div
                                    className="w-full min-w-4 rounded-t"
                                    style={{height: `${height}%`, backgroundColor: color}}
                                    aria-label={`${period}: ${hasValue ? `${value}${unit}` : "Unavailable"}`}
                                />
                                <span className="mb-1 max-w-20 truncate text-[10px] text-slate-600">{period}</span>
                            </div>
                        );
                    })}
                </div>
            )}
        </section>
    );
}

function DataTable({headers, rows, emptyMessage, minWidth = "600px", maxHeight}) {
    return (
        <div className={`${maxHeight ? "overflow-auto" : "overflow-x-auto"} rounded-lg border bg-white p-4`}
            style={maxHeight ? {maxHeight} : undefined}>
            <table className="w-full text-left text-sm" style={{minWidth}}>
                <thead className={`border-b bg-slate-50 text-xs font-semibold text-slate-500 ${maxHeight ? "sticky top-0 z-10" : ""}`}>
                    <tr>{headers.map((header) => <th key={header} className="px-3 py-3 first:pl-2">{header}</th>)}</tr>
                </thead>
                <tbody>
                    {rows}
                    {!rows.length && (
                        <tr><td colSpan={headers.length} className="py-8 text-center text-slate-500">{emptyMessage}</td></tr>
                    )}
                </tbody>
            </table>
        </div>
    );
}

function HouseHistoryTable({title, rows, showDates = false, emptyMessage}) {
    return (
        <section className="space-y-2">
            <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
            <DataTable
                headers={showDates ? ["House ID", "Recorded days", "Recorded dates"] : ["House ID", "Area / beat"]}
                rows={rows.map((row) => (
                    <tr key={row.house_id} className="border-b last:border-0">
                        <td className="py-2 pr-3 font-medium">{row.house_id}</td>
                        {showDates ? (
                            <>
                                <td className="py-2 pr-3">{formatNumber(row.visit_days, 0)}</td>
                                <td className="py-2">
                                    <div className="max-h-20 max-w-[26rem] overflow-auto whitespace-normal break-words">
                                        {(row.visit_dates || []).join(", ") || "—"}
                                    </div>
                                </td>
                            </>
                        ) : (
                            <td className="py-2">{row.beat_name || row.beat_id || "Unavailable"}</td>
                        )}
                    </tr>
                ))}
                emptyMessage={emptyMessage}
                minWidth={showDates ? "620px" : "420px"}
                maxHeight="18rem"
            />
        </section>
    );
}

function CollectionDayComparison({dates, references}) {
    const [firstDate, setFirstDate] = useState("");
    const [secondDate, setSecondDate] = useState("");

    useEffect(() => {
        if (!dates.length) {
            setFirstDate("");
            setSecondDate("");
            return;
        }
        const latest = dates[dates.length - 1];
        const previous = dates.length > 1 ? dates[dates.length - 2] : latest;
        if (!dates.includes(firstDate)) setFirstDate(previous);
        if (!dates.includes(secondDate) || secondDate === firstDate) setSecondDate(latest);
    }, [dates.join(","), firstDate, secondDate]);

    const firstHouseIds = new Set(
        references.filter((row) => row.collection_dates?.includes(firstDate))
            .map((row) => row.house_id)
    );
    const secondHouseIds = new Set(
        references.filter((row) => row.collection_dates?.includes(secondDate))
            .map((row) => row.house_id)
    );
    const comparisonRows = [...new Set([...firstHouseIds, ...secondHouseIds])]
        .sort((a, b) => a.localeCompare(b))
        .map((houseId) => {
            const recordedFirst = firstHouseIds.has(houseId);
            const recordedSecond = secondHouseIds.has(houseId);
            return (
                <tr key={houseId} className="border-b last:border-0">
                    <td className="px-3 py-2 font-medium">{houseId}</td>
                    <td className="px-3 py-2">{recordedFirst ? "Recorded" : "No record"}</td>
                    <td className="px-3 py-2">{recordedSecond ? "Recorded" : "No record"}</td>
                    <td className="px-3 py-2">
                        {recordedFirst && !recordedSecond
                            ? `In ${firstDate} list only`
                            : recordedSecond && !recordedFirst
                                ? `In ${secondDate} list only`
                                : "In both daily lists"}
                    </td>
                </tr>
            );
        });

    return (
        <section className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div>
                <h3 className="text-sm font-semibold text-slate-900">Compare collection lists by day</h3>
                <p className="mt-1 text-xs text-slate-600">
                    The vehicle may collect from the same houses every day, so repeated House IDs are expected. This compares which IDs appear in each day’s list; differences can reflect the assigned area, route, or collection load and do not by themselves mean a house was missed.
                </p>
            </div>
            {dates.length > 1 ? (
                <>
                    <div className="grid gap-3 sm:grid-cols-2">
                        <label className="grid gap-1 text-xs font-medium text-slate-600">
                            First day
                            <select className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800"
                                value={firstDate} onChange={(event) => setFirstDate(event.target.value)}>
                                {dates.map((date) => (
                                    <option key={date} value={date} disabled={date === secondDate}>{date}</option>
                                ))}
                            </select>
                        </label>
                        <label className="grid gap-1 text-xs font-medium text-slate-600">
                            Compare with
                            <select className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800"
                                value={secondDate} onChange={(event) => setSecondDate(event.target.value)}>
                                {dates.map((date) => (
                                    <option key={date} value={date} disabled={date === firstDate}>{date}</option>
                                ))}
                            </select>
                        </label>
                    </div>
                    <div className="flex flex-wrap gap-2 text-xs">
                        <span className="rounded-full bg-teal-100 px-3 py-1 font-medium text-teal-800">
                            {formatNumber(firstHouseIds.size, 0)} recorded on {firstDate}
                        </span>
                        <span className="rounded-full bg-blue-100 px-3 py-1 font-medium text-blue-800">
                            {formatNumber(secondHouseIds.size, 0)} recorded on {secondDate}
                        </span>
                        <span className="rounded-full bg-slate-100 px-3 py-1 font-medium text-slate-700">
                            {formatNumber([...firstHouseIds].filter((id) => secondHouseIds.has(id)).length, 0)} recorded on both days
                        </span>
                        <span className="rounded-full bg-slate-100 px-3 py-1 font-medium text-slate-700">
                            {formatNumber([...firstHouseIds].filter((id) => !secondHouseIds.has(id)).length, 0)} recorded on first day only
                        </span>
                        <span className="rounded-full bg-slate-100 px-3 py-1 font-medium text-slate-700">
                            {formatNumber([...secondHouseIds].filter((id) => !firstHouseIds.has(id)).length, 0)} recorded on second day only
                        </span>
                    </div>
                    <DataTable
                        headers={["House ID", firstDate || "First day", secondDate || "Compare day", "Comparison"]}
                        rows={comparisonRows}
                        emptyMessage="No House IDs are recorded on either selected day."
                        minWidth="640px"
                        maxHeight="20rem"
                    />
                    <p className="text-xs text-slate-500">
                        The comparison uses House IDs that appear in the selected employee’s daily collection lists. It describes list overlap only; it is not a complete beat-house roster unless all houses are represented in those lists.
                    </p>
                </>
            ) : (
                <p className="rounded-lg border bg-white p-3 text-sm text-slate-600">
                    Upload records for at least two dates to compare collection lists.
                </p>
            )}
        </section>
    );
}

function FitMapBounds({points}) {
    const map = useMap();
    useEffect(() => {
        if (points.length === 1) map.setView(points[0], 15);
        else if (points.length > 1) map.fitBounds(points, {padding: [24, 24]});
    }, [map, points]);
    return null;
}

function GeographicMap({data}) {
    const [showHouses, setShowHouses] = useState(true);
    const [showCollections, setShowCollections] = useState(true);
    const [showGps, setShowGps] = useState(true);
    const [showBeats, setShowBeats] = useState(true);
    const segments = data?.route_segments || [];
    const houses = data?.houses || [];
    const anonymousHouses = data?.anonymous_house_locations || [];
    const collections = data?.collection_locations || [];
    const points = useMemo(() => [
        ...(showHouses ? houses.map((item) => [item.lat, item.lon]) : []),
        ...(showHouses ? anonymousHouses.map((item) => [item.lat, item.lon]) : []),
        ...(showCollections ? collections.map((item) => [item.lat, item.lon]) : []),
        ...(showGps ? segments.flatMap((segment) => segment.points.map((item) => [item.lat, item.lon])) : []),
        ...(showBeats ? (data?.beats || []).flatMap((beat) => beat.polygon) : []),
    ], [anonymousHouses, collections, data?.beats, houses, segments, showBeats, showCollections, showGps, showHouses]);
    const chronologicalPoints = segments
        .flatMap((segment) => segment.points)
        .sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp));
    const tablePoints = chronologicalPoints.length > 500
        ? chronologicalPoints.filter((_, index) => index % Math.ceil(chronologicalPoints.length / 500) === 0)
        : chronologicalPoints;

    return (
        <div className="space-y-3">
            <div className="flex flex-wrap gap-4 rounded border bg-white p-3 text-sm">
                <label className="flex items-center gap-2"><input type="checkbox" checked={showHouses} onChange={(event) => setShowHouses(event.target.checked)}/> Houses</label>
                <label className="flex items-center gap-2"><input type="checkbox" checked={showCollections} onChange={(event) => setShowCollections(event.target.checked)}/> Collection locations</label>
                <label className="flex items-center gap-2"><input type="checkbox" checked={showGps} onChange={(event) => setShowGps(event.target.checked)}/> GPS route</label>
                <label className="flex items-center gap-2"><input type="checkbox" checked={showBeats} onChange={(event) => setShowBeats(event.target.checked)}/> Beat boundaries</label>
                <span className="text-xs text-slate-500">Green: recorded collection · Red: no record · Yellow: unclear ID/coordinate · Blue: collection scan · Purple: GPS route</span>
            </div>
            {points.length ? (
                <div className="h-[440px] overflow-hidden rounded-lg border">
                    <MapContainer center={points[0]} zoom={13} className="h-full w-full" scrollWheelZoom>
                        <TileLayer
                            attribution="&copy; OpenStreetMap contributors"
                            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                        />
                        <FitMapBounds points={points}/>
                        {showBeats && (data.beats || []).map((beat) => (
                            <Polygon key={beat.beat_id} positions={beat.polygon}
                                pathOptions={{color: "#475569", fillOpacity: 0.02, weight: 2, dashArray: "6 5"}}>
                                <Popup>{beat.beat_name} boundary. The data does not confirm employee assignment to this beat.</Popup>
                            </Polygon>
                        ))}
                        {showGps && segments.map((segment) => segment.points.length > 1 && (
                            <Polyline key={`${segment.vehicle_id}-${segment.trip_id}-${segment.beat_id}`}
                                positions={segment.points.map((point) => [point.lat, point.lon])}
                                pathOptions={{color: "#7c3aed", weight: 3, opacity: 0.75}}>
                                <Popup>
                                    GPS route for {segment.vehicle_id}, trip {segment.trip_id || "not identified"}.
                                    {" "}Recorded beat: {segment.beat_id || "Unavailable"}.
                                    {" "}{segment.points[0]?.timestamp} to {segment.points[segment.points.length - 1]?.timestamp}
                                </Popup>
                            </Polyline>
                        ))}
                        {showGps && segments.flatMap((segment) => {
                            const routeEnds = segment.points.length > 1
                                ? [segment.points[0], segment.points[segment.points.length - 1]]
                                : segment.points;
                            return routeEnds.map((point, index) => (
                                <CircleMarker key={`gps-end-${segment.vehicle_id}-${segment.trip_id}-${segment.beat_id}-${index}`}
                                    center={[point.lat, point.lon]} radius={4}
                                    pathOptions={{color: "#6d28d9", fillColor: "#a78bfa", fillOpacity: 0.9}}>
                                    <Popup>
                                        GPS point for {segment.vehicle_id}, trip {segment.trip_id || "not identified"}.<br/>
                                        Recorded beat: {segment.beat_id || "Unavailable"}<br/>
                                        Time: {point.timestamp || "Unavailable"}
                                    </Popup>
                                </CircleMarker>
                            ));
                        })}
                        {showHouses && houses.map((house) => (
                            <CircleMarker key={`${house.beat_id}-${house.house_id}`}
                                center={[house.lat, house.lon]} radius={5}
                                pathOptions={{
                                    color: house.collection_link_ambiguous || house.scan_coordinate_mismatch
                                        ? "#a16207" : house.has_recorded_collection ? "#15803d" : "#b91c1c",
                                    fillColor: house.collection_link_ambiguous || house.scan_coordinate_mismatch
                                        ? "#facc15" : house.has_recorded_collection ? "#22c55e" : "#ef4444",
                                    fillOpacity: 0.8,
                                }}>
                                <Popup>
                                    House ID: {house.house_id}<br/>
                                    Beat: {house.beat_name}<br/>
                                    {house.has_recorded_collection
                                        ? "Collection record found in uploaded records"
                                        : house.collection_link_ambiguous
                                            ? "House ID appears in multiple house records; collection link is unclear"
                                            : "No collection record found in uploaded records"}
                                    <br/>Last collection record: {house.last_collection_timestamp || "Unavailable"}
                                    {house.scan_coordinate_mismatch && (
                                        <>
                                            <br/>Collection scan coordinates differ from the House ID master at six-decimal precision.
                                            {" "}Maximum recorded difference: {formatNumber(house.max_scan_coordinate_difference_m)} m.
                                            {" "}House ID match is still used.
                                        </>
                                    )}
                                </Popup>
                            </CircleMarker>
                        ))}
                        {showHouses && anonymousHouses.map((house, index) => (
                            <CircleMarker key={`anonymous-house-${index}`}
                                center={[house.lat, house.lon]} radius={3}
                                pathOptions={{color: "#64748b", fillColor: "#94a3b8", fillOpacity: 0.6}}>
                                <Popup>
                                    House ID unavailable; this coordinate is not linked to an identified house.<br/>
                                    Location: {house.lat}, {house.lon}
                                </Popup>
                            </CircleMarker>
                        ))}
                        {showCollections && collections.map((collection, index) => (
                            <CircleMarker key={`collection-${index}`} center={[collection.lat, collection.lon]}
                                radius={5} pathOptions={{color: "#1d4ed8", fillColor: "#60a5fa", fillOpacity: 0.9}}>
                                <Popup>
                                    House ID: {collection.reference_id || "Unavailable"}<br/>
                                    Recorded collection location; it does not prove a linked house visit.<br/>
                                    Employee: {collection.vehicle_id || "Unavailable"}<br/>
                                    Time: {collection.timestamp || "Unavailable"}<br/>
                                    Distance from unique House ID master location: {collection.distance_from_house_m == null
                                        ? "Unavailable"
                                        : `${formatNumber(collection.distance_from_house_m)} m`}. The exact House ID match is used even when coordinates differ.
                                </Popup>
                            </CircleMarker>
                        ))}
                    </MapContainer>
                </div>
            ) : (
                <div className="flex min-h-[240px] items-center justify-center rounded-lg border bg-white p-4 text-center text-sm text-slate-600">
                    No mapped house, scan, GPS or beat coordinates are available for this selection.
                </div>
            )}
            <p className="text-xs text-slate-600">
                House records without a collection are identified only by exact unique House ID matches in the house master. Coordinate differences are shown as warnings and do not cancel an exact ID match. GPS points near a house never count as collection. GPS points are grouped by their recorded beat ID when one exists; otherwise beat boundaries are for location context only and do not prove assignment.
                {data.house_markers_truncated || data.collection_markers_truncated || data.anonymous_house_markers_truncated || data.gps_points_truncated
                    ? " Some map markers or route points are sampled to keep the map responsive."
                    : ""}
            </p>
            <section className="space-y-2">
                <div>
                    <h3 className="text-sm font-semibold text-slate-800">GPS points in time order</h3>
                    <p className="text-xs text-slate-500">Showing {formatNumber(tablePoints.length, 0)} of {formatNumber(chronologicalPoints.length, 0)} displayed route points.</p>
                </div>
                <DataTable headers={["Time", "Employee", "Recorded beat", "Latitude", "Longitude"]}
                    rows={tablePoints.map((point, index) => (
                        <tr key={`${point.vehicle_id}-${point.trip_id}-${point.beat_id}-${point.timestamp}-${index}`} className="border-b last:border-0">
                            <td className="py-2 pr-3">{point.timestamp || "Unavailable"}</td>
                            <td className="py-2 pr-3">{point.vehicle_id}</td>
                            <td className="py-2 pr-3">{point.beat_id || "Unavailable"}</td>
                            <td className="py-2 pr-3">{point.lat}</td>
                            <td className="py-2">{point.lon}</td>
                        </tr>
                    ))}
                    emptyMessage="No GPS route points are available for this map date."
                    minWidth="620px" maxHeight="16rem"/>
            </section>
        </div>
    );
}

function TravelHouseComparison({rows, metrics, quality, selectedEmployee, timeByDate}) {
    const {highTravelLowCollection: flaggedDays} = getTravelCollectionSignals(rows);
    const maxDistance = Math.max(0, ...rows.map((row) => Number(row.distance_km) || 0));
    const maxHouses = Math.max(0, ...rows.map((row) => Number(row.houses_recorded_visited) || 0));
    const maxTime = Math.max(0, ...rows.map((row) =>
        Number(timeByDate.get(row.date)?.gps_observed_seconds) || 0
    ));
    const gpsTimeValues = [...timeByDate.values()]
        .map((row) => row.gps_observed_seconds)
        .filter((seconds) => seconds != null);
    const totalGpsObservedSeconds = gpsTimeValues.reduce(
        (total, seconds) => total + seconds, 0
    );
    const housesAvailable = Boolean(metrics.house_visits_available);
    const housesPerKm = (
        housesAvailable && metrics.total_distance_km > 0
            ? metrics.total_unique_houses_recorded_visited / metrics.total_distance_km
            : null
    );
    const housesPerHour = (
        housesAvailable && totalGpsObservedSeconds > 0
            ? metrics.total_unique_houses_recorded_visited
                / (totalGpsObservedSeconds / 3600)
            : null
    );
    return (
        <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div>
                <h2 className="text-lg font-semibold text-slate-900">5. Collection Efficiency</h2>
                <p className="text-xs text-slate-600">
                    These descriptive ratios compare recorded unique House IDs with GPS distance and time. They are not a direct measure of employee efficiency.
                </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
                <MetricCard label="Total GPS distance" value={metrics.total_distance_km == null ? "Unavailable" : `${formatNumber(metrics.total_distance_km)} km`}/>
                <MetricCard label="Unique houses recorded" value={housesAvailable
                    ? formatNumber(metrics.total_unique_houses_recorded_visited, 0)
                    : "Unavailable"}/>
                <MetricCard label="Average recorded houses per day" value={metrics.average_daily_houses_recorded_visited == null ? "Unavailable" : formatNumber(metrics.average_daily_houses_recorded_visited, 0)}/>
                <MetricCard label="Houses per km" value={housesPerKm == null ? "Unavailable" : formatNumber(housesPerKm, 2)}
                    detail="Uses total unique recorded House IDs"/>
                <MetricCard label="Houses per GPS-observed hour" value={housesPerHour == null ? "Unavailable" : formatNumber(housesPerHour, 1)}
                    detail="GPS-observed time is not shift time"/>
                <MetricCard label="Distance per recorded house" value={metrics.distance_per_recorded_house_km == null ? "Unavailable" : `${formatNumber(metrics.distance_per_recorded_house_km, 3)} km`}
                    detail="A descriptive ratio, not an efficiency score"/>
            </div>
            <section className="rounded-lg border bg-white p-4">
                <h3 className="mb-2 text-sm font-semibold text-slate-800">Daily distance, time and recorded houses</h3>
                <div className="mb-2 flex gap-4 text-xs text-slate-600">
                    <span><span className="mr-1 inline-block h-2.5 w-2.5 bg-blue-600"/>Distance (km)</span>
                    <span><span className="mr-1 inline-block h-2.5 w-2.5 bg-teal-600"/>House IDs</span>
                    <span><span className="mr-1 inline-block h-2.5 w-2.5 bg-violet-600"/>GPS time</span>
                </div>
                {!rows.length ? (
                    <p className="py-8 text-center text-sm text-slate-500">No daily travel or collection records for this selection.</p>
                ) : (
                    <div className="flex h-52 items-end gap-2 overflow-x-auto border-b border-l px-2">
                        {rows.map((row) => {
                            const distance = row.distance_km;
                            const houses = row.houses_recorded_visited;
                            const seconds = timeByDate.get(row.date)?.gps_observed_seconds;
                            const highTravelLowCollection = flaggedDays.some((day) => day.date === row.date);
                            return (
                                <div key={row.date} className={`flex h-full min-w-14 flex-1 flex-col items-center justify-end gap-1 ${highTravelLowCollection ? "rounded-t bg-amber-50" : ""}`}
                                    title={`${row.date}: ${distance == null ? "Distance unavailable" : `${formatNumber(distance)} km`}; ${seconds == null ? "Time unavailable" : formatDuration(seconds)}; ${houses == null ? "House count unavailable" : `${formatNumber(houses, 0)} houses`}`}>
                                    <span className="text-[9px] text-slate-600">{seconds == null ? "—" : formatDuration(seconds)}</span>
                                    <div className="flex h-32 w-full items-end justify-center gap-1">
                                        <div className="w-3 rounded-t bg-blue-600" style={{height: `${maxDistance && distance != null ? Math.max(2, distance / maxDistance * 100) : 0}%`}}/>
                                        <div className="w-3 rounded-t bg-teal-600" style={{height: `${maxHouses && houses != null ? Math.max(2, houses / maxHouses * 100) : 0}%`}}/>
                                        <div className="w-3 rounded-t bg-violet-600" style={{height: `${maxTime && seconds != null ? Math.max(2, seconds / maxTime * 100) : 0}%`}}/>
                                    </div>
                                    <span className="text-[9px] text-slate-600">{houses == null ? "—" : formatNumber(houses, 0)}</span>
                                    <span className="mb-1 max-w-16 truncate text-[9px] text-slate-600">{row.date}</span>
                                </div>
                            );
                        })}
                    </div>
                )}
            </section>
            <div className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                <p className="font-medium">Days with above-typical distance and below-typical recorded houses</p>
                <p className="mt-1 text-xs">
                    {flaggedDays.length
                        ? flaggedDays.map((row) => `${row.date} (${formatNumber(row.distance_km)} km, ${formatNumber(row.houses_recorded_visited, 0)} houses)`).join("; ")
                        : "No such days were identified from the available paired records."}
                    {" "}The comparison uses the median of days with both measurements and is not an efficiency rating.
                </p>
            </div>
            <p className="text-xs text-slate-500">
                Data checks: {formatNumber(quality.duplicate_collection_scan_rows || 0, 0)} exact duplicate collection scan row(s), {formatNumber(quality.duplicate_gps_point_rows || 0, 0)} exact duplicate GPS point row(s), and {formatNumber(quality.reference_ids_recorded_under_multiple_employees || 0, 0)} House ID(s) appearing under multiple employees across the uploaded records{selectedEmployee ? `, including ${selectedEmployee}` : ""}. Repeated House IDs on different dates are normal history, not duplicates.
            </p>
        </section>
    );
}

function CollectionGapAnalysis({data, rows, timeByDate}) {
    const longest = data?.longest_between_collection_interval;
    const baselineCounts = rows
        .map((item) => item.houses_recorded_visited)
        .filter((count) => count != null);
    const sortedCounts = baselineCounts.slice().sort((a, b) => a - b);
    const middle = Math.floor(sortedCounts.length / 2);
    const median = sortedCounts.length
        ? (sortedCounts.length % 2
            ? sortedCounts[middle]
            : (sortedCounts[middle - 1] + sortedCounts[middle]) / 2)
        : null;
    const tableRows = rows.map((row) => {
        const time = timeByDate.get(row.date);
        const houses = row.houses_recorded_visited;
        const lowActivity = houses != null && (
            houses === 0 || (median != null && median > 0 && houses < median * 0.5)
        );
        return (
            <tr key={row.date} className="border-b last:border-0">
                <td className="py-2 pr-3">{row.date}</td>
                <td className="py-2 pr-3">{houses == null ? "Unavailable" : formatNumber(houses, 0)}</td>
                <td className="py-2 pr-3">{formatDuration(time?.average_between_collection_seconds)}</td>
                <td className="py-2 pr-3">{formatDuration(time?.longest_between_collection_seconds)}</td>
                <td className="py-2 pr-3">{time?.between_collection_interval_count == null
                    ? "Unavailable"
                    : formatNumber(time.between_collection_interval_count, 0)}</td>
                <td className="py-2">{houses == null
                    ? "Unavailable"
                    : lowActivity ? "Low recorded activity" : "No low-activity flag"}</td>
            </tr>
        );
    });

    return (
        <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div>
                <h2 className="text-lg font-semibold text-slate-900">6. Collection Gap Analysis</h2>
                <p className="text-xs text-slate-600">
                    Gaps are elapsed time between timestamped unique House IDs on the same employee-day. They may include travel, stops, or missing scans; they do not prove wasted time.
                </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
                <MetricCard label="Average gap between records"
                    value={formatDuration(data?.average_between_collection_seconds)}
                    detail={`${formatNumber(data?.total_interval_count, 0)} timestamped interval(s)`}/>
                <MetricCard label="Longest gap between records"
                    value={formatDuration(data?.longest_between_collection_seconds)}
                    detail={longest
                        ? `${longest.date} · ${longest.from_house_id} to ${longest.to_house_id} (${longest.vehicle_id || "Employee unavailable"})`
                        : "Requires at least two unique timestamped House IDs in one employee-day"}/>
            </div>
            <DataTable
                headers={["Date", "Houses recorded", "Average collection gap", "Longest collection gap", "Timed intervals", "Activity check"]}
                rows={tableRows}
                emptyMessage="No daily collection records are available in this period."
                minWidth="850px"
                maxHeight="24rem"
            />
            <p className="text-xs text-slate-500">
                “Low recorded activity” means zero recorded House IDs or less than half the selected-period median. It is a prompt to check the records and context, not a performance judgment. Missing counts remain unavailable.
            </p>
        </section>
    );
}

function DailyPerformanceSummary({rows, timeByDate}) {
    const tableRows = rows.map((row) => {
        const seconds = timeByDate.get(row.date)?.gps_observed_seconds;
        const houses = row.houses_recorded_visited;
        const distanceKm = row.distance_m == null
            ? row.distance_km
            : row.distance_m / 1000;
        const housesPerHour = houses != null && seconds > 0
            ? houses / (seconds / 3600)
            : null;
        const housesPerKm = houses != null && distanceKm > 0
            ? houses / distanceKm
            : null;
        return (
            <tr key={row.date} className="border-b last:border-0">
                <td className="py-2 pr-3">{row.date}</td>
                <td className="py-2 pr-3">{distanceKm == null ? "Unavailable" : `${formatNumber(distanceKm, 2)} km`}</td>
                <td className="py-2 pr-3">{formatDuration(seconds)}</td>
                <td className="py-2 pr-3">{houses == null ? "Unavailable" : formatNumber(houses, 0)}</td>
                <td className="py-2 pr-3">{housesPerHour == null ? "Unavailable" : formatNumber(housesPerHour, 1)}</td>
                <td className="py-2 pr-3">{housesPerKm == null ? "Unavailable" : formatNumber(housesPerKm, 2)}</td>
                <td className="py-2 pr-3">{formatNumber(row.dumping_trips, 0)}</td>
                <td className="py-2">{formatWeight(row.garbage_weight_kg)}</td>
            </tr>
        );
    });

    return (
        <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div>
                <h2 className="text-lg font-semibold text-slate-900">7. Daily Performance Summary</h2>
                <p className="text-xs text-slate-600">
                    One row per date in the selected reporting period. Ratios are unavailable when their source data or denominator is missing.
                </p>
            </div>
            <DataTable
                headers={["Date", "Distance", "Time", "Houses Collected", "Houses/Hour", "Houses/Km", "Dumping Trips", "Garbage Weight"]}
                rows={tableRows}
                emptyMessage="No daily records are available in this reporting period."
                minWidth="1050px"
                maxHeight="28rem"
            />
        </section>
    );
}

function formatDuration(seconds) {
    if (seconds == null) return "Unavailable";
    if (Number(seconds) < 60) return `${Math.round(Number(seconds))}s`;
    const totalMinutes = Math.floor(Number(seconds) / 60);
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

function TimeAnalysis({data}) {
    const dailyRows = data?.daily || [];
    const intervals = data?.intervals || [];
    const observedSeconds = dailyRows.reduce(
        (total, row) => total + (row.gps_observed_seconds || 0), 0
    );
    const observedByDate = new Map();
    dailyRows.forEach((row) => {
        if (row.gps_observed_seconds == null) return;
        observedByDate.set(
            row.date,
            (observedByDate.get(row.date) || 0) + row.gps_observed_seconds
        );
    });
    const averageDailyObservedSeconds = observedByDate.size
        ? observedSeconds / observedByDate.size
        : null;
    const benchmarkDays = dailyRows.filter((row) => row.benchmark_time_seconds != null).length;
    const rows = dailyRows.map((row) => (
        <tr key={`${row.date}-${row.vehicle_id}`} className="border-b last:border-0">
            <td className="py-2 pr-3">{row.date}</td>
            <td className="py-2 pr-3">{row.vehicle_id || "Unavailable"}</td>
            <td className="py-2 pr-3">{formatDuration(row.gps_span_seconds)}</td>
            <td className="py-2 pr-3">{formatDuration(row.gps_observed_seconds)}</td>
            <td className="py-2 pr-3">
                {row.benchmark_time_seconds == null
                    ? "Unavailable"
                    : `${formatDuration(row.benchmark_time_seconds)} (${row.benchmark_date})`}
            </td>
            <td className="py-2 pr-3">
                {row.time_difference_from_benchmark_seconds == null
                    ? "Unavailable"
                    : row.time_difference_from_benchmark_seconds > 0
                        ? `${formatDuration(row.time_difference_from_benchmark_seconds)} longer`
                        : row.time_difference_from_benchmark_seconds < 0
                            ? `${formatDuration(Math.abs(row.time_difference_from_benchmark_seconds))} shorter`
                            : "Same time"}
            </td>
            <td className="py-2">{formatDuration(row.average_between_collection_seconds)}</td>
        </tr>
    ));
    const intervalRows = intervals.map((item, index) => (
        <tr key={`${item.date}-${item.vehicle_id}-${item.from_timestamp}-${item.to_timestamp}-${index}`}
            className="border-b last:border-0">
            <td className="py-2 pr-3">{item.date}</td>
            <td className="py-2 pr-3">{item.vehicle_id || "Unavailable"}</td>
            <td className="py-2 pr-3">{item.from_house_id}</td>
            <td className="py-2 pr-3">{item.to_house_id}</td>
            <td className="py-2 pr-3">{item.from_timestamp}</td>
            <td className="py-2 pr-3">{item.to_timestamp}</td>
            <td className="py-2">{formatDuration(item.duration_seconds)}</td>
        </tr>
    ));

    return (
        <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div>
                <h2 className="text-lg font-semibold text-slate-900">2. Time</h2>
                <p className="text-xs text-slate-600">
                    GPS times help compare recorded activity between days. They are estimates, not official shift hours.
                </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                <MetricCard label="GPS time counted" value={dailyRows.some((row) => row.gps_observed_seconds != null)
                    ? formatDuration(observedSeconds) : "Unavailable"}
                    detail="Adds GPS gaps up to 15 minutes; longer gaps are left out"/>
                <MetricCard label="Average GPS time per day"
                    value={formatDuration(averageDailyObservedSeconds)}
                    detail="For all selected employees on each recorded date"/>
                <MetricCard label="Average collection gap"
                    value={formatDuration(data?.average_between_collection_seconds)}
                    detail="Between timestamped unique House IDs"/>
                <MetricCard label="Longest collection gap"
                    value={formatDuration(data?.longest_between_collection_seconds)}
                    detail={data?.longest_between_collection_interval
                        ? `${data.longest_between_collection_interval.date}: ${data.longest_between_collection_interval.from_house_id} to ${data.longest_between_collection_interval.to_house_id}`
                        : "Requires two timestamped House IDs in one employee-day"}/>
                <MetricCard label="Days with a comparable-time benchmark"
                    value={formatNumber(benchmarkDays, 0)}
                    detail="Days with enough similar records to compare"/>
            </div>
            <DataTable
                headers={["Date", "Employee", "First-to-last GPS", "GPS time counted", "Fastest similar day", "Difference", "Time between houses (average)"]}
                rows={rows}
                emptyMessage="No GPS or timestamped House ID records are available in the uploaded data."
                minWidth="1050px"
                maxHeight="20rem"
            />
            <p className="text-xs text-slate-500">
                “Fastest similar day” means the quickest other day for this employee with roughly the same distance and number of recorded houses (within 20%). We need at least two similar days to compare. This is a past-day reference, not an ideal target. GPS time counted includes only gaps up to 15 minutes, so it may be shorter than the full day.
            </p>
            <section className="space-y-2">
                <div>
                    <h3 className="text-sm font-semibold text-slate-800">Time between recorded houses</h3>
                    <p className="text-xs text-slate-500">
                        Elapsed time from one recorded House ID to the next. It may include travel, stops, or missing scans; it does not by itself mean time was wasted.
                    </p>
                </div>
                <DataTable
                    headers={["Date", "Employee", "From house", "To house", "Start", "Next record", "Time taken"]}
                    rows={intervalRows}
                    emptyMessage="At least two unique House IDs with timestamps on the same employee-day are needed to calculate an interval."
                    minWidth="900px"
                    maxHeight="24rem"
                />
                {data?.intervals_truncated && (
                    <p className="text-xs text-slate-500">
                        Showing the first {formatNumber(intervals.length, 0)} of {formatNumber(data.total_interval_count, 0)} intervals.
                    </p>
                )}
            </section>
        </section>
    );
}

function ImprovementSuggestions({rows, metrics, quality, selectedEmployee}) {
    const {paired, highTravelLowCollection} = getTravelCollectionSignals(rows);
    const suggestions = [];

    if (highTravelLowCollection.length) {
        suggestions.push({
            title: "Review days with more travel and fewer recorded collections",
            detail: `${highTravelLowCollection.map((row) =>
                `${row.date} (${formatNumber(row.distance_km)} km; ${formatNumber(row.houses_recorded_visited, 0)} House IDs)`
            ).join("; ")} showed above-typical travel and below-typical recorded collections versus other days with both measurements.`,
            action: "Discuss whether beat assignment, road closures, service interruptions, or route changes explain the pattern. If appropriate, plan the beat sequence to reduce repeat travel.",
        });
    } else if (paired.length < 3) {
        suggestions.push({
            title: "Collect more comparable daily records",
            detail: `Only ${paired.length} day(s) have both GPS distance and House ID collection data, which is not enough to identify a reliable pattern.`,
            action: "Confirm GPS tracks and collection lists are uploaded for the same employee and dates, then review again when more complete records are available.",
        });
    } else {
        suggestions.push({
            title: "No unusual travel/collection pattern identified",
            detail: "No day in the uploaded records showed both above-typical travel and below-typical recorded House IDs.",
            action: "Continue monitoring these measures. This comparison alone does not establish employee efficiency.",
        });
    }

    const daysMissingCollections = rows.filter((row) =>
        row.distance_km != null && row.houses_recorded_visited == null);
    if (daysMissingCollections.length) {
        suggestions.push({
            title: "Check collection-record completeness",
            detail: `${daysMissingCollections.length} day(s) have GPS distance but no available House ID count.`,
            action: "Check that the collection list was uploaded and its reference IDs are present. Missing records are unavailable data, not zero houses collected.",
        });
    }

    const daysMissingGps = rows.filter((row) =>
        row.houses_recorded_visited != null && row.distance_km == null);
    if (daysMissingGps.length) {
        suggestions.push({
            title: "Check GPS coverage",
            detail: `${daysMissingGps.length} day(s) have collection records but no usable GPS distance.`,
            action: "Check tracker uploads, timestamps, and GPS coverage for those days before comparing travel with collections.",
        });
    }

    if (Number(metrics.invalid_gps_intervals) > 0) {
        suggestions.push({
            title: "Review GPS data quality",
            detail: `${formatNumber(metrics.invalid_gps_intervals, 0)} GPS interval(s) were excluded as invalid.`,
            action: "Check tracker time settings and GPS signal quality before using distance comparisons for operational decisions.",
        });
    }

    if (Number(quality.duplicate_collection_scan_rows) > 0
        || Number(quality.duplicate_gps_point_rows) > 0
        || Number(quality.reference_ids_recorded_under_multiple_employees) > 0) {
        suggestions.push({
            title: "Verify duplicate records and employee attribution",
            detail: `${formatNumber(quality.duplicate_collection_scan_rows || 0, 0)} duplicate collection row(s), ${formatNumber(quality.duplicate_gps_point_rows || 0, 0)} duplicate GPS point(s), and ${formatNumber(quality.reference_ids_recorded_under_multiple_employees || 0, 0)} House ID(s) associated with multiple employees were found.`,
            action: "Check file imports and employee assignments before drawing conclusions. A shared House ID may be valid if employees worked together or covered separate shifts.",
        });
    }

    if (Number(metrics.dumping_trips) > 0 && metrics.total_garbage_weight_kg == null) {
        suggestions.push({
            title: "Complete dumping weight records",
            detail: "Dumping trips are recorded, but a complete verified total weight is unavailable.",
            action: "Record a measured weight and unit for each dumping trip. Missing weights should remain unavailable rather than being entered as zero.",
        });
    }

    return (
        <section className="space-y-3 rounded-lg border border-blue-200 bg-blue-50 p-4">
            <div>
                <h2 className="text-lg font-semibold text-slate-900">8. Improvement Suggestions</h2>
                <p className="mt-1 text-xs text-slate-600">
                    Suggestions for {selectedEmployee || "all employees"}, based on the uploaded records. These are review prompts, not a rating or proof of poor performance.
                </p>
            </div>
            {suggestions.length ? (
                <div className="grid gap-3 lg:grid-cols-2">
                    {suggestions.map((suggestion) => (
                        <article key={suggestion.title} className="rounded-lg border bg-white p-4">
                            <h3 className="text-sm font-semibold text-slate-800">{suggestion.title}</h3>
                            <p className="mt-1 text-sm text-slate-600">{suggestion.detail}</p>
                            <p className="mt-2 text-sm text-blue-900">
                                <span className="font-medium">Suggested next step: </span>
                                {suggestion.action}
                            </p>
                        </article>
                    ))}
                </div>
            ) : (
                <p className="rounded border bg-white p-3 text-sm text-slate-600">
                    No specific suggestion can be made from the available uploaded records.
                </p>
            )}
            <p className="text-xs text-slate-500">
                Higher travel or lower recorded collection may have valid operational reasons. Review route assignments, service conditions and record completeness with the employee before taking action.
            </p>
        </section>
    );
}

function addDays(date, days) {
    const value = new Date(`${date}T00:00:00Z`);
    value.setUTCDate(value.getUTCDate() + days);
    return value.toISOString().slice(0, 10);
}

function averageValue(values) {
    return values.length
        ? values.reduce((total, value) => total + value, 0) / values.length
        : null;
}

function medianValue(values) {
    if (!values.length) return null;
    const sorted = values.slice().sort((left, right) => left - right);
    const middle = Math.floor(sorted.length / 2);
    return sorted.length % 2
        ? sorted[middle]
        : (sorted[middle - 1] + sorted[middle]) / 2;
}

function coefficientOfVariation(values) {
    const mean = averageValue(values);
    if (values.length < 3 || mean == null || mean === 0) return null;
    const variance = averageValue(values.map((value) => (value - mean) ** 2));
    return Math.sqrt(variance) / mean * 100;
}

function getProgressTrend(previous, current, higherIsBetter) {
    if (previous == null || current == null) return "unavailable";
    if (previous === 0) {
        if (current === 0) return "stable";
        return (higherIsBetter ? current > previous : current < previous)
            ? "improving"
            : "worsening";
    }
    const relativeChange = (current - previous) / Math.abs(previous);
    if (Math.abs(relativeChange) <= 0.1) return "stable";
    const increased = relativeChange > 0;
    return increased === higherIsBetter ? "improving" : "worsening";
}

function getProgressWindow(rows, timeByDate, history, endDate, days = 7) {
    const currentStart = addDays(endDate, -(days - 1));
    const previousEnd = addDays(currentStart, -1);
    const previousStart = addDays(previousEnd, -(days - 1));
    const inWindow = (row, start, end) => row.date >= start && row.date <= end;
    const previousRows = rows.filter((row) => inWindow(row, previousStart, previousEnd));
    const currentRows = rows.filter((row) => inWindow(row, currentStart, endDate));

    const getComparison = (previousValues, currentValues, higherIsBetter) => {
        const previous = previousValues.length >= 3 ? averageValue(previousValues) : null;
        const current = currentValues.length >= 3 ? averageValue(currentValues) : null;
        return {
            previous,
            current,
            previousDays: previousValues.length,
            currentDays: currentValues.length,
            trend: getProgressTrend(previous, current, higherIsBetter),
        };
    };

    const collection = getComparison(
        previousRows
            .filter((row) => row.houses_recorded_visited != null)
            .map((row) => row.houses_recorded_visited),
        currentRows
            .filter((row) => row.houses_recorded_visited != null)
            .map((row) => row.houses_recorded_visited),
        true,
    );
    const previousConsistencyValues = previousRows
        .map((row) => row.houses_recorded_visited)
        .filter((value) => value != null);
    const currentConsistencyValues = currentRows
        .map((row) => row.houses_recorded_visited)
        .filter((value) => value != null);
    const previousConsistency = previousConsistencyValues.length >= 3
        ? coefficientOfVariation(previousConsistencyValues)
        : null;
    const currentConsistency = currentConsistencyValues.length >= 3
        ? coefficientOfVariation(currentConsistencyValues)
        : null;
    const consistency = {
        previous: previousConsistency,
        current: currentConsistency,
        previousDays: previousConsistencyValues.length,
        currentDays: currentConsistencyValues.length,
        trend: getProgressTrend(previousConsistency, currentConsistency, false),
    };
    const getDailyHouseRatios = (periodRows) => periodRows
        .filter((row) => row.houses_recorded_visited != null)
        .map((row) => {
            const distanceM = row.distance_m ?? (
                row.distance_km == null ? null : row.distance_km * 1000
            );
            return distanceM > 0
                ? row.houses_recorded_visited / (distanceM / 1000)
                : null;
        })
        .filter((value) => value != null);
    const travel = getComparison(
        getDailyHouseRatios(previousRows),
        getDailyHouseRatios(currentRows),
        true,
    );
    const getDailyGaps = (periodRows) => periodRows
        .map((row) => timeByDate.get(row.date)?.average_between_collection_seconds)
        .filter((value) => value != null);
    const gaps = getComparison(
        getDailyGaps(previousRows),
        getDailyGaps(currentRows),
        false,
    );

    let houseCoverage = {
        previous: null, current: null, previousDays: 0, currentDays: 0,
        trend: "unavailable",
    };
    if (history.house_master_available && history.house_master_count > 0) {
        const recordedHouseCount = (start, end) => new Set(
            (history.reference_ids || []).flatMap((reference) =>
                (reference.collection_dates || [])
                    .filter((date) => date >= start && date <= end)
                    .map(() => reference.house_id)
            )
        ).size;
        const previousCount = recordedHouseCount(previousStart, previousEnd);
        const currentCount = recordedHouseCount(currentStart, endDate);
        const previousCoverageDays = previousRows.filter(
            (row) => row.houses_recorded_visited != null
        ).length;
        const currentCoverageDays = currentRows.filter(
            (row) => row.houses_recorded_visited != null
        ).length;
        const previousCoverage = previousCoverageDays >= 3
            ? previousCount / history.house_master_count * 100
            : null;
        const currentCoverage = currentCoverageDays >= 3
            ? currentCount / history.house_master_count * 100
            : null;
        houseCoverage = {
            previous: previousCoverage,
            current: currentCoverage,
            previousDays: previousCoverageDays,
            currentDays: currentCoverageDays,
            trend: getProgressTrend(
                previousCoverage,
                currentCoverage,
                true,
            ),
        };
    }

    const previousLongestGaps = previousRows
        .map((row) => timeByDate.get(row.date)?.longest_between_collection_seconds)
        .filter((value) => value != null);
    const currentLongestGaps = currentRows
        .map((row) => timeByDate.get(row.date)?.longest_between_collection_seconds)
        .filter((value) => value != null);
    const getQuartile = (values, percentile) => {
        if (!values.length) return null;
        const sorted = values.slice().sort((left, right) => left - right);
        return sorted[Math.floor((sorted.length - 1) * percentile)];
    };
    const baselineMedianGap = previousLongestGaps.length >= 3
        ? medianValue(previousLongestGaps)
        : null;
    const baselineIqrGap = previousLongestGaps.length >= 3
        ? getQuartile(previousLongestGaps, 0.75) - getQuartile(previousLongestGaps, 0.25)
        : null;
    const longGapThreshold = baselineMedianGap == null
        ? null
        : baselineMedianGap + 1.5 * (baselineIqrGap || 0);
    const recurringLongGapDates = longGapThreshold == null
        || currentLongestGaps.length < 3
        ? []
        : currentRows.filter((row) => {
            const longest = timeByDate.get(row.date)?.longest_between_collection_seconds;
            return longest != null && longest > longGapThreshold;
        }).map((row) => row.date);

    const previousHouseValues = previousRows
        .map((row) => row.houses_recorded_visited)
        .filter((value) => value != null);
    const currentHouseValues = currentRows
        .map((row) => row.houses_recorded_visited)
        .filter((value) => value != null);
    const previousHouseMedian = medianValue(previousHouseValues);
    const lowCollectionDates = previousHouseMedian == null || previousHouseMedian <= 0
        || previousHouseValues.length < 3 || currentHouseValues.length < 3
        ? []
        : currentRows.filter((row) =>
            row.houses_recorded_visited != null
            && row.houses_recorded_visited < previousHouseMedian * 0.5
        ).map((row) => row.date);

    return {
        startDate: previousStart,
        previousEnd,
        currentStart,
        endDate,
        previousRows,
        currentRows,
        metrics: [
            {key: "collection", label: "Collection activity", unit: "houses/day", ...collection},
            {key: "consistency", label: "Collection consistency", unit: "% variation", ...consistency},
            {key: "coverage", label: "House coverage", unit: "% of known roster", ...houseCoverage},
            {key: "travel", label: "Travel efficiency", unit: "houses/km", ...travel},
            {key: "gaps", label: "Activity gaps", unit: "seconds", ...gaps},
        ],
        recurringLongGapDates,
        lowCollectionDates,
        currentGapDays: currentLongestGaps.length,
        currentCollectionDays: currentHouseValues.length,
    };
}

function getOverallProgressStatus(snapshot) {
    if (!snapshot) return "Insufficient Data";
    const groups = new Map();
    snapshot.metrics.forEach((metric) => {
        const group = metric.key === "collection" || metric.key === "consistency"
            ? "collection"
            : metric.key === "coverage"
                ? "coverage"
                : metric.key === "travel"
                    ? "travel"
                    : "activity";
        if (metric.trend !== "unavailable") {
            groups.set(group, [...(groups.get(group) || []), metric.trend]);
        }
    });
    const groupTrends = [...groups.values()].map((trends) => {
        const uniqueTrends = new Set(trends);
        if (uniqueTrends.size === 1) return trends[0];
        if (uniqueTrends.has("improving") && uniqueTrends.has("worsening")) return "mixed";
        if (uniqueTrends.has("improving")) return "improving";
        if (uniqueTrends.has("worsening")) return "worsening";
        return "stable";
    });
    if (groupTrends.length < 2) return "Insufficient Data";
    const improving = groupTrends.filter((trend) => trend === "improving").length;
    const worsening = groupTrends.filter((trend) => trend === "worsening").length;
    const mixed = groupTrends.filter((trend) => trend === "mixed").length;
    if (worsening >= 2 && improving === 0 && mixed === 0) return "Declining";
    if (snapshot.recurringLongGapDates.length >= 2
        || snapshot.lowCollectionDates.length >= 2
        || mixed > 0
        || (improving > 0 && worsening > 0)
        || (worsening >= 2 && improving < 2)) {
        return "Needs Attention";
    }
    if (improving >= 2 && worsening <= 1 && mixed === 0) return "Improving";
    return "Stable";
}

function displayProgressValue(metric, value) {
    if (value == null) return "Unavailable";
    if (metric.key === "gaps") return formatDuration(value);
    return `${formatNumber(value, metric.key === "collection" ? 0 : 1)} ${metric.unit}`;
}

function ProgressBar({metric}) {
    if (metric.previous == null || metric.current == null) {
        return <span className="text-xs text-slate-500">Unavailable</span>;
    }
    const maximum = Math.max(metric.previous, metric.current, 0);
    const previousWidth = maximum ? Math.max(4, metric.previous / maximum * 100) : 4;
    const currentWidth = maximum ? Math.max(4, metric.current / maximum * 100) : 4;
    const statusText = {
        improving: "↑ Improving",
        stable: "→ Stable",
        worsening: "↓ Worsening",
        unavailable: "Unavailable",
    }[metric.trend];
    return (
        <div className="min-w-40 space-y-1">
            <div className="space-y-1">
                <div className="flex items-center gap-2">
                    <span className="w-16 text-[10px] text-slate-500">Previous</span>
                    <span className="block h-2 rounded bg-slate-300" style={{width: `${previousWidth}%`}}/>
                </div>
                <div className="flex items-center gap-2">
                    <span className="w-16 text-[10px] text-slate-500">Current</span>
                    <span className={`block h-2 rounded ${metric.trend === "improving" ? "bg-emerald-500" : metric.trend === "worsening" ? "bg-rose-500" : "bg-blue-500"}`}
                        style={{width: `${currentWidth}%`}}/>
                </div>
            </div>
            <p className="text-xs font-medium text-slate-700">{statusText}</p>
        </div>
    );
}

function EmployeeProgressAnalysis({rows, timeByDate, history, selectedEmployee}) {
    const eligibleRows = selectedEmployee ? rows : [];
    const timeline = [];
    if (eligibleRows.length) {
        const firstCheckpoint = addDays(eligibleRows[0].date, 13);
        const lastDate = eligibleRows[eligibleRows.length - 1].date;
        if (lastDate >= firstCheckpoint) {
            for (let checkpoint = firstCheckpoint; checkpoint <= lastDate;
                checkpoint = addDays(checkpoint, 7)) {
                timeline.push(getProgressWindow(
                    eligibleRows, timeByDate, history, checkpoint
                ));
            }
            const latestCheckpoint = timeline[timeline.length - 1]?.endDate;
            if (latestCheckpoint !== lastDate) {
                timeline.push(getProgressWindow(
                    eligibleRows, timeByDate, history, lastDate
                ));
            }
        }
    }
    const currentSnapshot = timeline[timeline.length - 1];
    const overallStatus = getOverallProgressStatus(currentSnapshot);
    const timelineStatuses = timeline
        .map((snapshot) => ({
            date: snapshot.endDate,
            status: getOverallProgressStatus(snapshot),
        }))
        .filter((point) => point.status !== "Insufficient Data");
    const firstTimelineStatus = timelineStatuses[0];
    const currentTimelineStatus = timelineStatuses[timelineStatuses.length - 1];
    const progressSnapshot = currentSnapshot || {
        metrics: [
            {key: "collection", label: "Collection activity", unit: "houses/day", previous: null, current: null, trend: "unavailable"},
            {key: "consistency", label: "Collection consistency", unit: "% variation", previous: null, current: null, trend: "unavailable"},
            {key: "coverage", label: "House coverage", unit: "% of known roster", previous: null, current: null, trend: "unavailable"},
            {key: "travel", label: "Travel efficiency", unit: "houses/km", previous: null, current: null, trend: "unavailable"},
            {key: "gaps", label: "Activity gaps", unit: "seconds", previous: null, current: null, trend: "unavailable"},
        ],
        recurringLongGapDates: [],
        lowCollectionDates: [],
        currentGapDays: 0,
        currentCollectionDays: 0,
        currentRows: [],
    };
    const strengths = [];
    const areas = [];
    const recommendations = [];
    if (currentSnapshot) {
        currentSnapshot.metrics.forEach((metric) => {
            if (metric.key === "coverage" && metric.trend === "unavailable") return;
            if (metric.trend === "improving") {
                strengths.push(`${metric.label} improved compared with the employee’s previous week.`);
            } else if (metric.trend === "worsening") {
                const priority = metric.key === "collection" || metric.key === "gaps" ? "High" : "Medium";
                const observation = metric.key === "gaps"
                    ? "Average time between timestamped House IDs increased."
                    : metric.key === "collection"
                        ? "Average daily recorded House IDs decreased."
                        : metric.key === "travel"
                            ? "GPS distance per recorded House ID increased."
                            : "Day-to-day variation in recorded House IDs increased.";
                areas.push({area: metric.label, observation, priority});
            } else if (metric.trend === "stable") {
                strengths.push(`${metric.label} remained stable against the employee’s previous week.`);
            }
        });
        if (currentSnapshot.recurringLongGapDates.length >= 2) {
            areas.push({
                area: "Recurring collection gaps",
                observation: `Longer-than-usual gaps appeared on ${currentSnapshot.recurringLongGapDates.length} recent recorded day(s), based on this employee’s previous-period pattern.`,
                priority: currentSnapshot.recurringLongGapDates.length >= 3 ? "High" : "Medium",
            });
        }
        if (currentSnapshot.lowCollectionDates.length >= 2) {
            areas.push({
                area: "Low recorded collection activity",
                observation: `${currentSnapshot.lowCollectionDates.length} recent day(s) had fewer than half the employee’s previous-week median House IDs.`,
                priority: "High",
            });
        }
    }
    if (areas.some((area) => area.area.includes("gap"))) {
        recommendations.push("Review the dates with longer-than-usual intervals and confirm route context and timestamp completeness before interpreting them as delays.");
    }
    if (areas.some((area) => area.area.includes("collection") || area.area.includes("House"))) {
        recommendations.push("Review daily collection lists alongside assigned area, route, and collection load; day-to-day House ID counts alone do not prove a missed visit.");
    }
    if (areas.some((area) => area.area.includes("Travel"))) {
        recommendations.push("Compare GPS distance per recorded House ID with this employee’s earlier period and verify route changes; these records cannot identify unnecessary travel by themselves.");
    }
    if (areas.some((area) => area.area.includes("consistency") || area.area.includes("Consistency"))) {
        recommendations.push("Check whether daily variation reflects legitimate workload or area changes, and confirm the GPS and collection uploads are complete.");
    }
    if (currentSnapshot?.metrics.some((metric) =>
        metric.key === "coverage" && metric.trend === "unavailable"
    )) {
        recommendations.push("Provide a verified assigned-house roster if management needs a true house-coverage percentage.");
    }
    if (!recommendations.length && overallStatus === "Insufficient Data") {
        recommendations.push("Keep uploading complete daily GPS and House ID records. At least three recorded days in each comparison week are needed to identify a personal trend.");
    } else if (!recommendations.length) {
        recommendations.push("Continue reviewing records against the employee’s own history; no specific deterioration was detected in the comparable measures.");
    }

    return (
        <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div>
                <h2 className="text-lg font-semibold text-slate-900">9. Employee Progress & Development</h2>
                <p className="mt-1 text-xs text-slate-600">
                    Personal trend summary for {selectedEmployee || "the selected employee"}. Comparisons use the latest 7 calendar days versus the preceding 7 days in the selected reporting period.
                </p>
                {currentSnapshot && (
                    <p className="mt-1 text-xs text-slate-500">
                        Previous: {currentSnapshot.startDate} to {currentSnapshot.previousEnd}
                        {" · "}Current: {currentSnapshot.currentStart} to {currentSnapshot.endDate}
                    </p>
                )}
            </div>
            {!selectedEmployee ? (
                <p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                    Select one employee to view an individual progress status. Combining employees would not be a fair personal-history comparison.
                </p>
            ) : (
                <>
                    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Overall employee status</p>
                        <p className="mt-1 text-2xl font-bold text-slate-900">Employee Performance: {overallStatus}</p>
                        <p className="mt-2 text-sm text-slate-700">
                            {overallStatus === "Insufficient Data"
                                ? "At least two independent measures, each with three recorded days in both comparison weeks, are needed for a reliable personal comparison."
                                : overallStatus === "Improving"
                                ? "Several measured areas are improving against this employee’s previous week."
                                : overallStatus === "Declining"
                                    ? "Several measured areas are worsening against this employee’s previous week."
                                    : overallStatus === "Needs Attention"
                                        ? "Some measures or recurring patterns need a management review against the employee’s route and records."
                                        : "Measured activity is broadly stable against this employee’s previous week."}
                            {" "}House coverage is {progressSnapshot.metrics.find((metric) => metric.key === "coverage")?.trend === "unavailable"
                                ? "unavailable because a verified assigned-house roster is not available."
                                : "based only on the verified house roster."}
                        </p>
                    </div>

                    <div className="grid gap-4 xl:grid-cols-2">
                        <section className="space-y-2">
                            <h3 className="text-sm font-semibold text-slate-800">Employee Strengths</h3>
                            {strengths.length ? (
                                <ul className="list-disc space-y-1 rounded-lg border border-emerald-200 bg-emerald-50 p-4 pl-8 text-sm text-emerald-900">
                                    {strengths.map((strength) => <li key={strength}>{strength}</li>)}
                                </ul>
                            ) : (
                                <p className="rounded-lg border bg-slate-50 p-4 text-sm text-slate-600">
                                    {overallStatus === "Insufficient Data"
                                        ? "Insufficient comparable data to identify strengths."
                                        : "No clear improvement or stable measure can be highlighted from these periods."}
                                </p>
                            )}
                        </section>
                        <section className="space-y-2">
                            <h3 className="text-sm font-semibold text-slate-800">Areas Requiring Improvement</h3>
                            <DataTable
                                headers={["Area", "Observation", "Priority"]}
                                rows={areas.map((area) => (
                                    <tr key={area.area} className="border-b last:border-0">
                                        <td className="py-2 pr-3 font-medium">{area.area}</td>
                                        <td className="py-2 pr-3">{area.observation}</td>
                                        <td className="py-2">{area.priority}</td>
                                    </tr>
                                ))}
                                emptyMessage={overallStatus === "Insufficient Data"
                                    ? "Insufficient comparable data to identify an improvement area."
                                    : "No recurring or worsening area was identified from the comparable data."}
                                minWidth="540px"
                                maxHeight="16rem"
                            />
                        </section>
                    </div>

                    <section className="space-y-2">
                        <h3 className="text-sm font-semibold text-slate-800">Progress Tracking</h3>
                        <DataTable
                            headers={["Area", "Previous period", "Current period", "Progress"]}
                            rows={progressSnapshot.metrics.map((metric) => (
                                <tr key={metric.key} className="border-b last:border-0">
                                    <td className="py-2 pr-3 font-medium">{metric.label}</td>
                                    <td className="py-2 pr-3">{displayProgressValue(metric, metric.previous)}</td>
                                    <td className="py-2 pr-3">{displayProgressValue(metric, metric.current)}</td>
                                    <td className="py-2"><ProgressBar metric={metric}/></td>
                                </tr>
                            ))}
                            emptyMessage="No comparable measures are available."
                            minWidth="800px"
                            maxHeight="20rem"
                        />
                    </section>

                    <section className="space-y-2">
                        <h3 className="text-sm font-semibold text-slate-800">Employee Progress Timeline</h3>
                        {timeline.length ? (
                            <div className="flex gap-3 overflow-x-auto pb-2">
                                {timeline.slice(-8).map((snapshot) => {
                                    const status = getOverallProgressStatus(snapshot);
                                    const color = status === "Improving" ? "bg-emerald-100 text-emerald-800"
                                        : status === "Declining" ? "bg-rose-100 text-rose-800"
                                            : status === "Needs Attention" ? "bg-amber-100 text-amber-900"
                                                : status === "Stable" ? "bg-blue-100 text-blue-800"
                                                    : "bg-slate-100 text-slate-700";
                                    return (
                                        <article key={snapshot.endDate} className="min-w-40 rounded-lg border bg-white p-3">
                                            <p className="text-xs text-slate-500">{snapshot.endDate}</p>
                                            <p className={`mt-2 inline-flex rounded-full px-2 py-1 text-xs font-semibold ${color}`}>
                                                {status}
                                            </p>
                                        </article>
                                    );
                                })}
                            </div>
                        ) : (
                            <p className="rounded border bg-slate-50 p-3 text-sm text-slate-600">
                                More date history is needed to build a progress timeline.
                            </p>
                        )}
                        <p className="text-xs text-slate-500">
                            Each timeline point compares its 7-day period with the preceding 7 days. It shows direction over time, not an absolute employee rating.
                        </p>
                        {firstTimelineStatus && currentTimelineStatus && (
                            <p className="text-sm font-medium text-slate-700">
                                Progress: {firstTimelineStatus.status === currentTimelineStatus.status
                                    ? `status has remained ${currentTimelineStatus.status} across comparable checkpoints`
                                    : `moved from ${firstTimelineStatus.status} on ${firstTimelineStatus.date} to ${currentTimelineStatus.status} on ${currentTimelineStatus.date}`}.
                            </p>
                        )}
                    </section>

                    <div className="grid gap-4 xl:grid-cols-2">
                        <section className="space-y-2">
                            <h3 className="text-sm font-semibold text-slate-800">Recurring Issues</h3>
                            <ul className="space-y-2 text-sm">
                                {progressSnapshot.recurringLongGapDates.length >= 2 && (
                                    <li className="rounded border border-amber-200 bg-amber-50 p-3">
                                        <strong>Long collection gaps — {progressSnapshot.recurringLongGapDates.length} of {progressSnapshot.currentGapDays} recent day(s) with timed intervals.</strong>
                                        {" "}These were longer than the employee’s own earlier pattern.
                                    </li>
                                )}
                                {progressSnapshot.lowCollectionDates.length >= 2 && (
                                    <li className="rounded border border-amber-200 bg-amber-50 p-3">
                                        <strong>Lower recorded collection activity — {progressSnapshot.lowCollectionDates.length} of {progressSnapshot.currentCollectionDays} recent day(s) with House ID records.</strong>
                                        {" "}Counts were below half the employee’s previous-week median; this is not proof of missed houses.
                                    </li>
                                )}
                                {!progressSnapshot.recurringLongGapDates.length
                                    && !progressSnapshot.lowCollectionDates.length && (
                                    <li className="rounded border bg-slate-50 p-3 text-slate-600">
                                        {overallStatus === "Insufficient Data"
                                            ? "Insufficient data to determine whether collection gaps or low activity are recurring."
                                            : "No recurring gap or low-recorded-activity pattern was detected from the available daily records."}
                                    </li>
                                )}
                            </ul>
                        </section>
                        <section className="space-y-2">
                            <h3 className="text-sm font-semibold text-slate-800">Recommended Improvement Focus</h3>
                            <ol className="list-decimal space-y-2 rounded-lg border bg-slate-50 p-4 pl-8 text-sm text-slate-700">
                                {recommendations.map((recommendation) => <li key={recommendation}>{recommendation}</li>)}
                            </ol>
                        </section>
                    </div>
                    <p className="text-xs text-slate-500">
                        Status reflects this employee’s own prior records, not a company-wide target. A change must exceed 10% from the prior-period value to be labeled improving or worsening; smaller changes are labeled stable. Each measure needs at least three recorded days in both weeks. Incomplete collection logs, route/area changes, and GPS gaps can affect these comparisons; this is a management review aid, not a disciplinary score.
                    </p>
                </>
            )}
        </section>
    );
}

function normalizeGpsFile(records, employeeId) {
    if (!Array.isArray(records) || !records.every((record) =>
        record && record.date && Array.isArray(record.emproute))) {
        throw new Error("GPS-only uploads must be a dated JSON array with date and emproute records.");
    }
    return {
        gps_routes: records.map((record) => ({...record, vehicle_id: employeeId})),
    };
}

function assignEmployeeId(payload, employeeId) {
    const employeeScopedArrays = [
        "vehicles",
        "collection_records",
        "gps_points",
        "gps_routes",
        "dumping_weights",
        "collection_scans",
        "dump_events",
    ];
    const scopedPayload = {...payload, vehicle_id: employeeId};
    employeeScopedArrays.forEach((key) => {
        if (Array.isArray(payload[key])) {
            scopedPayload[key] = payload[key].map((record) =>
                record && typeof record === "object"
                    ? {
                        ...record,
                        vehicle_id: employeeId,
                        ...(key === "collection_scans" && record.scan_id
                            ? {scan_id: `${employeeId}::${record.scan_id}`}
                            : {}),
                        ...(key === "dump_events" && record.dump_id
                            ? {dump_id: `${employeeId}::${record.dump_id}`}
                            : {}),
                        ...(key === "dumping_weights" && (record.record_id || record.dumping_id)
                            ? {record_id: `${employeeId}::${record.record_id || record.dumping_id}`}
                            : {}),
                        ...(key === "vehicles" ? {vehicle_name: employeeId} : {}),
                    }
                    : record
            );
        }
    });
    return scopedPayload;
}

function formatNumber(value, digits = 1) {
    return value == null ? "Unavailable" : Number(value).toLocaleString(undefined, {maximumFractionDigits: digits});
}

function formatWeight(value) {
    return value == null ? "Unavailable" : `${formatNumber(value)} kg`;
}

function getTravelCollectionSignals(rows) {
    const paired = rows.filter((row) =>
        row.distance_km != null && row.houses_recorded_visited != null);
    if (!paired.length) return {paired, highTravelLowCollection: []};
    const median = (values) => {
        const sorted = values.slice().sort((a, b) => a - b);
        const middle = Math.floor(sorted.length / 2);
        return sorted.length % 2
            ? sorted[middle]
            : (sorted[middle - 1] + sorted[middle]) / 2;
    };
    const typicalDistance = median(paired.map((row) => row.distance_km));
    const typicalHouseCount = median(paired.map((row) => row.houses_recorded_visited));
    return {
        paired,
        highTravelLowCollection: paired.filter((row) =>
            row.distance_km > typicalDistance
            && row.houses_recorded_visited < typicalHouseCount),
    };
}

export default function AnalyticsDashboard({visible}) {
    const [summary, setSummary] = useState(null);
    const [selectedEmployee, setSelectedEmployee] = useState("");
    const [periodMode, setPeriodMode] = useState("all");
    const [selectedDate, setSelectedDate] = useState("");
    const [startDate, setStartDate] = useState("");
    const [endDate, setEndDate] = useState("");
    const [importFiles, setImportFiles] = useState([]);
    const [loading, setLoading] = useState(false);
    const [importing, setImporting] = useState(false);
    const [error, setError] = useState("");
    const [notice, setNotice] = useState("");

    const query = useMemo(() => {
        const params = new URLSearchParams();
        if (selectedEmployee) params.set("vehicle_id", selectedEmployee);
        if (periodMode === "date" && selectedDate) {
            params.set("start_date", selectedDate);
            params.set("end_date", selectedDate);
        } else if (periodMode === "range") {
            if (startDate) params.set("start_date", startDate);
            if (endDate) params.set("end_date", endDate);
        }
        return params.toString();
    }, [selectedEmployee, periodMode, selectedDate, startDate, endDate]);

    const loadDashboard = async (signal) => {
        setLoading(true);
        try {
            const response = await fetch(`${API_URL}analytics/dashboard${query ? `?${query}` : ""}`, {signal});
            const data = await response.json();
            if (!response.ok) throw new Error(data.message || `Analytics request failed (${response.status}).`);
            setSummary(data);
            setError("");
        } catch (requestError) {
            if (requestError.name !== "AbortError") setError(requestError.message);
        } finally {
            if (!signal?.aborted) setLoading(false);
        }
    };

    useEffect(() => {
        if (!visible) return undefined;
        const controller = new AbortController();
        loadDashboard(controller.signal);
        return () => controller.abort();
    }, [query, visible]);

    const availableDates = summary?.available_dates || [];
    useEffect(() => {
        if (!availableDates.length) return;
        if (!selectedDate) setSelectedDate(availableDates[availableDates.length - 1]);
        if (!startDate) setStartDate(availableDates[0]);
        if (!endDate) setEndDate(availableDates[availableDates.length - 1]);
    }, [availableDates.join(","), selectedDate, startDate, endDate]);

    const importRecords = async () => {
        if (!importFiles.length) {
            setError("Choose one operational JSON export per employee.");
            return;
        }
        if (importFiles.some((entry) => !entry.employeeId.trim())) {
            setError("Enter an employee ID for every selected file.");
            return;
        }
        const employeeIds = importFiles.map((entry) => entry.employeeId.trim());
        if (new Set(employeeIds).size !== employeeIds.length) {
            setError("Each selected file must have a different employee ID.");
            return;
        }
        setImporting(true);
        setError("");
        setNotice("");
        const reports = [];
        for (const entry of importFiles) {
            const employeeId = entry.employeeId.trim();
            try {
                const parsed = JSON.parse(await entry.file.text());
                let payload = Array.isArray(parsed) ? normalizeGpsFile(parsed, employeeId) : parsed;
                if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
                    throw new Error("The JSON file must contain an operational data object or a dated GPS array.");
                }
                payload = assignEmployeeId(payload, employeeId);
                if (entry.weightUnit && payload.routes) {
                    payload.weight_unit = entry.weightUnit;
                }
                const response = await fetch(`${API_URL}analytics/import`, {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify(payload),
                });
                const result = await response.json();
                if (!response.ok) throw new Error(result.message || `Import failed (${response.status}).`);
                const rejected = Object.values(result.rejected || {}).reduce((sum, count) => sum + count, 0);
                const counts = Object.entries(result.upserted || {})
                    .filter(([, count]) => count > 0)
                    .map(([type, count]) => `${count.toLocaleString()} ${type.replaceAll("_", " ")}`)
                    .join(", ");
                reports.push({
                    ok: true,
                    text: `${employeeId} (${entry.file.name}): ${counts || result.message}` +
                        (rejected ? `; ${rejected.toLocaleString()} incomplete rows skipped.` : ""),
                });
            } catch (importError) {
                reports.push({ok: false, text: `${employeeId} (${entry.file.name}): ${importError.message}`});
            }
        }
        const successful = reports.filter((report) => report.ok);
        const failed = reports.filter((report) => !report.ok);
        setImportFiles([]);
        try {
            await loadDashboard();
        } finally {
            setImporting(false);
        }
        setNotice(`Imported ${successful.length} of ${reports.length} employee file(s).\n${successful.map((report) => report.text).join("\n")}`);
        if (failed.length) setError(`Some files were not imported:\n${failed.map((report) => report.text).join("\n")}`);
    };

    const dates = summary?.daily_performance || [];
    const metrics = summary?.daily_summary || {};
    const history = summary?.house_history || {};
    const quality = summary?.record_quality || {};
    const employees = summary?.filters?.vehicle_id || [];
    const chartRows = (key) => dates.filter((row) => row[key] != null);
    const hasHouseVisitData = Boolean(metrics.house_visits_available);
    const selectedEmployeeLabel = selectedEmployee || "All Employees";
    const timeRows = summary?.daily_time_performance?.daily || [];
    const timeByDate = new Map();
    timeRows.forEach((row) => {
        const aggregate = timeByDate.get(row.date) || {
            gps_observed_seconds: null,
            between_collection_interval_count: 0,
            total_between_collection_seconds: 0,
            longest_between_collection_seconds: null,
        };
        if (row.gps_observed_seconds != null) {
            aggregate.gps_observed_seconds =
                (aggregate.gps_observed_seconds || 0) + row.gps_observed_seconds;
        }
        aggregate.between_collection_interval_count +=
            row.between_collection_interval_count || 0;
        aggregate.total_between_collection_seconds +=
            row.total_between_collection_seconds || 0;
        if (row.longest_between_collection_seconds != null
            && (aggregate.longest_between_collection_seconds == null
                || row.longest_between_collection_seconds > aggregate.longest_between_collection_seconds)) {
            aggregate.longest_between_collection_seconds =
                row.longest_between_collection_seconds;
        }
        timeByDate.set(row.date, aggregate);
    });
    timeByDate.forEach((aggregate) => {
        aggregate.average_between_collection_seconds =
            aggregate.between_collection_interval_count
                ? Math.round(aggregate.total_between_collection_seconds
                    / aggregate.between_collection_interval_count)
                : null;
    });
    const houseIdsByDate = new Map();
    (history.reference_ids || []).forEach((reference) => {
        (reference.collection_dates || []).forEach((date) => {
            if (!houseIdsByDate.has(date)) houseIdsByDate.set(date, new Set());
            houseIdsByDate.get(date).add(reference.house_id);
        });
    });
    const earlierMonthlyHouseIds = new Map();
    const monthlyMissingHousesByDate = new Map();
    dates.forEach((row) => {
        const month = row.date.slice(0, 7);
        const recordedToday = houseIdsByDate.get(row.date) || new Set();
        const recordedEarlierThisMonth = earlierMonthlyHouseIds.get(month) || new Set();
        monthlyMissingHousesByDate.set(row.date, {
            baselineCount: recordedEarlierThisMonth.size,
            houseIds: [...recordedEarlierThisMonth]
                .filter((houseId) => !recordedToday.has(houseId))
                .sort((a, b) => a.localeCompare(b)),
        });
        const updatedMonthHouseIds = new Set(recordedEarlierThisMonth);
        recordedToday.forEach((houseId) => updatedMonthHouseIds.add(houseId));
        earlierMonthlyHouseIds.set(month, updatedMonthHouseIds);
    });
    const hasGpsTime = timeRows.some((row) => row.gps_observed_seconds != null);
    const availableDateCount = availableDates.length;
    const availableDatesLabel = summary && periodMode === "date" && selectedDate
        ? `Date: ${selectedDate}`
        : summary && periodMode === "range"
            ? `Date range: ${startDate || "start"} to ${endDate || "end"}`
        : summary
        ? `All uploaded dates (${availableDateCount})`
        : loading ? "Loading uploaded dates…" : "No uploaded dates";

    return (
        <div className="h-full overflow-y-auto bg-slate-50 p-4 sm:p-6">
            <div className="mx-auto max-w-[1400px] space-y-5">
                <header className="rounded-2xl bg-gradient-to-r from-slate-900 via-blue-900 to-teal-800 px-5 py-6 text-white shadow-lg sm:px-7">
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-teal-200">Operations overview</p>
                    <h1 className="mt-2 text-2xl font-bold tracking-tight sm:text-3xl">Employee Performance Analysis</h1>
                    <p className="mt-2 max-w-2xl text-sm leading-6 text-blue-100">
                        A clear view of recorded travel, house collections, time and dumping activity.
                    </p>
                    <p className="mt-4 text-xs font-medium text-blue-100">
                        {selectedEmployeeLabel}
                        <span className="px-1 text-blue-300">·</span>
                        {availableDatesLabel}
                    </p>
                </header>

                <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
                    <div className="mb-4">
                        <h2 className="text-base font-semibold text-slate-900">Choose what to review</h2>
                        <p className="mt-1 text-xs text-slate-500">
                            All dates are included by default. Choose an employee and, if needed, a single date or date range.
                        </p>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                        <label className="grid gap-1 text-xs font-medium text-slate-600">
                            Employee
                            <select
                                className="rounded border bg-white px-3 py-2 text-sm text-slate-800"
                                value={selectedEmployee}
                                onChange={(event) => setSelectedEmployee(event.target.value)}
                            >
                                <option value="">All Employees</option>
                                {employees.map((employee) => (
                                    <option key={employee} value={employee}>
                                        {employee === "unassigned-sample" ? "Unassigned sample data" : employee}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <label className="grid gap-1 text-xs font-medium text-slate-600">
                            Reporting period
                            <select className="rounded border bg-white px-3 py-2 text-sm text-slate-800"
                                value={periodMode} onChange={(event) => setPeriodMode(event.target.value)}>
                                <option value="all">All available dates</option>
                                <option value="date">One date</option>
                                <option value="range">Date range</option>
                            </select>
                        </label>
                        {periodMode === "date" && (
                            <label className="grid gap-1 text-xs font-medium text-slate-600">
                                Date
                                <input type="date" className="rounded border bg-white px-3 py-2 text-sm text-slate-800"
                                    value={selectedDate}
                                    min={availableDates[0]}
                                    max={availableDates[availableDates.length - 1]}
                                    onChange={(event) => setSelectedDate(event.target.value)}/>
                            </label>
                        )}
                        {periodMode === "range" && (
                            <>
                                <label className="grid gap-1 text-xs font-medium text-slate-600">
                                    Start date
                                    <input type="date" className="rounded border bg-white px-3 py-2 text-sm text-slate-800"
                                        value={startDate}
                                        max={endDate || undefined}
                                        onChange={(event) => setStartDate(event.target.value)}/>
                                </label>
                                <label className="grid gap-1 text-xs font-medium text-slate-600">
                                    End date
                                    <input type="date" className="rounded border bg-white px-3 py-2 text-sm text-slate-800"
                                        value={endDate}
                                        min={startDate || undefined}
                                        onChange={(event) => setEndDate(event.target.value)}/>
                                </label>
                            </>
                        )}
                    </div>
                </section>

                <details className="rounded-lg border bg-white p-4">
                    <summary className="cursor-pointer text-sm font-semibold text-slate-800">Upload employee files</summary>
                    <div className="mt-3 space-y-3">
                        <label className="grid gap-1 text-sm text-slate-700">
                            Select one JSON/TXT export per employee
                            <input type="file" accept=".json,.txt,application/json,text/plain" multiple
                                onChange={(event) => setImportFiles(
                                    Array.from(event.target.files || []).map((file) => ({
                                        file,
                                        employeeId: "",
                                        weightUnit: "",
                                    }))
                                )}/>
                        </label>
                        {importFiles.map((entry, index) => (
                            <div key={`${entry.file.name}-${index}`} className="grid max-w-3xl gap-2 text-xs text-slate-600 sm:grid-cols-[1fr_0.7fr_0.7fr] sm:items-center">
                                <span className="truncate" title={entry.file.name}>{entry.file.name}</span>
                                <input className="rounded border px-2 py-1 text-sm" value={entry.employeeId}
                                    onChange={(event) => setImportFiles((current) => current.map((item, itemIndex) =>
                                        itemIndex === index ? {...item, employeeId: event.target.value} : item
                                    ))}
                                    placeholder="Employee ID"/>
                                <select className="rounded border bg-white px-2 py-1 text-sm"
                                    aria-label={`Weight unit for ${entry.file.name}`}
                                    value={entry.weightUnit}
                                    onChange={(event) => setImportFiles((current) => current.map((item, itemIndex) =>
                                        itemIndex === index ? {...item, weightUnit: event.target.value} : item
                                    ))}>
                                    <option value="">Weight unit from file</option>
                                    <option value="kg">Weights are in kilograms</option>
                                    <option value="tonnes">Weights are in tonnes</option>
                                </select>
                            </div>
                        ))}
                        <p className="text-xs text-slate-500">
                            Each file is imported under its employee ID. If the file’s dump records do not specify a unit, choose the correct unit here; values are converted to kilograms. Imports merge with existing records. A file should contain data for one employee.
                        </p>
                        <button className="rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                            onClick={importRecords} disabled={importing || !importFiles.length}>
                            {importing ? "Importing…" : "Import employee files"}
                        </button>
                    </div>
                </details>

                {error && <div role="alert" className="whitespace-pre-line rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">{error}</div>}
                {notice && <div role="status" className="whitespace-pre-line rounded border border-green-300 bg-green-50 p-3 text-sm text-green-800">{notice}</div>}
                {loading && <p className="text-sm text-slate-500">Loading performance data…</p>}
                {summary && !summary.data_available && (
                    <div className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
                        No records are available yet. Upload an employee file to begin.
                    </div>
                )}

                {summary?.daily_summary && (
                    <>
                        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                            <div className="mb-4">
                                <h2 className="text-base font-semibold text-slate-900">At a glance</h2>
                                <p className="mt-1 text-xs text-slate-500">
                                    Key totals for {selectedEmployeeLabel} · {dates.length} date(s) with records in this view.
                                </p>
                            </div>
                            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                                <MetricCard label="Distance travelled"
                                    value={metrics.total_distance_km == null ? "Unavailable" : `${formatNumber(metrics.total_distance_km)} km`}
                                    detail="GPS-based estimate"/>
                                <MetricCard label="Unique houses recorded"
                                    value={hasHouseVisitData
                                        ? formatNumber(metrics.total_unique_houses_recorded_visited, 0)
                                        : "Unavailable"}
                                    detail="House IDs recorded in collection lists"/>
                                <MetricCard label="Average houses per day"
                                    value={!hasHouseVisitData || metrics.average_daily_houses_recorded_visited == null
                                        ? "Unavailable"
                                        : formatNumber(metrics.average_daily_houses_recorded_visited, 0)}
                                    detail={hasHouseVisitData
                                        ? `${metrics.house_collection_days_included || 0} recorded collection day(s)`
                                        : "Collection records unavailable"}/>
                                <MetricCard label="GPS time counted"
                                    value={hasGpsTime
                                        ? formatDuration(timeRows.reduce(
                                            (total, row) => total + (row.gps_observed_seconds || 0), 0
                                        ))
                                        : "Unavailable"}
                                    detail="Only valid GPS intervals are included"/>
                            </div>
                        </section>

                        <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                            <div>
                                <h2 className="text-lg font-semibold text-slate-900">1. Distance</h2>
                                <p className="text-xs text-slate-600">
                                    GPS-based point-to-point distance; it is not road distance. Gaps over 15 minutes and unrealistic jumps are excluded.
                                </p>
                            </div>
                            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                                <MetricCard label="Total distance" value={metrics.total_distance_km == null ? "Unavailable" : `${formatNumber(metrics.total_distance_km)} km`}/>
                                <MetricCard label="Average per recorded GPS day" value={metrics.average_daily_distance_km == null ? "Unavailable" : `${formatNumber(metrics.average_daily_distance_km)} km`}
                                    detail={`${metrics.distance_days_included} day(s) with usable GPS data`}/>
                                <MetricCard label="Longest travel day" value={metrics.highest_distance_day ? `${metrics.highest_distance_day.date} · ${formatNumber(metrics.highest_distance_day.distance_km)} km` : "Unavailable"}/>
                                <MetricCard label="Shortest travel day" value={metrics.lowest_distance_day ? `${metrics.lowest_distance_day.date} · ${formatNumber(metrics.lowest_distance_day.distance_km)} km` : "Unavailable"}/>
                            </div>
                            <TrendChart title="Distance by day (km)" rows={chartRows("distance_km")} valueKey="distance_km" color="#2563eb"
                                unit=" km" emptyMessage="No usable GPS distance for this selection."/>
                            <DataTable headers={["Date", "Distance travelled"]}
                                rows={dates.map((row) => (
                                    <tr key={row.date} className="border-b last:border-0">
                                        <td className="py-2 pr-3">{row.date}</td>
                                        <td className="py-2">{row.distance_km == null ? "Unavailable" : `${formatNumber(row.distance_km)} km`}</td>
                                    </tr>
                                ))}
                                emptyMessage="No daily records are available in the uploaded data."
                                minWidth="360px" maxHeight="20rem"/>
                        </section>

                        <TimeAnalysis data={summary.daily_time_performance}/>

                        <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                            <div>
                                <h2 className="text-lg font-semibold text-slate-900">3. Houses Collected</h2>
                                <p className="text-xs text-slate-600">
                                    As confirmed for this dataset, each collection-list reference ID is a House ID. The same ID is counted once per day, even if it appears in multiple scans.
                                </p>
                            </div>
                            {hasHouseVisitData ? (
                                <>
                                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                                        <MetricCard label="Unique houses recorded visited" value={formatNumber(metrics.total_unique_houses_recorded_visited, 0)}/>
                                        <MetricCard label="Average houses visited per recorded day"
                                            value={formatNumber(metrics.average_daily_houses_recorded_visited, 0)}
                                            detail={`${metrics.house_collection_days_included} day(s) with House IDs recorded`}/>
                                        <MetricCard label="House IDs recorded on multiple days"
                                            value={formatNumber(history.collected_multiple_days_count, 0)}
                                            detail="Repeat records are expected for daily collection"/>
                                        <MetricCard label="Recorded once"
                                            value={formatNumber(history.collected_once_count, 0)}
                                            detail="Known House IDs recorded on one selected-period date"/>
                                        <MetricCard label="Known IDs with no record in period"
                                            value={formatNumber(history.houses_without_recorded_visit_count, 0)}
                                            detail="Known reference/master IDs only; not a complete beat roster"/>
                                    </div>
                                    <TrendChart title="Houses recorded visited by day"
                                        rows={chartRows("houses_recorded_visited")}
                                        valueKey="houses_recorded_visited" color="#0f766e"
                                        emptyMessage="No House IDs were recorded for this selection."/>
                                    <DataTable headers={["Date", "House IDs in list", "Earlier House IDs not in today’s list"]}
                                        rows={dates.map((row) => {
                                            const missing = monthlyMissingHousesByDate.get(row.date);
                                            return (
                                            <tr key={row.date} className="border-b last:border-0">
                                                <td className="py-2 pr-3">{row.date}</td>
                                                <td className="py-2 pr-3">
                                                    {row.houses_recorded_visited == null
                                                        ? "Unavailable"
                                                        : formatNumber(row.houses_recorded_visited, 0)}
                                                </td>
                                                <td className="py-2">
                                                    {row.houses_recorded_visited == null ? (
                                                        <span className="text-xs text-slate-500">
                                                            Unavailable — no House ID records to compare for this date
                                                        </span>
                                                    ) : missing?.baselineCount ? (
                                                        <div className="max-h-24 max-w-[42rem] overflow-auto rounded-md bg-slate-50 p-2 text-xs text-slate-700">
                                                            <span className="mb-1 block font-medium text-slate-800">
                                                                {formatNumber(missing.houseIds.length, 0)} of {formatNumber(missing.baselineCount, 0)} earlier House IDs are absent from today’s list
                                                            </span>
                                                            {missing.houseIds.length
                                                                ? missing.houseIds.join(", ")
                                                                : "All previously recorded House IDs also appear today."}
                                                        </div>
                                                    ) : (
                                                        <span className="text-xs text-slate-500">
                                                            No earlier House IDs this month to compare
                                                        </span>
                                                    )}
                                                </td>
                                            </tr>
                                        )})}
                                        emptyMessage="No daily records are available in the uploaded data."
                                        minWidth="760px" maxHeight="24rem"/>
                                    <p className="text-xs text-slate-500">
                                        This is a list comparison, not a missed-house count. Garbage vehicles may revisit the same houses daily, while daily totals and House IDs can vary with the assigned area, route, or collection load.
                                    </p>
                                    <p className="text-xs text-slate-500">
                                        Repeated and once-only counts describe how often House IDs appear across selected-period lists. “Known IDs with no record” is limited to IDs present in the available history/master records; it does not confirm a missed collection.
                                    </p>
                                </>
                            ) : (
                                <p className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
                                    No collection-list House IDs are available for this employee in the uploaded data.
                                </p>
                            )}
                        </section>

                        <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                            <div>
                                <h2 className="text-lg font-semibold text-slate-900">4. Garbage Collection</h2>
                                <p className="text-xs text-slate-600">
                                    Weight is shown only when the recorded value is positive and its unit is known. Missing or zero weights are unavailable, not zero waste.
                                </p>
                            </div>
                            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                                <MetricCard label="Dumping trips" value={formatNumber(metrics.dumping_trips, 0)}/>
                                <MetricCard label="Total garbage weight" value={formatWeight(metrics.total_garbage_weight_kg)}
                                    detail={metrics.dump_weight_complete ? "All recorded trips have valid weights" : "Unavailable if any trip weight is missing or unverified"}/>
                                <MetricCard label="Weight from trips with valid measurements" value={formatWeight(metrics.recorded_garbage_weight_kg)}
                                    detail={metrics.weighted_dump_trips == null
                                        ? "Valid trip weights unavailable"
                                        : `${formatNumber(metrics.weighted_dump_trips, 0)} of ${formatNumber(metrics.dumping_trips, 0)} trips have valid weights; ${formatNumber(metrics.unweighted_dump_trips, 0)} unavailable`}/>
                                <MetricCard label="Average weight per day" value={formatWeight(metrics.average_daily_garbage_weight_kg)}
                                    detail={`${metrics.weight_days_included || 0} day(s) with usable weight records`}/>
                                <MetricCard label="Weight per dumping trip" value={formatWeight(metrics.weight_per_dumping_trip_kg)}
                                    detail="Available only when every recorded trip has a valid weight"/>
                                <MetricCard label="Weight per recorded house" value={formatWeight(metrics.garbage_weight_per_collected_house_kg)}
                                    detail="Requires complete trip weights and recorded House IDs"/>
                                <MetricCard label="Wet waste" value={formatWeight(metrics.wet_waste_weight_kg)}/>
                                <MetricCard label="Dry waste" value={formatWeight(metrics.dry_waste_weight_kg)}/>
                            </div>
                            {!metrics.dump_weight_complete && metrics.recorded_garbage_weight_kg != null && (
                                <p className="rounded border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
                                    Some recorded dumping trips have no valid weight. The complete total is unavailable; the partial amount above includes only trips with verified positive weights.
                                </p>
                            )}
                            <TrendChart title="Recorded garbage weight by day (kg)"
                                rows={chartRows("garbage_weight_kg")} valueKey="garbage_weight_kg" color="#d97706"
                                unit=" kg" emptyMessage="Weight is unavailable because no complete valid weight records were supplied."/>
                            <DataTable headers={["Date", "Dumping trips", "Total weight", "Wet waste", "Dry waste"]}
                                rows={dates.filter((row) => row.dumping_trips || row.garbage_weight_kg != null).map((row) => (
                                    <tr key={row.date} className="border-b last:border-0">
                                        <td className="py-2 pr-3">{row.date}</td>
                                        <td className="py-2 pr-3">{formatNumber(row.dumping_trips, 0)}</td>
                                        <td className="py-2 pr-3">{formatWeight(row.garbage_weight_kg)}</td>
                                        <td className="py-2 pr-3">{formatWeight(row.wet_weight_kg)}</td>
                                        <td className="py-2">{formatWeight(row.dry_weight_kg)}</td>
                                    </tr>
                                ))}
                                emptyMessage="No dumping records are available in the uploaded data."
                                minWidth="620px" maxHeight="20rem"/>
                        </section>

                        <details className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                            <summary className="cursor-pointer list-none">
                                <h2 className="text-lg font-semibold text-slate-900">House Collection History</h2>
                                <p className="text-xs text-slate-600">
                                    The collection-list reference ID is the House ID. “No record” means no collection-list entry exists for that House ID on those dates; it does not confirm whether the house was physically missed.
                                </p>
                            </summary>
                            <div className="mt-3 space-y-3">
                            {hasHouseVisitData ? (
                                <>
                                    <CollectionDayComparison
                                        dates={dates.map((row) => row.date)}
                                        references={history.reference_ids || []}
                                    />
                                    <HouseHistoryTable title="House IDs recorded on multiple days"
                                        rows={history.visited_on_multiple_days || []}
                                        showDates
                                        emptyMessage="No House IDs appear on multiple selected days."/>
                                    <HouseHistoryTable title="Known House IDs with no record in selected period"
                                        rows={(history.houses_without_recorded_visit || []).map((row) => ({...row, visit_days: 0}))}
                                        emptyMessage="Every known House ID was recorded in this period."/>
                                    {history.houses_without_recorded_visit?.length >= 500 && (
                                        <p className="text-xs text-slate-500">
                                            Showing up to 500 known House IDs without a record.
                                        </p>
                                    )}
                                </>
                            ) : (
                                <p className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
                                    House history is unavailable because no collection-list House IDs were recorded in the uploaded data.
                                </p>
                            )}
                            <section className="space-y-2 border-t pt-3">
                                <div>
                                    <h3 className="text-sm font-semibold text-slate-800">Collection performance by house-location grid</h3>
                                    <p className="text-xs text-slate-600">
                                        Each House ID is placed using its house-master coordinates. The rate is the share of registered houses in that grid with a collection record in the uploaded data. No record does not prove a missed visit.
                                    </p>
                                </div>
                                {summary.house_grid_performance?.available ? (
                                    <>
                                        <DataTable
                                            headers={["Grid", "Houses recorded visited", "Registered houses", "Recorded coverage", "No visit record"]}
                                            rows={(summary.house_grid_performance.zones || []).map((zone) => (
                                                <tr key={zone.zone} className="border-b last:border-0">
                                                    <td className="py-2 pr-3 font-medium">{zone.zone}</td>
                                                    <td className="py-2 pr-3">{formatNumber(zone.houses_recorded_visited, 0)}</td>
                                                    <td className="py-2 pr-3">{formatNumber(zone.registered_houses, 0)}</td>
                                                    <td className="py-2 pr-3">{zone.recorded_visit_rate_pct == null ? "Unavailable" : `${formatNumber(zone.recorded_visit_rate_pct)}%`}</td>
                                                    <td className="py-2">{formatNumber(zone.houses_without_recorded_visit, 0)}</td>
                                                </tr>
                                            ))}
                                            emptyMessage="No House ID locations are available to build grids."
                                            minWidth="700px"
                                            maxHeight="18rem"
                                        />
                                        {(summary.house_grid_performance.unmatched_reference_ids > 0
                                            || summary.house_grid_performance.ambiguous_reference_ids > 0) && (
                                            <p className="text-xs text-amber-800">
                                                {formatNumber(summary.house_grid_performance.unmatched_reference_ids, 0)} collection-list IDs had no matching House ID location; {formatNumber(summary.house_grid_performance.ambiguous_reference_ids, 0)} matched multiple house records and were not assigned to a grid.
                                            </p>
                                        )}
                                    </>
                                ) : summary.geographic_activity_zones?.length ? (
                                    <>
                                        <p className="text-xs text-amber-800">
                                            The uploaded house coordinates have no linked House IDs, so house coverage cannot be calculated. This grid shows scan locations only; it does not confirm that a house was visited.
                                        </p>
                                        <DataTable
                                            headers={["Grid", "House-coordinate points", "Collection IDs at scan locations", "Scan observations"]}
                                            rows={summary.geographic_activity_zones.map((zone) => (
                                                <tr key={zone.zone} className="border-b last:border-0">
                                                    <td className="py-2 pr-3 font-medium">{zone.zone}</td>
                                                    <td className="py-2 pr-3">{formatNumber(zone.house_coordinate_count, 0)}</td>
                                                    <td className="py-2 pr-3">{formatNumber(zone.unique_reference_ids, 0)}</td>
                                                    <td className="py-2">{formatNumber(zone.scan_observation_count, 0)}</td>
                                                </tr>
                                            ))}
                                            emptyMessage="No coordinate grid activity is available in the uploaded data."
                                            minWidth="700px"
                                            maxHeight="18rem"
                                        />
                                        <p className="text-xs text-slate-500">
                                            Grids are based on the uploaded house-coordinate list. Scan activity is grouped by the scan’s GPS position, so one collection ID may appear in multiple grids.
                                        </p>
                                    </>
                                ) : (
                                    <p className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
                                        Grid data is unavailable. Upload house coordinates and collection scans with recorded locations.
                                    </p>
                                )}
                            </section>
                            </div>
                        </details>

                        <TravelHouseComparison rows={dates} metrics={metrics} quality={quality}
                            selectedEmployee={selectedEmployee} timeByDate={timeByDate}/>
                        <CollectionGapAnalysis data={summary.daily_time_performance}
                            rows={dates} timeByDate={timeByDate}/>
                        <DailyPerformanceSummary rows={dates} timeByDate={timeByDate}/>

                        <p className="text-xs text-slate-500">
                            Showing {selectedEmployeeLabel}. Averages use days with valid records. {formatNumber(metrics.invalid_gps_intervals, 0)} invalid GPS intervals were excluded. House visits use House IDs from collection lists or explicit collection records; GPS movement alone is not counted as a visit.
                        </p>
                        <ImprovementSuggestions rows={dates} metrics={metrics} quality={quality}
                            selectedEmployee={selectedEmployee}/>
                        <EmployeeProgressAnalysis
                            rows={dates}
                            timeByDate={timeByDate}
                            history={history}
                            selectedEmployee={selectedEmployee}
                        />
                    </>
                )}
            </div>
        </div>
    );
}
