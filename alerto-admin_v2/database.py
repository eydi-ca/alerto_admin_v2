import sqlite3
from datetime import datetime
from config import DATABASE_PATH


def get_connection():
    conn = sqlite3.connect(
        DATABASE_PATH,
        timeout=10,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=10000;")
    conn.execute("PRAGMA foreign_keys=ON;")

    return conn


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def ensure_column(cur, table_name, column_name, column_definition):
    cur.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cur.fetchall()]

    if column_name not in columns:
        cur.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
        )


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alert_id TEXT UNIQUE,
        packet_type TEXT,
        raw_packet TEXT,
        device_id TEXT,
        user_id TEXT,
        zone TEXT,
        subzone TEXT,
        emergency_type TEXT,
        emergency_label TEXT,
        message TEXT,
        received_at TEXT,
        rssi REAL,
        snr REAL,
        verification_status TEXT DEFAULT 'Unverified',
        alert_status TEXT DEFAULT 'New',
        ack_message TEXT,
        ack_sent INTEGER DEFAULT 0,
        ack_sent_at TEXT,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT UNIQUE,
        full_name TEXT,
        phone_number TEXT,
        address TEXT,
        status TEXT DEFAULT 'Active',
        created_at TEXT,
        updated_at TEXT
    )
    """)
    
        # Extra columns for Supabase-to-SQLite offline sync.
    # These ALTER checks make the update safe even if alerto.db already exists.
    ensure_column(cur, "users", "profile_id", "TEXT")
    ensure_column(cur, "users", "auth_user_id", "TEXT")
    ensure_column(cur, "users", "user_code", "TEXT")
    ensure_column(cur, "users", "role", "TEXT DEFAULT 'resident'")
    ensure_column(cur, "users", "approval_status", "TEXT DEFAULT 'pending'")
    ensure_column(cur, "users", "source", "TEXT DEFAULT 'local'")
    ensure_column(cur, "users", "last_synced_at", "TEXT")
    ensure_column(cur, "alerts", "updated_at", "TEXT")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS stations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        station_id TEXT UNIQUE,
        station_name TEXT,
        device_id TEXT,
        assigned_zone TEXT,
        assigned_subzone TEXT,
        lat REAL,
        lng REAL,
        status TEXT DEFAULT 'Standby',
        description TEXT,
        source TEXT DEFAULT 'local',
        last_synced_at TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sync_metadata (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT UNIQUE,
        user_id TEXT,
        status TEXT DEFAULT 'Pending',
        last_seen_at TEXT,
        approved_at TEXT,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS registration_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT UNIQUE,
        user_id TEXT,
        device_id TEXT,
        full_name TEXT,
        phone_number TEXT,
        address TEXT,
        status TEXT DEFAULT 'Pending',
        requested_at TEXT,
        reviewed_at TEXT,
        admin_notes TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS status_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alert_id TEXT,
        old_status TEXT,
        new_status TEXT,
        changed_at TEXT,
        notes TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS invalid_packets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_packet TEXT,
        reason TEXT,
        rssi REAL,
        snr REAL,
        received_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS alert_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alert_id TEXT,
        rescuer_code TEXT,
        assigned_by TEXT,
        assignment_status TEXT DEFAULT 'Assigned',
        assigned_at TEXT,
        updated_at TEXT,
        notes TEXT,
        UNIQUE(alert_id, rescuer_code)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS rescuer_status_updates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alert_id TEXT,
        station_id TEXT,
        rescuer_code TEXT,
        status TEXT,
        packet_timestamp TEXT,
        raw_packet TEXT,
        rssi REAL,
        snr REAL,
        accepted INTEGER DEFAULT 0,
        reason TEXT,
        received_at TEXT
    )
    """)

    ensure_column(cur, "alert_assignments", "updated_at", "TEXT")
    ensure_column(cur, "rescuer_status_updates", "created_at", "TEXT")

    conn.commit()
    conn.close()


def emergency_label_from_code(code):
    labels = {
        "F": "Fire",
        "M": "Medical",
        "D": "Disaster",
        "L": "Flood",
        "R": "Rescue",
        "C": "Crime",
        "O": "Other"
    }
    return labels.get(code, "Unknown")


