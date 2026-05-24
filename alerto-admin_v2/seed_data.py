from database import init_db, insert_alert, insert_registration_request, approve_device, now, emergency_label_from_code


def seed():
    init_db()

    insert_registration_request({
        "request_id": "REQ001",
        "user_id": "U001",
        "device_id": "TB001",
        "full_name": "Juan Dela Cruz",
        "phone_number": "09123456789",
        "address": "Barangay Kaligayahan, Quezon City",
        "status": "Pending"
    })

    approve_device("REQ001")

    sample_alerts = [
        {
            "alert_id": "260523173201",
            "packet_type": "A",
            "raw_packet": "A|260523173201|TB001|U001|10-5|2-5|F|FTEST1",
            "device_id": "TB001",
            "user_id": "U001",
            "zone": "10-5",
            "subzone": "2-5",
            "emergency_type": "F",
            "emergency_label": emergency_label_from_code("F"),
            "message": "FTEST1",
            "received_at": now(),
            "rssi": -78,
            "snr": 7.5,
            "ack_message": "K|260523173201|OK",
            "ack_sent": 1,
            "ack_sent_at": now()
        },
        {
            "alert_id": "260523174010",
            "packet_type": "A",
            "raw_packet": "A|260523174010|TB999|U999|8-2|1-3|M|HELP",
            "device_id": "TB999",
            "user_id": "U999",
            "zone": "8-2",
            "subzone": "1-3",
            "emergency_type": "M",
            "emergency_label": emergency_label_from_code("M"),
            "message": "HELP",
            "received_at": now(),
            "rssi": -91,
            "snr": 3.2,
            "ack_message": "K|260523174010|OK",
            "ack_sent": 1,
            "ack_sent_at": now()
        }
    ]

    for alert in sample_alerts:
        insert_alert(alert)

    print("Database initialized and sample data inserted.")


if __name__ == "__main__":
    seed()