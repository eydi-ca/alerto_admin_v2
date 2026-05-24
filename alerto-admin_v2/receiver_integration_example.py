from database import insert_alert, insert_invalid_packet, emergency_label_from_code, now


def parse_alert_packet(raw_packet):
    """
    Expected format:
    A|alert_id|device_id|user_id|zone|subzone|type|message

    Example:
    A|260523173201|TB001|U001|10-5|2-5|F|FTEST1
    """

    parts = raw_packet.strip().split("|")

    if len(parts) != 8:
        return None, "Invalid field count"

    packet_type = parts[0]

    if packet_type != "A":
        return None, "Unsupported packet type"

    alert_id = parts[1]
    device_id = parts[2]
    user_id = parts[3]
    zone = parts[4]
    subzone = parts[5]
    emergency_type = parts[6]
    message = parts[7]

    if not alert_id or not device_id or not user_id:
        return None, "Missing required identifier"

    emergency_label = emergency_label_from_code(emergency_type)

    if emergency_label == "Unknown":
        return None, "Unknown emergency type"

    alert_data = {
        "alert_id": alert_id,
        "packet_type": packet_type,
        "raw_packet": raw_packet,
        "device_id": device_id,
        "user_id": user_id,
        "zone": zone,
        "subzone": subzone,
        "emergency_type": emergency_type,
        "emergency_label": emergency_label,
        "message": message,
        "received_at": now()
    }

    return alert_data, None


def handle_received_packet(raw_packet, rssi=None, snr=None):
    alert_data, error = parse_alert_packet(raw_packet)

    if error:
        insert_invalid_packet(
            raw_packet=raw_packet,
            reason=error,
            rssi=rssi,
            snr=snr
        )
        print(f"Invalid packet logged: {error}")
        return None

    alert_id = alert_data["alert_id"]

    ack_message = f"K|{alert_id}|OK"

    alert_data["rssi"] = rssi
    alert_data["snr"] = snr
    alert_data["ack_message"] = ack_message
    alert_data["ack_sent"] = 1
    alert_data["ack_sent_at"] = now()

    insert_alert(alert_data)

    print("Alert saved to database.")
    print(f"ACK to send: {ack_message}")

    return ack_message


if __name__ == "__main__":
    sample_packet = "A|260523173201|TB001|U001|10-5|2-5|F|FTEST1"
    handle_received_packet(sample_packet, rssi=-80, snr=7.5)