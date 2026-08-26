// State Variables
let isDrawingRoi = false;
let roiPoints = [];
let currentFilterStatus = 'All';
let currentSearchQuery = '';

// DOM Elements
const canvas = document.getElementById('roi-canvas');
const ctx = canvas ? canvas.getContext('2d') : null;
const streamImg = document.getElementById('live-stream');

// Initialize Dashboard
document.addEventListener('DOMContentLoaded', () => {
    initCanvas();
    fetchStats();
    fetchViolations();
    fetchSettings();

    // Start Alert Polling Interval (Every 2.5 seconds)
    setInterval(pollLatestAlerts, 2500);
    setInterval(fetchStats, 5000);
});

// Canvas & ROI Drawing Logic
function initCanvas() {
    if (!canvas || !streamImg) return;
    
    function resizeCanvas() {
        canvas.width = streamImg.clientWidth || 640;
        canvas.height = streamImg.clientHeight || 480;
        redrawCanvas();
    }

    window.addEventListener('resize', resizeCanvas);
    streamImg.onload = resizeCanvas;
    resizeCanvas();

    canvas.addEventListener('click', (e) => {
        if (!isDrawingRoi) return;
        
        const rect = canvas.getBoundingClientRect();
        const scaleX = 640 / canvas.width;
        const scaleY = 480 / canvas.height;

        const x = Math.round((e.clientX - rect.left) * scaleX);
        const y = Math.round((e.clientY - rect.top) * scaleY);

        roiPoints.push([x, y]);
        redrawCanvas();
    });
}

function toggleRoiDrawing() {
    isDrawingRoi = !isDrawingRoi;
    const btn = document.getElementById('btn-draw-roi');
    const banner = document.getElementById('drawing-banner');

    if (isDrawingRoi) {
        roiPoints = [];
        canvas.classList.add('active-drawing');
        btn.classList.add('btn-primary');
        banner.style.display = 'flex';
    } else {
        canvas.classList.remove('active-drawing');
        btn.classList.remove('btn-primary');
        banner.style.display = 'none';
        redrawCanvas();
    }
}

function redrawCanvas() {
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (roiPoints.length === 0) return;

    const scaleX = canvas.width / 640;
    const scaleY = canvas.height / 480;

    ctx.strokeStyle = '#ef4444';
    ctx.fillStyle = 'rgba(239, 68, 68, 0.2)';
    ctx.lineWidth = 3;

    ctx.beginPath();
    ctx.moveTo(roiPoints[0][0] * scaleX, roiPoints[0][1] * scaleY);

    for (let i = 1; i < roiPoints.length; i++) {
        ctx.lineTo(roiPoints[i][0] * scaleX, roiPoints[i][1] * scaleY);
    }

    if (roiPoints.length >= 3) {
        ctx.closePath();
        ctx.fill();
    }
    ctx.stroke();

    // Draw point nodes
    roiPoints.forEach(([x, y]) => {
        ctx.beginPath();
        ctx.arc(x * scaleX, y * scaleY, 5, 0, Math.PI * 2);
        ctx.fillStyle = '#ffffff';
        ctx.fill();
        ctx.strokeStyle = '#ef4444';
        ctx.stroke();
    });
}

function resetRoiPolygon() {
    roiPoints = [];
    redrawCanvas();
    saveRoiPolygon();
}

function saveRoiPolygon() {
    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ roi_polygon: roiPoints })
    })
    .then(res => res.json())
    .then(data => {
        if (isDrawingRoi) toggleRoiDrawing();
        showNotification('No-Parking Zone ROI updated successfully!', 'success');
    });
}

// Camera Source Controls
function switchCamera(cameraUrl) {
    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ camera_url: cameraUrl })
    })
    .then(res => res.json())
    .then(data => {
        document.getElementById('status-text').innerText = `CAMERA LIVE (${cameraUrl.toUpperCase()})`;
        // Force refresh image stream
        streamImg.src = '/video_feed?t=' + new Date().getTime();
        showNotification(`Switched camera source to ${cameraUrl.toUpperCase()}`, 'info');
    });
}

