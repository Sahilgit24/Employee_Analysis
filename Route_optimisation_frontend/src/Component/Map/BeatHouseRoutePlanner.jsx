import React, {useMemo, useRef, useState} from "react";
import L from "leaflet";
import {CircleMarker, MapContainer, Marker, Polygon, Polyline, Popup, TileLayer, useMap} from "react-leaflet";
import {API_URL} from "@/config.js";

const startIcon = L.divIcon({
    className: "",
    html: '<div style="font-size:30px;line-height:34px;text-shadow:0 1px 3px #fff" title="Route start">🚛</div>',
    iconSize: [36, 36],
    iconAnchor: [18, 30],
});
const endIcon = L.divIcon({
    className: "",
    html: '<div style="font-size:28px;line-height:34px;text-shadow:0 1px 3px #fff" title="Route end">🏁</div>',
    iconSize: [36, 36],
    iconAnchor: [18, 30],
});
const dumpyardIcon = L.divIcon({
    className: "",
    html: '<div style="font-size:27px;line-height:32px;text-shadow:0 1px 3px #fff" title="Dumpyard">🗑️</div>',
    iconSize: [36, 36],
    iconAnchor: [18, 28],
});
const playbackVehicleIcon = L.divIcon({
    className: "",
    html: '<div style="font-size:24px;line-height:28px;text-shadow:0 1px 3px #fff" title="Optimized route position">🚛</div>',
    iconSize: [32, 32],
    iconAnchor: [16, 24],
});

function getRoutePosition(routePath, progress) {
    if (!routePath?.length) return null;
    if (routePath.length === 1 || progress <= 0) return [routePath[0].lat, routePath[0].lon];

    const segmentLengths = [];
    let totalLength = 0;
    for (let index = 1; index < routePath.length; index += 1) {
        const previous = routePath[index - 1];
        const current = routePath[index];
        const latDistance = (current.lat - previous.lat) * 111320;
        const lonDistance = (current.lon - previous.lon) * 111320 *
            Math.cos((previous.lat + current.lat) * Math.PI / 360);
        const segmentLength = Math.hypot(latDistance, lonDistance);
        segmentLengths.push(segmentLength);
        totalLength += segmentLength;
    }

    let remainingDistance = totalLength * progress;
    for (let index = 0; index < segmentLengths.length; index += 1) {
        const segmentLength = segmentLengths[index];
        if (remainingDistance <= segmentLength || index === segmentLengths.length - 1) {
            const fraction = segmentLength === 0 ? 0 : Math.min(1, remainingDistance / segmentLength);
            const from = routePath[index];
            const to = routePath[index + 1];
            return [
                from.lat + (to.lat - from.lat) * fraction,
                from.lon + (to.lon - from.lon) * fraction,
            ];
        }
        remainingDistance -= segmentLength;
    }
    const lastPoint = routePath[routePath.length - 1];
    return [lastPoint.lat, lastPoint.lon];
}

function distanceFromRouteMeters(point, routePath) {
    if (!routePath?.length) return null;
    let minimum = Infinity;
    const metersPerDegree = 111320;
    const cosLatitude = Math.cos(point.lat * Math.PI / 180);
    for (let index = 0; index < routePath.length; index += 1) {
        const from = routePath[index];
        const to = routePath[Math.min(index + 1, routePath.length - 1)];
        const fromX = (from.lon - point.lon) * metersPerDegree * cosLatitude;
        const fromY = (from.lat - point.lat) * metersPerDegree;
        const toX = (to.lon - point.lon) * metersPerDegree * cosLatitude;
        const toY = (to.lat - point.lat) * metersPerDegree;
        const dx = toX - fromX;
        const dy = toY - fromY;
        const lengthSquared = dx * dx + dy * dy;
        const fraction = lengthSquared === 0
            ? 0
            : Math.max(0, Math.min(1, -(fromX * dx + fromY * dy) / lengthSquared));
        minimum = Math.min(minimum, Math.hypot(fromX + fraction * dx, fromY + fraction * dy));
    }
    return minimum;
}

function isInsidePolygon(point, polygon) {
    let inside = false;
    const x = point.lon;
    const y = point.lat;
    for (let index = 0, previous = polygon.length - 1; index < polygon.length; previous = index, index += 1) {
        const currentPoint = polygon[index];
        const previousPoint = polygon[previous];
        const cross = (x - previousPoint[1]) * (currentPoint[0] - previousPoint[0]) -
            (y - previousPoint[0]) * (currentPoint[1] - previousPoint[1]);
        if (Math.abs(cross) < 1e-10 &&
            x >= Math.min(previousPoint[1], currentPoint[1]) && x <= Math.max(previousPoint[1], currentPoint[1]) &&
            y >= Math.min(previousPoint[0], currentPoint[0]) && y <= Math.max(previousPoint[0], currentPoint[0])) {
            return true;
        }
        const crosses = ((currentPoint[0] > y) !== (previousPoint[0] > y)) &&
            (x < (previousPoint[1] - currentPoint[1]) * (y - currentPoint[0]) /
                (previousPoint[0] - currentPoint[0]) + currentPoint[1]);
        if (crosses) inside = !inside;
    }
    return inside;
}

function parseVehicleFile(fileName, data) {
    if (!Array.isArray(data)) {
        throw new Error(`${fileName} must contain a JSON array of dated vehicle routes.`);
    }

    return data.map((record, dayIndex) => {
        if (!record?.date || !Array.isArray(record.emproute)) {
            throw new Error(`${fileName} has an invalid record at item ${dayIndex + 1}.`);
        }
        const trackPoints = record.emproute.map((point, pointIndex) => {
            const lat = Number(point?.lat);
            const lon = Number(point?.lon);
            const timestamp = Date.parse(point?.datetime);
            if (point?.lat == null || String(point.lat).trim() === "" || point?.lon == null || String(point.lon).trim() === "" ||
                !Number.isFinite(lat) || Math.abs(lat) > 90 || !Number.isFinite(lon) || Math.abs(lon) > 180 || !Number.isFinite(timestamp)) {
                throw new Error(`${fileName} has an invalid GPS coordinate or timestamp on ${record.date} (point ${pointIndex + 1}).`);
            }
            return {lat, lon, timestamp, datetime: point.datetime};
        }).sort((a, b) => a.timestamp - b.timestamp);
        const collectionList = record.Collectionlist ?? record.collectionList ?? [];
        if (!Array.isArray(collectionList)) {
            throw new Error(`${fileName} has an invalid Collectionlist on ${record.date}.`);
        }
        const collectionScans = collectionList.map((collection, collectionIndex) => {
            const plateId = collection?.referanceId ?? collection?.referenceId;
            const hasLat = collection?.lat != null && String(collection.lat).trim() !== "";
            const hasLon = collection?.lon != null && String(collection.lon).trim() !== "";
            let lat = null;
            let lon = null;
            if (hasLat !== hasLon) {
                throw new Error(`${fileName} has an incomplete collection coordinate on ${record.date} (item ${collectionIndex + 1}).`);
            }
            if (hasLat) {
                lat = Number(collection.lat);
                lon = Number(collection.lon);
                if (!Number.isFinite(lat) || Math.abs(lat) > 90 || !Number.isFinite(lon) || Math.abs(lon) > 180) {
                    throw new Error(`${fileName} has an invalid collection coordinate on ${record.date} (item ${collectionIndex + 1}).`);
                }
            }
            const plateIdText = plateId == null ? "" : String(plateId).trim();
            if (!plateIdText && lat == null) {
                throw new Error(`${fileName} has a collection without a plate ID or coordinates on ${record.date} (item ${collectionIndex + 1}).`);
            }
            return {plateId: plateIdText || null, lat, lon, datetime: collection?.datetime ?? null};
        });
        return {date: String(record.date), trackPoints, collectionScans};
    }).sort((a, b) => a.date.localeCompare(b.date));
}

