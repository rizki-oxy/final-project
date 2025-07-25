from flask import Flask, request, jsonify
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import os
import time
import json
import requests
from datetime import datetime, timedelta
import threading
import math
import mysql.connector
from mysql.connector import Error
import io
from PIL import Image
import base64
import pandas as pd
from dotenv import load_dotenv
from thresholds import (
    MIN_DATA_POINTS, ANALYSIS_INTERVAL, EARTH_RADIUS, MAX_GPS_GAP,
    SURFACE_CHANGE_THRESHOLDS, SHOCK_THRESHOLDS, VIBRATION_THRESHOLDS,
    get_surface_change_severity, get_shock_severity, get_vibration_severity,
    classify_damage_three_params, VEHICLE_SHOCK_FILTER, VEHICLE_VIBRATION_FILTER
)
from dashboard import dashboard_bp

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.register_blueprint(dashboard_bp, url_prefix='/dashboard')

# Konfigurasi dari .env
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'road_monitoring'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'charset': 'utf8mb4',
    'autocommit': True
}

# ThingsBoard Configuration
THINGSBOARD_CONFIG = {
    'server': os.getenv('THINGSBOARD_SERVER', '192.168.43.18'),
    'port': os.getenv('THINGSBOARD_PORT', '8081'),
    'access_token': os.getenv('THINGSBOARD_ACCESS_TOKEN', '0939gxC3IXo3uoCIgAED')
}

# Konfigurasi untuk ThingsBoard image compatibility
THINGSBOARD_IMAGE_CONFIG = {
    'max_width': 1024,           # Maksimal lebar untuk ThingsBoard
    'max_height': 768,           # Maksimal tinggi untuk ThingsBoard
    'jpeg_quality': 85,          # Kualitas JPEG yang bagus tapi tidak terlalu besar
    'max_payload_size': 50000,   # 50KB - batas aman untuk ThingsBoard
    'format': 'JPEG'            # Format yang lebih efisien daripada PNG
}

# Build ThingsBoard URL
THINGSBOARD_URL = f"http://{THINGSBOARD_CONFIG['server']}:{THINGSBOARD_CONFIG['port']}/api/v1/{THINGSBOARD_CONFIG['access_token']}/telemetry"

UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'static')
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Data storage untuk analisis 30 detik
class DataBuffer:
    def __init__(self, max_duration=30):
        self.max_duration = max_duration
        self.data_points = []
        self.lock = threading.Lock()
    
    def add_data(self, data):
        with self.lock:
            current_time = datetime.now()
            data['timestamp'] = current_time
            self.data_points.append(data)
            
            # Hapus data yang lebih dari 30 detik
            cutoff_time = current_time - timedelta(seconds=self.max_duration)
            self.data_points = [dp for dp in self.data_points if dp['timestamp'] >= cutoff_time]
    
    def get_data(self):
        with self.lock:
            return list(self.data_points)
    
    def get_data_count(self):
        with self.lock:
            return len(self.data_points)

# Global data buffer
data_buffer = DataBuffer(ANALYSIS_INTERVAL)
last_analysis_time = 0
first_data_received_time = None  # Waktu pertama data diterima dari ESP32
INITIAL_SKIP_PERIOD = 30  # Skip 30 detik pertama setelah data pertama

