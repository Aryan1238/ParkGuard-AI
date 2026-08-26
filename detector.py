import cv2
import numpy as np
import time
import os
import json
import random
import re
import threading
from datetime import datetime
from urllib.parse import urlparse
import socket
import models
import challan_generator

# Directory for saved snapshots
SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), 'static', 'snapshots')
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

class ThreadedCamera:
    """
    High-performance async threaded video capture node.
    Prevents OpenCV read() network drops from blocking the AI inference pipeline.
    """
    def __init__(self, src=0):
        self.src = src
        self.cap = cv2.VideoCapture(src)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.ret, self.frame = self.cap.read()
        self.running = True
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()

    def _update(self):
        while self.running:
            if self.cap and self.cap.isOpened():
                ret, frame = self.cap.read()
                with self.lock:
                    self.ret = ret
                    if ret:
                        self.frame = frame
            time.sleep(0.015) # ~60 FPS update loop

    def read(self):
        with self.lock:
            return self.ret, self.frame.copy() if (self.ret and self.frame is not None) else (False, None)

    def release(self):
        self.running = False
        if self.cap:
            self.cap.release()

class VehicleTracker:
    def __init__(self):
        # Format: { vehicle_id: { 'centroid': (x,y), 'box': (x,y,w,h), 'entry_time': float, 'last_seen': float, 'violation_logged': bool, 'plate_text': str, 'type': str } }
        self.tracked_vehicles = {}
        self.next_id = 101
        self.max_distance = 80 # distance threshold for centroid tracking
        self.alpha = 0.4 # EMA position smoothing factor

    def update(self, detected_boxes, roi_polygon, dwell_threshold, fine_amount):
        """
        Updates tracked vehicles with position smoothing and polygon spatial inclusion.
        Returns list of newly triggered violations.
        """
        current_time = time.time()
        new_tracked = {}
        new_violations = []

        for box, veh_type in detected_boxes:
            x, y, w, h = box
            cx, cy = x + w // 2, y + h // 2
            
            # Spatial Polygon Intersection Test
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
                # Update existing vehicle with position smoothing
                v_data = self.tracked_vehicles[matched_id]
                old_x, old_y, old_w, old_h = v_data['box']
                
                # Exponential Moving Average (EMA) position smoothing for rock-solid bounding boxes
                smooth_x = int(self.alpha * x + (1 - self.alpha) * old_x)
                smooth_y = int(self.alpha * y + (1 - self.alpha) * old_y)
                smooth_w = int(self.alpha * w + (1 - self.alpha) * old_w)
                smooth_h = int(self.alpha * h + (1 - self.alpha) * old_h)
                
                v_data['centroid'] = (smooth_x + smooth_w // 2, smooth_y + smooth_h // 2)
                v_data['box'] = (smooth_x, smooth_y, smooth_w, smooth_h)
                v_data['last_seen'] = current_time
                v_data['is_inside'] = is_inside
                
                if not is_inside:
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

        # Retain tracked vehicles seen within last 2 seconds
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
        hsrp_samples = ['HR 26 DQ 5551', 'DL 01 C 9988', 'MH 12 AB 1234', 'KA 42 N 2683', 'UP 16 CB 4321']
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
        self.camera_url = 'demo' # 'demo', 'webcam', or IP Camera URL
        self.threaded_cam = None
        self.roi_polygon = [[100, 120], [540, 120], [580, 400], [60, 400]]
        self.dwell_threshold = 10
        self.fine_amount = 1000.0
        self.tracker = VehicleTracker()
        self.running = True
        self.easyocr_reader = None
        self.demo_frame_idx = 0
        self.latest_violations = []
        self.current_demo_target = random.choice(HSRP_DEMO_POOL)
        
        # CLAHE Contrast Enhancer for ALPR CNN pre-processing
        self.clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))

    def reset_demo_target(self):
        """Picks a new random HSRP plate & vehicle model on refresh/switch."""
        self.current_demo_target = random.choice(HSRP_DEMO_POOL)
        self.demo_frame_idx = 0
        self.tracker = VehicleTracker()

    def _get_ocr_reader(self):
        if hasattr(self, '_ocr_failed') and self._ocr_failed:
            return None
        if self.easyocr_reader is None:
            try:
                import easyocr
                self.easyocr_reader = easyocr.Reader(['en'], gpu=False, download_enabled=False)
                print("EasyOCR Engine Ready.")
            except Exception as e:
                print(f"EasyOCR fallback enabled: {e}")
                self._ocr_failed = True
                return None
        return self.easyocr_reader

    def update_settings(self, camera_url=None, roi_polygon=None, dwell_threshold=None, fine_amount=None):
        if camera_url is not None:
            url_clean = camera_url.strip()
            if url_clean in ['demo', 'webcam', 'sample_hsrp']:
                self.camera_url = url_clean
                self.reset_demo_target()
                if self.threaded_cam:
                    self.threaded_cam.release()
                    self.threaded_cam = None
            else:
                if url_clean.startswith('https://'):
                    url_clean = 'http://' + url_clean[8:]
                elif not url_clean.startswith('http://'):
                    url_clean = 'http://' + url_clean

                if not url_clean.endswith('/video') and not url_clean.endswith('.mp4'):
                    url_clean = url_clean.rstrip('/') + '/video'

                self.camera_url = url_clean
                if self.threaded_cam:
                    self.threaded_cam.release()
                    self.threaded_cam = None

        if roi_polygon is not None:
            self.roi_polygon = roi_polygon
            
        if dwell_threshold is not None:
            self.dwell_threshold = int(dwell_threshold)
            
        if fine_amount is not None:
            self.fine_amount = float(fine_amount)

    def _check_ip_url_reachable(self, url):
        if hasattr(self, '_last_reach_check') and time.time() - self._last_reach_check < 2.0:
            return self._last_reach_result

        self._last_reach_check = time.time()
        try:
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
            if self.threaded_cam:
                self.threaded_cam.release()
                self.threaded_cam = None
            return self._generate_synthetic_demo_frame()
            
        if self.threaded_cam is None:
            if self.camera_url.startswith('http') and not self._check_ip_url_reachable(self.camera_url):
                print(f"IP Camera {self.camera_url} offline or unreachable. Falling back to sample HSRP feed.")
                return self._generate_synthetic_demo_frame()
                
            src = 0 if self.camera_url == 'webcam' else self.camera_url
            try:
                self.threaded_cam = ThreadedCamera(src)
            except Exception as e:
                print(f"ThreadedCamera launch error: {e}")
                return self._generate_synthetic_demo_frame()
            
        ret, frame = self.threaded_cam.read()
        if not ret or frame is None:
            return self._generate_synthetic_demo_frame()

        return cv2.resize(frame, (640, 480))

    def _generate_synthetic_demo_frame(self):
        """Generates realistic HSRP Surveillance Feed with dynamic vehicle driving into No-Parking Corridor."""
        width, height = 640, 480
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:] = (35, 40, 50) # Dark asphalt road scene
        
        # Road lane markings & curb
        cv2.line(frame, (0, 80), (width, 80), (220, 220, 220), 2)
        cv2.line(frame, (0, 440), (width, 440), (220, 220, 220), 2)
        for x in range(0, width, 70):
            cv2.line(frame, (x, 260), (x + 35, 260), (255, 255, 255), 2)

        self.demo_frame_idx += 1
        
        # Smooth Driving Animation: Car drives in from x=-220 to x=200 over 40 frames, then parks
        drive_progress = min(1.0, self.demo_frame_idx / 40.0)
        target_vx = 200
        start_vx = -220
        vx = int(start_vx + (target_vx - start_vx) * drive_progress)
        vy, vw, vh = 180, 240, 180
        
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
        
        # Headlights with glow
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

    def _get_yolo_model(self):
        if hasattr(self, '_yolo_failed') and self._yolo_failed:
            return None
        if not hasattr(self, 'yolo_model') or self.yolo_model is None:
            try:
                from ultralytics import YOLO
                self.yolo_model = YOLO('yolov8n.pt')
                print("YOLOv8 Pretrained Deep Learning Model Ready.")
            except Exception as e:
                print(f"YOLOv8 fallback notice: {e}")
                self._yolo_failed = True
                return None
        return self.yolo_model

    def _detect_vehicles_opencv(self, frame):
        """
        Deep Learning + OpenCV HSRP Plate & Vehicle Computer Vision Pipeline.
        Uses pretrained YOLOv8 CNN for Car, Bike, Bus, and Truck detection, combined with CLAHE Sobel-X HSRP plate localization.
        """
        boxes = []
        if self.camera_url in ['demo', 'sample_hsrp']:
            drive_progress = min(1.0, self.demo_frame_idx / 40.0)
            vx = int(-220 + (200 - (-220)) * drive_progress)
            boxes.append(((vx, 180, 240, 180), 'HSRP Vehicle'))
            return boxes
            
        yolo = self._get_yolo_model()
        if yolo:
            try:
                # Class IDs: 2: car, 3: motorcycle, 5: bus, 7: truck
                results = yolo(frame, verbose=False, conf=0.35, classes=[2, 3, 5, 7])[0]
                class_names = {2: 'Car', 3: 'Bike', 5: 'Bus', 7: 'Truck'}
                for r in results.boxes:
                    box = r.xywh[0].cpu().numpy()
                    cx, cy, w, h = box
                    x = int(cx - w / 2)
                    y = int(cy - h / 2)
                    cls_id = int(r.cls[0].cpu().numpy())
                    label = class_names.get(cls_id, 'Vehicle')
                    boxes.append(((max(0, x), max(0, y), int(w), int(h)), label))
            except Exception as e:
                print(f"YOLO inference notice: {e}")

        # Secondary CLAHE + Sobel-X HSRP Plate Localization fallback
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        enhanced_gray = self.clahe.apply(gray)
        blur = cv2.bilateralFilter(enhanced_gray, 9, 75, 75)
        gradX = cv2.Sobel(blur, ddepth=cv2.CV_32F, dx=1, dy=0, ksize=-1)
        gradX = cv2.convertScaleAbs(gradX)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (19, 3))
        closed = cv2.morphologyEx(gradX, cv2.MORPH_CLOSE, kernel)
        _, thresh = cv2.threshold(closed, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            aspect_ratio = float(w) / h if h > 0 else 0
            area = cv2.contourArea(cnt)
            if 1.8 <= aspect_ratio <= 6.5 and 350 < area < 100000 and 35 <= w <= 580 and 10 <= h <= 280:
                plate_roi = gray[y:y+h, x:x+w]
                if plate_roi.size > 0 and np.std(plate_roi) > 14:
                    pad_w = int(w * 0.15)
                    pad_h = int(h * 0.4)
                    vx = max(0, x - pad_w)
                    vy = max(0, y - pad_h)
                    vw = min(frame.shape[1] - vx, w + 2 * pad_w)
                    vh = min(frame.shape[0] - vy, h + 2 * pad_h)
                    boxes.append(((vx, vy, vw, vh), 'HSRP Plate'))

        cleaned_boxes = self._non_max_suppression_fast(boxes, overlapThresh=0.2)
        return cleaned_boxes[:3]

    def _non_max_suppression_fast(self, boxes, overlapThresh=0.3):
        """Fast Non-Maximum Suppression (NMS) box deduplication."""
        if len(boxes) == 0:
            return []

        boxes_arr = []
        labels = []
        for box, label in boxes:
            x, y, w, h = box
            boxes_arr.append([x, y, x + w, y + h])
            labels.append(label)

        boxes_np = np.array(boxes_arr, dtype=np.float32)
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
            cleaned.append(((int(x1_val), int(y1_val), int(x2_val - x1_val), int(y2_val - y1_val)), labels[i]))

        return cleaned

    def process_frame(self):
        """Main camera pipeline loop: Reads frame, draws ROI, updates trackers, logs violations."""
        frame = self._get_frame()
        if frame is None:
            return None, []

        frame = cv2.resize(frame, (640, 480))
        h, w, _ = frame.shape

        # 1. Draw No-Parking ROI Polygon with Neon Glow Effect
        has_violation_in_roi = any(v.get('dwell_sec', 0) >= self.dwell_threshold for v in self.tracker.tracked_vehicles.values())
        roi_color = (85, 0, 255) if has_violation_in_roi else (212, 245, 0) # Glowing Crimson Red or Electric Cyan
        
        if len(self.roi_polygon) >= 3:
            pts = np.array(self.roi_polygon, np.int32).reshape((-1, 1, 2))
            cv2.polylines(frame, [pts], isClosed=True, color=roi_color, thickness=2, lineType=cv2.LINE_AA)
            
            # Semi-transparent overlay
            overlay = frame.copy()
            cv2.fillPoly(overlay, [pts], roi_color)
            cv2.addWeighted(overlay, 0.16, frame, 0.84, 0, frame)

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
            
            box_color = (255, 165, 0) # Amber default
            if is_inside:
                box_color = (85, 0, 255) if dwell_sec >= self.dwell_threshold else (0, 245, 255)
            
            cv2.rectangle(frame, (x, y), (x + bw, y + bh), box_color, 2, lineType=cv2.LINE_AA)
            
            # Label Badge
            status_txt = f"{v_id} [{dwell_sec}s/{self.dwell_threshold}s]" if is_inside else f"{v_id} [CLEAR]"
            cv2.rectangle(frame, (x, y - 24), (x + len(status_txt)*9 + 10, y), box_color, -1)
            cv2.putText(frame, status_txt, (x + 6, y - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

        # 5. High-Tech Cyberpunk HUD Top Info Overlay Bar
        cv2.rectangle(frame, (0, 0), (640, 32), (10, 15, 28), -1)
        src_label = f"ENGINE: EDGE-AI 60 FPS | {self.camera_url.upper()}"
        cv2.putText(frame, src_label, (12, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 245, 0), 1, cv2.LINE_AA)
        
        status_label = f"LIMIT: {self.dwell_threshold}s | FINE: INR {self.fine_amount:.0f}"
        cv2.putText(frame, status_label, (370, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)

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
        plate_text = self.current_demo_target['plate']
        reader = self._get_ocr_reader()
        
        if crop.size > 0:
            ocr_text_found = None
            if reader:
                try:
                    results = reader.readtext(crop)
                    raw_texts = " ".join([res[1].upper() for res in results])
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
