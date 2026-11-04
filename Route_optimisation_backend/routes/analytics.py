from flask import Blueprint, jsonify, request

from analytics_store import (
    get_dashboard,
    get_geographic_map,
    import_operational_records,
)


analytics_bp = Blueprint("analytics", __name__, url_prefix="/analytics")


@analytics_bp.route("/dashboard", methods=["GET"])
def analytics_dashboard():
    filters = {
        "state": request.args.get("state"),
        "municipal_corporation": request.args.get("municipal_corporation"),
        "zone": request.args.get("zone"),
        "ward": request.args.get("ward"),
        "beat_id": request.args.get("beat_id"),
        "vehicle_id": request.args.get("vehicle_id"),
        "start_date": request.args.get("start_date"),
        "end_date": request.args.get("end_date"),
        "interval": request.args.get("interval", "daily"),
        "history_all_dates": request.args.get("history_all_dates"),
    }
    filters = {key: value for key, value in filters.items() if value}
    try:
        return jsonify(get_dashboard(filters))
    except ValueError as error:
        return jsonify({"status": "error", "message": str(error)}), 400
    except Exception as error:
        return jsonify({"status": "error", "message": str(error)}), 500


@analytics_bp.route("/map", methods=["GET"])
def analytics_map():
    filters = {
        "state": request.args.get("state"),
        "municipal_corporation": request.args.get("municipal_corporation"),
        "zone": request.args.get("zone"),
        "ward": request.args.get("ward"),
        "beat_id": request.args.get("beat_id"),
        "vehicle_id": request.args.get("vehicle_id"),
        "date": request.args.get("date"),
        "start_date": request.args.get("start_date"),
        "end_date": request.args.get("end_date"),
    }
    filters = {key: value for key, value in filters.items() if value}
    try:
        return jsonify(get_geographic_map(filters))
    except ValueError as error:
        return jsonify({"status": "error", "message": str(error)}), 400
    except Exception as error:
        return jsonify({"status": "error", "message": str(error)}), 500


@analytics_bp.route("/import", methods=["POST"])
def import_analytics_records():
    if request.content_length and request.content_length > 64 * 1024 * 1024:
        return jsonify({
            "status": "error",
            "message": "Analytics imports are limited to 64 MB per request.",
        }), 413
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "error",
            "message": "Upload a JSON object containing operational record arrays.",
        }), 400
    try:
        return jsonify(import_operational_records(payload))
    except ValueError as error:
        return jsonify({"status": "error", "message": str(error)}), 400
    except Exception as error:
        return jsonify({"status": "error", "message": str(error)}), 500