function parseBeatFile(fileName, data) {
    if (!data || typeof data !== "object" || typeof data.geofence !== "string" || !Array.isArray(data.houses)) {
        throw new Error(`${fileName} must contain a geofence string and a houses array.`);
    }

    const geofence = data.geofence.split(";").map((pair, index) => {
        const values = pair.split(",").map(Number);
        if (values.length !== 2 || !values.every(Number.isFinite) || Math.abs(values[0]) > 90 || Math.abs(values[1]) > 180) {
            throw new Error(`${fileName} has an invalid geofence coordinate at item ${index + 1}.`);
        }
        return values;
    });
    if (geofence.length < 3) {
        throw new Error(`${fileName} geofence must contain at least three coordinates.`);
    }

    const coordinateOccurrences = new Map();
    const houses = data.houses.map((house, index) => {
        const lat = Number(house?.lat);
        const lon = Number(house?.lon);
        const houseId = house?.house_id ?? house?.House_Id ?? house?.houseId;
        const masterPlateId = house?.master_plate_id ?? house?.masterPlateId;
        if (house?.lat == null || String(house.lat).trim() === "" || house?.lon == null || String(house.lon).trim() === "" ||
            !Number.isFinite(lat) || Math.abs(lat) > 90 || !Number.isFinite(lon) || Math.abs(lon) > 180) {
            throw new Error(`${fileName} has an invalid house coordinate at item ${index + 1}.`);
        }
        const coordinateKey = `${lat.toFixed(7)},${lon.toFixed(7)}`;
        const occurrence = coordinateOccurrences.get(coordinateKey) || 0;
        coordinateOccurrences.set(coordinateKey, occurrence + 1);
        const normalizedHouseId = houseId == null || String(houseId).trim() === ""
            ? null
            : String(houseId).trim();
        return {
            lat,
            lon,
            house_id: normalizedHouseId,
            route_key: `${coordinateKey}:${occurrence}`,
            hasHouseId: normalizedHouseId != null,
            master_plate_id: masterPlateId == null || String(masterPlateId).trim() === ""
                ? null
                : String(masterPlateId).trim(),
        };
    });
    if (houses.length === 0) {
        throw new Error(`${fileName} contains no houses.`);
    }
    if (data.dumpyards != null && !Array.isArray(data.dumpyards)) {
        throw new Error(`${fileName} dumpyards property must be an array.`);
    }
    const dumpyards = (data.dumpyards || []).map((dumpyard, index) => {
        const lat = Number(dumpyard?.lat);
        const lon = Number(dumpyard?.lon);
        if (dumpyard?.lat == null || String(dumpyard.lat).trim() === "" ||
            dumpyard?.lon == null || String(dumpyard.lon).trim() === "" ||
            !Number.isFinite(lat) || Math.abs(lat) > 90 || !Number.isFinite(lon) || Math.abs(lon) > 180) {
            throw new Error(`${fileName} has an invalid dumpyard coordinate at item ${index + 1}.`);
        }
        return {lat, lon, name: String(dumpyard.name || dumpyard.dumpyard_id || `Dumpyard ${index + 1}`)};
    });
    return {
        geofence: data.geofence,
        fencePoints: geofence,
        houses,
        dumpyards,
        hasHouseIds: houses.every((house) => house.hasHouseId),
        name: fileName,
    };
}

function parseCombinedFile(fileName, data) {
    if (!data || typeof data !== "object" || Array.isArray(data) ||
        typeof data.geofence !== "string" || !Array.isArray(data.houses) || !Array.isArray(data.routes)) {
        throw new Error(`${fileName} must contain geofence, houses, and routes properties in JSON format.`);
    }

    const beat = parseBeatFile(fileName, data);
    const days = parseVehicleFile(fileName, data.routes);
    const coordinatesByReference = new Map();
    for (const day of days) {
        for (const scan of day.collectionScans) {
            if (!scan.plateId || scan.lat == null || scan.lon == null) continue;
            const coordinates = coordinatesByReference.get(scan.plateId) || new Set();
            coordinates.add(`${scan.lat},${scan.lon}`);
            coordinatesByReference.set(scan.plateId, coordinates);
        }
    }
    const dumpRecords = data.routes.reduce((count, route) =>
        count + (Array.isArray(route?.dumplist) ? route.dumplist.length : 0), 0);

    return {
        beat: {
            ...beat,
            dataQuality: {
                housesWithIds: beat.houses.filter((house) => house.hasHouseId).length,
                referencesAtMultipleCoordinates: [...coordinatesByReference.values()]
                    .filter((coordinates) => coordinates.size > 1).length,
                dumpRecords,
                hasVehicleId: Boolean(data.vehicle_id || data.vehicleId ||
                    data.routes.some((route) => route?.vehicle_id || route?.vehicleId)),
                hasBeatId: Boolean(data.beat_id || data.beatId),
            },
        },
        days,
    };
}

function getOutsideBeatSections(routePath, polygon) {
    if (!routePath?.length || polygon?.length < 3) {
        return {sections: [], distanceKm: 0};
    }

    const sections = [];
    let activeSection = null;
    let distanceMeters = 0;
    const closeSection = () => {
        if (activeSection?.length > 1) sections.push(activeSection);
        activeSection = null;
    };

    for (let index = 1; index < routePath.length; index += 1) {
        const from = routePath[index - 1];
        const to = routePath[index];
        const midpointLatitude = (from.lat + to.lat) / 2;
        const dx = (to.lon - from.lon) * 111320 * Math.cos(midpointLatitude * Math.PI / 180);
        const dy = (to.lat - from.lat) * 111320;
        const segmentLength = Math.hypot(dx, dy);
        const steps = Math.max(1, Math.ceil(segmentLength / 25));

        for (let step = 0; step < steps; step += 1) {
            const startFraction = step / steps;
            const endFraction = (step + 1) / steps;
            const start = {
                lat: from.lat + (to.lat - from.lat) * startFraction,
                lon: from.lon + (to.lon - from.lon) * startFraction,
            };
            const end = {
                lat: from.lat + (to.lat - from.lat) * endFraction,
                lon: from.lon + (to.lon - from.lon) * endFraction,
            };
            const midpoint = {
                lat: (start.lat + end.lat) / 2,
                lon: (start.lon + end.lon) / 2,
            };
            if (!isInsidePolygon(midpoint, polygon)) {
                if (!activeSection) activeSection = [start];
                activeSection.push(end);
                distanceMeters += segmentLength / steps;
            } else {
                closeSection();
            }
        }
    }
    closeSection();

    return {sections, distanceKm: distanceMeters / 1000};
}