function connectPhoneCameraStream() {
    const url = document.getElementById('phone-url-input').value.trim();
    if (!url) {
        alert("Please enter a valid Phone Camera stream URL!");
        return;
    }
    switchCamera(url);
    closePhoneModal();
}

// System Settings Sync
function fetchSettings() {
    fetch('/api/settings')
        .then(res => res.json())
        .then(data => {
            if (data.roi_polygon) {
                roiPoints = data.roi_polygon;
                redrawCanvas();
            }
            if (data.dwell_threshold) {
                document.getElementById('dwell-select').value = data.dwell_threshold;
            }
            if (data.fine_amount) {
                document.getElementById('fine-input').value = data.fine_amount;
            }
        });
}

function updateDwellThreshold(val) {
    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dwell_threshold: parseInt(val) })
    });
}

function updateFineAmount(val) {
    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fine_amount: parseFloat(val) })
    });
}

// Dashboard Data Polling
function fetchStats() {
    fetch('/api/stats')
        .then(res => res.json())
        .then(data => {
            document.getElementById('stat-total').innerText = data.total_violations || 0;
            document.getElementById('stat-unpaid').innerText = `₹${(data.total_fines - data.collected_fines).toLocaleString()}`;
            document.getElementById('stat-collected').innerText = `₹${data.collected_fines.toLocaleString()}`;
            document.getElementById('stat-active').innerText = data.active_tracked_vehicles || 0;
        });
}

function pollLatestAlerts() {
    fetch('/api/latest_alerts')
        .then(res => res.json())
        .then(data => {
            if (data.alerts && data.alerts.length > 0) {
                // Play Audio Alarm
                const sound = document.getElementById('alarm-sound');
                if (sound) sound.play().catch(e => console.log('Audio autoplay blocked'));

                // Append alert cards & update table
                data.alerts.forEach(renderAlertCard);
                fetchViolations();
                fetchStats();
            }
        });
}

function renderAlertCard(alertData) {
    const list = document.getElementById('alerts-list');
    const emptyMsg = list.querySelector('.empty-alerts');
    if (emptyMsg) emptyMsg.remove();

    const card = document.createElement('div');
    card.className = 'alert-card';
    card.innerHTML = `
        <img src="${alertData.plate_crop_path || '/static/snapshots/placeholder.jpg'}" class="alert-crop-img" alt="Plate Crop">
        <div class="alert-details">
            <div class="alert-header-row">
                <span class="alert-plate">${alertData.plate_number || 'UNKNOWN'}</span>
                <span class="alert-fine">₹${alertData.fine_amount || 1000}</span>
            </div>
            <div class="alert-time">Code: ${alertData.violation_code} | Dwell: ${alertData.dwell_sec || 10}s</div>
            <div style="margin-top: 6px;">
                <a href="${alertData.pdf_url}" target="_blank" class="btn btn-xs btn-primary"><i class="fa-solid fa-file-pdf"></i> Download Challan</a>
            </div>
        </div>
    `;

    list.prepend(card);

    // Keep max 10 alerts in feed
    while (list.children.length > 10) {
        list.removeChild(list.lastChild);
    }
}

// Violations Table Rendering & Filtering
function fetchViolations() {
    const url = `/api/violations?search=${encodeURIComponent(currentSearchQuery)}&status=${encodeURIComponent(currentFilterStatus)}`;
    fetch(url)
        .then(res => res.json())
        .then(data => {
            renderViolationsTable(data.violations || []);
        });
}