def get_db_connection():
    """Membuat koneksi ke database MySQL"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        if connection.is_connected():
            return connection
    except Error as e:
        print(f"❌ Error connecting to MySQL: {e}")
        return None

def filter_vehicle_shock(shocks, timestamps=None):
    """
    Filter guncangan kendaraan bermotor dari guncangan jalan rusak
    
    Args:
        shocks (list): List guncangan dalam m/s²
        timestamps (list): List timestamp untuk analisis pola (optional)
    
    Returns:
        dict: Hasil filter dengan guncangan yang sudah dibersihkan
    """
    if not shocks or len(shocks) < 3:
        return {
            'filtered_shocks': shocks,
            'vehicle_shocks': [],
            'road_shocks': shocks,
            'filter_applied': False,
            'stats': {
                'total_count': len(shocks),
                'vehicle_count': 0,
                'road_count': len(shocks)
            }
        }
    
    # Konversi ke numpy array untuk analisis
    shock_array = np.array(shocks)
    
    # Hitung baseline guncangan (guncangan konstan kendaraan)
    baseline = np.median(shock_array)
    
    # Variasi guncangan (guncangan motor cenderung konsisten)
    shock_std = np.std(shock_array)
    shock_mean = np.mean(shock_array)
    
    # Deteksi lonjakan guncangan yang tidak wajar (indikasi jalan rusak)
    vehicle_shocks = []
    road_shocks = []
    
    for i, shock in enumerate(shock_array):
        is_vehicle_shock = False
        
        # Kriteria 1: Guncangan dalam range normal kendaraan
        if (VEHICLE_SHOCK_FILTER['baseline_min'] <= shock <= VEHICLE_SHOCK_FILTER['baseline_max']):
            is_vehicle_shock = True
        
        # Kriteria 2: Guncangan konsisten dengan baseline
        if abs(shock - baseline) <= VEHICLE_SHOCK_FILTER['baseline_tolerance']:
            is_vehicle_shock = True
        
        # Kriteria 3: Analisis pola jika ada data sekitar
        if i > 0 and i < len(shock_array) - 1:
            prev_shock = shock_array[i-1]
            next_shock = shock_array[i+1]
            
            # Guncangan motor cenderung gradual, bukan spike tiba-tiba
            gradient_prev = abs(shock - prev_shock)
            gradient_next = abs(shock - next_shock)
            
            if (gradient_prev <= VEHICLE_SHOCK_FILTER['max_gradient'] and 
                gradient_next <= VEHICLE_SHOCK_FILTER['max_gradient']):
                is_vehicle_shock = True
        
        # Kriteria 4: Override untuk spike tinggi (pasti jalan rusak)
        if shock >= VEHICLE_SHOCK_FILTER['road_spike_threshold']:
            is_vehicle_shock = False
        
        # Kategorikan guncangan
        if is_vehicle_shock:
            vehicle_shocks.append(shock)
        else:
            road_shocks.append(shock)
    
    # Hasil filter
    result = {
        'filtered_shocks': road_shocks,  # Hanya guncangan jalan
        'vehicle_shocks': vehicle_shocks,  # Guncangan kendaraan
        'road_shocks': road_shocks,  # Guncangan jalan rusak
        'filter_applied': True,
        'stats': {
            'total_count': len(shocks),
            'vehicle_count': len(vehicle_shocks),
            'road_count': len(road_shocks),
            'baseline': float(baseline),
            'shock_std': float(shock_std),
            'shock_mean': float(shock_mean)
        }
    }
    
    # Log hasil filter
    print(f"🔧 Filter Guncangan Kendaraan:")
    print(f"   Total: {len(shocks)} → Kendaraan: {len(vehicle_shocks)}, Jalan: {len(road_shocks)}")
    print(f"   Baseline: {baseline:.2f} m/s², Std: {shock_std:.2f} m/s²")
    
    return result

def filter_vehicle_vibration(vibrations, timestamps=None):
    """
    Filter getaran kendaraan bermotor dari getaran jalan rusak
    Untuk gyroscope dalam deg/s dengan filter untuk tanjakan/turunan
    
    Args:
        vibrations (list): List getaran dalam deg/s
        timestamps (list): List timestamp untuk analisis pola (optional)
    
    Returns:
        dict: Hasil filter dengan getaran yang sudah dibersihkan
    """
    if not vibrations or len(vibrations) < 3:
        return {
            'filtered_vibrations': vibrations,
            'vehicle_vibrations': [],
            'slope_vibrations': [],
            'road_vibrations': vibrations,
            'filter_applied': False,
            'stats': {
                'total_count': len(vibrations),
                'vehicle_count': 0,
                'slope_count': 0,
                'road_count': len(vibrations)
            }
        }
    
    # Konversi ke numpy array untuk analisis
    vib_array = np.array(vibrations)
    
    # Hitung baseline getaran
    baseline = np.median(vib_array)
    
    # Variasi getaran
    vib_std = np.std(vib_array)
    vib_mean = np.mean(vib_array)
    
    # Deteksi berbagai jenis getaran
    vehicle_vibrations = []
    slope_vibrations = []
    road_vibrations = []
    
    for i, vib in enumerate(vib_array):
        is_vehicle_vibration = False
        is_slope_vibration = False
        
        # Kriteria 1: Getaran dalam range normal kendaraan
        if (VEHICLE_VIBRATION_FILTER['baseline_min'] <= vib <= VEHICLE_VIBRATION_FILTER['baseline_max']):
            is_vehicle_vibration = True
        
        # Kriteria 2: Getaran konsisten dengan baseline
        if abs(vib - baseline) <= VEHICLE_VIBRATION_FILTER['baseline_tolerance']:
            is_vehicle_vibration = True
        
        # Kriteria 3: Deteksi pola tanjakan/turunan (rotasi konstan dalam satu arah)
        if i >= 2 and i < len(vib_array) - 2:
            # Ambil 5 point sekitar untuk analisis tren
            window = vib_array[i-2:i+3]
            
            # Cek apakah ada tren konstan (tanjakan/turunan)
            if len(window) >= 5:
                # Hitung tren linear
                trend = np.polyfit(range(len(window)), window, 1)[0]
                
                # Jika tren konstan dan dalam range slope
                if abs(trend) <= VEHICLE_VIBRATION_FILTER['slope_trend_threshold']:
                    # Cek apakah amplitudo dalam range slope
                    if abs(vib) <= VEHICLE_VIBRATION_FILTER['slope_amplitude_threshold']:
                        is_slope_vibration = True
        
        # Kriteria 4: Analisis gradien untuk getaran motor
        if i > 0 and i < len(vib_array) - 1:
            prev_vib = vib_array[i-1]
            next_vib = vib_array[i+1]
            
            # Getaran motor cenderung gradual
            gradient_prev = abs(vib - prev_vib)
            gradient_next = abs(vib - next_vib)
            
            if (gradient_prev <= VEHICLE_VIBRATION_FILTER['max_gradient'] and 
                gradient_next <= VEHICLE_VIBRATION_FILTER['max_gradient']):
                is_vehicle_vibration = True
        
        # Kriteria 5: Override untuk spike tinggi (pasti jalan rusak)
        if abs(vib) >= VEHICLE_VIBRATION_FILTER['road_spike_threshold']:
            is_vehicle_vibration = False
            is_slope_vibration = False
        
        # Kategorikan getaran
        if is_slope_vibration:
            slope_vibrations.append(vib)
        elif is_vehicle_vibration:
            vehicle_vibrations.append(vib)
        else:
            road_vibrations.append(vib)
    
    # Hasil filter
    result = {
        'filtered_vibrations': road_vibrations,  # Hanya getaran jalan
        'vehicle_vibrations': vehicle_vibrations,  # Getaran kendaraan
        'slope_vibrations': slope_vibrations,  # Getaran tanjakan/turunan
        'road_vibrations': road_vibrations,  # Getaran jalan rusak
        'filter_applied': True,
        'stats': {
            'total_count': len(vibrations),
            'vehicle_count': len(vehicle_vibrations),
            'slope_count': len(slope_vibrations),
            'road_count': len(road_vibrations),
            'baseline': float(baseline),
            'vib_std': float(vib_std),
            'vib_mean': float(vib_mean)
        }
    }
    
    # Log hasil filter
    print(f"🔧 Filter Getaran Gyroscope:")
    print(f"   Total: {len(vibrations)} → Kendaraan: {len(vehicle_vibrations)}, Slope: {len(slope_vibrations)}, Jalan: {len(road_vibrations)}")
    print(f"   Baseline: {baseline:.2f} deg/s, Std: {vib_std:.2f} deg/s")
    
    return result

def analyze_speed_data(data_points):
    """Analisis data kecepatan untuk tracking dan informasi saja (bukan klasifikasi)"""
    speeds = []
    
    for data in data_points:
        speed = data.get('speed')  # km/h dari GPS
        if speed is not None and speed >= 0:
            speeds.append(speed)
    
    if not speeds:
        return {
            'speeds': speeds,
            'avg_speed': 0,
            'max_speed': 0,
            'min_speed': 0,
            'speed_range': "0 km/h",
            'count': 0,
            'has_speed_data': False
        }
    
    avg_speed = sum(speeds) / len(speeds)
    max_speed = max(speeds)
    min_speed = min(speeds)
    
    # Format range kecepatan
    if min_speed == max_speed:
        speed_range = f"~{avg_speed:.1f} km/h"
    else:
        speed_range = f"{min_speed:.1f} - {max_speed:.1f} km/h"
    
    return {
        'speeds': speeds,
        'avg_speed': avg_speed,
        'max_speed': max_speed,
        'min_speed': min_speed,
        'speed_range': speed_range,
        'count': len(speeds),
        'has_speed_data': True
    }

def send_to_thingsboard(payload_data, data_type="analysis"):
    """Mengirim data ke ThingsBoard via HTTP"""
    try:
        # Add prefix to identify data source
        prefixed_payload = {}
        for key, value in payload_data.items():
            prefixed_payload[f"fls_{key}"] = value
        
        # Add metadata
        prefixed_payload["fls_data_source"] = "flask_server"
        prefixed_payload["fls_data_type"] = data_type
        prefixed_payload["fls_timestamp"] = datetime.now().isoformat()
        
        headers = {
            'Content-Type': 'application/json'
        }
        
        response = requests.post(
            THINGSBOARD_URL, 
            json=prefixed_payload, 
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            print(f"✅ ThingsBoard: {data_type} data sent successfully")
            return True
        else:
            print(f"⚠️ ThingsBoard: HTTP {response.status_code} - {response.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ ThingsBoard connection error: {e}")
        return False
    except Exception as e:
        print(f"❌ ThingsBoard error: {e}")
        return False

def save_sensor_data(data):
    """Menyimpan data sensor mentah ke database - UPDATED untuk shock dan vibration"""
    connection = get_db_connection()
    if not connection:
        return False
    
    try:
        cursor = connection.cursor()
        
        insert_query = """
        INSERT INTO sensor_data (
            timestamp, 
            sensor1_distance, sensor2_distance, sensor3_distance, sensor4_distance,
            sensor5_distance, sensor6_distance, sensor7_distance, sensor8_distance,
            accel_x, accel_y, accel_z, accel_magnitude,
            accel_x_ms2, accel_y_ms2, accel_z_ms2, accel_magnitude_ms2,
            gyro_x, gyro_y, gyro_z, rotation_magnitude,
            gyro_x_dps, gyro_y_dps, gyro_z_dps, rotation_magnitude_dps,
            shock_magnitude, vibration_magnitude,
            latitude, longitude, speed, satellites
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s
        )
        """
        
        # Calculate magnitudes dari raw data jika belum ada
        accel_magnitude = None
        if all(data.get(key) is not None for key in ['accelX', 'accelY', 'accelZ']):
            accel_magnitude = math.sqrt(data['accelX']**2 + data['accelY']**2 + data['accelZ']**2)
        
        rotation_magnitude = None
        if all(data.get(key) is not None for key in ['gyroX', 'gyroY', 'gyroZ']):
            rotation_magnitude = math.sqrt(
                (data['gyroX']/131.0)**2 + (data['gyroY']/131.0)**2 + (data['gyroZ']/131.0)**2
            )
        
        # Calculate converted magnitudes
        accel_magnitude_ms2 = None
        if all(data.get(key) is not None for key in ['accelX_ms2', 'accelY_ms2', 'accelZ_ms2']):
            accel_magnitude_ms2 = math.sqrt(
                data['accelX_ms2']**2 + data['accelY_ms2']**2 + data['accelZ_ms2']**2
            )
        elif data.get('accel_magnitude_ms2') is not None:
            accel_magnitude_ms2 = data['accel_magnitude_ms2']
        
        rotation_magnitude_dps = None
        if all(data.get(key) is not None for key in ['gyroX_dps', 'gyroY_dps', 'gyroZ_dps']):
            rotation_magnitude_dps = math.sqrt(
                data['gyroX_dps']**2 + data['gyroY_dps']**2 + data['gyroZ_dps']**2
            )
        elif data.get('rotation_magnitude_dps') is not None:
            rotation_magnitude_dps = data['rotation_magnitude_dps']
        
        insert_data = (
            datetime.now(),
            # Ultrasonic data
            data.get('sensor1'), data.get('sensor2'), data.get('sensor3'), data.get('sensor4'),
            data.get('sensor5'), data.get('sensor6'), data.get('sensor7'), data.get('sensor8'),
            # Raw accelerometer data
            data.get('accelX'), data.get('accelY'), data.get('accelZ'), accel_magnitude,
            # Converted accelerometer data (m/s²)
            data.get('accelX_ms2'), data.get('accelY_ms2'), data.get('accelZ_ms2'), accel_magnitude_ms2,
            # Raw gyroscope data  
            data.get('gyroX'), data.get('gyroY'), data.get('gyroZ'), rotation_magnitude,
            # Converted gyroscope data (deg/s)
            data.get('gyroX_dps'), data.get('gyroY_dps'), data.get('gyroZ_dps'), rotation_magnitude_dps,
            # Shock & Vibration magnitude dari ESP32
            data.get('shock_magnitude'),      # m/s² (dari accelerometer)
            data.get('vibration_magnitude'),  # deg/s (dari gyroscope)
            # GPS data
            data.get('latitude'), data.get('longitude'), data.get('speed'), data.get('satellites')
        )
        
        cursor.execute(insert_query, insert_data)
        connection.commit()
        
        shock_val = data.get('shock_magnitude', 0)
        vibration_val = data.get('vibration_magnitude', 0)
        print(f"✅ Raw sensor data saved to MySQL (ID: {cursor.lastrowid})")
        print(f"📊 Shock: {shock_val:.2f} m/s², Vibration: {vibration_val:.2f} deg/s")
        return True
        
    except Error as e:
        print(f"❌ Error saving sensor data: {e}")
        return False
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def calculate_distance(lat1, lon1, lat2, lon2):
    """Menghitung jarak antara dua koordinat GPS dalam meter"""
    if any(coord is None for coord in [lat1, lon1, lat2, lon2]):
        return 0
    
    # Convert to radians
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    return EARTH_RADIUS * c

def analyze_surface_changes(data_points):
    """Analisis perubahan permukaan jalan dari data ultrasonic"""
    changes = []
    
    for i in range(1, len(data_points)):
        prev_data = data_points[i-1]
        curr_data = data_points[i]
        
        for sensor_idx in range(1, 9):
            sensor_key = f'sensor{sensor_idx}'
            prev_val = prev_data.get(sensor_key)
            curr_val = curr_data.get(sensor_key)
            
            if prev_val is not None and curr_val is not None and prev_val != -1 and curr_val != -1:
                change = curr_val - prev_val  # Bisa positif atau negatif
                if abs(change) >= SURFACE_CHANGE_THRESHOLDS['minor']:
                    changes.append(change)  # Simpan dengan tanda asli
    
    return {
        'changes': changes,
        'max_change': max([abs(c) for c in changes]) if changes else 0,  # ABSOLUT untuk klasifikasi
        'avg_change': sum([abs(c) for c in changes]) / len(changes) if changes else 0,  # ABSOLUT
        'max_positive': max([c for c in changes if c > 0]) if any(c > 0 for c in changes) else 0,  # Lubang terdalam
        'max_negative': min([c for c in changes if c < 0]) if any(c < 0 for c in changes) else 0,  # Gundukan tertinggi
        'count': len(changes)
    }

def analyze_shocks(data_points):
    """Analisis guncangan dari shock_magnitude ESP32 (accelerometer)"""
    shocks = []
    
    for data in data_points:
        # Gunakan shock_magnitude dari ESP32 langsung
        shock = data.get('shock_magnitude')
        
        if shock is not None and shock >= SHOCK_THRESHOLDS['light']:
            shocks.append(shock)
    
    # Terapkan filter kendaraan pada data shock
    if shocks:
        filter_result = filter_vehicle_shock(shocks)
        
        # Gunakan guncangan yang sudah difilter (hanya guncangan jalan)
        filtered_shocks = filter_result['filtered_shocks']
        
        return {
            'shocks': filtered_shocks,
            'max_shock': max(filtered_shocks) if filtered_shocks else 0,
            'avg_shock': sum(filtered_shocks) / len(filtered_shocks) if filtered_shocks else 0,
            'count': len(filtered_shocks),
            'filter_info': {
                'original_count': len(shocks),
                'filtered_count': len(filtered_shocks),
                'vehicle_count': filter_result['stats']['vehicle_count'],
                'filter_applied': filter_result['filter_applied'],
                'baseline': filter_result['stats'].get('baseline', 0),
                'shock_std': filter_result['stats'].get('shock_std', 0)
            }
        }
    
    return {
        'shocks': shocks,
        'max_shock': max(shocks) if shocks else 0,
        'avg_shock': sum(shocks) / len(shocks) if shocks else 0,
        'count': len(shocks),
        'filter_info': {
            'original_count': 0,
            'filtered_count': 0,
            'vehicle_count': 0,
            'filter_applied': False,
            'baseline': 0,
            'shock_std': 0
        }
    }

def analyze_vibrations(data_points):
    """Analisis getaran dari vibration_magnitude ESP32 (gyroscope)"""
    vibrations = []
    
    for data in data_points:
        # Gunakan vibration_magnitude dari ESP32 langsung
        vibration = data.get('vibration_magnitude')
        
        if vibration is not None and abs(vibration) >= VIBRATION_THRESHOLDS['light']:
            vibrations.append(abs(vibration))
    
    # Terapkan filter kendaraan dan slope pada data vibration
    if vibrations:
        filter_result = filter_vehicle_vibration(vibrations)
        
        # Gunakan getaran yang sudah difilter (hanya getaran jalan)
        filtered_vibrations = filter_result['filtered_vibrations']
        
        return {
            'vibrations': filtered_vibrations,
            'max_vibration': max(filtered_vibrations) if filtered_vibrations else 0,
            'avg_vibration': sum(filtered_vibrations) / len(filtered_vibrations) if filtered_vibrations else 0,
            'count': len(filtered_vibrations),
            'filter_info': {
                'original_count': len(vibrations),
                'filtered_count': len(filtered_vibrations),
                'vehicle_count': filter_result['stats']['vehicle_count'],
                'slope_count': filter_result['stats']['slope_count'],
                'filter_applied': filter_result['filter_applied'],
                'baseline': filter_result['stats'].get('baseline', 0),
                'vib_std': filter_result['stats'].get('vib_std', 0)
            }
        }
    
    return {
        'vibrations': vibrations,
        'max_vibration': max(vibrations) if vibrations else 0,
        'avg_vibration': sum(vibrations) / len(vibrations) if vibrations else 0,
        'count': len(vibrations),
        'filter_info': {
            'original_count': 0,
            'filtered_count': 0,
            'vehicle_count': 0,
            'slope_count': 0,
            'filter_applied': False,
            'baseline': 0,
            'vib_std': 0
        }
    }

def process_realtime_shock(data):
    """Memproses guncangan real-time dari shock_magnitude ESP32"""
    shock = data.get('shock_magnitude')
    
    if shock is not None:
        # Terapkan filter guncangan kendaraan pada single data point
        is_vehicle_shock = (
            VEHICLE_SHOCK_FILTER['baseline_min'] <= shock <= VEHICLE_SHOCK_FILTER['baseline_max']
        )
        if shock >= VEHICLE_SHOCK_FILTER['road_spike_threshold']:
            is_vehicle_shock = False
        
        if not is_vehicle_shock:
            return {
                'filtered_shock': shock,
                'is_road_shock': True
            }
        else:
            return {
                'filtered_shock': 0,
                'is_road_shock': False
            }
    return None

def process_realtime_vibration(data):
    """Memproses getaran real-time dari vibration_magnitude ESP32"""
    vibration = data.get('vibration_magnitude')
    
    if vibration is not None:
        abs_vibration = abs(vibration)
        
        # Terapkan filter getaran kendaraan pada single data point
        is_vehicle_vibration = (
            VEHICLE_VIBRATION_FILTER['baseline_min'] <= abs_vibration <= VEHICLE_VIBRATION_FILTER['baseline_max']
        )
        if abs_vibration >= VEHICLE_VIBRATION_FILTER['road_spike_threshold']:
            is_vehicle_vibration = False
        
        if not is_vehicle_vibration:
            return {
                'filtered_vibration': abs_vibration,
                'is_road_vibration': True
            }
        else:
            return {
                'filtered_vibration': 0,
                'is_road_vibration': False
            }
    return None

def calculate_damage_length(data_points, has_damage=False):
    """Menghitung panjang kerusakan berdasarkan data GPS - hanya jika ada kerusakan"""
    if not has_damage:
        return 0
    
    gps_points = []
    
    for data in data_points:
        if data.get('latitude') is not None and data.get('longitude') is not None:
            gps_points.append((data['latitude'], data['longitude']))
    
    if len(gps_points) < 2:
        return 0
    
    total_distance = 0
    for i in range(1, len(gps_points)):
        distance = calculate_distance(
            gps_points[i-1][0], gps_points[i-1][1],
            gps_points[i][0], gps_points[i][1]
        )
        
        # Skip jika jarak terlalu jauh (mungkin error GPS)
        if distance <= MAX_GPS_GAP:
            total_distance += distance
    
    return total_distance

def detect_anomalies(data_points):
    """Deteksi semua anomali dalam periode analisis"""
    anomalies = []
    
    # Analisis perubahan permukaan
    surface_analysis = analyze_surface_changes(data_points)
    if surface_analysis['count'] > 0:
        anomalies.append({
            'type': 'surface_change',
            'details': surface_analysis,
            'severity': get_surface_change_severity(surface_analysis['max_change'])
        })
    
    # Analisis guncangan (m/s²) - dengan filter kendaraan
    shock_analysis = analyze_shocks(data_points)
    if shock_analysis['count'] > 0:
        anomalies.append({
            'type': 'shock',
            'details': shock_analysis,
            'severity': get_shock_severity(shock_analysis['max_shock'])
        })
    
    # Analisis getaran (deg/s) - dengan filter kendaraan dan slope
    vibration_analysis = analyze_vibrations(data_points)
    if vibration_analysis['count'] > 0:
        anomalies.append({
            'type': 'vibration',
            'details': vibration_analysis,
            'severity': get_vibration_severity(vibration_analysis['max_vibration'])
        })
    
    return anomalies

def create_analysis_visualization(analysis_data):
    """Membuat visualisasi analisis untuk disimpan - hanya jika ada kerusakan"""
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
    
    # Buat time axis dalam detik (0-30 detik)
    analysis_duration = 30
    
    # 1. Data perubahan permukaan
    if analysis_data['surface_analysis']['changes']:
        num_changes = len(analysis_data['surface_analysis']['changes'])
        time_points = [i * (analysis_duration / (num_changes - 1)) if num_changes > 1 else 0 
                      for i in range(num_changes)]
        
        negative_changes = [-change for change in analysis_data['surface_analysis']['changes']]
        ax1.plot(time_points, negative_changes, 
                marker='o', linewidth=2, markersize=4, color='orange', alpha=0.8)
        ax1.axhline(y=-analysis_data['surface_analysis']['max_change'], 
                color='red', linestyle='--', alpha=0.7,
                label=f'Max Surface Change: {analysis_data["surface_analysis"]["max_change"]:.1f}cm')
        ax1.axhline(y=-analysis_data['surface_analysis']['avg_change'], 
                color='blue', linestyle=':', alpha=0.7,
                label=f'Avg Surface Change: {analysis_data["surface_analysis"]["avg_change"]:.1f}cm')
        
        ax1.fill_between(time_points, negative_changes, 
                alpha=0.3, color='orange')
        ax1.set_title('Perubahan Permukaan Jalan')
        ax1.set_xlabel('Waktu (detik)')
        ax1.set_ylabel('Kedalaman Lubang / Perubahan (cm)')
        ax1.set_xlim(0, 30)
        ax1.legend()
        ax1.grid(True, alpha=0.3)
    else:
        ax1.text(0.5, 0.5, 'Tidak ada perubahan\npermukaan signifikan', 
                ha='center', va='center', transform=ax1.transAxes, fontsize=14)
        ax1.set_title('Perubahan Permukaan Jalan')
        ax1.set_xlabel('Waktu (detik)')
        ax1.set_xlim(0, 30)
        ax1.grid(True, alpha=0.3)
        
        def format_y_label(value, pos):
            return f'{abs(value):.0f}'
        
        from matplotlib.ticker import FuncFormatter
        ax1.yaxis.set_major_formatter(FuncFormatter(format_y_label))
    
    # 2. Data guncangan (shock) - m/s²
    if analysis_data['shock_analysis']['shocks']:
        num_shocks = len(analysis_data['shock_analysis']['shocks'])
        time_points = [i * (analysis_duration / (num_shocks - 1)) if num_shocks > 1 else 0 
                      for i in range(num_shocks)]
        
        ax2.plot(time_points, analysis_data['shock_analysis']['shocks'], 
                marker='s', linewidth=2, markersize=4, color='red', alpha=0.8)
        ax2.axhline(y=analysis_data['shock_analysis']['max_shock'], 
                   color='darkred', linestyle='--', alpha=0.7,
                   label=f'Max: {analysis_data["shock_analysis"]["max_shock"]:.1f}m/s²')
        ax2.axhline(y=analysis_data['shock_analysis']['avg_shock'], 
                   color='blue', linestyle=':', alpha=0.7,
                   label=f'Avg: {analysis_data["shock_analysis"]["avg_shock"]:.1f}m/s²')
        
        ax2.fill_between(time_points, analysis_data['shock_analysis']['shocks'], 
                        alpha=0.3, color='red')
        
        # Tambahkan info filter
        filter_info = analysis_data['shock_analysis'].get('filter_info', {})
        title = f'Guncangan Jalan (Filtered: {filter_info.get("filtered_count", 0)}/{filter_info.get("original_count", 0)})'
        ax2.set_title(title)
        ax2.set_xlabel('Waktu (detik)')
        ax2.set_ylabel('Guncangan (m/s²)')
        ax2.set_xlim(0, 30)
        ax2.legend()
        ax2.grid(True, alpha=0.3)
    else:
        ax2.text(0.5, 0.5, 'Tidak ada guncangan\njalan rusak terdeteksi', 
                ha='center', va='center', transform=ax2.transAxes, fontsize=14)
        ax2.set_title('Guncangan Jalan (Filtered)')
        ax2.set_xlabel('Waktu (detik)')
        ax2.set_xlim(0, 30)
        ax2.grid(True, alpha=0.3)
    
    # 3. Data getaran (vibration) - deg/s
    if analysis_data['vibration_analysis']['vibrations']:
        num_vibrations = len(analysis_data['vibration_analysis']['vibrations'])
        time_points = [i * (analysis_duration / (num_vibrations - 1)) if num_vibrations > 1 else 0 
                      for i in range(num_vibrations)]
        
        ax3.plot(time_points, analysis_data['vibration_analysis']['vibrations'], 
                marker='^', linewidth=2, markersize=4, color='purple', alpha=0.8)
        ax3.axhline(y=analysis_data['vibration_analysis']['max_vibration'], 
                   color='darkmagenta', linestyle='--', alpha=0.7,
                   label=f'Max: {analysis_data["vibration_analysis"]["max_vibration"]:.1f}deg/s')
        ax3.axhline(y=analysis_data['vibration_analysis']['avg_vibration'], 
                   color='blue', linestyle=':', alpha=0.7,
                   label=f'Avg: {analysis_data["vibration_analysis"]["avg_vibration"]:.1f}deg/s')
        
        ax3.fill_between(time_points, analysis_data['vibration_analysis']['vibrations'], 
                        alpha=0.3, color='purple')
        
        # Tambahkan info filter
        filter_info = analysis_data['vibration_analysis'].get('filter_info', {})
        title = f'Getaran Jalan (Filtered: {filter_info.get("filtered_count", 0)}/{filter_info.get("original_count", 0)})'
        ax3.set_title(title)
        ax3.set_xlabel('Waktu (detik)')
        ax3.set_ylabel('Getaran (deg/s)')
        ax3.set_xlim(0, 30)
        ax3.legend()
        ax3.grid(True, alpha=0.3)
    else:
        ax3.text(0.5, 0.5, 'Tidak ada getaran\njalan rusak terdeteksi', 
                ha='center', va='center', transform=ax3.transAxes, fontsize=14)
        ax3.set_title('Getaran Jalan (Filtered)')
        ax3.set_xlabel('Waktu (detik)')
        ax3.set_xlim(0, 30)
        ax3.grid(True, alpha=0.3)
    
    # 4. Info lokasi dan klasifikasi
    info_text = f"KLASIFIKASI KERUSAKAN:\n"
    info_text += f"   {analysis_data['damage_classification'].upper().replace('_', ' ')}\n\n"
    
    info_text += f"PANJANG KERUSAKAN:\n"
    info_text += f"   {analysis_data['damage_length']:.1f} meter\n\n"
    
    info_text += f"PARAMETER UTAMA:\n"
    info_text += f"   Surface: {analysis_data['surface_analysis']['max_change']:.1f}cm\n"
    info_text += f"   Shock: {analysis_data['shock_analysis']['max_shock']:.1f}m/s²\n"
    info_text += f"   Vibration: {analysis_data['vibration_analysis']['max_vibration']:.1f}deg/s\n\n"
    
    # TAMBAH SPEED INFO:
    info_text += f"ESTIMASI KECEPATAN:\n"
    if analysis_data['speed_analysis']['has_speed_data']:
        info_text += f"   {analysis_data['speed_analysis']['speed_range']}\n"
        info_text += f"   Rata-rata: {analysis_data['speed_analysis']['avg_speed']:.1f} km/h\n"
        info_text += f"   Data GPS: {analysis_data['speed_analysis']['count']} points\n\n"
    else:
        info_text += f"   Data GPS tidak tersedia\n\n"
    
    # Tambahkan info lokasi
    if analysis_data['start_location']:
        info_text += f"LOKASI AWAL:\n"
        info_text += f"   Lat: {analysis_data['start_location'][0]:.6f}\n"
        info_text += f"   Lng: {analysis_data['start_location'][1]:.6f}\n\n"
    
    if analysis_data['end_location']:
        info_text += f"LOKASI AKHIR:\n"
        info_text += f"   Lat: {analysis_data['end_location'][0]:.6f}\n"
        info_text += f"   Lng: {analysis_data['end_location'][1]:.6f}"
    
    # Color based on classification
    color_map = {
        'rusak_ringan': 'lightgreen',
        'rusak_sedang': 'yellow', 
        'rusak_berat': 'lightcoral'
    }
    bg_color = color_map.get(analysis_data['damage_classification'], 'lightgray')
    
    ax4.text(0.05, 0.95, info_text, ha='left', va='top', transform=ax4.transAxes, 
            fontsize=9, bbox=dict(boxstyle="round,pad=0.5", facecolor=bg_color, alpha=0.8))
    ax4.set_title('Info Kerusakan (3 Parameter)')
    ax4.axis('off')
    
    plt.tight_layout()
    
    # Save dengan timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'road_damage_{timestamp}.png'
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    plt.savefig(filepath, dpi=100, bbox_inches='tight')
    plt.close()
    
    return filepath, filename

def save_analysis_to_database(analysis_data, image_path=None, image_filename=None):
    """Menyimpan hasil analisis ke database - FIXED: database tetap PNG asli"""
    
    # Cek apakah ada kerusakan
    if not analysis_data.get('has_damage', False):
        print("💡 Jalan dalam kondisi baik - Tidak ada data yang disimpan ke MySQL")
        return True
    
    connection = get_db_connection()
    if not connection:
        print("❌ Database connection failed")
        return False
    
    try:
        cursor = connection.cursor()
        
        # FIXED: Database tetap simpan PNG asli (tidak dikompres)
        image_data = None
        if image_path and os.path.exists(image_path):
            print(f"📸 Saving original PNG to database: {image_filename}")
            
            # Simpan PNG asli ke database
            with open(image_path, 'rb') as img_file:
                image_data = base64.b64encode(img_file.read()).decode('utf-8')
            
            original_size = len(image_data)
            print(f"💾 Original PNG saved to database: {original_size} bytes ({original_size/1024:.1f}KB)")
            print(f"📡 ThingsBoard akan menerima versi terkompresi saat dikirim")
        
        insert_query = """
        INSERT INTO road_damage_analysis (
            analysis_timestamp, start_latitude, start_longitude, end_latitude, end_longitude,
            damage_classification, damage_length, 
            surface_change_max, surface_change_avg, surface_change_count,
            shock_max, shock_avg, shock_count,
            vibration_max, vibration_avg, vibration_count, 
            speed_min, speed_max, speed_avg, speed_range, speed_data_count,
            anomalies, analysis_image, image_filename
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 
            %s, %s, %s, %s, %s, %s, %s, %s
        )
        """
        
        start_lat = analysis_data['start_location'][0] if analysis_data['start_location'] else None
        start_lng = analysis_data['start_location'][1] if analysis_data['start_location'] else None
        end_lat = analysis_data['end_location'][0] if analysis_data['end_location'] else None
        end_lng = analysis_data['end_location'][1] if analysis_data['end_location'] else None
        
        insert_data = (
            datetime.now(),
            start_lat, start_lng, end_lat, end_lng,
            analysis_data['damage_classification'],
            analysis_data['damage_length'],
            analysis_data['surface_analysis']['max_change'],
            analysis_data['surface_analysis']['avg_change'],
            analysis_data['surface_analysis']['count'],
            analysis_data['shock_analysis']['max_shock'],
            analysis_data['shock_analysis']['avg_shock'],
            analysis_data['shock_analysis']['count'],
            analysis_data['vibration_analysis']['max_vibration'],
            analysis_data['vibration_analysis']['avg_vibration'],
            analysis_data['vibration_analysis']['count'],
            analysis_data['speed_analysis']['min_speed'] if analysis_data['speed_analysis']['has_speed_data'] else None,
            analysis_data['speed_analysis']['max_speed'] if analysis_data['speed_analysis']['has_speed_data'] else None,
            analysis_data['speed_analysis']['avg_speed'] if analysis_data['speed_analysis']['has_speed_data'] else None,
            analysis_data['speed_analysis']['speed_range'] if analysis_data['speed_analysis']['has_speed_data'] else None,
            analysis_data['speed_analysis']['count'],
            json.dumps(analysis_data['anomalies']),
            image_data,  # PNG base64 asli (tidak dikompres)
            image_filename
        )
        
        cursor.execute(insert_query, insert_data)
        connection.commit()
        
        analysis_id = cursor.lastrowid
        
        print(f"✅ Kerusakan berhasil disimpan ke MySQL: {analysis_data['damage_classification']} (ID: {analysis_id})")
        print(f"📊 Surface: {analysis_data['surface_analysis']['max_change']:.2f}cm")
        print(f"📊 Shock: {analysis_data['shock_analysis']['max_shock']:.2f}m/s² (filtered)")
        print(f"📊 Vibration: {analysis_data['vibration_analysis']['max_vibration']:.2f}deg/s (filtered)")
        print(f"💾 Database: PNG asli tersimpan")
        print(f"📡 ThingsBoard: Akan dikirim versi JPEG terkompresi")
        
        # Send to ThingsBoard dengan gambar dalam thread terpisah
        threading.Thread(
            target=send_analysis_with_image_to_thingsboard, 
            args=(analysis_id,),
            daemon=True
        ).start()
        
        return True
        
    except Error as e:
        print(f"❌ Error saving analysis: {e}")
        return False
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def perform_30s_analysis():
    """Melakukan analisis komprehensif setiap 30 detik dengan 3 parameter - SKIP 30 detik pertama"""
    global last_analysis_time
    
    current_time = time.time()
    
    # CEK APAKAH SUDAH MENERIMA DATA DARI ESP32
    if first_data_received_time is None:
        print(f"⏳ Belum menerima data dari ESP32 - Menunggu koneksi hardware...")
        return
    
    # CEK APAKAH MASIH DALAM PERIODE SKIP 30 DETIK SETELAH DATA PERTAMA
    elapsed_since_first_data = current_time - first_data_received_time
    if elapsed_since_first_data < INITIAL_SKIP_PERIOD:
        remaining_time = INITIAL_SKIP_PERIOD - elapsed_since_first_data
        print(f"⏳ Skipping analysis - Hardware warming up: {remaining_time:.1f}s remaining")
        print(f"💡 Reason: Sensor stabilization, GPS acquisition, initial data settling")
        return
    
    data_points = data_buffer.get_data()
    
    if len(data_points) < MIN_DATA_POINTS:
        print(f"⏳ Data tidak cukup untuk analisis: {len(data_points)}/{MIN_DATA_POINTS}")
        return
    
    print(f"🔍 Memulai analisis 30 detik dengan {len(data_points)} data points...")
    print(f"📊 Menggunakan 3 parameter: Surface + Shock + Vibration")
    print(f"✅ Hardware sudah stabil - Warming up period selesai ({elapsed_since_first_data:.1f}s since first data)")
    
    start_time = time.time()
    
    # Analisis berbagai aspek dengan filter
    surface_analysis = analyze_surface_changes(data_points)
    shock_analysis = analyze_shocks(data_points)        # m/s² dengan filter
    vibration_analysis = analyze_vibrations(data_points) # deg/s dengan filter
    speed_analysis = analyze_speed_data(data_points)
    
    print(f"📊 Speed Info:")
    if speed_analysis['has_speed_data']:
        print(f"   - Speed Range: {speed_analysis['speed_range']}")
        print(f"   - Average: {speed_analysis['avg_speed']:.1f} km/h")
        print(f"   - Data Points: {speed_analysis['count']}")
    else:
        print(f"   - No GPS speed data available")
    
    anomalies = detect_anomalies(data_points)
    
    # Tentukan lokasi awal dan akhir
    start_location = None
    end_location = None
    
    for data in data_points:
        if data.get('latitude') is not None and data.get('longitude') is not None:
            if start_location is None:
                start_location = (data['latitude'], data['longitude'])
            end_location = (data['latitude'], data['longitude'])
    
    # Klasifikasi dengan 3 parameter
    max_surface_change = surface_analysis['max_change']
    max_shock = shock_analysis['max_shock']
    max_vibration = vibration_analysis['max_vibration']
    
    damage_classification = classify_damage_three_params(max_surface_change, max_shock, max_vibration)
    
    # Hitung panjang kerusakan jika ada kerusakan
    has_damage = damage_classification != 'baik'
    damage_length = calculate_damage_length(data_points, has_damage)
    
    print(f"📊 Parameter Klasifikasi (3 Parameter dengan Filter):")
    print(f"   - Surface Change Max: {max_surface_change:.2f} cm")
    print(f"   - Shock Max: {max_shock:.2f} m/s² (FILTERED)")
    print(f"   - Vibration Max: {max_vibration:.2f} deg/s (FILTERED)")
    print(f"   - Hasil Klasifikasi: {damage_classification.upper().replace('_', ' ')}")
    print(f"   - Panjang Kerusakan: {damage_length:.1f}m")
    
    # HANYA PROSES LEBIH LANJUT JIKA ADA KERUSAKAN
    if has_damage:
        print(f"⚠️  KERUSAKAN TERDETEKSI - Memproses dan menyimpan data...")
        
        # Compile analysis data
        analysis_data = {
            'surface_analysis': surface_analysis,
            'shock_analysis': shock_analysis,
            'vibration_analysis': vibration_analysis,
            'speed_analysis': speed_analysis,
            'damage_length': damage_length,
            'anomalies': anomalies,
            'damage_classification': damage_classification,
            'start_location': start_location,
            'end_location': end_location,
            'has_damage': has_damage
        }
        
        # Buat dan simpan visualisasi
        image_path = None
        image_filename = None
        
        try:
            image_path, image_filename = create_analysis_visualization(analysis_data)
            print(f"📸 Gambar analisis dibuat: {image_filename}")
        except Exception as e:
            print(f"❌ Error membuat visualisasi: {e}")
        
        # Simpan ke database dan kirim ke ThingsBoard
        try:
            save_analysis_to_database(analysis_data, image_path, image_filename)
            print(f"✅ Analisis kerusakan tersimpan - Klasifikasi: {damage_classification}")
            print(f"📏 Panjang kerusakan: {damage_length:.1f}m")
            print(f"💾 Data dikirim ke MySQL dan ThingsBoard")
            
        except Exception as e:
            print(f"❌ Error menyimpan analisis: {e}")
    
    else:
        print(f"✅ JALAN DALAM KONDISI BAIK - Tidak ada data yang disimpan")
        print(f"💡 Resource saved: No MySQL insert, no ThingsBoard data, no image generated")
        print(f"📊 Threshold tidak terpenuhi untuk ketiga parameter")
    
    last_analysis_time = current_time

@app.route('/multisensor', methods=['POST'])
def multisensor():
    """Endpoint untuk menerima data sensor dari ESP32 - FIXED Warming Up Period"""
    global last_analysis_time, first_data_received_time
    
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data received"}), 400
    
    current_time = time.time()
    
    # SET WAKTU PERTAMA MENERIMA DATA
    if first_data_received_time is None:
        first_data_received_time = current_time
        print(f"🔌 ESP32 connected! Hardware warming up started ({INITIAL_SKIP_PERIOD}s)")
        print(f"💡 During warming up: NO data save, NO buffer collection, NO analysis")
    
    # CEK WARMING UP SEBELUM SEMUA OPERASI
    elapsed_since_first_data = current_time - first_data_received_time
    
    if elapsed_since_first_data < INITIAL_SKIP_PERIOD:
        remaining_time = INITIAL_SKIP_PERIOD - elapsed_since_first_data
        print(f"⏳ Warming up: {remaining_time:.1f}s remaining - SKIPPING all data operations")
        
        # Return immediately - NO data save, NO buffer, NO processing
        return jsonify({
            "status": "warming_up",
            "message": "Hardware warming up - data not saved or processed",
            "remaining_seconds": remaining_time,
            "elapsed_seconds": elapsed_since_first_data,
            "timestamp": datetime.now().isoformat(),
            "data_saved": False,
            "buffer_updated": False,
            "warming_up": True
        }), 200
    
    # CLEAR BUFFER SAAT PERTAMA KALI KELUAR DARI WARMING UP
    if not hasattr(multisensor, 'warming_up_cleared'):
        with data_buffer.lock:
            data_buffer.data_points.clear()  # Clear semua data warming up
        multisensor.warming_up_cleared = True
        last_analysis_time = current_time
        print("🧹 Buffer cleared after warming up period - Starting fresh data collection")
        print("✅ Hardware stabilized - Normal operations begin")
    
    # OPERASI NORMAL DIMULAI SETELAH WARMING UP SELESAI
    print(f"📩 Data diterima: {datetime.now().strftime('%H:%M:%S')} (Post warming up)")
    
    # Simpan data mentah ke database (HANYA SETELAH WARMING UP)
    save_sensor_data(data)
    
    # Tambahkan ke buffer untuk analisis (HANYA SETELAH WARMING UP)
    data_buffer.add_data(data)
    
    # Proses shock dan vibration real-time
    shock_result = process_realtime_shock(data)
    vibration_result = process_realtime_vibration(data)
    
    # Kirim payload real-time ke ThingsBoard
    realtime_payload = {}
    
    if shock_result and shock_result['is_road_shock']:
        realtime_payload["fls_realtime_shock_ms2"] = shock_result['filtered_shock']
        print(f"📡 Shock real-time: {shock_result['filtered_shock']:.2f} m/s²")
    
    if vibration_result and vibration_result['is_road_vibration']:
        realtime_payload["fls_realtime_vibration_dps"] = vibration_result['filtered_vibration']
        print(f"📡 Vibration real-time: {vibration_result['filtered_vibration']:.2f} deg/s")
    
    if realtime_payload:
        realtime_payload.update({
            "fls_timestamp": datetime.now().isoformat(),
            "fls_data_type": "realtime_3param",
            "fls_shock_filter_enabled": True,
            "fls_vibration_filter_enabled": True,
            "fls_post_warming_up": True
        })
        send_to_thingsboard(realtime_payload, "realtime_3param")
    
    # Cek apakah sudah waktunya untuk analisis 30 detik
    if (current_time - last_analysis_time) >= ANALYSIS_INTERVAL:
        # Jalankan analisis di thread terpisah agar tidak blocking
        analysis_thread = threading.Thread(target=perform_30s_analysis)
        analysis_thread.daemon = True
        analysis_thread.start()
    
    return jsonify({
        "status": "success",
        "message": "Data processed successfully (post warming up)",
        "timestamp": datetime.now().isoformat(),
        "data_buffer_count": data_buffer.get_data_count(),
        "data_saved": True,
        "buffer_updated": True,
        "warming_up": False,
        "warming_up_completed": True,
        "elapsed_since_connection": elapsed_since_first_data,
        "parameters": "surface + shock + vibration",
        "filters": "shock & vibration filters enabled"
    }), 200

@app.route('/status', methods=['GET'])
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

def compress_image_for_thingsboard(image_path):
    """
    Kompres gambar PNG menjadi JPEG yang kompatibel dengan ThingsBoard
    Fokus pada mengatasi masalah payload size dan format compatibility
    """
    try:
        print(f"📸 Processing image for ThingsBoard: {image_path}")
        
        # Buka gambar asli
        with Image.open(image_path) as img:
            original_size = os.path.getsize(image_path)
            print(f"   Original PNG size: {original_size} bytes ({original_size/1024:.1f}KB)")
            
            # Convert RGBA ke RGB jika perlu (PNG dengan transparency)
            if img.mode in ('RGBA', 'LA', 'P'):
                # Buat background putih
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'RGBA':
                    background.paste(img, mask=img.split()[-1])
                elif img.mode == 'P':
                    img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1])
                else:
                    background.paste(img)
                img = background
                print(f"   Converted {img.mode} to RGB")
            
            # Resize jika terlalu besar
            original_dimensions = (img.width, img.height)
            if img.width > THINGSBOARD_IMAGE_CONFIG['max_width'] or img.height > THINGSBOARD_IMAGE_CONFIG['max_height']:
                img.thumbnail((
                    THINGSBOARD_IMAGE_CONFIG['max_width'], 
                    THINGSBOARD_IMAGE_CONFIG['max_height']
                ), Image.Resampling.LANCZOS)
                print(f"   Resized: {original_dimensions} → {img.size}")
            
            # Simpan sebagai JPEG dengan kompresi optimal
            img_buffer = io.BytesIO()
            img.save(img_buffer, 
                    format=THINGSBOARD_IMAGE_CONFIG['format'], 
                    quality=THINGSBOARD_IMAGE_CONFIG['jpeg_quality'], 
                    optimize=True)
            
            compressed_data = img_buffer.getvalue()
            compressed_size = len(compressed_data)
            
            print(f"   JPEG compressed size: {compressed_size} bytes ({compressed_size/1024:.1f}KB)")
            print(f"   Compression ratio: {compressed_size/original_size*100:.1f}%")
            
            # Convert ke base64
            base64_string = base64.b64encode(compressed_data).decode('utf-8')
            base64_size = len(base64_string)
            
            print(f"   Base64 size: {base64_size} bytes ({base64_size/1024:.1f}KB)")
            
            # Cek apakah ukuran sudah sesuai untuk ThingsBoard
            if base64_size <= THINGSBOARD_IMAGE_CONFIG['max_payload_size']:
                print(f"   ✅ ThingsBoard compatible ({base64_size} ≤ {THINGSBOARD_IMAGE_CONFIG['max_payload_size']})")
                return base64_string, base64_size, True
            else:
                print(f"   ⚠️ Still too large for ThingsBoard ({base64_size} > {THINGSBOARD_IMAGE_CONFIG['max_payload_size']})")
                # Coba dengan kualitas lebih rendah
                return try_further_compression(img, compressed_size)
                
    except Exception as e:
        print(f"❌ Error compressing image for ThingsBoard: {e}")
        return None, 0, False

def try_further_compression(img, current_size):
    """
    Coba kompresi lebih lanjut jika masih terlalu besar
    """
    print(f"   🔄 Trying further compression...")
    
    # Coba dengan kualitas yang lebih rendah
    for quality in [75, 65, 55, 45]:
        try:
            img_buffer = io.BytesIO()
            img.save(img_buffer, 
                    format='JPEG', 
                    quality=quality, 
                    optimize=True)
            
            compressed_data = img_buffer.getvalue()
            base64_string = base64.b64encode(compressed_data).decode('utf-8')
            base64_size = len(base64_string)
            
            print(f"   Quality {quality}%: {base64_size} bytes ({base64_size/1024:.1f}KB)")
            
            if base64_size <= THINGSBOARD_IMAGE_CONFIG['max_payload_size']:
                print(f"   ✅ Success with quality {quality}%")
                return base64_string, base64_size, True
                
        except Exception as e:
            print(f"   ❌ Failed at quality {quality}%: {e}")
            continue
    
    # Jika masih gagal, coba resize lebih kecil
    print(f"   🔄 Trying smaller dimensions...")
    for scale in [0.8, 0.6, 0.4]:
        try:
            new_width = int(img.width * scale)
            new_height = int(img.height * scale)
            resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            img_buffer = io.BytesIO()
            resized_img.save(img_buffer, format='JPEG', quality=75, optimize=True)
            
            compressed_data = img_buffer.getvalue()
            base64_string = base64.b64encode(compressed_data).decode('utf-8')
            base64_size = len(base64_string)
            
            print(f"   Scale {scale}: {new_width}x{new_height}, {base64_size} bytes")
            
            if base64_size <= THINGSBOARD_IMAGE_CONFIG['max_payload_size']:
                print(f"   ✅ Success with scale {scale}")
                return base64_string, base64_size, True
                
        except Exception as e:
            print(f"   ❌ Failed at scale {scale}: {e}")
            continue
    
    print(f"   ❌ All compression attempts failed")
    return None, 0, False

def send_analysis_with_optimized_image_to_thingsboard(analysis_id):
    """
    Kirim data analisis dengan gambar yang dioptimasi untuk ThingsBoard
    UPDATED: Kompres dari file lokal, bukan dari database
    """
    connection = get_db_connection()
    if not connection:
        return False
    
    try:
        cursor = connection.cursor(dictionary=True)
        
        query = "SELECT * FROM road_damage_analysis WHERE id = %s"
        cursor.execute(query, (analysis_id,))
        result = cursor.fetchone()
        
        if not result:
            print(f"❌ Analysis ID {analysis_id} not found")
            return False
        
        print(f"🔍 Sending analysis ID {analysis_id} to ThingsBoard with image compression")
        
        # Buat payload dasar (tanpa gambar dulu)
        thingsboard_payload = {
            "analysis_id": result['id'],
            "analysis_timestamp": result['analysis_timestamp'].isoformat() if result['analysis_timestamp'] else None,
            "damage_classification": result['damage_classification'],
            "damage_length": float(result['damage_length']) if result['damage_length'] else 0,
            "surface_change_max": float(result['surface_change_max']) if result['surface_change_max'] else 0,
            "shock_max_ms2": float(result['shock_max']) if result['shock_max'] else 0,
            "vibration_max_dps": float(result['vibration_max']) if result['vibration_max'] else 0,
            "speed_min_kmh": float(result['speed_min']) if result['speed_min'] else None,
    "speed_max_kmh": float(result['speed_max']) if result['speed_max'] else None,
    "speed_avg_kmh": float(result['speed_avg']) if result['speed_avg'] else None,
    "speed_range": result['speed_range'] if result['speed_range'] else "No GPS data",
    "speed_data_points": int(result['speed_data_count']) if result['speed_data_count'] else 0,
            "damage_detected": True,
            "compression_strategy": "file_to_thingsboard_only"
        }
        
        # Add location if available
        if result['start_latitude'] and result['start_longitude']:
            thingsboard_payload["start_latitude"] = float(result['start_latitude'])
            thingsboard_payload["start_longitude"] = float(result['start_longitude'])
        
        # Proses gambar: Kompres dari file PNG asli untuk ThingsBoard
        image_success = False
        
        if result['image_filename']:
            image_path = os.path.join(UPLOAD_FOLDER, result['image_filename'])
            
            if os.path.exists(image_path):
                print(f"📸 Compressing PNG file for ThingsBoard: {result['image_filename']}")
                
                # Kompres dari file PNG asli (bukan dari database)
                compressed_base64, base64_size, success = compress_image_for_thingsboard(image_path)
                
                if success and compressed_base64:
                    # Kirim gambar terkompresi ke ThingsBoard
                    thingsboard_payload.update({
                        "analysis_image_base64": compressed_base64,
                        "has_image": True,
                        "image_format": "JPEG_compressed_from_PNG",
                        "image_size_bytes": base64_size,
                        "database_has_original": True,
                        "compression_applied": True
                    })
                    image_success = True
                    print(f"✅ Compressed image sent to ThingsBoard: {base64_size} bytes")
                    print(f"💾 Database tetap menyimpan PNG asli")
                    
                else:
                    # Jika kompresi gagal, kirim metadata saja
                    thingsboard_payload.update({
                        "has_image": False,
                        "image_error": "compression_failed",
                        "image_too_complex": True,
                        "database_has_original": True,
                        "original_filename": result['image_filename']
                    })
                    print(f"⚠️ Image too complex for ThingsBoard - sending metadata only")
                    print(f"💾 Original PNG tetap tersimpan di database")
            else:
                thingsboard_payload.update({
                    "has_image": False,
                    "image_error": "file_not_found",
                    "database_has_original": True
                })
                print(f"❌ PNG file not found: {image_path}")
        else:
            thingsboard_payload.update({
                "has_image": False,
                "image_error": "no_filename"
            })
        
        # Send ke ThingsBoard
        success = send_to_thingsboard(thingsboard_payload, "road_damage_compressed")
        
        if success:
            status = "with compressed image" if image_success else "metadata only"
            print(f"✅ Analysis data sent to ThingsBoard ({status}) - ID: {analysis_id}")
            return True
        else:
            print(f"❌ Failed to send data to ThingsBoard - ID: {analysis_id}")
            return False
            
    except Exception as e:
        print(f"❌ Error in ThingsBoard transmission: {e}")
        return False
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

# UPDATE: Ganti fungsi yang lama
def send_analysis_with_image_to_thingsboard(analysis_id):
    """
    UPDATED: Gunakan fungsi dengan image fix untuk ThingsBoard
    """
    return send_analysis_with_optimized_image_to_thingsboard(analysis_id)

# Endpoint untuk testing image fix
@app.route('/debug/thingsboard/image/test/<int:analysis_id>', methods=['GET'])
def test_thingsboard_image_fix(analysis_id):
    """Test image optimization untuk ThingsBoard"""
    connection = get_db_connection()
    if not connection:
        return jsonify({"error": "Database connection failed"}), 500
    
    try:
        cursor = connection.cursor(dictionary=True)
        query = "SELECT image_filename FROM road_damage_analysis WHERE id = %s"
        cursor.execute(query, (analysis_id,))
        result = cursor.fetchone()
        
        if not result or not result['image_filename']:
            return jsonify({"error": "Image not found for analysis"}), 404
        
        image_path = os.path.join(UPLOAD_FOLDER, result['image_filename'])
        
        if not os.path.exists(image_path):
            return jsonify({"error": "Image file not found on disk"}), 404
        
        # Test compression untuk ThingsBoard
        compressed_base64, base64_size, success = compress_image_for_thingsboard(image_path)
        original_size = os.path.getsize(image_path)
        
        test_result = {
            "analysis_id": analysis_id,
            "image_filename": result['image_filename'],
            "original_size_bytes": original_size,
            "original_size_kb": round(original_size/1024, 1),
            "compressed_size_bytes": base64_size,
            "compressed_size_kb": round(base64_size/1024, 1),
            "compression_ratio": f"{base64_size/original_size*100:.1f}%" if original_size > 0 else "0%",
            "thingsboard_compatible": success,
            "max_allowed_size": THINGSBOARD_IMAGE_CONFIG['max_payload_size'],
            "max_allowed_size_kb": round(THINGSBOARD_IMAGE_CONFIG['max_payload_size']/1024, 1),
            "optimization_config": THINGSBOARD_IMAGE_CONFIG,
            "status": "success" if success else "failed"
        }
        
        return jsonify(test_result)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

@app.route('/debug/thingsboard/image/retry/<int:analysis_id>', methods=['POST'])
def retry_send_to_thingsboard(analysis_id):
    """Retry sending analysis with image fix to ThingsBoard"""
    try:
        success = send_analysis_with_optimized_image_to_thingsboard(analysis_id)
        
        return jsonify({
            "analysis_id": analysis_id,
            "retry_success": success,
            "timestamp": datetime.now().isoformat(),
            "message": "Analysis resent with image optimization" if success else "Failed to resend analysis"
        })
        
    except Exception as e:
        return jsonify({
            "analysis_id": analysis_id,
            "retry_success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

@app.route('/analysis', methods=['GET'])
def get_analysis():
    """Endpoint untuk mengambil data analisis dari database - UPDATED 3 parameter"""
    connection = get_db_connection()
    if not connection:
        return jsonify({"error": "Database connection failed"}), 500
    
    try:
        cursor = connection.cursor(dictionary=True)
        
        # Parameter query
        limit = request.args.get('limit', 20, type=int)
        offset = request.args.get('offset', 0, type=int)
        classification = request.args.get('classification', None)
        
        # Base query
        base_query = "SELECT * FROM road_damage_analysis"
        count_query = "SELECT COUNT(*) as total FROM road_damage_analysis"
        
        # Filter
        where_clause = ""
        params = []
        if classification:
            where_clause = " WHERE damage_classification = %s"
            params = [classification]
        
        # Get total count
        cursor.execute(count_query + where_clause, params)
        total_count = cursor.fetchone()['total']
        
        # Get data
        main_query = base_query + where_clause + " ORDER BY analysis_timestamp DESC LIMIT %s OFFSET %s"
        cursor.execute(main_query, params + [limit, offset])
        
        analyses = cursor.fetchall()
        
        # Parse JSON anomalies and add unit info
        for analysis in analyses:
            if analysis['anomalies']:
                try:
                    analysis['anomalies'] = json.loads(analysis['anomalies'])
                except json.JSONDecodeError:
                    analysis['anomalies'] = []
            
            # Add unit information
            analysis['surface_unit'] = 'cm'
            analysis['shock_unit'] = 'm/s² (filtered)'
            analysis['vibration_unit'] = 'deg/s (filtered)'
            analysis['speed_unit'] = 'km/h (GPS estimated)'
        
        return jsonify({
            "total": total_count,
            "count": len(analyses),
            "analyses": analyses,
            "parameters_info": {
                "surface_unit": "cm",
                "shock_unit": "m/s² (filtered)",
                "vibration_unit": "deg/s (filtered)",
                "speed_unit": "km/h (GPS estimated)",
                "note": "3 parameters with vehicle & slope filters"
            }
        })
        
    except Error as e:
        print(f"❌ Error fetching analyses: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

@app.route('/summary', methods=['GET'])
def get_summary():
    """Endpoint untuk mendapatkan ringkasan data kerusakan jalan - UPDATED 3 parameter"""
    connection = get_db_connection()
    if not connection:
        return jsonify({"error": "Database connection failed"}), 500
    
    try:
        cursor = connection.cursor(dictionary=True)
        
        # Summary statistics
        stats_query = """
        SELECT 
            damage_classification,
            COUNT(*) as count,
            AVG(damage_length) as avg_length,
            SUM(damage_length) as total_length,
            MAX(surface_change_max) as max_surface_change,
            MAX(shock_max) as max_shock_ms2,
            AVG(shock_max) as avg_shock_ms2,
            MAX(vibration_max) as max_vibration_dps,
            AVG(vibration_max) as avg_vibration_dps,
            AVG(speed_avg) as avg_speed_kmh,
            MAX(speed_max) as max_speed_kmh,
            MIN(speed_min) as min_speed_kmh
        FROM road_damage_analysis 
        GROUP BY damage_classification
        """
        
        cursor.execute(stats_query)
        stats = cursor.fetchall()
        
        # Recent activity
        recent_query = """
        SELECT analysis_timestamp, damage_classification, damage_length, 
               start_latitude, start_longitude, end_latitude, end_longitude,
               surface_change_max, shock_max, vibration_max, speed_avg, speed_range
        FROM road_damage_analysis 
        ORDER BY analysis_timestamp DESC 
        LIMIT 10
        """
        
        cursor.execute(recent_query)
        recent = cursor.fetchall()
        
        return jsonify({
            "statistics": stats,
            "recent_activity": recent,
            "timestamp": datetime.now().isoformat(),
            "units": {
                "surface_change": "cm",
                "shock": "m/s² (filtered)",
                "vibration": "deg/s (filtered)",
                "speed": "km/h (GPS estimated)",
                "damage_length": "meters"
            },
            "parameters_note": "3 parameters: surface + shock + vibration with filters"
        })
        
    except Error as e:
        print(f"❌ Error fetching summary: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

@app.route('/debug/filters/test', methods=['GET'])
def debug_filters_test():
    """Debug endpoint untuk test filter shock dan vibration"""
    # Test data shock
    test_shocks = [
        1.5, 2.1, 1.8, 2.0, 1.9,  # Shock kendaraan normal
        28.5, 32.2, 27.8,          # Shock jalan rusak
        2.2, 1.7, 2.3, 1.6,        # Shock kendaraan lagi
        45.1, 52.3, 41.8,          # Shock jalan rusak parah
        2.0, 1.9, 2.1               # Shock kendaraan
    ]
    
    # Test data vibration
    test_vibrations = [
        50, 45, 55, 48, 52,         # Vibration kendaraan normal
        150, 180, 165,              # Vibration jalan rusak
        60, 55, 58, 62,             # Vibration kendaraan lagi
        220, 250, 210,              # Vibration jalan rusak parah
        48, 52, 49                  # Vibration kendaraan
    ]
    
    # Terapkan filter
    shock_filter_result = filter_vehicle_shock(test_shocks)
    vibration_filter_result = filter_vehicle_vibration(test_vibrations)
    
    return jsonify({
        "shock_test": {
            "original_data": test_shocks,
            "filter_result": shock_filter_result,
            "filter_parameters": {
                "baseline_range": f"{VEHICLE_SHOCK_FILTER['baseline_min']}-{VEHICLE_SHOCK_FILTER['baseline_max']} m/s²",
                "tolerance": f"{VEHICLE_SHOCK_FILTER['baseline_tolerance']} m/s²",
                "spike_threshold": f"{VEHICLE_SHOCK_FILTER['road_spike_threshold']} m/s²"
            }
        },
        "vibration_test": {
            "original_data": test_vibrations,
            "filter_result": vibration_filter_result,
            "filter_parameters": {
                "baseline_range": f"{VEHICLE_VIBRATION_FILTER['baseline_min']}-{VEHICLE_VIBRATION_FILTER['baseline_max']} deg/s",
                "tolerance": f"{VEHICLE_VIBRATION_FILTER['baseline_tolerance']} deg/s",
                "spike_threshold": f"{VEHICLE_VIBRATION_FILTER['road_spike_threshold']} deg/s",
                "slope_threshold": f"{VEHICLE_VIBRATION_FILTER['slope_trend_threshold']} deg/s"
            }
        }
    })

@app.route('/thingsboard/test', methods=['GET'])
def test_thingsboard():
    """Endpoint untuk test koneksi ThingsBoard - UPDATED 3 parameter"""
    test_payload = {
        "test_message": "Road monitoring test with 3 parameters",
        "test_timestamp": datetime.now().isoformat(),
        "test_status": "active",
        "mysql_connection": "ok" if get_db_connection() else "failed",
        "parameters": "surface + shock + vibration",
        "shock_unit": "m/s² (filtered)",
        "vibration_unit": "deg/s (filtered)",
        "filters": "shock & vibration filters enabled"
    }
    
    success = send_to_thingsboard(test_payload, "connection_test")
    
    return jsonify({
        "thingsboard_connection": "success" if success else "failed",
        "thingsboard_url": THINGSBOARD_URL,
        "timestamp": datetime.now().isoformat(),
        "parameters_status": "3 parameters enabled",
        "filters_status": "shock & vibration filters enabled"
    })

@app.route('/debug/thingsboard/test-compression/<int:analysis_id>', methods=['GET'])
def test_compression_only(analysis_id):
    """Test kompresi gambar tanpa mengubah database"""
    connection = get_db_connection()
    if not connection:
        return jsonify({"error": "Database connection failed"}), 500
    
    try:
        cursor = connection.cursor(dictionary=True)
        query = "SELECT image_filename FROM road_damage_analysis WHERE id = %s"
        cursor.execute(query, (analysis_id,))
        result = cursor.fetchone()
        
        if not result or not result['image_filename']:
            return jsonify({"error": "Image not found for analysis"}), 404
        
        image_path = os.path.join(UPLOAD_FOLDER, result['image_filename'])
        
        if not os.path.exists(image_path):
            return jsonify({"error": "PNG file not found on disk"}), 404
        
        # Test compression dari file PNG
        original_size = os.path.getsize(image_path)
        compressed_base64, base64_size, success = compress_image_for_thingsboard(image_path)
        
        test_result = {
            "analysis_id": analysis_id,
            "strategy": "database_original_thingsboard_compressed",
            "png_file": result['image_filename'],
            "original_png_size_bytes": original_size,
            "original_png_size_kb": round(original_size/1024, 1),
            "compressed_jpeg_size_bytes": base64_size,
            "compressed_jpeg_size_kb": round(base64_size/1024, 1),
            "compression_ratio": f"{base64_size/original_size*100:.1f}%" if original_size > 0 else "0%",
            "thingsboard_compatible": success,
            "database_storage": "PNG asli tetap tersimpan",
            "thingsboard_transmission": "JPEG terkompresi",
            "status": "success" if success else "failed"
        }
        
        return jsonify(test_result)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

if __name__ == '__main__':
    print("🚀 Road Monitoring Flask Server Starting...")
    print("=" * 60)
    print("⏳ HARDWARE WARMING UP PERIOD:")
    print(f"   - Skip first {INITIAL_SKIP_PERIOD} seconds after ESP32 connects")
    print(f"   - Warming up starts when first data received")
    print(f"   - Allows sensor stabilization and GPS acquisition")
    print(f"   - Raw data collection continues normally")
    print(f"   - Only road damage analysis is skipped")
    print("=" * 60)
    print("📡 Available Endpoints:")
    print("   - POST /multisensor       : Receive ESP32 sensor data (3 parameters)")
    print("   - GET  /status           : System status")
    print("   - GET  /analysis         : Get analysis results")
    print("   - GET  /summary          : Get damage summary")
    print("   - GET  /thingsboard/test : Test ThingsBoard connection")
    print("   - GET  /debug/filters/test : Test shock & vibration filters")
    print("=" * 60)
    print("🔗 ThingsBoard Integration:")
    print(f"   - Server: {THINGSBOARD_CONFIG['server']}:{THINGSBOARD_CONFIG['port']}")
    print(f"   - URL: {THINGSBOARD_URL}")
    print(f"   - Data Prefix: fls_ (Flask)")
    print("=" * 60)
    # print("📊 SISTEM KLASIFIKASI (3 PARAMETERS):")
    # print("   ✅ PARAMETER 1: Surface Change (cm) - Ultrasonic")
    # print("   ✅ PARAMETER 2: Shock (m/s²) - Accelerometer + Vehicle Filter")
    # print("   ✅ PARAMETER 3: Vibration (deg/s) - Gyroscope + Vehicle & Slope Filter")
    # print("   ✅ Klasifikasi: 3 parameters dengan threshold masing-masing")
    # print("=" * 60)
    # print("🔧 FILTER PARAMETERS:")
    # print(f"   SHOCK FILTER (m/s²):")
    # print(f"   - Baseline Range: {VEHICLE_SHOCK_FILTER['baseline_min']}-{VEHICLE_SHOCK_FILTER['baseline_max']} m/s²")
    # print(f"   - Spike Threshold: {VEHICLE_SHOCK_FILTER['road_spike_threshold']} m/s²")
    # print(f"   VIBRATION FILTER (deg/s):")
    # print(f"   - Baseline Range: {VEHICLE_VIBRATION_FILTER['baseline_min']}-{VEHICLE_VIBRATION_FILTER['baseline_max']} deg/s")
    # print(f"   - Spike Threshold: {VEHICLE_VIBRATION_FILTER['road_spike_threshold']} deg/s")
    # print(f"   - Slope Filter: Detects slope vs road damage")
    # print("=" * 60)
    # print("🔄 Classification Rules (3 Parameters):")
    # print("   - Surface Change: Ultrasonic sensor differences")
    # print("   - Shock: Accelerometer spikes (filtered from vehicle)")
    # print("   - Vibration: Gyroscope oscillations (filtered from vehicle & slope)")
    # print("   - Logic: Based on threshold combinations")
    # print("=" * 60)
    # print("💾 Resource Optimization:")
    # print("   - Image saved only when damage detected")
    # print("   - MySQL & ThingsBoard: DAMAGE DATA ONLY")
    # print("   - Good road conditions: No database insert, no image")
    # print("   - Data: 3 parameters with proper filtering")
    # print("=" * 60)
    
    # Test database connection
    test_conn = get_db_connection()
    if test_conn:
        print("✅ Database connection successful")
        test_conn.close()
    else:
        print("❌ Database connection failed - check configuration")
        exit(1)
    
    # # Test filters
    # test_shocks = [1.5, 2.1, 28.5, 2.0, 45.1, 1.9]
    # test_vibrations = [50, 45, 150, 48, 220, 52]
    
    # shock_filter_result = filter_vehicle_shock(test_shocks)
    # vibration_filter_result = filter_vehicle_vibration(test_vibrations)
    
    # print(f"🔧 Shock Filter Test:")
    # print(f"   Original: {len(test_shocks)} shocks")
    # print(f"   Vehicle: {shock_filter_result['stats']['vehicle_count']} (filtered out)")
    # print(f"   Road: {shock_filter_result['stats']['road_count']} (analyzed)")
    
    # print(f"🔧 Vibration Filter Test:")
    # print(f"   Original: {len(test_vibrations)} vibrations")
    # print(f"   Vehicle: {vibration_filter_result['stats']['vehicle_count']} (filtered out)")
    # print(f"   Slope: {vibration_filter_result['stats']['slope_count']} (filtered out)")
    # print(f"   Road: {vibration_filter_result['stats']['road_count']} (analyzed)")
    
    # Test ThingsBoard connection
    test_payload = {
        "startup_test": "Flask server starting with 3 parameters",
        "startup_timestamp": datetime.now().isoformat(),
        "parameters": "surface + shock + vibration",
        "shock_unit": "m/s² (filtered)",
        "vibration_unit": "deg/s (filtered)",
        "filters": "shock & vibration filters enabled"
    }
    
    if send_to_thingsboard(test_payload, "startup_test"):
        print("✅ ThingsBoard connection successful")
    else:
        print("⚠️ ThingsBoard connection failed - check configuration")
    
    # Start server
    flask_host = os.getenv('FLASK_HOST', '0.0.0.0')
    flask_port = int(os.getenv('FLASK_PORT', 5000))
    flask_debug = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
       
    print(f"🌐 Server running on http://{flask_host}:{flask_port}")
    print("=" * 60)
    
    app.run(host=flask_host, port=flask_port, debug=flask_debug)