def check_verification(device_id, user_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM devices
        WHERE device_id = ? AND user_id = ? AND status = 'Approved'
    """, (device_id, user_id))

    device = cur.fetchone()
    conn.close()

    if device:
        return "Verified"
    return "Unverified"


def insert_alert(alert_data):
    conn = get_connection()
    cur = conn.cursor()

    verification_status = check_verification(
        alert_data.get("device_id"),
        alert_data.get("user_id")
    )

    cur.execute("""
        INSERT OR IGNORE INTO alerts (
            alert_id, packet_type, raw_packet, device_id, user_id,
            zone, subzone, emergency_type, emergency_label, message,
            received_at, rssi, snr, verification_status, alert_status,
            ack_message, ack_sent, ack_sent_at, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        alert_data.get("alert_id"),
        alert_data.get("packet_type", "A"),
        alert_data.get("raw_packet"),
        alert_data.get("device_id"),
        alert_data.get("user_id"),
        alert_data.get("zone"),
        alert_data.get("subzone"),
        alert_data.get("emergency_type"),
        alert_data.get("emergency_label"),
        alert_data.get("message"),
        alert_data.get("received_at", now()),
        alert_data.get("rssi"),
        alert_data.get("snr"),
        verification_status,
        alert_data.get("alert_status", "New"),
        alert_data.get("ack_message"),
        alert_data.get("ack_sent", 0),
        alert_data.get("ack_sent_at"),
        now()
    ))

    conn.commit()
    conn.close()


def get_alerts(status=None):
    conn = get_connection()
    cur = conn.cursor()

    if status:
        cur.execute("""
            SELECT * FROM alerts
            WHERE alert_status = ?
            ORDER BY received_at DESC
        """, (status,))
    else:
        cur.execute("""
            SELECT * FROM alerts
            ORDER BY received_at DESC
        """)

    rows = cur.fetchall()
    conn.close()
    return rows


def get_recent_alerts(limit=5):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM alerts
        ORDER BY received_at DESC
        LIMIT ?
    """, (limit,))

    rows = cur.fetchall()
    conn.close()
    return rows


def get_alert_by_id(alert_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,))
    row = cur.fetchone()

    conn.close()
    return row


def update_alert_status(alert_id, new_status, notes=None):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT alert_status FROM alerts WHERE alert_id = ?", (alert_id,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return False

    old_status = row["alert_status"]

    cur.execute("""
        UPDATE alerts
        SET alert_status = ?
        WHERE alert_id = ?
    """, (new_status, alert_id))

    cur.execute("""
        INSERT INTO status_logs (
            alert_id, old_status, new_status, changed_at, notes
        )
        VALUES (?, ?, ?, ?, ?)
    """, (alert_id, old_status, new_status, now(), notes))

    conn.commit()
    conn.close()
    return True


def insert_invalid_packet(raw_packet, reason, rssi=None, snr=None):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO invalid_packets (
            raw_packet, reason, rssi, snr, received_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (raw_packet, reason, rssi, snr, now()))

    conn.commit()
    conn.close()


def insert_registration_request(request_data):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR IGNORE INTO registration_requests (
            request_id, user_id, device_id, full_name,
            phone_number, address, status, requested_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        request_data.get("request_id"),
        request_data.get("user_id"),
        request_data.get("device_id"),
        request_data.get("full_name"),
        request_data.get("phone_number"),
        request_data.get("address"),
        request_data.get("status", "Pending"),
        request_data.get("requested_at", now())
    ))

    conn.commit()
    conn.close()


def approve_device(request_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM registration_requests
        WHERE request_id = ?
    """, (request_id,))

    request = cur.fetchone()

    if not request:
        conn.close()
        return False

    reviewed_at = now()

    cur.execute("""
        UPDATE registration_requests
        SET status = 'Approved', reviewed_at = ?
        WHERE request_id = ?
    """, (reviewed_at, request_id))

    cur.execute("""
        INSERT OR IGNORE INTO users (
            user_id, full_name, phone_number, address,
            status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, 'Active', ?, ?)
    """, (
        request["user_id"],
        request["full_name"],
        request["phone_number"],
        request["address"],
        reviewed_at,
        reviewed_at
    ))

    cur.execute("""
        INSERT OR REPLACE INTO devices (
            device_id, user_id, status, last_seen_at,
            approved_at, created_at
        )
        VALUES (?, ?, 'Approved', ?, ?, ?)
    """, (
        request["device_id"],
        request["user_id"],
        reviewed_at,
        reviewed_at,
        reviewed_at
    ))

    conn.commit()
    conn.close()
    return True


