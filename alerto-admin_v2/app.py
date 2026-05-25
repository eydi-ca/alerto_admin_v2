from flask import Flask, render_template, jsonify, request, redirect, url_for
from config import APP_HOST, APP_PORT, APP_DEBUG
from datetime import datetime, timezone, timedelta
import supabase_admin
from supabase_admin import (
    create_resident_account,
    create_rescuer_account,
    get_pending_residents,
    get_all_residents,
    update_resident_approval,
    reset_user_password,
    update_resident_profile,
    get_profile_by_user_code,
    get_profiles_for_offline_sync,
    get_devices_for_offline_sync,
    get_stations_for_offline_sync,
)

from flask_cors import CORS
import traceback
from database import (
    init_db,
    get_alerts,
    get_recent_alerts,
    get_alert_by_id,
    update_alert_status,
    get_dashboard_metrics,
    get_registration_requests,
    approve_device,
    reject_device,
    get_users,
    get_devices,
    get_map_alerts,
    get_alerts_with_assignments,
    get_rescuers,
    assign_alert_to_rescuer,
    get_rescuer_assignments,
    update_assignment_status_from_api,

    # Offline sync/local SQLite helpers
    upsert_synced_user,
    get_local_users,
    get_local_user_by_code,
    upsert_station,
    get_local_stations,
    set_sync_metadata,
    get_sync_metadata,
)

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

init_db()

MANILA_TZ = timezone(timedelta(hours=8))

def is_supabase_online():
    """
    Lightweight online check.
    If Supabase is unreachable, admin pages should still load from SQLite.
    """
    try:
        (
            supabase_admin.supabase
            .table("profiles")
            .select("id")
            .limit(1)
            .execute()
        )
        return True
    except Exception:
        return False


def _parse_supabase_datetime(value):
    """
    Converts Supabase ISO timestamp into Manila time.
    Supabase usually returns timestamps like:
    2026-05-24T14:30:22.123456+00:00
    """
    if not value:
        return None

    if isinstance(value, datetime):
        dt = value
    else:
        raw_value = str(value).strip()

        if raw_value.endswith("Z"):
            raw_value = raw_value[:-1] + "+00:00"

        try:
            dt = datetime.fromisoformat(raw_value)
        except ValueError:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(MANILA_TZ)


@app.template_filter("manila_datetime")
def manila_datetime(value):
    dt = _parse_supabase_datetime(value)

    if dt is None:
        return "Not available"

    return dt.strftime("%b %d, %Y • %I:%M %p")


