import sqlite3
from datetime import datetime
from config import DATABASE_PATH


def get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
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
    ensure_column(cur, "users", "auth_user_id", "TEXT")
    ensure_column(cur, "users", "user_code", "TEXT")
    ensure_column(cur, "users", "role", "TEXT DEFAULT 'resident'")
    ensure_column(cur, "users", "approval_status", "TEXT DEFAULT 'pending'")
    ensure_column(cur, "users", "source", "TEXT DEFAULT 'local'")
    ensure_column(cur, "users", "last_synced_at", "TEXT")

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
    Saves an approved Supabase profile into local SQLite.
    This allows the Raspberry Pi dashboard to display users even when offline.
    """
    conn = get_connection()
    cur = conn.cursor()

    user_code = profile.get("user_code") or profile.get("user_id")
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
            user_id, user_code, auth_user_id, full_name, phone_number,
            address, role, approval_status, status, source,
            last_synced_at, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            user_code = excluded.user_code,
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