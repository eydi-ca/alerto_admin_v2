from LoRaRF import SX127x
from datetime import datetime
import time

from database import insert_alert, insert_invalid_packet, process_rescuer_status_update
# ==============================
# ALERTO Raspberry Pi Hub
# SX1276 Receiver + Compact ACK Sender
#
# Expected incoming packet from T-Beam:
# A|260514045304|TB001|U001|4-5|6-2|R|BLET3
#
# ACK reply to T-Beam:
# K|260514045304|OK
# ==============================

LORA_FREQUENCY = 915000000
SPREADING_FACTOR = 7
BANDWIDTH = 125000
CODING_RATE = 5
PREAMBLE_LENGTH = 8
SYNC_WORD = 0x12

LoRa = SX127x()

print("===== ALERTO Raspberry Pi LoRa Receiver with Compact ACK =====")
print("Initializing SX1276...")

# SPI bus 0, CE0, 1 MHz.
LoRa.setSpi(0, 0, 1000000)

# RESET = GPIO22 / physical pin 15
LoRa.setPins(22)

if not LoRa.begin():
    raise Exception("SX1276 failed to start. Check wiring, SPI, power, and module.")

# Match the T-Beam settings.
LoRa.setFrequency(LORA_FREQUENCY)
LoRa.setLoRaModulation(SPREADING_FACTOR, BANDWIDTH, CODING_RATE, False)
LoRa.setLoRaPacket(LoRa.HEADER_EXPLICIT, PREAMBLE_LENGTH, 255, True, False)
LoRa.setSyncWord(SYNC_WORD)

print("SX1276 started successfully.")
print("Receiver ready.")
print("Settings:")
print(f"  Frequency: {LORA_FREQUENCY} Hz")
print(f"  SF: {SPREADING_FACTOR}")
print(f"  Bandwidth: {BANDWIDTH} Hz")
print(f"  Coding Rate: 4/{CODING_RATE}")
print(f"  Sync Word: 0x{SYNC_WORD:02X}")
print("Waiting for compact ALERTO packets...\n")


def read_packet_text():
    received_bytes = []

    while LoRa.available() > 0:
        received_bytes.append(LoRa.read())

    if len(received_bytes) == 0:
        return ""

    return bytes(received_bytes).decode("utf-8", errors="replace").strip("\x00").strip()


def parse_compact_alert_packet(message):
    """
    Expected format:
    A|alert_id|device_id|user_id|zone|subzone|type|message

    Example:
    A|260514045304|TB001|U001|4-5|6-2|R|BLET3
    """

    parts = message.strip().split("|")

    if len(parts) < 8:
        return None

    if parts[0] != "A":
        return None

    alert = {
        "packet_type": parts[0],
        "alert_id": parts[1],
        "device_id": parts[2],
        "user_id": parts[3],
        "zone": parts[4],
        "subzone": parts[5],
        "emergency_type": parts[6],
        "message": parts[7],
    }

    # Basic validation
    if alert["alert_id"] == "":
        return None

    if alert["device_id"] == "":
        return None

    if alert["user_id"] == "":
        return None

    if alert["zone"] == "":
        return None

    if alert["subzone"] == "":
        return None

    if alert["emergency_type"] == "":
        return None

    return alert

def parse_rescuer_status_packet(message):
    """
    Expected format:
    S|alert_id|station_id|rescuer_code|status|timestamp

    Example:
    S|260525041500A7|TB002|R001|RESOLVED|260525050500
    """

    parts = message.strip().split("|")

    if len(parts) < 6:
        return None

    if parts[0] != "S":
        return None

    status_update = {
        "packet_type": parts[0],
        "alert_id": parts[1],
        "station_id": parts[2],
        "rescuer_code": parts[3],
        "status": parts[4],
        "packet_timestamp": parts[5],
    }

    if status_update["alert_id"] == "":
        return None

    if status_update["station_id"] == "":
        return None

    if status_update["rescuer_code"] == "":
        return None

    if status_update["status"] == "":
        return None

    return status_update

def expand_emergency_type(code):
    emergency_types = {
        "F": "Fire",
        "M": "Medical",
        "D": "Disaster",
        "L": "Flood",
        "R": "Rescue",
        "C": "Crime",
        "O": "Other",
    }

    return emergency_types.get(code, "Unknown")


def build_ack(alert_id, success=True):
    if alert_id == "":
        alert_id = "UNKNOWN"

    if success:
        return f"K|{alert_id}|OK"

    return f"K|{alert_id}|FAIL"


def send_ack(ack_message):
    ack_bytes = [ord(ch) for ch in ack_message]

    print(f"Sending ACK: {ack_message}")

    LoRa.beginPacket()
    LoRa.write(ack_bytes, len(ack_bytes))
    LoRa.endPacket()
    LoRa.wait()

    print("ACK sent.\n")
    