@app.template_filter("request_age")
def request_age(value):
    dt = _parse_supabase_datetime(value)

    if dt is None:
        return "Unknown"

    now = datetime.now(MANILA_TZ)
    difference = now - dt

    total_minutes = int(difference.total_seconds() // 60)

    if total_minutes < 1:
        return "Just now"

    if total_minutes < 60:
        return f"{total_minutes} min ago"

    total_hours = total_minutes // 60

    if total_hours < 24:
        return f"{total_hours} hr ago"

    total_days = total_hours // 24

    if total_days == 1:
        return "1 day ago"

    return f"{total_days} days ago"

# ==============================
# ALERTO Fixed T-Beam Stations
# ==============================
# Update these coordinates later based on the actual deployed station locations.
# device_id from the packet is now interpreted as the fixed T-Beam station ID.

STATIONS = {
    "TB001": {
        "station_id": "TB001",
        "station_name": "Station 1",
        "assigned_zone": "Zone 1",
        "lat": 14.7388,
        "lng": 121.0507,
        "status": "Active",
        "description": "Primary test station near Barangay Kaligayahan monitoring center."
    },
    "TB002": {
        "station_id": "TB002",
        "station_name": "Station 2",
        "assigned_zone": "Zone 2",
        "lat": 14.7410,
        "lng": 121.0479,
        "status": "Standby",
        "description": "Planned fixed T-Beam station."
    },
    "TB003": {
        "station_id": "TB003",
        "station_name": "Station 3",
        "assigned_zone": "Zone 3",
        "lat": 14.7358,
        "lng": 121.0534,
        "status": "Standby",
        "description": "Planned fixed T-Beam station."
    }
}


@app.route("/")
def dashboard():
    metrics = get_dashboard_metrics()
    recent_alerts = get_recent_alerts(5)
    return render_template(
        "dashboard.html",
        metrics=metrics,
        recent_alerts=recent_alerts
    )


@app.route("/alerts")
def alerts_page():
    status = request.args.get("status")
    alerts = get_alerts_with_assignments(status)
    rescue_teams = get_rescuers()

    return render_template(
        "alerts.html",
        alerts=alerts,
        rescue_teams=rescue_teams,
        selected_status=status
    )


@app.route("/api/alerts")
def api_alerts():
    alerts = get_alerts()
    return jsonify([dict(row) for row in alerts])


@app.route("/api/alerts/recent")
def api_recent_alerts():
    alerts = get_recent_alerts(5)
    return jsonify([dict(row) for row in alerts])


@app.route("/api/alerts/<alert_id>")
def api_alert_detail(alert_id):
    alert = get_alert_by_id(alert_id)
    if not alert:
        return jsonify({"error": "Alert not found"}), 404
    return jsonify(dict(alert))


@app.route("/api/alerts/<alert_id>/status", methods=["POST"])
def api_update_alert_status(alert_id):
    data = request.get_json()
    new_status = data.get("status")
    notes = data.get("notes")

    allowed_statuses = [
    "New",
    "Acknowledged",
    "Assigned",
    "Responding",
    "On Scene",
    "Resolved",
    "Cancelled",
    "Invalid"
]

    if new_status not in allowed_statuses:
        return jsonify({"error": "Invalid status"}), 400

    updated = update_alert_status(alert_id, new_status, notes)

    if not updated:
        return jsonify({"error": "Alert not found"}), 404

    return jsonify({"message": "Status updated", "status": new_status})

@app.route("/api/alerts/<alert_id>/assign", methods=["POST"])
def api_assign_alert(alert_id):
    data = request.get_json() or {}

    rescuer_code = (
        data.get("rescuer_code")
        or data.get("team_id")
        or data.get("assigned_team_id")
        or ""
    ).strip().upper()

    if not rescuer_code:
        return jsonify({"error": "Rescuer code is required."}), 400

    success, message = assign_alert_to_rescuer(
        alert_id=alert_id,
        rescuer_code=rescuer_code,
        assigned_by="ADMIN",
    )

    if not success:
        return jsonify({"error": message}), 400

    return jsonify({
        "message": message,
        "alert_id": alert_id,
        "rescuer_code": rescuer_code,
        "status": "Assigned"
    })

@app.route("/api/rescuer/assignments/<int:assignment_id>/status", methods=["POST"])
def api_update_rescuer_assignment_status(assignment_id):
    data = request.get_json(silent=True) or {}

    rescuer_code = (data.get("rescuer_code") or "").strip().upper()
    status = (data.get("status") or "").strip().upper()

    allowed_statuses = {
        "ASSIGNED",
        "ACKNOWLEDGED",
        "ACCEPTED",
        "RESPONDING",
        "ON_SCENE",
        "RESOLVED",
        "CANCELLED",
    }

    if not rescuer_code:
        return jsonify({"error": "rescuer_code is required."}), 400

    if status not in allowed_statuses:
        return jsonify({
            "error": "Invalid status.",
            "allowed_statuses": sorted(list(allowed_statuses))
        }), 400

    try:
        result = update_assignment_status_from_api(
            assignment_id=assignment_id,
            rescuer_code=rescuer_code,
            status=status,
        )

        if not result.get("success"):
            return jsonify({"error": result.get("message", "Status update failed.")}), 400

        return jsonify({
            "message": result.get("message"),
            "assignment_id": result.get("assignment_id", assignment_id),
            "rescuer_code": result.get("rescuer_code", rescuer_code),
            "status": result.get("status", status),
        })

    except Exception as exc:
        print("RESCUER STATUS API ERROR:", exc)
        return jsonify({"error": str(exc)}), 500

@app.route("/acknowledgements")
def acknowledgements_page():
    alerts = get_alerts()
    return render_template("acknowledgements.html", alerts=alerts)


@app.route("/approvals")
def approvals():
    try:
        pending_residents = get_pending_residents()
    except Exception as e:
        print("APPROVALS PAGE ERROR:")
        traceback.print_exc()
        pending_residents = []

    return render_template(
        "approvals.html",
        pending_residents=pending_residents,
    )


@app.route("/api/approvals/<request_id>/approve", methods=["POST"])
def api_approve_request(request_id):
    approve_device(request_id)
    return redirect(url_for("approvals_page"))


@app.route("/api/approvals/<request_id>/reject", methods=["POST"])
def api_reject_request(request_id):
    reject_device(request_id)
    return redirect(url_for("approvals_page"))


@app.route("/users-devices")
def users_devices():
    """
    Users / Stations page now reads from local SQLite first.
    Supabase is only used when the admin manually clicks Sync Offline Data.
    """
    try:
        users = [dict(row) for row in get_local_users()]
    except Exception:
        print("LOCAL USERS PAGE ERROR:")
        traceback.print_exc()
        users = []

    try:
        stations = [dict(row) for row in get_local_stations()]
    except Exception:
        print("LOCAL STATIONS PAGE ERROR:")
        traceback.print_exc()
        stations = []

    # If local stations are still empty, seed them from the Flask STATIONS config.
    if not stations:
        for station in STATIONS.values():
            upsert_station(station)

        stations = [dict(row) for row in get_local_stations()]

    sync_row = get_sync_metadata("offline_data_last_sync")

    sync_status = {
        "supabase_online": is_supabase_online(),
        "last_sync": sync_row["value"] if sync_row else "Never synced",
    }

    user_stats = {
        "total": len(users),
        "approved": len([
            user for user in users
            if (user.get("approval_status") or "").lower() == "approved"
        ]),
        "pending": len([
            user for user in users
            if (user.get("approval_status") or "").lower() == "pending"
        ]),
        "restricted": len([
            user for user in users
            if (user.get("approval_status") or "").lower() in ["rejected", "suspended"]
        ]),
    }

    station_stats = {
        "total": len(stations),
        "active": len([
            station for station in stations
            if (station.get("status") or "").lower() == "active"
        ]),
        "standby": len([
            station for station in stations
            if (station.get("status") or "").lower() == "standby"
        ]),
    }

    return render_template(
        "users_devices.html",
        users=users,
        stations=stations,
        user_stats=user_stats,
        station_stats=station_stats,
        sync_status=sync_status,
    )
    
@app.route("/api/admin/sync-offline-data", methods=["POST"])
def api_sync_offline_data():
    """
    Pulls approved online preparation records from Supabase
    and stores them locally in SQLite for offline dashboard use.
    """
    try:
        synced_users = 0
        synced_stations = 0

        profiles = get_profiles_for_offline_sync()

        for profile in profiles:
            if upsert_synced_user(profile):
                synced_users += 1

        supabase_stations = get_stations_for_offline_sync()

        if supabase_stations:
            for station in supabase_stations:
                if upsert_station(station):
                    synced_stations += 1
        else:
            # Fallback to local configured fixed T-Beam stations.
            for station in STATIONS.values():
                if upsert_station(station):
                    synced_stations += 1

        timestamp = datetime.now(MANILA_TZ).strftime("%Y-%m-%d %H:%M:%S")
        set_sync_metadata("offline_data_last_sync", timestamp)

        return jsonify({
            "status": "ok",
            "message": "Offline data sync completed.",
            "synced_users": synced_users,
            "synced_stations": synced_stations,
            "last_sync": timestamp,
        }), 200

    except Exception as e:
        print("OFFLINE DATA SYNC ERROR:")
        traceback.print_exc()

        return jsonify({
            "status": "error",
            "error": "Offline data sync failed. Check internet/Supabase connection.",
            "details": str(e),
        }), 503


@app.route("/api/map/alerts")
def api_map_alerts():
    alerts = get_map_alerts(50)

    fallback_lat = 14.7388
    fallback_lng = 121.0507

    data = []

    for index, alert in enumerate(alerts):
        station = STATIONS.get(alert["device_id"])

        if station:
            lat = station["lat"]
            lng = station["lng"]
            station_name = station["station_name"]
            assigned_zone = station["assigned_zone"]
            station_status = station["status"]
        else:
            # Unknown station/device fallback.
            # This prevents the alert from disappearing from the map.
            lat = fallback_lat + ((index % 4) - 2) * 0.0005
            lng = fallback_lng + ((index // 4) - 2) * 0.0005
            station_name = "Unknown Station"
            assigned_zone = "Unassigned"
            station_status = "Unknown"

        data.append({
            "alert_id": alert["alert_id"],
            "device_id": alert["device_id"],
            "station_name": station_name,
            "assigned_zone": assigned_zone,
            "station_status": station_status,
            "user_id": alert["user_id"],
            "zone": alert["zone"],
            "subzone": alert["subzone"],
            "emergency_type": alert["emergency_type"],
            "emergency_label": alert["emergency_label"],
            "message": alert["message"],
            "received_at": alert["received_at"],
            "rssi": alert["rssi"],
            "snr": alert["snr"],
            "verification_status": alert["verification_status"],
            "alert_status": alert["alert_status"],
            "ack_sent": alert["ack_sent"],
            "ack_message": alert["ack_message"],
            "lat": lat,
            "lng": lng
        })

    return jsonify(data)

@app.route("/api/map/stations")
def api_map_stations():
    return jsonify(list(STATIONS.values()))

@app.route("/api/auth/register-resident", methods=["POST"])
def api_register_resident():
    data = request.get_json() or {}

    full_name = (data.get("full_name") or "").strip()
    phone_number = (data.get("phone_number") or "").strip()
    address = (data.get("address") or "").strip()
    password = (data.get("password") or "").strip()

    if not full_name or not address or not password:
        return jsonify({
            "error": "Full name, address, and password are required."
        }), 400

    if len(password) < 6:
        return jsonify({
            "error": "Password/PIN must be at least 6 characters."
        }), 400

    try:
        result = create_resident_account(
            full_name=full_name,
            phone_number=phone_number,
            address=address,
            password=password,
        )

        return jsonify({
            "message": "Resident registration submitted.",
            "user_code": result["user_code"],
            "approval_status": result["approval_status"],
        }), 201

    except Exception as e:
        print("REGISTER RESIDENT ERROR:")
        traceback.print_exc()

        return jsonify({
            "error": "Resident registration failed.",
            "details": str(e),
        }), 500


@app.route("/api/admin/create-rescuer", methods=["POST"])
def api_create_rescuer():
    data = request.get_json() or {}

    required_fields = [
        "full_name",
        "password",
        "organization",
        "rescuer_id",
    ]

    missing = [
        field for field in required_fields
        if not (data.get(field) or "").strip()
    ]

    if missing:
        return jsonify({
            "error": "Missing required fields.",
            "missing": missing,
        }), 400

    password = (data.get("password") or "").strip()

    if len(password) < 6:
        return jsonify({
            "error": "Password/PIN must be at least 6 characters."
        }), 400

    try:
        result = create_rescuer_account(
            full_name=(data.get("full_name") or "").strip(),
            phone_number=(data.get("phone_number") or "").strip(),
            address=(data.get("address") or "").strip(),
            password=password,
            organization=(data.get("organization") or "").strip(),
            rescuer_id=(data.get("rescuer_id") or "").strip(),

            # This is kept only because the current Supabase rescuer_profiles table
            # has assigned_zone/assigned_subzone columns.
            # Operational assignment location should come from the alert, not the rescuer account.
            assigned_zone="Barangay-wide",
            assigned_subzone="",
        )

        return jsonify({
            "message": "Rescuer account created.",
            "user_code": result["user_code"],
            "approval_status": result["approval_status"],
            "verification_status": result["verification_status"],
        }), 201

    except Exception as e:
        return jsonify({
            "error": "Rescuer account creation failed.",
            "details": str(e),
        }), 500
        
@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({
        "status": "ok",
        "message": "ALERTO Flask API is running."
    }), 200
    
@app.route("/api/debug/supabase-profiles", methods=["GET"])
def debug_supabase_profiles():
    from supabase_admin import supabase

    try:
        result = supabase.table("profiles").select("user_code").execute()

        return jsonify({
            "status": "ok",
            "data": result.data,
        }), 200

    except Exception as e:
        print("SUPABASE DEBUG ERROR:")
        traceback.print_exc()

        return jsonify({
            "status": "error",
            "details": str(e),
        }), 500
        
@app.route("/api/admin/pending-residents", methods=["GET"])
def api_pending_residents():
    try:
        residents = get_pending_residents()

        return jsonify({
            "status": "ok",
            "residents": residents,
        }), 200

    except Exception as e:
        print("FETCH PENDING RESIDENTS ERROR:")
        traceback.print_exc()

        return jsonify({
            "status": "error",
            "error": "Failed to fetch pending residents.",
            "details": str(e),
        }), 500

@app.route("/api/admin/residents", methods=["GET"])
def api_all_residents():
    try:
        residents = get_all_residents()

        return jsonify({
            "status": "ok",
            "residents": residents,
        }), 200

    except Exception as e:
        print("FETCH RESIDENTS ERROR:")
        traceback.print_exc()

        return jsonify({
            "status": "error",
            "error": "Failed to fetch residents.",
            "details": str(e),
        }), 500
        
@app.route("/api/admin/residents/<profile_id>/approval", methods=["POST"])
def api_update_resident_approval(profile_id):
    data = request.get_json() or {}
    approval_status = (data.get("approval_status") or "").strip()

    if approval_status not in ["approved", "rejected", "suspended", "pending"]:
        return jsonify({
            "status": "error",
            "error": "Invalid approval status.",
        }), 400

    try:
        updated_profile = update_resident_approval(
            profile_id=profile_id,
            approval_status=approval_status,
        )

        return jsonify({
            "status": "ok",
            "message": f"Resident status updated to {approval_status}.",
            "profile": updated_profile,
        }), 200

    except Exception as e:
        print("UPDATE RESIDENT APPROVAL ERROR:")
        traceback.print_exc()

        return jsonify({
            "status": "error",
            "error": "Failed to update resident approval.",
            "details": str(e),
        }), 500
        
@app.route("/api/auth/profile-status/<user_code>", methods=["GET"])
def api_profile_status(user_code):
    try:
        profile = get_profile_by_user_code(user_code.strip().upper())

        if profile is None:
            return jsonify({
                "status": "error",
                "error": "Profile not found.",
            }), 404

        return jsonify({
            "status": "ok",
            "profile": {
                "user_code": profile.get("user_code"),
                "full_name": profile.get("full_name"),
                "role": profile.get("role"),
                "approval_status": profile.get("approval_status"),
            }
        }), 200

    except Exception as e:
        print("PROFILE STATUS ERROR:")
        traceback.print_exc()

        return jsonify({
            "status": "error",
            "error": "Failed to fetch profile status.",
            "details": str(e),
        }), 500
        
@app.route("/api/admin/users/<profile_id>/reset-password", methods=["POST"])
def api_reset_user_password(profile_id):
    data = request.get_json() or {}
    new_password = (data.get("new_password") or "").strip()

    if len(new_password) < 6:
        return jsonify({
            "status": "error",
            "error": "Password/PIN must be at least 6 characters.",
        }), 400

    try:
        # Fetch profile first so we can get auth_user_id
        result = (
            supabase_admin.supabase
            .table("profiles")
            .select("id, auth_user_id, user_code, full_name")
            .eq("id", profile_id)
            .execute()
        )

        if not result.data:
            return jsonify({
                "status": "error",
                "error": "Profile not found.",
            }), 404

        profile = result.data[0]
        auth_user_id = profile["auth_user_id"]

        reset_user_password(
            auth_user_id=auth_user_id,
            new_password=new_password,
        )

        return jsonify({
            "status": "ok",
            "message": f"Password/PIN reset for {profile.get('user_code')}.",
            "user_code": profile.get("user_code"),
        }), 200

    except Exception as e:
        print("RESET PASSWORD ERROR:")
        traceback.print_exc()

        return jsonify({
            "status": "error",
            "error": "Failed to reset password/PIN.",
            "details": str(e),
        }), 500
        
@app.route("/api/admin/residents/<profile_id>/edit", methods=["POST"])
def api_edit_resident_profile(profile_id):
    data = request.get_json() or {}

    full_name = (data.get("full_name") or "").strip()
    phone_number = (data.get("phone_number") or "").strip()
    address = (data.get("address") or "").strip()

    if not full_name or not address:
        return jsonify({
            "status": "error",
            "error": "Full name and address are required.",
        }), 400

    try:
        updated_profile = update_resident_profile(
            profile_id=profile_id,
            full_name=full_name,
            phone_number=phone_number,
            address=address,
        )

        return jsonify({
            "status": "ok",
            "message": "Resident profile updated.",
            "profile": updated_profile,
        }), 200

    except Exception as e:
        print("EDIT RESIDENT PROFILE ERROR:")
        traceback.print_exc()

        return jsonify({
            "status": "error",
            "error": "Failed to update resident profile.",
            "details": str(e),
        }), 500

if __name__ == "__main__":
    init_db()
    app.run(host=APP_HOST, port=APP_PORT, debug=APP_DEBUG)