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
            notes: `Marked as ${status} from command center dashboard`
        })
    });

    if (response.ok) {
        location.reload();
    } else {
        alert("Failed to update alert status.");
    }
}

async function assignAlert(alertId) {
    const select = document.getElementById(`rescuer-select-${alertId}`);

    if (!select) {
        alert("Rescuer selector was not found for this alert.");
        return;
    }

    const rescuerCode = select.value;

    if (!rescuerCode) {
        alert("Please select a rescuer first.");
        return;
    }

    const confirmed = confirm(`Assign alert ${alertId} to ${rescuerCode}?`);

    if (!confirmed) {
        return;
    }

    const response = await fetch(`/api/alerts/${alertId}/assign`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            rescuer_code: rescuerCode,
            notes: `Assigned to ${rescuerCode} from dispatcher interface`
        })
    });

    const result = await response.json();

    if (response.ok) {
        alert(result.message || "Alert assigned.");
        location.reload();
    } else {
        alert(result.error || "Failed to assign alert.");
    }
}

// ==============================
// Recent Alerts Feed
// ==============================

async function refreshRecentAlerts() {
    const feed = document.getElementById("recent-alerts-body");

    if (!feed) {
        return;
    }

    try {
        const response = await fetch("/api/alerts/recent");
        const alerts = await response.json();

        feed.innerHTML = "";

        alerts.forEach(alert => {
            const item = document.createElement("article");
            item.className = "incident-item";

            item.innerHTML = `
                <div class="incident-topline">
                    <strong>${alert.emergency_label}</strong>
                    <span>${alert.alert_status}</span>
                </div>
                <p>Station: ${alert.device_id} · User: ${alert.user_id}</p>
                <p>Reported Area: ${alert.zone} / ${alert.subzone}</p>
                <small>${alert.received_at} · ${alert.verification_status}</small>
            `;

            feed.appendChild(item);
        });
    } catch (error) {
        console.error("Failed to refresh recent alerts:", error);
    }
}


// ==============================
// ALERTO Command Map
// ==============================

let alertMap = null;
let alertMarkerLayer = null;
let stationMarkerLayer = null;
let boundaryLayer = null;
let landmarkMarkerLayer = null;
let latestAlertLatLng = null;

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

    if (
        alert.alert_status === "Pending" ||
        alert.alert_status === "Assigned" ||
        alert.alert_status === "In Progress"
    ) {
        statusClass = "progress";
    }

    if (alert.alert_status === "Resolved") {
        statusClass = "resolved";
    }

    if (alert.alert_status === "Failed") {
        statusClass = "failed";
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
        iconSize: [34, 34],
        iconAnchor: [17, 17],
        popupAnchor: [0, -17]
    });
}


function createStationIcon() {
    return L.divIcon({
        className: "",
        html: `<div class="station-marker"><div class="station-marker-inner"></div></div>`,
        iconSize: [34, 34],
        iconAnchor: [17, 17],
        popupAnchor: [0, -17]
    });
}


function buildAlertPopup(alert) {
    const ackText = alert.ack_sent ? "ACK Sent" : "ACK Failed / Not Sent";

    return `
        <strong>${alert.emergency_label} ALERT</strong><br>
        <b>Source Station:</b> ${alert.station_name} (${alert.device_id})<br>
        <b>Station Zone:</b> ${alert.assigned_zone}<br>
        <b>Reported Area:</b> ${alert.zone} / ${alert.subzone}<br>
        <b>User ID:</b> ${alert.user_id}<br>
        <b>Message:</b> ${alert.message}<br>
        <b>Status:</b> ${alert.alert_status}<br>
        <b>Verification:</b> ${alert.verification_status}<br>
        <b>ACK:</b> ${ackText}<br>
        <b>RSSI:</b> ${alert.rssi ?? "N/A"} dBm<br>
        <b>SNR:</b> ${alert.snr ?? "N/A"} dB<br>
        <b>Received:</b> ${alert.received_at}
    `;
}


