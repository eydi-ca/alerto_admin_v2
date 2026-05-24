async function updateStatus(alertId, status) {
    const confirmed = confirm(`Mark alert ${alertId} as ${status}?`);

    if (!confirmed) {
        return;
    }

    const response = await fetch(`/api/alerts/${alertId}/status`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            status: status,
            notes: `Marked as ${status} from admin dashboard`
        })
    });

    if (response.ok) {
        location.reload();
    } else {
        alert("Failed to update alert status.");
    }
}


// ==============================
// Recent Alerts Polling
// ==============================

async function refreshRecentAlerts() {
    const tbody = document.getElementById("recent-alerts-body");

    if (!tbody) {
        return;
    }

    try {
        const response = await fetch("/api/alerts/recent");
        const alerts = await response.json();

        tbody.innerHTML = "";

        alerts.forEach(alert => {
            const row = document.createElement("tr");

            row.innerHTML = `
                <td>${alert.alert_id}</td>
                <td>${alert.device_id}</td>
                <td>${alert.user_id}</td>
                <td>${alert.zone} / ${alert.subzone}</td>
                <td>${alert.emergency_label}</td>
                <td><span class="badge">${alert.alert_status}</span></td>
                <td><span class="badge">${alert.verification_status}</span></td>
                <td>${alert.received_at}</td>
            `;

            tbody.appendChild(row);
        });
    } catch (error) {
        console.error("Failed to refresh recent alerts:", error);
    }
}


// ==============================
// ALERTO Leaflet Map
// ==============================

let alertMap = null;
let alertMarkerLayer = null;
let boundaryLayer = null;
let landmarkMarkerLayer = null;

const KALIGAYAHAN_CENTER = [14.7388, 121.0507];
const DEFAULT_ZOOM = 15;

const LOCAL_LANDMARKS = [
    {
        name: "Barangay Kaligayahan Center",
        type: "Barangay Area",
        lat: 14.7388,
        lng: 121.0507
    },
    {
        name: "Kaligayahan",
        type: "General Area",
        lat: 14.7388,
        lng: 121.0507
    },
    {
        name: "Novaliches",
        type: "Nearby Area",
        lat: 14.7216,
        lng: 121.0378
    },
    {
        name: "Tawid Sapa",
        type: "Local Area",
        lat: 14.7445,
        lng: 121.0465
    }
];


function getMarkerClass(alert) {
    let statusClass = "new";

    if (alert.alert_status === "Acknowledged" || alert.alert_status === "In Progress") {
        statusClass = "progress";
    }

    if (alert.alert_status === "Resolved") {
        statusClass = "resolved";
    }

    let verificationClass = "";

    if (alert.verification_status !== "Verified") {
        verificationClass = "unverified";
    }

    return `alert-marker ${statusClass} ${verificationClass}`;
}


function createAlertIcon(alert) {
    return L.divIcon({
        className: "",
        html: `<div class="${getMarkerClass(alert)}"></div>`,
        iconSize: [28, 28],
        iconAnchor: [14, 14],
        popupAnchor: [0, -14]
    });
}


function buildPopup(alert) {
    const ackText = alert.ack_sent ? "ACK Sent" : "ACK Failed / Not Sent";

    return `
        <strong>${alert.emergency_label}</strong><br>
        <b>Alert ID:</b> ${alert.alert_id}<br>
        <b>Device:</b> ${alert.device_id}<br>
        <b>User:</b> ${alert.user_id}<br>
        <b>Zone/Subzone:</b> ${alert.zone} / ${alert.subzone}<br>
        <b>Message:</b> ${alert.message}<br>
        <b>Status:</b> ${alert.alert_status}<br>
        <b>Verification:</b> ${alert.verification_status}<br>
        <b>ACK:</b> ${ackText}<br>
        <b>RSSI:</b> ${alert.rssi ?? "N/A"} dBm<br>
        <b>SNR:</b> ${alert.snr ?? "N/A"} dB<br>
        <b>Received:</b> ${alert.received_at}
    `;
}