def reject_device(request_id, notes=None):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE registration_requests
        SET status = 'Rejected', reviewed_at = ?, admin_notes = ?
        WHERE request_id = ?
    """, (now(), notes, request_id))

    conn.commit()
    conn.close()
    return True


def get_registration_requests():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM registration_requests
        ORDER BY requested_at DESC
    """)

    rows = cur.fetchall()
    conn.close()
    return rows


def get_users():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users ORDER BY created_at DESC")
    rows = cur.fetchall()

    conn.close()
    return rows


def get_devices():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM devices ORDER BY created_at DESC")
    rows = cur.fetchall()

    conn.close()
    return rows


def get_dashboard_metrics():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS count FROM alerts")
    total_alerts = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) AS count FROM alerts WHERE alert_status = 'New'")
    new_alerts = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) AS count FROM alerts WHERE alert_status = 'Acknowledged'")
    acknowledged_alerts = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) AS count FROM alerts WHERE alert_status = 'Resolved'")
    resolved_alerts = cur.fetchone()["count"]

    cur.execute("""
        SELECT zone, COUNT(*) AS count
        FROM alerts
        GROUP BY zone
        ORDER BY count DESC
        LIMIT 1
    """)
    zone_row = cur.fetchone()
    most_active_zone = zone_row["zone"] if zone_row else "None"

    cur.execute("""
        SELECT received_at
        FROM alerts
        ORDER BY received_at DESC
        LIMIT 1
    """)
    latest_row = cur.fetchone()
    latest_alert_time = latest_row["received_at"] if latest_row else "No alerts"

    conn.close()

    return {
        "total_alerts": total_alerts,
        "new_alerts": new_alerts,
        "acknowledged_alerts": acknowledged_alerts,
        "resolved_alerts": resolved_alerts,
        "most_active_zone": most_active_zone,
        "latest_alert_time": latest_alert_time
    }
    
def get_map_alerts(limit=50):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            alert_id,
            raw_packet,
            device_id,
            user_id,
            zone,
            subzone,
            emergency_type,
            emergency_label,
            message,
            received_at,
            rssi,
            snr,
            verification_status,
            alert_status,
            ack_message,
            ack_sent,
            ack_sent_at
        FROM alerts
        ORDER BY received_at DESC
        LIMIT ?
    """, (limit,))

    rows = cur.fetchall()
    conn.close()
    return rows

def upsert_synced_user(profile):
    """
    Saves a Supabase profile into local SQLite.
    This allows the Raspberry Pi dashboard to display users even when offline.

    It syncs residents, rescuers, pending users, approved users, and rejected users.
    """
    conn = get_connection()
    cur = conn.cursor()

    user_code = profile.get("user_code") or profile.get("user_id")
    profile_id = profile.get("id")
    auth_user_id = profile.get("auth_user_id")
    full_name = profile.get("full_name")
    phone_number = profile.get("phone_number")
    address = profile.get("address")
    role = profile.get("role") or "resident"
    approval_status = profile.get("approval_status") or "pending"
    created_at = profile.get("created_at") or now()
    updated_at = profile.get("updated_at") or now()
    synced_at = now()

    if not user_code:
        conn.close()
        return False

    cur.execute("""
        INSERT INTO users (
            user_id, user_code, profile_id, auth_user_id, full_name, phone_number,
            address, role, approval_status, status, source,
            last_synced_at, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            user_code = excluded.user_code,
            profile_id = excluded.profile_id,
            auth_user_id = excluded.auth_user_id,
            full_name = excluded.full_name,
            phone_number = excluded.phone_number,
            address = excluded.address,
            role = excluded.role,
            approval_status = excluded.approval_status,
            status = excluded.status,
            source = excluded.source,
            last_synced_at = excluded.last_synced_at,
            updated_at = excluded.updated_at
    """, (
        user_code,
        user_code,
        profile_id,
        auth_user_id,
        full_name,
        phone_number,
        address,
        role,
        approval_status,
        approval_status,
        "supabase_sync",
        synced_at,
        created_at,
        updated_at,
    ))

    conn.commit()
    conn.close()
    return True


def get_local_users():
    """
    Reads users from local SQLite, not Supabase.
    This is what the admin dashboard should use during offline operation.
    """
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            user_id,
            user_code,
            profile_id,
            auth_user_id,
            full_name,
            phone_number,
            address,
            role,
            approval_status,
            status,
            source,
            last_synced_at,
            created_at,
            updated_at
        FROM users
        ORDER BY created_at DESC
    """)

    rows = cur.fetchall()
    conn.close()
    return rows