function buildStationPopup(station) {
    return `
        <strong>${station.station_name}</strong><br>
        <b>Station ID:</b> ${station.station_id}<br>
        <b>Assigned Zone:</b> ${station.assigned_zone}<br>
        <b>Status:</b> ${station.status}<br>
        <b>Description:</b> ${station.description}
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
                color: "#38bdf8",
                weight: 4,
                opacity: 1,
                fillColor: "#38bdf8",
                fillOpacity: 0.06
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
                padding: [25, 25]
            });
        }
    } catch (error) {
        console.error("Failed to load barangay boundary:", error);
    }
}


async function loadStations() {
    const stationList = document.getElementById("station-list");
    const stationCount = document.getElementById("station-count");

    if (!alertMap || !stationMarkerLayer) {
        return;
    }

    try {
        const response = await fetch("/api/map/stations");
        const stations = await response.json();

        stationMarkerLayer.clearLayers();

        if (stationList) {
            stationList.innerHTML = "";
        }

        if (stationCount) {
            stationCount.textContent = `${stations.length} Stations`;
        }

        stations.forEach(station => {
            const marker = L.marker([station.lat, station.lng], {
                icon: createStationIcon()
            });

            marker.bindPopup(buildStationPopup(station));
            marker.addTo(stationMarkerLayer);

            if (stationList) {
                const item = document.createElement("div");
                item.className = "station-item";

                item.innerHTML = `
                    <div>
                        <strong>${station.station_name}</strong>
                        <span>${station.station_id} · ${station.assigned_zone}</span>
                    </div>
                    <div class="station-status">${station.status}</div>
                `;

                item.onclick = () => {
                    alertMap.setView([station.lat, station.lng], 17);
                    marker.openPopup();
                };

                stationList.appendChild(item);
            }
        });
    } catch (error) {
        console.error("Failed to load stations:", error);
    }
}


async function loadAlertMarkers() {
    if (!alertMap || !alertMarkerLayer) {
        return;
    }

    try {
        const response = await fetch("/api/map/alerts");
        const alerts = await response.json();

        alertMarkerLayer.clearLayers();

        if (alerts.length > 0) {
            latestAlertLatLng = [alerts[0].lat, alerts[0].lng];
        }

        alerts.forEach(alert => {
            if (!alert.lat || !alert.lng) {
                return;
            }

            const marker = L.marker([alert.lat, alert.lng], {
                icon: createAlertIcon(alert)
            });

            marker.bindPopup(buildAlertPopup(alert));
            marker.addTo(alertMarkerLayer);
        });
    } catch (error) {
        console.error("Failed to load alert markers:", error);
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
            <span class="map-note">No local landmark found. Add this location to LOCAL_LANDMARKS.</span>
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

    alertMap = L.map("alert-map", {
        zoomControl: false
    }).setView(KALIGAYAHAN_CENTER, DEFAULT_ZOOM);

    L.control.zoom({
        position: "bottomright"
    }).addTo(alertMap);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap contributors"
    }).addTo(alertMap);

    stationMarkerLayer = L.layerGroup().addTo(alertMap);
    alertMarkerLayer = L.layerGroup().addTo(alertMap);
    landmarkMarkerLayer = L.layerGroup().addTo(alertMap);

    loadBarangayBoundary();
    loadStations();
    loadAlertMarkers();
}


function resetMapView() {
    if (!alertMap) {
        return;
    }

    if (boundaryLayer) {
        const bounds = boundaryLayer.getBounds();

        if (bounds.isValid()) {
            alertMap.fitBounds(bounds, {
                padding: [25, 25]
            });
            return;
        }
    }

    alertMap.setView(KALIGAYAHAN_CENTER, DEFAULT_ZOOM);
}


function focusLatestAlert() {
    if (alertMap && latestAlertLatLng) {
        alertMap.setView(latestAlertLatLng, 17);
    }
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