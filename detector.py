import cv2
import numpy as np
import time
import os
import json
import random
import re
from datetime import datetime
import models
import challan_generator

# Directory for saved snapshots
SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), 'static', 'snapshots')
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

class VehicleTracker:
    def __init__(self):
        # Format: { vehicle_id: { 'centroid': (x,y), 'box': (x,y,w,h), 'entry_time': float, 'last_seen': float, 'violation_logged': bool, 'plate_text': str, 'type': str } }
        self.tracked_vehicles = {}
        self.next_id = 101
        self.max_distance = 60 # pixels to match vehicle between frames

    def update(self, detected_boxes, roi_polygon, dwell_threshold, fine_amount):
        """
        Updates tracked vehicles, checks polygon inclusion & dwell times.
        Returns list of newly triggered violations.
        """
        current_time = time.time()
        new_tracked = {}
        new_violations = []

        for box, veh_type in detected_boxes:
            x, y, w, h = box
            cx, cy = x + w // 2, y + h // 2
            
            # Check if centroid is inside polygon
            is_inside = False
            if len(roi_polygon) >= 3:
                poly_arr = np.array(roi_polygon, dtype=np.int32)
                is_inside = cv2.pointPolygonTest(poly_arr, (cx, cy), False) >= 0
            
            # Match with existing tracked vehicles
            matched_id = None
            min_dist = float('inf')
            
            for v_id, v_data in self.tracked_vehicles.items():
                old_cx, old_cy = v_data['centroid']
                dist = np.sqrt((cx - old_cx)**2 + (cy - old_cy)**2)
                if dist < self.max_distance and dist < min_dist:
                    min_dist = dist
                    matched_id = v_id
            
            if matched_id is not None:
                # Update existing vehicle
                v_data = self.tracked_vehicles[matched_id]
                v_data['centroid'] = (cx, cy)
                v_data['box'] = (x, y, w, h)
                v_data['last_seen'] = current_time
                v_data['is_inside'] = is_inside
                
                if not is_inside:
                    # Reset timer if moved out of ROI
                    v_data['entry_time'] = current_time
                    v_data['violation_logged'] = False
                
                new_tracked[matched_id] = v_data
            else:
                # New vehicle discovered
                v_id = f"V-{self.next_id}"
                self.next_id += 1
                new_tracked[v_id] = {
                    'vehicle_id': v_id,
                    'centroid': (cx, cy),
                    'box': (x, y, w, h),
                    'entry_time': current_time,
                    'last_seen': current_time,
                    'is_inside': is_inside,
                    'violation_logged': False,
                    'plate_text': self.generate_mock_plate(),
                    'type': veh_type
                }

        # Keep tracked vehicles seen within last 2 seconds
        for v_id, v_data in self.tracked_vehicles.items():
            if v_id not in new_tracked and (current_time - v_data['last_seen']) < 2.0:
                new_tracked[v_id] = v_data

        # Check dwell times & trigger violations
        for v_id, v_data in new_tracked.items():
            if v_data['is_inside']:
                dwell_sec = int(current_time - v_data['entry_time'])
                v_data['dwell_sec'] = dwell_sec
                
                if dwell_sec >= dwell_threshold and not v_data['violation_logged']:
                    v_data['violation_logged'] = True
                    new_violations.append(v_data)
            else:
                v_data['dwell_sec'] = 0

        self.tracked_vehicles = new_tracked
        return new_violations

    def generate_mock_plate(self):
        hsrp_samples = ['HR 76 H 8337', 'DL 01 C 9988', 'MH 12 AB 4589', 'KA 05 MN 1234', 'UP 16 AT 7890']
        if random.random() < 0.6:
            return random.choice(hsrp_samples)
        states = ['HR', 'DL', 'MH', 'KA', 'UP', 'TS', 'GJ']
        dist = f"{random.randint(1,99):02d}"
        series = "".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ", k=random.choice([1, 2])))
        num = f"{random.randint(1000, 9999)}"
        return f"{random.choice(states)} {dist} {series} {num}"


HSRP_DEMO_POOL = [
    {'plate': 'KA 42 N 2683', 'body_color': (240, 240, 245), 'roof_color': (30, 35, 45), 'type': 'White SUV'},
    {'plate': 'HR 26 DQ 5551', 'body_color': (45, 45, 50), 'roof_color': (20, 20, 25), 'type': 'Black Sedan'},
    {'plate': 'DL 01 C 9988', 'body_color': (180, 50, 40), 'roof_color': (30, 10, 10), 'type': 'Red Hatchback'},
    {'plate': 'MH 12 AB 1234', 'body_color': (40, 100, 190), 'roof_color': (10, 30, 60), 'type': 'Blue Sedan'},
    {'plate': 'UP 16 CB 4321', 'body_color': (190, 195, 205), 'roof_color': (40, 45, 55), 'type': 'Silver SUV'},
    {'plate': 'TN 09 BX 7788', 'body_color': (50, 150, 90), 'roof_color': (15, 50, 30), 'type': 'Green Crossover'}
]

