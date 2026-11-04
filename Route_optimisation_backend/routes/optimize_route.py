from flask import Blueprint, request, jsonify
from route_optimizer import (
    optimize_beat_house_routes,
    optimize_employee_track_route,
    process_route_optimization,
)

optimize_route_bp = Blueprint('optimize_route', __name__)

@optimize_route_bp.route('/optimize_employee_route', methods=['POST'])
def optimize_employee_route():
    data = request.get_json(silent=True) or {}
    track_points = data.get('track_points')
    if not isinstance(track_points, list) or not track_points:
        return jsonify({
            "status": "error",
            "message": "Provide at least one timestamped GPS track point."
        }), 400

    try:
        result = optimize_employee_track_route(track_points)
        return jsonify(result)
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@optimize_route_bp.route('/optimize_beat_routes', methods=['POST'])
def optimize_beat_routes():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            "status": "error",
            "message": "Provide the route, beat geofence, and house data as a JSON object."
        }), 400
    track_points = data.get('track_points')
    houses = data.get('houses')
    geofence = data.get('geofence')
    if not isinstance(track_points, list) or not track_points:
        return jsonify({
            "status": "error",
            "message": "Provide at least one timestamped GPS track point."
        }), 400
    if not isinstance(houses, list) or not houses:
        return jsonify({
            "status": "error",
            "message": "Provide the selected beat's house coordinates."
        }), 400

    try:
        result = optimize_beat_house_routes(
            track_points,
            houses,
            geofence,
            data.get('max_routes', 4),
            data.get('max_distance_km'),
        )
        return jsonify(result)
    except ValueError as error:
        return jsonify({
            "status": "error",
            "message": str(error)
        }), 400
    except Exception as error:
        return jsonify({
            "status": "error",
            "message": str(error)
        }), 500


@optimize_route_bp.route('/optimize_route', methods=['POST'])
def optimize_route():
    data = request.get_json()

    # Required input fields
    geofence_str = data.get('geofence')
    houses_raw = data.get('houses')
    start_loc = data.get('start_location')   # e.g., {"lat": ..., "lon": ...}
    dump_loc = data.get('dump_location')     # e.g., {"lat": ..., "lon": ...}
    garage_loc = data.get('end_location')    # Now mandatory (garage)

    batch_sz = data.get('batch_size', len(houses_raw))

    # Basic validation
    if not (geofence_str and start_loc and dump_loc and garage_loc):
        return jsonify({
            "status": "error",
            "message": "Missing required fields: geofence, start_location, dump_location, end_location (garage)"
        }), 400

    if not houses_raw:
        # Skip batch generation but still do garage trip logic
        house_coords = []

    # Parse dump location into list of [lat, lon]
    dump_coords = [[dump_loc['lat'], dump_loc['lon']]]

    # Standardize house objects
    house_coords = []
    for idx, house in enumerate(houses_raw):
        house_data = {
            'lat': house.get('lat'),
            'lon': house.get('lon'),
            'house_id': house.get('house_id') or house.get('House_Id') or f"House-{idx + 1}"
        }
        house_coords.append(house_data)

    try:
        result = process_route_optimization(
            geofence_str=geofence_str,
            house_coords=house_coords,
            current_location=start_loc,
            dump_coords=dump_coords,
            batch_size=batch_sz,
            end_location=garage_loc  # Always passed now
        )
        return jsonify(result)

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
