from flask import Blueprint, jsonify
from datetime import datetime
import time

from analysis.buffer import data_buffer
from core.config import THINGSBOARD_URL
from core.thingsboard import send_to_thingsboard

from analysis.buffer import INITIAL_SKIP_PERIOD, first_data_received_time, last_analysis_time
from thresholds import ANALYSIS_INTERVAL


status_bp = Blueprint('status', __name__)

@status_bp.route('/status', methods=['GET'])
def status():
    """Endpoint untuk cek status sistem - UPDATED dengan 3 parameter"""
    data_points = data_buffer.get_data()
    
    # Cek warming up berdasarkan data pertama
    current_time = time.time()
    if first_data_received_time is not None:
        elapsed_since_first_data = current_time - first_data_received_time
        warming_up = elapsed_since_first_data < INITIAL_SKIP_PERIOD
        warming_up_remaining = max(0, INITIAL_SKIP_PERIOD - elapsed_since_first_data)
        hardware_connected_duration = elapsed_since_first_data
    else:
        warming_up = False
        warming_up_remaining = 0
        hardware_connected_duration = 0
    
    # Analisis data terbaru
    latest_data = data_points[-1] if data_points else {}
    
    # Status GPS
    gps_status = "active" if latest_data.get('latitude') is not None else "inactive"
    
    # Status sensor ultrasonic
    ultrasonic_active = sum(1 for i in range(1, 9) 
                           if latest_data.get(f'sensor{i}') not in [None, -1])
    
    # Status motion sensor
    motion_status = "inactive"
    if any(latest_data.get(key) is not None for key in ['accelX', 'accelY', 'accelZ']):
        motion_status = "active (shock + vibration)"
    
    # Test ThingsBoard connection
    test_payload = {
        "system_status": "testing", 
        "test_timestamp": datetime.now().isoformat(),
        "parameters": "3 (surface + shock + vibration)",
        "filters": "shock & vibration filters enabled"
    }
    thingsboard_status = "connected" if send_to_thingsboard(test_payload, "status_check") else "disconnected"
    
    return jsonify({
        "system_status": "running",
        "timestamp": datetime.now().isoformat(),
        "warming_up": {
            "is_warming_up": warming_up,
            "remaining_seconds": warming_up_remaining,
            "total_skip_period": INITIAL_SKIP_PERIOD,
            "hardware_connected": first_data_received_time is not None,
            "hardware_connected_duration": hardware_connected_duration,
            "reason": "Hardware sensor stabilization, GPS acquisition, initial data settling"
        },
        "data_buffer": {
            "count": len(data_points),
            "max_duration": ANALYSIS_INTERVAL
        },
        "sensors": {
            "ultrasonic_active": ultrasonic_active,
            "ultrasonic_total": 8,
            "motion_sensor": motion_status,
            "gps": gps_status
        },
        "integrations": {
            "thingsboard_status": thingsboard_status,
            "thingsboard_url": THINGSBOARD_URL
        },
        "parameters": {
            "surface_change": "cm (ultrasonic)",
            "shock": "m/s² (accelerometer filtered)",
            "vibration": "deg/s (gyroscope filtered)",
            "classification_logic": "3 parameters with threshold",
            "filters": "vehicle & slope filters enabled"
        },
        "last_analysis": datetime.fromtimestamp(last_analysis_time).isoformat() if last_analysis_time > 0 else "Never",
        "next_analysis_in": max(0, ANALYSIS_INTERVAL - (time.time() - last_analysis_time))
    })