def get_local_user_by_code(user_code):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM users
        WHERE user_id = ? OR user_code = ?
        LIMIT 1
    """, (user_code, user_code))

    row = cur.fetchone()
    conn.close()
    return row


def upsert_station(station):
    """
    Saves a fixed T-Beam station into local SQLite.
    """
    conn = get_connection()
    cur = conn.cursor()

    station_id = station.get("station_id") or station.get("device_id")
    if not station_id:
        conn.close()
        return False

    cur.execute("""
        INSERT INTO stations (
            station_id, station_name, device_id, assigned_zone,
            assigned_subzone, lat, lng, status, description,
            source, last_synced_at, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(station_id) DO UPDATE SET
            station_name = excluded.station_name,
            device_id = excluded.device_id,
            assigned_zone = excluded.assigned_zone,
            assigned_subzone = excluded.assigned_subzone,
            lat = excluded.lat,
            lng = excluded.lng,
            status = excluded.status,
            description = excluded.description,
            source = excluded.source,
            last_synced_at = excluded.last_synced_at,
            updated_at = excluded.updated_at
    """, (
        station_id,
        station.get("station_name") or station.get("device_name") or station_id,
        station.get("device_id") or station_id,
        station.get("assigned_zone"),
        station.get("assigned_subzone"),
        station.get("lat"),
        station.get("lng"),
        station.get("status") or "Standby",
        station.get("description"),
        station.get("source") or "local_config",
        now(),
        station.get("created_at") or now(),
        station.get("updated_at") or now(),
    ))

    conn.commit()
    conn.close()
    return True


def get_local_stations():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM stations
        ORDER BY station_id ASC
    """)

    rows = cur.fetchall()
    conn.close()
    return rows


def set_sync_metadata(key, value):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO sync_metadata (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
    """, (key, value, now()))

    conn.commit()
    conn.close()


def get_sync_metadata(key):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT value, updated_at
        FROM sync_metadata
        WHERE key = ?
        LIMIT 1
    """, (key,))

    row = cur.fetchone()
    conn.close()
    return row

def get_rescuers():
    """
    Reads synced rescuers from local SQLite.
    Works if role is synced as 'rescuer', or if rescuer user codes start with R.
    """
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT *
            FROM users
            WHERE LOWER(COALESCE(role, '')) = 'rescuer'
               OR user_id LIKE 'R%'
               OR user_code LIKE 'R%'
            ORDER BY full_name ASC
        """)
    except sqlite3.OperationalError:
        cur.execute("""
            SELECT *
            FROM users
            WHERE user_id LIKE 'R%'
            ORDER BY full_name ASC
        """)

    rows = cur.fetchall()
    conn.close()
    return rows


def get_alerts_with_assignments(status=None):
    conn = get_connection()
    cur = conn.cursor()

    base_query = """
        SELECT
            a.*,
            aa.rescuer_code AS assigned_rescuer_code,
            aa.assignment_status AS assignment_status,
            aa.assigned_at AS assigned_at,
            u.full_name AS assigned_rescuer_name
        FROM alerts a
        LEFT JOIN alert_assignments aa
            ON a.alert_id = aa.alert_id
        LEFT JOIN users u
            ON aa.rescuer_code = u.user_id
            OR aa.rescuer_code = u.user_code
    """

    if status:
        cur.execute(base_query + """
            WHERE a.alert_status = ?
            ORDER BY a.received_at DESC
        """, (status,))
    else:
        cur.execute(base_query + """
            ORDER BY a.received_at DESC
        """)

    rows = cur.fetchall()
    conn.close()
    return rows


def assign_alert_to_rescuer(alert_id, rescuer_code, assigned_by="ADMIN", notes=None):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,))
    alert = cur.fetchone()

    if not alert:
        conn.close()
        return False, "Alert not found."

    cur.execute("""
        SELECT *
        FROM users
        WHERE user_id = ? OR user_code = ?
        LIMIT 1
    """, (rescuer_code, rescuer_code))

    rescuer = cur.fetchone()

    if not rescuer:
        conn.close()
        return False, "Rescuer not found in local synced users."

    timestamp = now()

    cur.execute("""
        INSERT INTO alert_assignments (
            alert_id, rescuer_code, assigned_by,
            assignment_status, assigned_at, updated_at, notes
        )
        VALUES (?, ?, ?, 'Assigned', ?, ?, ?)
        ON CONFLICT(alert_id, rescuer_code) DO UPDATE SET
            assignment_status = 'Assigned',
            assigned_by = excluded.assigned_by,
            updated_at = excluded.updated_at,
            notes = excluded.notes
    """, (
        alert_id,
        rescuer_code,
        assigned_by,
        timestamp,
        timestamp,
        notes,
    ))

    cur.execute("""
        UPDATE alerts
        SET alert_status = 'Assigned'
        WHERE alert_id = ?
    """, (alert_id,))

    cur.execute("""
        INSERT INTO status_logs (
            alert_id, old_status, new_status, changed_at, notes
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        alert_id,
        alert["alert_status"],
        "Assigned",
        timestamp,
        f"Assigned to rescuer {rescuer_code}"
    ))

    conn.commit()
    conn.close()
    return True, "Alert assigned successfully."


