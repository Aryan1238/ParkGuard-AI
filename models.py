import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'database.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Violations table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            violation_code TEXT UNIQUE NOT NULL,
            plate_number TEXT NOT NULL,
            vehicle_type TEXT NOT NULL,
            dwell_time_seconds INTEGER NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            snapshot_path TEXT NOT NULL,
            plate_crop_path TEXT,
            fine_amount REAL NOT NULL,
            status TEXT DEFAULT 'Unpaid',
            location TEXT DEFAULT 'Zone A - Main Gate No-Parking Corridor',
            roi_points TEXT
        )
    ''')
    
    # Settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    
    # Reset/Sanitize default settings
    cursor.execute('''
        INSERT OR REPLACE INTO settings (key, value) VALUES 
        ('dwell_threshold', '10'),
        ('fine_amount', '1000'),
        ('camera_url', 'demo'),
        ('roi_polygon', '[[100, 120], [540, 120], [580, 400], [60, 400]]')
    ''')
    
    conn.commit()
    conn.close()

def add_violation(violation_code, plate_number, vehicle_type, dwell_time, snapshot_path, plate_crop_path, fine_amount, roi_points=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO violations 
            (violation_code, plate_number, vehicle_type, dwell_time_seconds, snapshot_path, plate_crop_path, fine_amount, roi_points)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            violation_code, 
            plate_number, 
            vehicle_type, 
            dwell_time, 
            snapshot_path, 
            plate_crop_path, 
            fine_amount,
            json.dumps(roi_points) if roi_points else "[]"
        ))
        conn.commit()
        violation_id = cursor.lastrowid
        conn.close()
        return violation_id
    except sqlite3.IntegrityError:
        conn.close()
        return None

def get_all_violations(limit=100, search_query=None, status_filter=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM violations WHERE 1=1"
    params = []
    
    if search_query:
        query += " AND (plate_number LIKE ? OR violation_code LIKE ?)"
        params.extend([f"%{search_query}%", f"%{search_query}%"])
        
    if status_filter and status_filter != 'All':
        query += " AND status = ?"
        params.append(status_filter)
        
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    violations = [dict(row) for row in rows]
    return violations

def get_violation_by_id(violation_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM violations WHERE id = ?", (violation_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_violation_status(violation_id, status):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE violations SET status = ? WHERE id = ?", (status, violation_id))
    conn.commit()
    conn.close()

def get_setting(key, default=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row['value'] if row else default

def set_setting(key, value):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def get_system_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) as total FROM violations")
    total_violations = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as unpaid FROM violations WHERE status = 'Unpaid'")
    unpaid_violations = cursor.fetchone()['unpaid']
    
    cursor.execute("SELECT SUM(fine_amount) as total_fines FROM violations")
    total_fines_row = cursor.fetchone()['total_fines']
    total_fines = total_fines_row if total_fines_row else 0.0
    
    cursor.execute("SELECT SUM(fine_amount) as collected FROM violations WHERE status = 'Paid'")
    collected_fines_row = cursor.fetchone()['collected']
    collected_fines = collected_fines_row if collected_fines_row else 0.0
    
    conn.close()
    
    return {
        "total_violations": total_violations,
        "unpaid_violations": unpaid_violations,
        "total_fines": total_fines,
        "collected_fines": collected_fines
    }

if __name__ == '__main__':
    init_db()
    print("Database initialized successfully.")