function getCollectedHouseIds(beat, day) {
    if (!beat?.hasHouseIds || !day) return new Set();
    const scannedPlateIds = new Set(day.collectionScans.map((scan) => scan.plateId).filter(Boolean));
    return new Set(beat.houses
        .filter((house) => scannedPlateIds.has(house.house_id) ||
            (house.master_plate_id && scannedPlateIds.has(house.master_plate_id)))
        .map((house) => house.house_id));
}

function getCollectionLocations(day) {
    if (!day) return [];
    const locations = new Map();
    for (const scan of day.collectionScans) {
        if (scan.lat == null || scan.lon == null) continue;
        const key = `${scan.lat.toFixed(7)},${scan.lon.toFixed(7)}`;
        if (!locations.has(key)) {
            locations.set(key, {lat: scan.lat, lon: scan.lon, plateIds: new Set()});
        }
        if (scan.plateId) locations.get(key).plateIds.add(scan.plateId);
    }
    return [...locations.values()].map(({lat, lon, plateIds}) => ({
        lat,
        lon,
        plateIds: [...plateIds].sort(),
        isMasterPlate: plateIds.size > 1,
    }));
}

function FitMapBounds({points, visible}) {
    const map = useMap();
    React.useEffect(() => {
        if (!visible || points.length === 0) return undefined;
        const frame = requestAnimationFrame(() => {
            map.invalidateSize();
            map.fitBounds(points, {padding: [28, 28]});
        });
        return () => cancelAnimationFrame(frame);
    }, [map, points, visible]);
    return null;
}

function formatDuration(minutes) {
    const totalMinutes = Math.round(Number(minutes) || 0);
    return `${Math.floor(totalMinutes / 60)}h ${totalMinutes % 60}m`;
}