def process_rescuer_status_update(
    alert_id,
    station_id,
    rescuer_code,
    status,
    packet_timestamp=None,
    raw_packet=None,
    rssi=None,
    snr=None
):
    """
    Called by receiver.py when it receives an S packet:
    S|alert_code|station_id|rescuer_code|status|timestamp
    """
    allowed_statuses = {
        "ACCEPTED": "Responding",
        "RESPONDING": "Responding",
        "ON_SCENE": "On Scene",
        "RESOLVED": "Resolved",
        "CANCELLED": "Cancelled",
    }

    normalized_status = (status or "").strip().upper()
    received_at = now()

    conn = get_connection()
    cur = conn.cursor()

    if normalized_status not in allowed_statuses:
        cur.execute("""
            INSERT INTO rescuer_status_updates (
                alert_id, station_id, rescuer_code, status,
                packet_timestamp, raw_packet, rssi, snr,
                accepted, reason, received_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
        """, (
            alert_id,
            station_id,
            rescuer_code,
            status,
            packet_timestamp,
            raw_packet,
            rssi,
            snr,
            "Invalid status value",
            received_at,
        ))

        conn.commit()
        conn.close()
        return False, "Invalid status value."

    cur.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,))
    alert = cur.fetchone()

    if not alert:
        cur.execute("""
            INSERT INTO rescuer_status_updates (
                alert_id, station_id, rescuer_code, status,
                packet_timestamp, raw_packet, rssi, snr,
                accepted, reason, received_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
        """, (
            alert_id,
            station_id,
            rescuer_code,
            normalized_status,
            packet_timestamp,
            raw_packet,
            rssi,
            snr,
            "Alert not found",
            received_at,
        ))

        conn.commit()
        conn.close()
        return False, "Alert not found."

    cur.execute("""
        SELECT *
        FROM alert_assignments
        WHERE alert_id = ?
          AND rescuer_code = ?
        LIMIT 1
    """, (alert_id, rescuer_code))

    assignment = cur.fetchone()

    if not assignment:
        cur.execute("""
            INSERT INTO rescuer_status_updates (
                alert_id, station_id, rescuer_code, status,
                packet_timestamp, raw_packet, rssi, snr,
                accepted, reason, received_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
        """, (
            alert_id,
            station_id,
            rescuer_code,
            normalized_status,
            packet_timestamp,
            raw_packet,
            rssi,
            snr,
            "Rescuer is not assigned to this alert",
            received_at,
        ))

        conn.commit()
        conn.close()
        return False, "Rescuer is not assigned to this alert."

    dashboard_status = allowed_statuses[normalized_status]

    timestamp = now()

    cur.execute("""
        UPDATE alert_assignments
        SET assignment_status = ?,
            updated_at = ?
        WHERE id = ?
    """, (
        status,
        timestamp,
        assignment_id,
    ))

    cur.execute("""
        UPDATE alerts
        SET alert_status = ?
        WHERE alert_id = ?
    """, (
        dashboard_status,
        alert_id,
    ))

    cur.execute("""
        INSERT INTO status_logs (
            alert_id, old_status, new_status, changed_at, notes
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        alert_id,
        alert["alert_status"],
        dashboard_status,
        received_at,
        f"Rescuer {rescuer_code} updated status via station {station_id}"
    ))

    cur.execute("""
        INSERT INTO rescuer_status_updates (
            alert_id, station_id, rescuer_code, status,
            packet_timestamp, raw_packet, rssi, snr,
            accepted, reason, received_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
    """, (
        alert_id,
        station_id,
        rescuer_code,
        normalized_status,
        packet_timestamp,
        raw_packet,
        rssi,
        snr,
        "Status update accepted",
        received_at,
    ))

    conn.commit()
    conn.close()

    return True, f"Status updated to {dashboard_status}."


def get_rescuer_assignments(rescuer_code):
    """
    For future rescuer app local API.
    The rescuer app can fetch assigned emergencies from the Raspberry Pi hub.
    """
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            aa.id AS assignment_id,
            aa.alert_id,
            aa.rescuer_code,
            aa.assignment_status,
            aa.assigned_at,
            aa.updated_at,
            a.device_id,
            a.user_id,
            a.zone,
            a.subzone,
            a.emergency_type,
            a.emergency_label,
            a.message,
            a.received_at,
            a.alert_status,
            u.full_name AS resident_name,
            u.phone_number AS resident_phone,
            u.address AS resident_address
        FROM alert_assignments aa
        JOIN alerts a
            ON aa.alert_id = a.alert_id
        LEFT JOIN users u
            ON a.user_id = u.user_id
            OR a.user_id = u.user_code
        WHERE aa.rescuer_code = ?
        ORDER BY aa.updated_at DESC
    """, (rescuer_code,))

    rows = cur.fetchall()
    conn.close()
    return rows

def update_assignment_status_from_api(assignment_id, rescuer_code, status):
    conn = get_connection()
    cur = conn.cursor()

    assignment = cur.execute("""
        SELECT 
            aa.id,
            aa.alert_id,
            aa.rescuer_code
        FROM alert_assignments aa
        WHERE aa.id = ?
    """, (assignment_id,)).fetchone()

    if not assignment:
        conn.close()
        return {
            "success": False,
            "message": "Assignment not found."
        }

    if str(assignment["rescuer_code"]).upper() != str(rescuer_code).upper():
        conn.close()
        return {
            "success": False,
            "message": "This assignment does not belong to this rescuer."
        }

    normalized_status = str(status).strip().upper()

    allowed_statuses = [
        "ASSIGNED",
        "ACKNOWLEDGED",
        "RESPONDING",
        "ON_SCENE",
        "RESOLVED",
        "CANCELLED"
    ]

    if normalized_status not in allowed_statuses:
        conn.close()
        return {
            "success": False,
            "message": "Invalid status."
        }

    alert_id = assignment["alert_id"]
    timestamp = now()

    status_map = {
        "ASSIGNED": "Assigned",
        "ACKNOWLEDGED": "Acknowledged",
        "RESPONDING": "Responding",
        "ON_SCENE": "On Scene",
        "RESOLVED": "Resolved",
        "CANCELLED": "Cancelled"
    }

    new_alert_status = status_map.get(normalized_status, normalized_status)

    cur.execute("""
        UPDATE alert_assignments
        SET assignment_status = ?,
            updated_at = ?
        WHERE id = ?
    """, (
        normalized_status,
        timestamp,
        assignment_id
    ))

    cur.execute("""
        UPDATE alerts
        SET alert_status = ?,
            updated_at = ?
        WHERE alert_id = ?
    """, (
        new_alert_status,
        timestamp,
        alert_id
    ))

    conn.commit()
    conn.close()

    return {
        "success": True,
        "message": f"Assignment updated to {normalized_status}.",
        "assignment_id": assignment_id,
        "rescuer_code": rescuer_code,
        "status": normalized_status
    }