def save_alert_to_database(alert, raw_packet, received_at, rssi=None, snr=None, ack_message=None, ack_sent=False):
    emergency_label = expand_emergency_type(alert["emergency_type"])

    alert_data = {
        "alert_id": alert["alert_id"],
        "packet_type": alert["packet_type"],
        "raw_packet": raw_packet,
        "device_id": alert["device_id"],
        "user_id": alert["user_id"],
        "zone": alert["zone"],
        "subzone": alert["subzone"],
        "emergency_type": alert["emergency_type"],
        "emergency_label": emergency_label,
        "message": alert["message"],
        "received_at": received_at,
        "rssi": rssi,
        "snr": snr,
        "verification_status": "Unverified",
        "alert_status": "New",
        "ack_message": ack_message,
        "ack_sent": 1 if ack_sent else 0,
        "ack_sent_at": received_at if ack_sent else None,
    }

    insert_alert(alert_data)

    print("Alert saved to SQLite database.")
    
def save_rescuer_status_to_database(status_update, raw_packet, received_at, rssi=None, snr=None):
    success, message = process_rescuer_status_update(
        alert_id=status_update["alert_id"],
        station_id=status_update["station_id"],
        rescuer_code=status_update["rescuer_code"],
        status=status_update["status"],
        packet_timestamp=status_update["packet_timestamp"],
        raw_packet=raw_packet,
        rssi=rssi,
        snr=snr
    )

    if success:
        print("Rescuer status update saved to SQLite.")
    else:
        print("Rescuer status update rejected.")
        print(f"Reason: {message}")

    return success, message
    
def save_invalid_packet_to_database(raw_packet, reason, received_at, rssi=None, snr=None):
    insert_invalid_packet(
        raw_packet=raw_packet,
        reason=reason,
        rssi=rssi,
        snr=snr
    )

    print("Invalid packet saved to SQLite database.")
    print(f"Reason: {reason}")


try:
    while True:
        # Wait for incoming T-Beam packet.
        LoRa.request()
        LoRa.wait()

        message = read_packet_text()

        if message == "":
            continue

        received_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        print("----------------------------------------")
        print(f"Received at hub: {received_at}")
        print(f"Received packet: {message}")

        rssi = None
        snr = None

        try:
            rssi = LoRa.packetRssi()
            print(f"RSSI: {rssi} dBm")
        except Exception:
            pass

        try:
            snr = LoRa.snr()
            print(f"SNR: {snr} dB")
        except Exception:
            pass

        alert = parse_compact_alert_packet(message)
        status_update = parse_rescuer_status_packet(message)

        if alert is None and status_update is None:
            print("Invalid ALERTO packet.")

            ack = build_ack("UNKNOWN", success=False)
            send_ack(ack)

            save_invalid_packet_to_database(
                raw_packet=message,
                reason="Invalid ALERTO packet format",
                received_at=received_at,
                rssi=rssi,
                snr=snr
            )

            time.sleep(0.2)
            continue

        if status_update is not None:
            print("Valid ALERTO rescuer status update packet.")
            print(f"Alert ID: {status_update['alert_id']}")
            print(f"Station ID: {status_update['station_id']}")
            print(f"Rescuer Code: {status_update['rescuer_code']}")
            print(f"Status: {status_update['status']}")
            print(f"Packet Timestamp: {status_update['packet_timestamp']}")

            success, result_message = save_rescuer_status_to_database(
                status_update=status_update,
                raw_packet=message,
                received_at=received_at,
                rssi=rssi,
                snr=snr
            )

            ack = build_ack(status_update["alert_id"], success=success)
            send_ack(ack)

            time.sleep(0.2)
            continue

        print("Valid compact ALERTO alert packet.")
        print(f"Alert ID: {alert['alert_id']}")
        print(f"Device ID: {alert['device_id']}")
        print(f"User ID: {alert['user_id']}")
        print(f"Zone: {alert['zone']}")
        print(f"Subzone: {alert['subzone']}")
        print(
            f"Emergency Type: {alert['emergency_type']} "
            f"({expand_emergency_type(alert['emergency_type'])})"
        )
        print(f"Message: {alert['message']}")

        # This is the full timestamp generated by the Raspberry Pi hub.
        # Later, this can be inserted into the local database as received_at.
        print(f"Hub timestamp for database: {received_at}")

        ack = build_ack(alert["alert_id"], success=True)
        send_ack(ack)

        save_alert_to_database(
            alert=alert,
            raw_packet=message,
            received_at=received_at,
            rssi=rssi,
            snr=snr,
            ack_message=ack,
            ack_sent=True
        )

        # Small pause before listening again.
        time.sleep(0.2)

except KeyboardInterrupt:
    print("\nReceiver stopped by user.")

finally:
    try:
        LoRa.end()
    except Exception:
        pass