async function loadBarangayBoundary() {
    if (!alertMap) {
        return;
    }

    try {
        const response = await fetch("/static/geojson/barangay_boundary.geojson");

        if (!response.ok) {
            console.error("Boundary GeoJSON not found:", response.status);
            return;
        }

        const boundaryData = await response.json();

        boundaryLayer = L.geoJSON(boundaryData, {
            style: {
                color: "#1d4ed8",
                weight: 4,
                opacity: 1,
                fillColor: "#3b82f6",
                fillOpacity: 0.08
            }
        }).addTo(alertMap);

        boundaryLayer.bindTooltip("Barangay Kaligayahan Boundary", {
            permanent: false,
            direction: "center",
            className: "boundary-label"
        });

        const bounds = boundaryLayer.getBounds();

        if (bounds.isValid()) {
            alertMap.fitBounds(bounds, {
                padding: [30, 30]
            });
        }
    } catch (error) {
        console.error("Failed to load barangay boundary:", error);
    }
}


function searchLandmark() {
    const input = document.getElementById("landmark-search");
    const resultsContainer = document.getElementById("landmark-results");

    if (!input || !resultsContainer || !alertMap) {
        return;
    }

    const query = input.value.trim().toLowerCase();

    resultsContainer.innerHTML = "";

    if (query.length === 0) {
        return;
    }

    const matches = LOCAL_LANDMARKS.filter(item =>
        item.name.toLowerCase().includes(query) ||
        item.type.toLowerCase().includes(query)
    );

    if (matches.length === 0) {
        resultsContainer.innerHTML = `
            <span class="map-note">No local landmark found. Add it to LOCAL_LANDMARKS first.</span>
        `;
        return;
    }

    matches.forEach(landmark => {
        const button = document.createElement("button");
        button.className = "landmark-result-btn";
        button.textContent = `${landmark.name} (${landmark.type})`;

        button.onclick = () => {
            goToLandmark(landmark);
        };

        resultsContainer.appendChild(button);
    });
}


function goToLandmark(landmark) {
    if (!alertMap || !landmarkMarkerLayer) {
        return;
    }

    landmarkMarkerLayer.clearLayers();

    const marker = L.marker([landmark.lat, landmark.lng])
        .bindPopup(`
            <strong>${landmark.name}</strong><br>
            ${landmark.type}<br>
            Lat: ${landmark.lat}<br>
            Lng: ${landmark.lng}
        `);

    marker.addTo(landmarkMarkerLayer);
    marker.openPopup();

    alertMap.setView([landmark.lat, landmark.lng], 17);
}


function initAlertMap() {
    const mapElement = document.getElementById("alert-map");

    if (!mapElement || typeof L === "undefined") {
        return;
    }

    alertMap = L.map("alert-map").setView(KALIGAYAHAN_CENTER, DEFAULT_ZOOM);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap contributors"
    }).addTo(alertMap);

    alertMarkerLayer = L.layerGroup().addTo(alertMap);
    landmarkMarkerLayer = L.layerGroup().addTo(alertMap);

    loadBarangayBoundary();
    loadAlertMarkers();
}


async function loadAlertMarkers() {
    if (!alertMap || !alertMarkerLayer) {
        return;
    }

    try {
        const response = await fetch("/api/map/alerts");
        const alerts = await response.json();

        alertMarkerLayer.clearLayers();

        alerts.forEach(alert => {
            if (!alert.lat || !alert.lng) {
                return;
            }

            const marker = L.marker([alert.lat, alert.lng], {
                icon: createAlertIcon(alert)
            });

            marker.bindPopup(buildPopup(alert));
            marker.addTo(alertMarkerLayer);
        });
    } catch (error) {
        console.error("Failed to load alert markers:", error);
    }
}


function resetMapView() {
    if (!alertMap) {
        return;
    }

    if (boundaryLayer) {
        const bounds = boundaryLayer.getBounds();

        if (bounds.isValid()) {
            alertMap.fitBounds(bounds, {
                padding: [30, 30]
            });
            return;
        }
    }

    alertMap.setView(KALIGAYAHAN_CENTER, DEFAULT_ZOOM);
}


document.addEventListener("DOMContentLoaded", () => {
    refreshRecentAlerts();
    initAlertMap();

    const landmarkInput = document.getElementById("landmark-search");

    if (landmarkInput) {
        landmarkInput.addEventListener("keydown", event => {
            if (event.key === "Enter") {
                searchLandmark();
            }
        });
    }

    setInterval(refreshRecentAlerts, 5000);
    setInterval(loadAlertMarkers, 5000);
});