from flask import Flask, render_template, Response, request, jsonify, send_file
from flask_cors import CORS
import cv2
import numpy as np
import json
import time
import os
import models
from detector import surveillance_engine

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

# Initialize database tables
models.init_db()

def generate_mjpeg_stream():
    """MJPEG stream generator for HTML5 video element."""
    while True:
        try:
            frame, new_viols = surveillance_engine.process_frame()
            if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
                time.sleep(0.03)
                continue

            ret, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 65])
            if not ret or buffer is None or len(buffer) == 0:
                time.sleep(0.03)
                continue
                
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            
            time.sleep(0.03)
        except Exception as e:
            time.sleep(0.03)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(generate_mjpeg_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'POST':
        data = request.json or {}
        camera_url = data.get('camera_url')
        roi_polygon = data.get('roi_polygon')
        dwell_threshold = data.get('dwell_threshold')
        fine_amount = data.get('fine_amount')
        
        surveillance_engine.update_settings(
            camera_url=camera_url,
            roi_polygon=roi_polygon,
            dwell_threshold=dwell_threshold,
            fine_amount=fine_amount
        )
        
        if camera_url:
            models.set_setting('camera_url', camera_url)
        if roi_polygon is not None:
            models.set_setting('roi_polygon', json.dumps(roi_polygon))
        if dwell_threshold:
            models.set_setting('dwell_threshold', dwell_threshold)
        if fine_amount:
            models.set_setting('fine_amount', fine_amount)

        return jsonify({'status': 'success', 'message': 'Settings updated successfully.'})
    
    # GET settings
    return jsonify({
        'camera_url': surveillance_engine.camera_url,
        'roi_polygon': surveillance_engine.roi_polygon,
        'dwell_threshold': surveillance_engine.dwell_threshold,
        'fine_amount': surveillance_engine.fine_amount
    })

@app.route('/api/violations', methods=['GET'])
def get_violations():
    query = request.args.get('search', '')
    status = request.args.get('status', 'All')
    limit = int(request.args.get('limit', 50))
    
    records = models.get_all_violations(limit=limit, search_query=query, status_filter=status)
    return jsonify({'status': 'success', 'violations': records})

@app.route('/api/violations/<int:violation_id>/pay', methods=['POST'])
def pay_violation(violation_id):
    models.update_violation_status(violation_id, 'Paid')
    return jsonify({'status': 'success', 'message': f'Violation #{violation_id} marked as Paid.'})

@app.route('/api/stats', methods=['GET'])
def get_stats():
    stats = models.get_system_stats()
    stats['active_tracked_vehicles'] = len(surveillance_engine.tracker.tracked_vehicles)
    stats['camera_url'] = surveillance_engine.camera_url
    return jsonify(stats)

@app.route('/api/latest_alerts', methods=['GET'])
def get_latest_alerts():
    alerts = list(surveillance_engine.latest_violations)
    surveillance_engine.latest_violations.clear() # Clear queue after fetch
    return jsonify({'alerts': alerts})

if __name__ == '__main__':
    print("🚀 Starting AI No-Parking Zone Monitoring Server on http://localhost:5050 ...")
    app.run(host='0.0.0.0', port=5050, debug=False, threaded=True)