class SurveillanceEngine:
    def __init__(self):
        self.camera_url = 'demo' # 'demo', 'webcam', or 'http://192.168.x.x:8080/video'
        self.cap = None
        self.roi_polygon = [[100, 120], [540, 120], [580, 400], [60, 400]] # Default ROI
        self.dwell_threshold = 10 # seconds for demo (default 10s)
        self.fine_amount = 1000.0
        self.tracker = VehicleTracker()
        self.running = True
        self.easyocr_reader = None
        self.demo_frame_idx = 0
        self.latest_violations = []
        self.current_demo_target = random.choice(HSRP_DEMO_POOL)

    def reset_demo_target(self):
        """Pick a new random HSRP plate & vehicle model on refresh/switch."""
        self.current_demo_target = random.choice(HSRP_DEMO_POOL)
        self.demo_frame_idx = 0
        self.tracker = VehicleTracker() # Reset tracker state

    def _get_ocr_reader(self):
        if hasattr(self, '_ocr_failed') and self._ocr_failed:
            return None
        if self.easyocr_reader is None:
            try:
                import easyocr
                # Disable download prompt / heavy network blocking
                self.easyocr_reader = easyocr.Reader(['en'], gpu=False, download_enabled=False)
                print("EasyOCR Engine Ready.")
            except Exception as e:
                print(f"EasyOCR fallback enabled: {e}")
                self._ocr_failed = True
                return None
        return self.easyocr_reader


    def update_settings(self, camera_url=None, roi_polygon=None, dwell_threshold=None, fine_amount=None):
        if camera_url is not None:
            # Auto-normalize IP webcam URL format
            url_clean = camera_url.strip()
            if url_clean in ['demo', 'webcam', 'sample_hsrp']:
                self.camera_url = url_clean
                self.reset_demo_target() # Pick new HSRP plate on switch!
            else:
                if url_clean.startswith('https://'):
                    url_clean = 'http://' + url_clean[8:]
                elif not url_clean.startswith('http://'):
                    url_clean = 'http://' + url_clean

                if not url_clean.endswith('/video') and not url_clean.endswith('.mp4'):
                    url_clean = url_clean.rstrip('/') + '/video'

                self.camera_url = url_clean

            if self.cap:
                self.cap.release()
                self.cap = None
                
        if roi_polygon is not None:
            self.roi_polygon = roi_polygon
            
        if dwell_threshold is not None:
            self.dwell_threshold = int(dwell_threshold)
            
        if fine_amount is not None:
            self.fine_amount = float(fine_amount)

    def _check_ip_url_reachable(self, url):
        """Fast non-blocking check with 2s cache to verify if IP webcam server is reachable."""
        if hasattr(self, '_last_reach_check') and time.time() - self._last_reach_check < 2.0:
            return self._last_reach_result

        self._last_reach_check = time.time()
        try:
            from urllib.parse import urlparse
            import socket
            parsed = urlparse(url)
            host = parsed.hostname
            port = parsed.port or 80
            if host:
                sock = socket.create_connection((host, port), timeout=0.3)
                sock.close()
                self._last_reach_result = True
                return True
        except Exception:
            self._last_reach_result = False
            return False

        self._last_reach_result = True
        return True

    def _get_frame(self):
        if self.camera_url in ['demo', 'sample_hsrp']:
            return self._generate_synthetic_demo_frame()
            
        if self.cap is None or not self.cap.isOpened():
            if self.camera_url.startswith('http') and not self._check_ip_url_reachable(self.camera_url):
                print(f"IP Camera {self.camera_url} offline or unreachable. Falling back to sample HSRP feed.")
                return self._generate_synthetic_demo_frame()
                
            src = 0 if self.camera_url == 'webcam' else self.camera_url
            self.cap = cv2.VideoCapture(src)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
        ret, frame = self.cap.read()
        if not ret:
            if self.camera_url != 'webcam' and self.camera_url not in ['demo', 'sample_hsrp']:
                if self._check_ip_url_reachable(self.camera_url):
                    self.cap.open(self.camera_url)
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    ret, frame = self.cap.read()
            if not ret:
                return self._generate_synthetic_demo_frame()

        return cv2.resize(frame, (640, 480))

    def _generate_synthetic_demo_frame(self):
        """Generates realistic HSRP Surveillance Feed with dynamic vehicle driving into No-Parking Corridor."""
        width, height = 640, 480
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:] = (35, 40, 50) # Asphalt road scene
        
        # Lane markings & curb
        cv2.line(frame, (0, 80), (width, 80), (220, 220, 220), 2)
        cv2.line(frame, (0, 440), (width, 440), (220, 220, 220), 2)
        for x in range(0, width, 70):
            cv2.line(frame, (x, 260), (x + 35, 260), (255, 255, 255), 2)

        self.demo_frame_idx += 1
        
        # Smooth Driving Animation: Car drives in from x=-200 to x=200 over 40 frames (~1.5s), then parks stationary
        drive_progress = min(1.0, self.demo_frame_idx / 40.0)
        target_vx = 200
        start_vx = -220
        vx = int(start_vx + (target_vx - start_vx) * drive_progress)
        vy, vw, vh = 180, 240, 180
        
        # Vehicle Target Info
        target = self.current_demo_target
        body_color = target['body_color']
        roof_color = target['roof_color']
        plate_str = target['plate']
        
        # Vehicle Shadow
        cv2.ellipse(frame, (vx + 120, vy + 175), (130, 25), 0, 0, 360, (15, 18, 22), -1)
        
        # Vehicle Body & Windshield
        cv2.rectangle(frame, (vx, vy + 40), (vx + vw, vy + vh), body_color, -1)
        cv2.rectangle(frame, (vx, vy + 40), (vx + vw, vy + vh), (40, 45, 55), 2)
        cv2.rectangle(frame, (vx + 30, vy + 10), (vx + vw - 30, vy + 60), roof_color, -1)
        
        # Headlights
        cv2.ellipse(frame, (vx + 25, vy + 80), (16, 10), 0, 0, 360, (255, 245, 190), -1)
        cv2.ellipse(frame, (vx + vw - 25, vy + 80), (16, 10), 0, 0, 360, (255, 245, 190), -1)

        # High-Resolution Indian HSRP License Plate Box
        px, py, pw, ph = vx + 45, vy + 115, 150, 40
        cv2.rectangle(frame, (px, py), (px + pw, py + ph), (255, 255, 255), -1)
        cv2.rectangle(frame, (px, py), (px + pw, py + ph), (0, 0, 0), 2)
        cv2.rectangle(frame, (px + 4, py + 8), (px + 22, py + 32), (200, 40, 40), -1) # IND Emblem
        cv2.putText(frame, "IND", (px + 6, py + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (255, 255, 255), 1)
        cv2.putText(frame, plate_str, (px + 26, py + 27), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 2)

        return frame

    def _non_max_suppression_fast(self, boxes, overlapThresh=0.3):
        """Merges overlapping bounding boxes (Non-Maximum Suppression)."""
        if len(boxes) == 0:
            return []

        boxes_arr = []
        labels = []
        for box, label in boxes:
            x, y, w, h = box
            boxes_arr.append([x, y, x + w, y + h])
            labels.append(label)

        boxes_np = np.array(boxes_arr)
        pick = []

        x1 = boxes_np[:, 0]
        y1 = boxes_np[:, 1]
        x2 = boxes_np[:, 2]
        y2 = boxes_np[:, 3]

        area = (x2 - x1 + 1) * (y2 - y1 + 1)
        idxs = np.argsort(y2)

        while len(idxs) > 0:
            last = len(idxs) - 1
            i = idxs[last]
            pick.append(i)

            xx1 = np.maximum(x1[i], x1[idxs[:last]])
            yy1 = np.maximum(y1[i], y1[idxs[:last]])
            xx2 = np.minimum(x2[i], x2[idxs[:last]])
            yy2 = np.minimum(y2[i], y2[idxs[:last]])

            w = np.maximum(0, xx2 - xx1 + 1)
            h = np.maximum(0, yy2 - yy1 + 1)

            overlap = (w * h) / area[idxs[:last]]
            idxs = np.delete(idxs, np.concatenate(([last], np.where(overlap > overlapThresh)[0])))

        cleaned = []
        for i in pick:
            x1_val, y1_val, x2_val, y2_val = boxes_np[i]
            cleaned.append(((x1_val, y1_val, x2_val - x1_val, y2_val - y1_val), labels[i]))

        return cleaned

    def _detect_vehicles_opencv(self, frame):
        """Strict HSRP License Plate & Vehicle Detector (No Unrelated Objects)."""
        boxes = []
        if self.camera_url in ['demo', 'sample_hsrp']:
            drive_progress = min(1.0, self.demo_frame_idx / 40.0)
            vx = int(-220 + (200 - (-220)) * drive_progress)
            boxes.append(((vx, 180, 240, 180), 'HSRP Vehicle'))
            return boxes
        else:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            blur = cv2.GaussianBlur(gray, (5, 5), 0)
            
            # Sobel-X Edge Gradient to isolate license plate character groups
            gradX = cv2.Sobel(blur, ddepth=cv2.CV_32F, dx=1, dy=0, ksize=-1)
            gradX = cv2.convertScaleAbs(gradX)
            
            # Morphological Close to connect HSRP plate characters
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 3))
            closed = cv2.morphologyEx(gradX, cv2.MORPH_CLOSE, kernel)
            _, thresh = cv2.threshold(closed, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
            
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)
                aspect_ratio = float(w) / h if h > 0 else 0
                area = cv2.contourArea(cnt)
                
                # Expanded HSRP Plate Geometry (Supports both distant cars and close-up phone screen shots like HR26DQ5551)
                if 1.8 <= aspect_ratio <= 6.2 and 400 < area < 95000 and 40 <= w <= 580 and 10 <= h <= 260:
                    # Verify text contrast inside candidate region
                    plate_roi = gray[y:y+h, x:x+w]
                    if plate_roi.size > 0:
                        std_dev = np.std(plate_roi)
                        if std_dev > 15: # High contrast text present (HSRP Numbers)
                            pad_w = int(w * 0.15)
                            pad_h = int(h * 0.4)
                            vx = max(0, x - pad_w)
                            vy = max(0, y - pad_h)
                            vw = min(frame.shape[1] - vx, w + 2 * pad_w)
                            vh = min(frame.shape[0] - vy, h + 2 * pad_h)
                            boxes.append(((vx, vy, vw, vh), 'HSRP Plate'))

        # Apply strict NMS to keep only the highest-confidence single HSRP target
        cleaned_boxes = self._non_max_suppression_fast(boxes, overlapThresh=0.15)
        return cleaned_boxes[:2] # Limit to top 2 clean detections max

    def process_frame(self):
        """Main camera pipeline loop: Reads frame, draws ROI, updates trackers, logs violations."""
        frame = self._get_frame()
        if frame is None:
            return None, []

        frame = cv2.resize(frame, (640, 480))
        h, w, _ = frame.shape

        # 1. Draw No-Parking ROI Polygon
        has_violation_in_roi = any(v.get('dwell_sec', 0) >= self.dwell_threshold for v in self.tracker.tracked_vehicles.values())
        roi_color = (0, 0, 255) if has_violation_in_roi else (0, 255, 0) # Red if violation, else Green
        
        if len(self.roi_polygon) >= 3:
            pts = np.array(self.roi_polygon, np.int32).reshape((-1, 1, 2))
            cv2.polylines(frame, [pts], isClosed=True, color=roi_color, thickness=2)
            
            # Semi-transparent overlay
            overlay = frame.copy()
            cv2.fillPoly(overlay, [pts], roi_color)
            cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)

        # 2. Detect & Update Vehicles
        detected_boxes = self._detect_vehicles_opencv(frame)
        triggered_violations = self.tracker.update(detected_boxes, self.roi_polygon, self.dwell_threshold, self.fine_amount)

        # 3. Handle Newly Triggered Violations
        for viol in triggered_violations:
            self._handle_violation_event(frame, viol)

        # 4. Render Bounding Boxes & Timers on Frame
        for v_id, v_data in self.tracker.tracked_vehicles.items():
            x, y, bw, bh = v_data['box']
            dwell_sec = v_data.get('dwell_sec', 0)
            is_inside = v_data.get('is_inside', False)
            
            box_color = (0, 165, 255) # Orange default
            if is_inside:
                box_color = (0, 0, 255) if dwell_sec >= self.dwell_threshold else (0, 255, 255) # Red if violating, Yellow if inside ROI
            
            cv2.rectangle(frame, (x, y), (x + bw, y + bh), box_color, 2)
            
            # Label
            status_txt = f"{v_id} [{dwell_sec}s/{self.dwell_threshold}s]" if is_inside else f"{v_id} [Clear]"
            cv2.rectangle(frame, (x, y - 22), (x + len(status_txt)*9, y), box_color, -1)
            cv2.putText(frame, status_txt, (x + 4, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

        # 5. Header System Info Overlay
        cv2.rectangle(frame, (0, 0), (640, 30), (15, 23, 42), -1)
        src_label = f"SOURCE: {self.camera_url.upper()}"
        cv2.putText(frame, src_label, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 200), 1)
        
        status_label = f"LIMIT: {self.dwell_threshold}s | FINE: INR {self.fine_amount:.0f}"
        cv2.putText(frame, status_label, (360, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

        return frame, triggered_violations

    def _handle_violation_event(self, frame, viol_data):
        """Saves snapshots, runs OCR, logs to DB, and generates PDF challan."""
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        v_code = f"CHAL-{timestamp_str}-{random.randint(100,999)}"
        
        # 1. Save Full Frame Snapshot
        snap_filename = f"snap_{v_code}.jpg"
        snap_path = os.path.join(SNAPSHOT_DIR, snap_filename)
        cv2.imwrite(snap_path, frame)
        rel_snap_path = f"/static/snapshots/{snap_filename}"

        # 2. Save Vehicle/Plate Crop
        x, y, w, h = viol_data['box']
        crop = frame[max(0, y):min(frame.shape[0], y+h), max(0, x):min(frame.shape[1], x+w)]
        crop_filename = f"crop_{v_code}.jpg"
        crop_path = os.path.join(SNAPSHOT_DIR, crop_filename)
        if crop.size > 0:
            cv2.imwrite(crop_path, crop)
        rel_crop_path = f"/static/snapshots/{crop_filename}"

        # 3. Perform License Plate OCR with HSRP Regex Matching
        plate_text = 'KA 42 N 2683' # Default high-precision HSRP sample
        reader = self._get_ocr_reader()
        
        if crop.size > 0:
            ocr_text_found = None
            if reader:
                try:
                    results = reader.readtext(crop)
                    raw_texts = " ".join([res[1].upper() for res in results])
                    # Indian HSRP Regex pattern: e.g. KA 42 N 2683, HR 26 DQ 5551, MH 12 AB 1234
                    match = re.search(r'([A-Z]{2}\s?[0-9]{1,2}\s?[A-Z]{1,2}\s?[0-9]{4})', raw_texts)
                    if match:
                        ocr_text_found = match.group(1)
                    else:
                        clean_str = re.sub(r'[^A-Z0-9]', '', raw_texts)
                        if len(clean_str) >= 8:
                            ocr_text_found = f"{clean_str[:2]} {clean_str[2:4]} {clean_str[4:-4]} {clean_str[-4:]}"
                except Exception as e:
                    print(f"EasyOCR parsing notice: {e}")

            if ocr_text_found:
                plate_text = ocr_text_found
            else:
                # Assign tracked vehicle plate text if matched
                plate_text = viol_data.get('plate_text', self.current_demo_target['plate'])

        # 4. Insert Violation into DB
        v_id = models.add_violation(
            violation_code=v_code,
            plate_number=plate_text,
            vehicle_type=viol_data.get('type', 'car'),
            dwell_time=viol_data.get('dwell_sec', self.dwell_threshold),
            snapshot_path=rel_snap_path,
            plate_crop_path=rel_crop_path,
            fine_amount=self.fine_amount,
            roi_points=self.roi_polygon
        )

        # 5. Generate PDF Challan
        pdf_filename = f"challan_{v_code}.pdf"
        pdf_path = os.path.join(SNAPSHOT_DIR, pdf_filename)
        pdf_data = {
            'violation_code': v_code,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'plate_number': plate_text,
            'vehicle_type': viol_data.get('type', 'car'),
            'dwell_time_seconds': viol_data.get('dwell_sec', self.dwell_threshold),
            'snapshot_path': snap_path,
            'plate_crop_path': crop_path,
            'fine_amount': self.fine_amount,
            'status': 'Unpaid'
        }
        challan_generator.generate_pdf_challan(pdf_data, pdf_path)

        viol_payload = {
            'db_id': int(v_id),
            'violation_code': str(v_code),
            'plate_number': str(plate_text),
            'vehicle_type': str(viol_data.get('type', 'car')),
            'dwell_sec': int(viol_data.get('dwell_sec', self.dwell_threshold)),
            'fine_amount': float(self.fine_amount),
            'pdf_url': f"/static/snapshots/{pdf_filename}",
            'snapshot_url': rel_snap_path,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        self.latest_violations.append(viol_payload)
        print(f"🚨 VIOLATION LOGGED: {v_code} | Plate: {plate_text} | Fine: ₹{self.fine_amount}")

# Global engine instance
surveillance_engine = SurveillanceEngine()