function renderViolationsTable(violations) {
    const tbody = document.getElementById('violations-tbody');
    tbody.innerHTML = '';

    if (violations.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 30px;">No violation records found matching filters.</td></tr>`;
        return;
    }

    violations.forEach(v => {
        const tr = document.createElement('tr');
        const isPaid = v.status === 'Paid';
        const badgeClass = isPaid ? 'badge-green' : 'badge-red';

        tr.innerHTML = `
            <td><code>${v.violation_code}</code></td>
            <td>${v.timestamp}</td>
            <td><span class="alert-plate">${v.plate_number}</span></td>
            <td><i class="fa-solid fa-car"></i> ${v.vehicle_type}</td>
            <td>${v.dwell_time_seconds}s</td>
            <td><b>₹${v.fine_amount.toLocaleString()}</b></td>
            <td><span class="badge ${badgeClass}">${v.status}</span></td>
            <td>
                <button class="btn btn-xs btn-dark" onclick="openPreviewModal(${v.id})"><i class="fa-solid fa-eye"></i> View</button>
                <a href="/static/snapshots/challan_${v.violation_code}.pdf" target="_blank" class="btn btn-xs btn-outline"><i class="fa-solid fa-download"></i> PDF</a>
                ${!isPaid ? `<button class="btn btn-xs btn-success" onclick="markPaid(${v.id})"><i class="fa-solid fa-check"></i> Pay</button>` : ''}
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function filterViolations() {
    currentSearchQuery = document.getElementById('search-input').value.trim();
    fetchViolations();
}

function setFilterStatus(status, btnElement) {
    currentFilterStatus = status;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btnElement.classList.add('active');
    fetchViolations();
}

function markPaid(id) {
    fetch(`/api/violations/${id}/pay`, { method: 'POST' })
        .then(res => res.json())
        .then(data => {
            fetchViolations();
            fetchStats();
            showNotification(`Challan #${id} marked as Paid!`, 'success');
        });
}

// Modal Handlers
function openPhoneModal() {
    document.getElementById('phone-modal').classList.add('active');
}

function closePhoneModal() {
    document.getElementById('phone-modal').classList.remove('active');
}

function openPreviewModal(violationId) {
    fetch('/api/violations')
        .then(res => res.json())
        .then(data => {
            const v = (data.violations || []).find(x => x.id === violationId);
            if (!v) return;

            const modal = document.getElementById('preview-modal');
            const content = document.getElementById('preview-content');

            content.innerHTML = `
                <div style="display: flex; gap: 20px; flex-wrap: wrap;">
                    <div style="flex: 1; min-width: 300px;">
                        <h4 style="margin-bottom: 8px;">Full Frame Snapshot</h4>
                        <img src="${v.snapshot_path}" style="width: 100%; border-radius: 8px; border: 1px solid var(--border-color);" alt="Snapshot">
                    </div>
                    <div style="width: 260px;">
                        <h4 style="margin-bottom: 8px;">Cropped License Plate</h4>
                        <img src="${v.plate_crop_path}" style="width: 100%; border-radius: 8px; border: 1px solid var(--border-color); margin-bottom: 12px;" alt="Plate Crop">
                        
                        <div style="background: var(--bg-dark); padding: 14px; border-radius: 8px; font-size: 13px;">
                            <p><b>Challan Code:</b> ${v.violation_code}</p>
                            <p><b>Plate Number:</b> ${v.plate_number}</p>
                            <p><b>Vehicle Type:</b> ${v.vehicle_type}</p>
                            <p><b>Dwell Time:</b> ${v.dwell_time_seconds} seconds</p>
                            <p><b>Fine Amount:</b> ₹${v.fine_amount}</p>
                            <p><b>Status:</b> ${v.status}</p>
                        </div>
                        
                        <div style="margin-top: 14px;">
                            <a href="/static/snapshots/challan_${v.violation_code}.pdf" target="_blank" class="btn btn-primary btn-sm" style="width: 100%; justify-content: center;">
                                <i class="fa-solid fa-file-pdf"></i> Download Official PDF
                            </a>
                        </div>
                    </div>
                </div>
            `;

            modal.classList.add('active');
        });
}

function closePreviewModal() {
    document.getElementById('preview-modal').classList.remove('active');
}

// Utility Toast Notifications
function showNotification(msg, type = 'info') {
    console.log(`[${type.toUpperCase()}] ${msg}`);
}