function BeatRouteMap({
    beat,
    routes,
    selectedRouteId,
    recordedRoute,
    trackPoints,
    layer,
    visible,
    nearRouteThreshold,
    coveredHouseIds,
    showCollectedOnly,
    collectionMappingAvailable,
    collectionLocations,
}) {
    const [isPlaying, setIsPlaying] = useState(false);
    const [playbackType, setPlaybackType] = useState("historical");
    const [progress, setProgress] = useState(0);
    const progressRef = useRef(0);
    const selectedRoute = routes.find((route) => route.route_id === selectedRouteId);
    const stops = selectedRoute?.stops || routes[0]?.stops || [];
    const plannedHouseKeys = useMemo(
        () => new Set(stops.filter((stop) => stop.type === "house").map((stop) => stop.house_id)),
        [stops],
    );
    const visibleHouses = useMemo(
        () => (beat?.houses || []).filter((house) =>
            !showCollectedOnly || (collectionMappingAvailable && coveredHouseIds.has(house.house_id))
        ),
        [beat, collectionMappingAvailable, coveredHouseIds, showCollectedOnly],
    );
    const historicalPath = useMemo(
        () => recordedRoute?.route_path?.length
            ? recordedRoute.route_path
            : trackPoints.map(({lat, lon}) => ({lat, lon})),
        [recordedRoute, trackPoints],
    );
    const historicalOutsideBeat = useMemo(
        () => getOutsideBeatSections(historicalPath, beat?.fencePoints),
        [historicalPath, beat],
    );
    const optimizedOutsideBeat = useMemo(
        () => getOutsideBeatSections(selectedRoute?.route_path, beat?.fencePoints),
        [selectedRoute, beat],
    );
    const playbackPath = playbackType === "historical" ? historicalPath : selectedRoute?.route_path || [];
    const gpsTrackDistances = useMemo(() => {
        const result = new Map();
        if (!beat || !trackPoints.length) return result;
        for (const house of beat.houses) {
            result.set(house.route_key, distanceFromRouteMeters(house, trackPoints));
        }
        return result;
    }, [beat, trackPoints]);
    const vehiclePosition = getRoutePosition(playbackPath, progress);
    const bounds = useMemo(() => {
        const pathPoints = (selectedRoute?.route_path || []).map((point) => [point.lat, point.lon]);
        const recordedPathPoints = recordedRoute?.route_path?.length
            ? recordedRoute.route_path.map((point) => [point.lat, point.lon])
            : trackPoints.map((point) => [point.lat, point.lon]);
        const housePoints = visibleHouses.map((house) => [house.lat, house.lon]);
        const collectionPoints = collectionLocations.map((location) => [location.lat, location.lon]);
        const dumpyardPoints = (beat?.dumpyards || []).map((dumpyard) => [dumpyard.lat, dumpyard.lon]);
        const endpoints = stops.filter((stop) => stop.type !== "house").map((stop) => [stop.lat, stop.lon]);
        return [...pathPoints, ...recordedPathPoints, ...housePoints, ...collectionPoints, ...dumpyardPoints, ...endpoints, ...(beat?.fencePoints || [])];
    }, [beat, collectionLocations, recordedRoute, selectedRoute, stops, visibleHouses]);
    const center = bounds[0] || [0, 0];
    const tileUrl = layer === "satellite"
        ? "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
        : "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
    const routeColors = ["#2563eb", "#ea580c", "#9333ea", "#0891b2"];

    React.useEffect(() => {
        progressRef.current = 0;
        setProgress(0);
        setIsPlaying(false);
    }, [selectedRouteId, trackPoints]);

    React.useEffect(() => {
        if (!isPlaying || playbackPath.length < 2) return undefined;
        const playbackDuration = 30000;
        const startedAt = performance.now() - progressRef.current * playbackDuration;
        let frameId;
        const updateProgress = (now) => {
            const nextProgress = Math.min(1, (now - startedAt) / playbackDuration);
            progressRef.current = nextProgress;
            setProgress(nextProgress);
            if (nextProgress >= 1) {
                setIsPlaying(false);
                return;
            }
            frameId = requestAnimationFrame(updateProgress);
        };
        frameId = requestAnimationFrame(updateProgress);
        return () => cancelAnimationFrame(frameId);
    }, [isPlaying, playbackPath]);

    return (
        <div className="relative h-full w-full">
        <MapContainer center={center} zoom={13} className="h-full w-full">
            <TileLayer
                attribution={layer === "satellite"
                    ? "Tiles &copy; Esri"
                    : '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}
                url={tileUrl}
            />
            <FitMapBounds points={bounds} visible={visible}/>
            {beat?.fencePoints?.length > 2 && (
                <Polygon
                    positions={beat.fencePoints}
                    pathOptions={{color: "#e11d48", weight: 3, fillOpacity: 0.04, dashArray: "7 5"}}
                />
            )}
            {recordedRoute?.route_path?.length > 1 && (
                <>
                    <Polyline
                        positions={recordedRoute.route_path.map((point) => [point.lat, point.lon])}
                        pathOptions={{color: "#fff", weight: 8, opacity: 0.9}}
                    />
                    <Polyline
                        positions={recordedRoute.route_path.map((point) => [point.lat, point.lon])}
                        pathOptions={{color: "#0f766e", weight: 4, opacity: 0.9, dashArray: "8 5"}}
                    >
                        <Popup>
                            Recorded vehicle trip, road-matched through {recordedRoute.point_count} timestamped GPS points.
                            <br/>
                            {recordedRoute.provider} road geometry
                        </Popup>
                    </Polyline>
                </>
            )}
            {!recordedRoute?.route_path?.length && trackPoints.length > 1 && (
                <Polyline
                    positions={trackPoints.map((point) => [point.lat, point.lon])}
                    pathOptions={{color: "#0f766e", weight: 4, opacity: 0.9, dashArray: "5 5"}}
                >
                    <Popup>
                        Recorded GPS points joined in timestamp order. This is a direct GPS line, not road-matched geometry.
                    </Popup>
                </Polyline>
            )}
            {historicalOutsideBeat.sections.map((section, index) => (
                <Polyline
                    key={`historical-outside-${index}`}
                    positions={section.map((point) => [point.lat, point.lon])}
                    pathOptions={{color: "#dc2626", weight: 7, opacity: 0.9}}
                >
                    <Popup>Historical road section outside the beat boundary (sampled estimate).</Popup>
                </Polyline>
            ))}
            {optimizedOutsideBeat.sections.map((section, index) => (
                <Polyline
                    key={`optimized-outside-${index}`}
                    positions={section.map((point) => [point.lat, point.lon])}
                    pathOptions={{color: "#7c3aed", weight: 8, opacity: 0.95}}
                >
                    <Popup>Optimized road section outside the beat boundary (sampled estimate).</Popup>
                </Polyline>
            ))}
            {selectedRoute?.route_path?.length > 1 && (
                <Polyline
                    positions={selectedRoute.route_path.map((point) => [point.lat, point.lon])}
                    pathOptions={{
                        color: routeColors[Math.max(0, routes.indexOf(selectedRoute)) % routeColors.length],
                        weight: 5,
                        opacity: 0.9,
                    }}
                />
            )}
            {vehiclePosition && playbackPath.length > 1 && (
                <Marker position={vehiclePosition} icon={playbackVehicleIcon} zIndexOffset={1000}>
                    <Popup>{playbackType === "historical" ? "Preview position along the selected day's historical route" : "Preview position along the optimized route"}</Popup>
                </Marker>
            )}
            {stops.filter((stop) =>
                stop.type === "house" && Number.isFinite(stop.road_lat) && Number.isFinite(stop.road_lon)
            ).map((stop) => (
                <Polyline
                    key={`house-access-${stop.sequence}`}
                    positions={[[stop.road_lat, stop.road_lon], [stop.lat, stop.lon]]}
                    pathOptions={{color: "#f97316", weight: 2, opacity: 0.75, dashArray: "3 4"}}
                />
            ))}
            {collectionLocations.map((location, index) => (
                <CircleMarker
                    key={`collection-${location.lat}-${location.lon}-${index}`}
                    center={[location.lat, location.lon]}
                    radius={location.isMasterPlate ? 9 : 7}
                    pathOptions={{color: "#047857", fillColor: "#34d399", fillOpacity: 0.95, weight: 3}}
                >
                    <Popup>
                        <strong>{location.isMasterPlate ? "Master-plate scan location" : "House collection scan"}</strong><br/>
                        {location.lat.toFixed(6)}, {location.lon.toFixed(6)}<br/>
                        {location.plateIds.length > 0
                            ? `${location.plateIds.length} distinct plate ID${location.plateIds.length === 1 ? "" : "s"} scanned here`
                            : "Plate ID unavailable"}<br/>
                        {location.plateIds.slice(0, 20).join(", ")}
                        {location.plateIds.length > 20 ? ", …" : ""}
                    </Popup>
                </CircleMarker>
            ))}
            {visibleHouses.map((house) => (
                (() => {
                    const historicalDistance = gpsTrackDistances.get(house.route_key);
                    const nearHistoricalRoute = Number.isFinite(historicalDistance) && historicalDistance <= nearRouteThreshold;
                    const includedInPlan = plannedHouseKeys.has(house.route_key);
                    const collectedToday = house.house_id != null && coveredHouseIds.has(house.house_id);
                    const markerColor = includedInPlan ? "#2563eb"
                        : collectedToday ? "#15803d"
                            : nearHistoricalRoute ? "#c2410c"
                                : collectionMappingAvailable ? "#b91c1c" : "#64748b";
                    const markerFill = includedInPlan ? "#60a5fa"
                        : collectedToday ? "#4ade80"
                            : nearHistoricalRoute ? "#fb923c"
                                : collectionMappingAvailable ? "#f87171" : "#cbd5e1";
                    return (
                        <CircleMarker
                            key={house.route_key}
                            center={[house.lat, house.lon]}
                            radius={5}
                            pathOptions={{color: markerColor, fillColor: markerFill, fillOpacity: 0.9, weight: 2}}
                        >
                            <Popup>
                                {house.house_id
                                    ? <>House ID: {house.house_id}<br/></>
                                    : <>House ID unavailable; coordinate-only candidate<br/></>}
                                {house.lat.toFixed(6)}, {house.lon.toFixed(6)}<br/>
                                {collectionMappingAvailable
                                    ? collectedToday ? "Collection recorded on the selected day" : "No collection record for the selected day"
                                    : "Collection status unavailable: house IDs are missing"}<br/>
                                {includedInPlan ? "Included in the recommended route (planned, not confirmed collected)" : "Not included in the recommended route"}<br/>
                                {house.master_plate_id && <>Master plate: {house.master_plate_id}<br/></>}
                                {nearHistoricalRoute
                                    ? `Route candidate: within ${nearRouteThreshold} m of the selected day's GPS track (${Math.round(historicalDistance)} m away)`
                                    : `Outside the ${nearRouteThreshold} m selected-route candidate corridor`}
                                <br/>GPS or route proximity does not confirm collection.
                            </Popup>
                        </CircleMarker>
                    );
                })()
            ))}
            {(beat?.dumpyards || []).map((dumpyard, index) => (
                <Marker key={`dumpyard-${index}`} position={[dumpyard.lat, dumpyard.lon]} icon={dumpyardIcon}>
                    <Popup>{dumpyard.name}<br/>{dumpyard.lat.toFixed(6)}, {dumpyard.lon.toFixed(6)}<br/>Reference location, not a route stop.</Popup>
                </Marker>
            ))}
            {stops.filter((stop) => stop.type !== "house").map((stop) => (
                <Marker
                    key={stop.type}
                    position={[stop.lat, stop.lon]}
                    icon={stop.type === "start" ? startIcon : endIcon}
                >
                    <Popup>{stop.type === "start" ? "Vehicle route start" : "Vehicle route end"}<br/>
                        {stop.lat.toFixed(6)}, {stop.lon.toFixed(6)}
                    </Popup>
                </Marker>
            ))}
        </MapContainer>
        <div className="absolute bottom-4 left-4 right-4 z-[1000] flex flex-wrap items-center gap-2 rounded-lg bg-white/95 p-3 shadow sm:right-auto sm:min-w-[420px]">
            <button type="button" onClick={() => {
                if (playbackType !== "historical") {
                    setPlaybackType("historical");
                    progressRef.current = 0;
                    setProgress(0);
                } else if (progress >= 1) {
                    progressRef.current = 0;
                    setProgress(0);
                }
                setIsPlaying((playing) => playbackType === "historical" && playing ? false : true);
            }} disabled={historicalPath.length < 2}
            className="shrink-0 rounded bg-teal-700 px-3 py-2 text-sm font-semibold text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-50">
                {isPlaying && playbackType === "historical" ? "Pause actual route" : progress >= 1 && playbackType === "historical" ? "Replay actual route" : "Play actual route"}
            </button>
            <button type="button" onClick={() => {
                if (playbackType !== "optimized") {
                    setPlaybackType("optimized");
                    progressRef.current = 0;
                    setProgress(0);
                } else if (progress >= 1) {
                    progressRef.current = 0;
                    setProgress(0);
                }
                setIsPlaying((playing) => playbackType === "optimized" && playing ? false : true);
            }} disabled={!selectedRoute?.route_path || selectedRoute.route_path.length < 2}
            className="shrink-0 rounded bg-blue-700 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50">
                {isPlaying && playbackType === "optimized" ? "Pause optimized route" : progress >= 1 && playbackType === "optimized" ? "Replay optimized route" : "Play optimized route"}
            </button>
            <input
                type="range"
                min="0"
                max="1"
                step="0.001"
                value={progress}
                aria-label={`${playbackType === "historical" ? "Actual" : "Optimized"} vehicle route position`}
                onChange={(event) => {
                    const nextProgress = Number(event.target.value);
                    progressRef.current = nextProgress;
                    setProgress(nextProgress);
                    if (nextProgress >= 1) setIsPlaying(false);
                }}
                className="min-w-0 flex-1 accent-blue-700"
            />
            <span className="shrink-0 text-xs tabular-nums text-slate-600">{Math.round(progress * 100)}%</span>
        </div>
        </div>
    );
}

export default function BeatHouseRoutePlanner({visible = true}) {
    const [days, setDays] = useState([]);
    const [selectedDate, setSelectedDate] = useState("");
    const [beat, setBeat] = useState(null);
    const [layer, setLayer] = useState("streets");
    const [routes, setRoutes] = useState([]);
    const [recordedRoute, setRecordedRoute] = useState(null);
    const [selectedRouteId, setSelectedRouteId] = useState("");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const [notice, setNotice] = useState("");
    const [maxDistanceKm, setMaxDistanceKm] = useState("30");
    const [nearRouteThreshold, setNearRouteThreshold] = useState("50");
    const [showCollectedOnly, setShowCollectedOnly] = useState(false);
    const day = days.find((item) => item.date === selectedDate) || null;
    const selectedRoute = routes.find((route) => route.route_id === selectedRouteId) || null;
    const collectionMappingAvailable = Boolean(beat?.hasHouseIds && day);
    const coveredHouseIds = useMemo(() => getCollectedHouseIds(beat, day), [beat, day]);
    const collectionLocations = useMemo(() => getCollectionLocations(day), [day]);
    const historicalOutsideBeat = useMemo(
        () => getOutsideBeatSections(recordedRoute?.route_path, beat?.fencePoints),
        [recordedRoute, beat],
    );
    const optimizedOutsideBeat = useMemo(
        () => getOutsideBeatSections(selectedRoute?.route_path, beat?.fencePoints),
        [selectedRoute, beat],
    );
    const closestHouseToRoute = useMemo(() => {
        if (!beat?.houses.length || !day?.trackPoints.length) return null;
        const referencePath = recordedRoute?.route_path?.length
            ? recordedRoute.route_path
            : day.trackPoints.map(({lat, lon}) => ({lat, lon}));
        return beat.houses
            .map((house) => ({house, distanceMeters: distanceFromRouteMeters(house, referencePath)}))
            .filter((item) => Number.isFinite(item.distanceMeters))
            .sort((a, b) => a.distanceMeters - b.distanceMeters)[0] || null;
    }, [beat, day, recordedRoute]);
    const routeCorridorMeters = Math.max(0, Number(nearRouteThreshold) || 0);
    const routeCandidateHouses = useMemo(() => {
        if (!beat?.houses.length) return [];
        return beat.houses.filter((house) => isInsidePolygon(house, beat.fencePoints));
    }, [beat]);
    const housesOnSelectedDayRoute = useMemo(() => {
        if (!day?.trackPoints.length) return [];
        const gpsPath = day.trackPoints.map(({lat, lon}) => ({lat, lon}));
        return routeCandidateHouses.filter((house) =>
            distanceFromRouteMeters(house, gpsPath) <= routeCorridorMeters
        );
    }, [day, routeCandidateHouses, routeCorridorMeters]);
    const collectedCandidateCount = collectionMappingAvailable
        ? routeCandidateHouses.filter((house) => coveredHouseIds.has(house.house_id)).length
        : null;

    const clearResults = () => {
        setRoutes([]);
        setRecordedRoute(null);
        setSelectedRouteId("");
    };

    const handleDataFile = async (event) => {
        const file = event.target.files?.[0];
        if (!file) return;
        setError("");
        setNotice("");
        clearResults();
        try {
            const {beat: parsedBeat, days: parsedDays} = parseCombinedFile(
                file.name,
                JSON.parse(await file.text()),
            );
            setBeat(parsedBeat);
            setDays(parsedDays);
            setShowCollectedOnly(false);
            const latestDayWithGps = [...parsedDays].reverse().find((item) => item.trackPoints.length > 0);
            setSelectedDate(latestDayWithGps?.date || parsedDays[parsedDays.length - 1]?.date || "");
            setNotice(
                `Loaded ${parsedBeat.houses.length} houses, ${parsedDays.length} route days, and ` +
                `${parsedBeat.dumpyards.length} dumpyard location${parsedBeat.dumpyards.length === 1 ? "" : "s"} from ${file.name}.` +
                (parsedBeat.hasHouseIds
                    ? ""
                    : " Collection records with coordinates will be shown on the map. Add house IDs only if you want to match scans to the beat's house markers; master-plate links are only needed for a shared master scan.")
            );
        } catch (fileError) {
            setBeat(null);
            setDays([]);
            setSelectedDate("");
            setError(fileError.message || "Could not read the route data file.");
        } finally {
            event.target.value = "";
        }
    };

    const handleOptimize = async () => {
        if (!day?.trackPoints.length || !beat) return;
        if (housesOnSelectedDayRoute.length === 0) {
            setError(`No houses inside the beat are within ${routeCorridorMeters} m of the selected day's GPS route. Increase the route corridor to include nearby houses.`);
            return;
        }
        const distanceLimit = Number(maxDistanceKm);
        if (!Number.isFinite(distanceLimit) || distanceLimit <= 0 || distanceLimit > 1000) {
            setError("Enter a maximum route distance between 0 and 1,000 km.");
            return;
        }
        setLoading(true);
        setError("");
        setNotice("");
        clearResults();
        try {
            const trackResponse = await fetch(`${API_URL}/optimize_employee_route`, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    track_points: day.trackPoints.map(({lat, lon, datetime}) => ({lat, lon, datetime})),
                }),
            });
            const trackData = await trackResponse.json();
            if (!trackResponse.ok) {
                throw new Error(trackData.message || `Could not road-match the recorded vehicle track (HTTP ${trackResponse.status}).`);
            }
            const recordedRouteOption = trackData.alternatives?.find((route) =>
                Array.isArray(route.route_path) && route.route_path.length > 1
            );
            if (!recordedRouteOption) {
                throw new Error("The routing service did not return road geometry for the recorded vehicle track.");
            }
            const actualDistanceKm = Number(recordedRouteOption.distance_km);
            if (!Number.isFinite(actualDistanceKm) || actualDistanceKm <= 0) {
                throw new Error("The road-matched actual route has no valid distance, so a safe route comparison cannot be made.");
            }
            const effectiveDistanceLimitKm = Math.min(distanceLimit, actualDistanceKm - 0.01);
            if (effectiveDistanceLimitKm <= 0) {
                throw new Error(
                    `The selected day's road-matched actual route is only ${actualDistanceKm.toFixed(2)} km; ` +
                    "there is no positive route limit that can guarantee a strictly shorter recommendation."
                );
            }
            const response = await fetch(`${API_URL}/optimize_beat_routes`, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    track_points: day.trackPoints.map(({lat, lon, datetime}) => ({lat, lon, datetime})),
                    houses: housesOnSelectedDayRoute.map((house) => ({
                        ...house,
                        house_id: house.route_key,
                    })),
                    geofence: beat.geofence,
                    max_routes: 4,
                    max_distance_km: effectiveDistanceLimitKm,
                }),
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.message || `Route request failed (HTTP ${response.status}).`);
            }
            const routesShorterThanActual = Array.isArray(data.routes)
                ? data.routes.filter((route) => Number(route.distance_km) < actualDistanceKm)
                : [];
            if (routesShorterThanActual.length === 0) {
                throw new Error(
                    `No optimized route is strictly shorter than the selected day's road-matched route (${actualDistanceKm.toFixed(2)} km). ` +
                    "Try reducing the candidate corridor; the planner will not show a route that is equal in length or longer."
                );
            }
            setRecordedRoute({
                ...recordedRouteOption,
                point_count: trackData.point_count,
            });
            setRoutes(routesShorterThanActual);
            setSelectedRouteId(routesShorterThanActual[0].route_id);
            const endpointNote = data.start_inside_beat && data.end_inside_beat
                ? ""
                : " The recorded vehicle start/end is outside the beat, so its connecting road route leaves the fence.";
            const routeCoverageSummary = `Using only the ${day.date} GPS route, the recommended route can visit ` +
                `${routesShorterThanActual[0].houses_covered} of ${data.house_count} houses within ${routeCorridorMeters} m of that track. ` +
                `Its road distance is strictly shorter than the actual route (${actualDistanceKm.toFixed(2)} km).`;
            setNotice(`${routeCoverageSummary} Planned visits are not proof of collection. Routes are ranked by coverage, road distance, estimated time, then repeated road distance, within the ${effectiveDistanceLimitKm.toFixed(2)} km limit.${endpointNote}`);
        } catch (requestError) {
            setError(`Could not plan beat house routes: ${requestError.message || requestError}`);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-slate-50 p-4">
            <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-4">
                <section className="rounded-xl bg-white p-5 shadow-sm">
                    <h1 className="text-2xl font-bold text-slate-900">Beat House Route Planner</h1>
                    <p className="mt-1 text-sm text-slate-600">
                    Upload one JSON or TXT file containing JSON with the beat geofence, house coordinates and IDs, dumpyards, and dated vehicle routes.
                    The selected day&apos;s route is playable; orange houses near that GPS track are the only houses considered for route optimization.
                    The planner uses OpenStreetMap driving roads, including mapped residential streets and lanes.
                    Public OSRM routing is used by default, so house and GPS coordinates are sent to its routing service.
                    </p>
                    {beat?.dataQuality && (
                        <div className="mt-3 rounded border border-amber-300 bg-amber-50 p-3 text-xs text-amber-950">
                            Data readiness: {beat.dataQuality.housesWithIds} of {beat.houses.length} house coordinates have explicit house IDs;
                            {" "}{beat.dataQuality.referencesAtMultipleCoordinates} collection reference IDs appear at multiple recorded coordinates,
                            so they are not automatically linked to house coordinates.
                            No IDs are assigned by house-list order. Dump records: {beat.dataQuality.dumpRecords};
                            vehicle ID: {beat.dataQuality.hasVehicleId ? "provided" : "missing"};
                            {" "}beat ID: {beat.dataQuality.hasBeatId ? "provided" : "missing"}.
                            {!beat.dataQuality.dumpRecords && " No recorded dump weights are available from this upload."}
                        </div>
                    )}
                    <div className="mt-4 flex flex-wrap items-end gap-4">
                        <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
                            Beat, houses, and route data (.json or .txt)
                            <input type="file" accept=".json,.txt,application/json,text/plain" onChange={handleDataFile}
                                className="max-w-xs rounded border border-slate-300 p-2 text-sm"/>
                        </label>
                        {days.length > 0 && (
                            <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
                                Vehicle route date
                                <select value={selectedDate} onChange={(event) => {
                                    setSelectedDate(event.target.value);
                                    setShowCollectedOnly(false);
                                    clearResults();
                                    setError("");
                                    setNotice("");
                                }} className="rounded border border-slate-300 bg-white p-2">
                                    {days.map((item, index) => (
                                        <option key={`${item.date}-${index}`} value={item.date}>
                                            {item.date}{item.trackPoints.length === 0 ? " (no GPS points)" : ""}
                                        </option>
                                    ))}
                                </select>
                            </label>
                        )}
                        <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
                            Maximum route distance (km)
                            <input type="number" min="1" max="1000" step="1" value={maxDistanceKm}
                                onChange={(event) => { setMaxDistanceKm(event.target.value); clearResults(); }}
                                className="w-40 rounded border border-slate-300 p-2"/>
                            <span className="max-w-52 text-xs font-normal text-slate-500">The selected day&apos;s actual distance is also a hard maximum.</span>
                        </label>
                        <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
                            Route candidate corridor from selected-day GPS (m)
                            <input type="number" min="0" max="1000" step="10" value={nearRouteThreshold}
                                onChange={(event) => { setNearRouteThreshold(event.target.value); clearResults(); }}
                                className="w-40 rounded border border-slate-300 p-2"/>
                            <span className="max-w-52 text-xs font-normal text-slate-500">Only houses this close to the selected day&apos;s GPS track are optimized.</span>
                            <span className="max-w-52 text-xs font-normal text-slate-500">Every other house in the beat is excluded; the optimizer may also skip nearby candidates.</span>
                        </label>
                        <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
                            Map style
                            <select value={layer} onChange={(event) => setLayer(event.target.value)}
                                className="rounded border border-slate-300 bg-white p-2">
                                <option value="streets">Streets</option>
                                <option value="satellite">Satellite</option>
                            </select>
                        </label>
                        <button type="button" onClick={handleOptimize}
                            disabled={loading || !day?.trackPoints.length || !beat}
                            className="rounded-lg bg-blue-700 px-4 py-2 font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50">
                            {loading ? "Optimizing road routes…" : "Find and compare routes"}
                        </button>
                    </div>
                    {loading && (
                        <p className="mt-3 text-sm text-slate-600">
                            Matching the selected day&apos;s historical GPS route to roads and optimizing only houses within {routeCorridorMeters} m of that day&apos;s GPS track. Large road-distance matrices and route alternatives can take several minutes on public routing services.
                        </p>
                    )}
                    {day && day.trackPoints.length === 0 && (
                        <p className="mt-3 text-sm text-amber-800">This day has no vehicle GPS points, so it cannot provide route endpoints.</p>
                    )}
                    {error && <p role="alert" className="mt-3 rounded bg-red-50 p-3 text-sm text-red-700">{error}</p>}
                    {notice && <p role="status" className="mt-3 rounded bg-blue-50 p-3 text-sm text-blue-800">{notice}</p>}
                </section>

                <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                    <div className="rounded-xl bg-white p-4 shadow-sm">
                        <div className="text-sm text-slate-500">Vehicle route day</div>
                        <div className="mt-1 text-lg font-semibold">{day?.date || "Upload a vehicle file"}</div>
                        {day?.trackPoints.length > 0 && <div className="mt-1 text-xs text-slate-500">{day.trackPoints.length} timestamped GPS points</div>}
                    </div>
                    <div className="rounded-xl bg-white p-4 shadow-sm">
                        <div className="text-sm text-slate-500">Beat houses</div>
                        <div className="mt-1 text-lg font-semibold">{beat ? beat.houses.length : "Upload a beat file"}</div>
                        {beat && <div className="mt-1 text-xs text-slate-500">{beat.dumpyards.length} dumpyard marker{beat.dumpyards.length === 1 ? "" : "s"}</div>}
                    </div>
                    <div className="rounded-xl bg-white p-4 shadow-sm">
                        <div className="text-sm text-slate-500">Houses near selected-day route</div>
                        <div className="mt-1 text-lg font-semibold">{beat ? housesOnSelectedDayRoute.length : "—"}</div>
                        <div className="mt-1 text-xs text-slate-500">
                            Within {routeCorridorMeters} m; {routeCandidateHouses.length} total in beat
                        </div>
                    </div>
                    <div className="rounded-xl bg-white p-4 shadow-sm">
                        <div className="text-sm text-slate-500">Collection status on selected day</div>
                        <div className="mt-1 text-lg font-semibold">
                            {collectedCandidateCount == null
                                ? `${collectionLocations.length} scan locations`
                                : `${collectedCandidateCount} collected / ${routeCandidateHouses.length - collectedCandidateCount} remaining`}
                        </div>
                        <div className="mt-1 text-xs text-slate-500">
                            {collectionMappingAvailable
                                ? "House-ID matched coverage"
                                : `${day?.collectionScans.length || 0} collection records; shown at scan coordinates`}
                        </div>
                    </div>
                    <div className="rounded-xl bg-white p-4 shadow-sm">
                        <div className="text-sm text-slate-500">Optimized road distance / time</div>
                        <div className="mt-1 text-lg font-semibold">{selectedRoute ? `${selectedRoute.distance_km} km` : "—"}</div>
                        {selectedRoute && (
                            <div className="mt-1 text-xs text-slate-500">
                                {formatDuration(selectedRoute.duration_minutes)} estimated driving time;
                                {" "}{selectedRoute.houses_covered} planned, {Math.max(0, housesOnSelectedDayRoute.length - selectedRoute.houses_covered)} route candidates not selected
                            </div>
                        )}
                    </div>
                </section>

                {selectedRoute && recordedRoute && (
                    <section className="rounded-xl bg-white p-4 shadow-sm">
                        <h2 className="font-semibold text-slate-900">Historical vs. optimized route</h2>
                        <p className="mt-1 text-xs text-slate-500">
                            Historical distance and time are the road-matched GPS trip. Negative changes indicate reductions; optimized estimates exclude collection-service time and live traffic.
                        </p>
                        <div className="mt-3 overflow-x-auto">
                            <table className="w-full min-w-[520px] text-left text-sm">
                                <thead className="border-b text-xs text-slate-500">
                                    <tr>
                                        <th className="py-2 pr-4">Route</th>
                                        <th className="py-2 pr-4">Houses planned</th>
                                        <th className="py-2 pr-4">Road distance</th>
                                        <th className="py-2 pr-4">Estimated driving time</th>
                                        <th className="py-2">Repeated road distance</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr className="border-b border-slate-100">
                                        <td className="py-2 pr-4">Historical ({recordedRoute.provider || "road matched"})</td>
                                        <td className="py-2 pr-4">—</td>
                                        <td className="py-2 pr-4">{Number(recordedRoute.distance_km).toFixed(2)} km</td>
                                        <td className="py-2 pr-4">{formatDuration(recordedRoute.duration_minutes)}</td>
                                        <td className="py-2">{Number(recordedRoute.backtrack_distance_km || 0).toFixed(2)} km</td>
                                    </tr>
                                    <tr className="font-medium text-slate-900">
                                        <td className="py-2 pr-4">Optimized route (planned stops)</td>
                                        <td className="py-2 pr-4">{selectedRoute.houses_covered} planned / {housesOnSelectedDayRoute.length} route candidates; {Math.max(0, housesOnSelectedDayRoute.length - selectedRoute.houses_covered)} not selected</td>
                                        <td className="py-2 pr-4">{Number(selectedRoute.distance_km).toFixed(2)} km</td>
                                        <td className="py-2 pr-4">{formatDuration(selectedRoute.duration_minutes)}</td>
                                        <td className="py-2">{Number(selectedRoute.backtrack_distance_km || 0).toFixed(2)} km</td>
                                    </tr>
                                    <tr className="border-t border-slate-100 text-xs text-slate-600">
                                        <td className="py-2 pr-4">Change from historical</td>
                                        <td className="py-2 pr-4">Planned houses shown above</td>
                                        <td className="py-2 pr-4">{(Number(selectedRoute.distance_km) - Number(recordedRoute.distance_km)).toFixed(2)} km</td>
                                        <td className="py-2 pr-4">{(Number(selectedRoute.duration_minutes) - Number(recordedRoute.duration_minutes)).toFixed(0)} min</td>
                                        <td className="py-2">—</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                        <div className="mt-3 rounded border border-amber-300 bg-amber-50 p-3 text-xs text-amber-950">
                            Beat-boundary check uses 25 m sampling of road geometry. Outside sections are highlighted in red (actual)
                            and purple (optimized). The optimized route has approximately {optimizedOutsideBeat.distanceKm.toFixed(2)} km
                            outside the beat; approved access connections were not supplied, so those sections need review.
                            {recordedRoute?.route_path?.length > 1 &&
                                ` The actual route has approximately ${historicalOutsideBeat.distanceKm.toFixed(2)} km outside the beat.`}
                            {" "}Vehicle capacity, operating-time limits, and dump-trip constraints are not enforced without validated inputs.
                        </div>
                    </section>
                )}

                {(beat || routes.length > 0) && (
                    <>
                    <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-white p-3 shadow-sm">
                        <div className="flex flex-wrap items-center gap-3 text-xs text-slate-700">
                            <>
                                {collectionMappingAvailable || collectionLocations.length > 0 ? (
                                    <>
                                        <span><span className="mr-1 inline-block h-3 w-3 rounded-full bg-green-500"/>{collectionMappingAvailable ? `Collected on ${day.date}` : `Collection scans on ${day?.date || "selected day"}`}</span>
                                        {collectionMappingAvailable && <span><span className="mr-1 inline-block h-3 w-3 rounded-full bg-red-500"/>Not recorded collected</span>}
                                        {routes.length > 0 && <span><span className="mr-1 inline-block h-3 w-3 rounded-full bg-blue-500"/>Planned route stop (not confirmed collected)</span>}
                                    </>
                                ) : <span>No collection records with coordinates or house-ID matches are available for this day.</span>}
                                <span><span className="mr-1 inline-block h-3 w-3 rounded-full bg-orange-500"/>Near selected-day GPS; optimization candidate</span>
                            </>
                        </div>
                        <button
                            type="button"
                            onClick={() => setShowCollectedOnly((showing) => !showing)}
                            disabled={collectionMappingAvailable
                                ? collectedCandidateCount === 0
                                : collectionLocations.length === 0}
                            className="rounded border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            {showCollectedOnly
                                ? "Show all houses"
                                : collectionMappingAvailable ? "Show collected houses today" : "Show collection scans today"}
                        </button>
                    </section>
                    <section className="grid min-h-[620px] flex-1 gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
                        <div className="min-h-[400px] overflow-hidden rounded-xl bg-white shadow-sm">
                            <BeatRouteMap
                                key={`${beat?.name || "empty"}-${layer}`}
                                beat={beat}
                                routes={routes}
                                selectedRouteId={selectedRouteId}
                                recordedRoute={recordedRoute}
                                trackPoints={day?.trackPoints || []}
                                layer={layer}
                                visible={visible}
                                nearRouteThreshold={Math.max(0, Number(nearRouteThreshold) || 0)}
                                coveredHouseIds={coveredHouseIds}
                                showCollectedOnly={showCollectedOnly}
                                collectionMappingAvailable={collectionMappingAvailable}
                                collectionLocations={collectionLocations}
                            />
                        </div>
                        <aside className="flex flex-col gap-3 rounded-xl bg-white p-4 text-sm text-slate-600 shadow-sm">
                            <div>
                                <h2 className="font-semibold text-slate-900">Optimized route</h2>
                                {closestHouseToRoute && (
                                    <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-slate-800">
                                        <div className="font-semibold">Closest house to the recorded route</div>
                                        <div className="mt-1">
                                            {closestHouseToRoute.house.house_id || "House ID unavailable"}
                                        </div>
                                        <div className="font-mono text-xs">
                                            {closestHouseToRoute.house.lat.toFixed(6)}, {closestHouseToRoute.house.lon.toFixed(6)}
                                        </div>
                                        <div className="mt-1 text-xs">
                                            About {Math.round(closestHouseToRoute.distanceMeters)} m from the {recordedRoute?.route_path?.length ? "road-matched route" : "GPS line"}.
                                            This indicates proximity only, not collection.
                                        </div>
                                    </div>
                                )}
                                <p className="mt-2">Only beat houses within {routeCorridorMeters} m of the selected day&apos;s raw GPS track are sent to the optimizer; houses farther away are excluded. The selected day&apos;s first and last GPS points anchor the proposed route. Route alternatives are ranked by maximum houses planned, minimum road distance, minimum estimated drive time, then repeated road distance. GPS proximity and a planned stop do not prove collection. Use “Play actual route” to replay that day&apos;s GPS track or “Play optimized route” to preview the proposal.</p>
                                {selectedRoute?.stops?.length > 1 && (
                                    <p className="mt-1 rounded bg-slate-50 p-2 text-xs text-slate-700">
                                        From {selectedRoute.stops[0].lat.toFixed(5)}, {selectedRoute.stops[0].lon.toFixed(5)}
                                        {" "}to {selectedRoute.stops[selectedRoute.stops.length - 1].lat.toFixed(5)}, {selectedRoute.stops[selectedRoute.stops.length - 1].lon.toFixed(5)}
                                    </p>
                                )}
                                <p className="mt-1">The teal dashed line is the historical trip. Green houses have a selected-day collection match, red houses do not, and blue houses are proposed route stops. Orange dashed links connect house locations to nearby roads; the red dashed outline is the beat boundary.</p>
                            </div>
                            {routes.map((route, index) => (
                                <label key={route.route_id}
                                    className={`flex cursor-pointer items-start gap-2 rounded border p-3 ${route.route_id === selectedRouteId ? "border-blue-600 bg-blue-50" : "border-slate-200"}`}>
                                    <input type="radio" name="beat-route" value={route.route_id}
                                        checked={route.route_id === selectedRouteId}
                                        onChange={() => setSelectedRouteId(route.route_id)}/>
                                    <span>
                                        <span className="block font-medium text-slate-900">{route.label || `Route ${index + 1}`}</span>
                                        <span className="text-xs text-slate-600">{route.houses_covered} houses · {route.distance_km} km · {route.duration_minutes} min</span>
                                    </span>
                                </label>
                            ))}
                            {selectedRoute && (
                                <p className="font-semibold text-slate-900">
                                    Selected: {selectedRoute.houses_covered} houses · {selectedRoute.distance_km} km · {selectedRoute.duration_minutes} min
                                </p>
                            )}
                            {selectedRoute && (
                                <div className="max-h-[520px] overflow-y-auto rounded border border-slate-200">
                                    <table className="w-full text-left text-xs">
                                        <thead className="sticky top-0 bg-slate-100 text-slate-700">
                                            <tr><th className="p-2">Stop</th><th className="p-2">Location</th></tr>
                                        </thead>
                                        <tbody>
                                            {selectedRoute.stops.map((stop) => (
                                                <tr key={`${selectedRoute.route_id}-${stop.sequence}`} className="border-t border-slate-100">
                                                    <td className="p-2">{stop.sequence}. {stop.type === "house"
                                                        ? routeCandidateHouses.find((house) => house.route_key === stop.house_id)?.house_id || "Unidentified house location"
                                                        : stop.type === "start" ? "Start" : "End"}</td>
                                                    <td className="p-2">{stop.lat.toFixed(5)}, {stop.lon.toFixed(5)}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            )}
                        </aside>
                    </section>
                    </>
                )}
            </div>
        </div>
    );
}
