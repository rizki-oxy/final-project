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
import base64
from dotenv import load_dotenv
from thresholds import (
    MIN_DATA_POINTS, ANALYSIS_INTERVAL, EARTH_RADIUS, MAX_GPS_GAP,
    SURFACE_CHANGE_THRESHOLDS, VIBRATION_THRESHOLDS, ROTATION_THRESHOLDS,
    get_surface_change_severity, get_vibration_severity, get_rotation_severity,
    classify_damage_or_logic  # MASIH PAKAI NAMA YANG SAMA, TAPI FUNGSINYA SUDAH BERUBAH
)

# Load environment variables
load_dotenv()

app = Flask(__name__)

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

def get_db_connection():
    """Membuat koneksi ke database MySQL"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        if connection.is_connected():
            return connection
    except Error as e:
        print(f"❌ Error connecting to MySQL: {e}")
        return None

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
    """Menyimpan data sensor mentah ke database"""
    connection = get_db_connection()
    if not connection:
        return False
    
    try:
        cursor = connection.cursor()
        
        insert_query = """
        INSERT INTO sensor_data (
            timestamp, sensor1_distance, sensor2_distance, sensor3_distance, sensor4_distance,
            sensor5_distance, sensor6_distance, sensor7_distance, sensor8_distance,
            accel_x, accel_y, accel_z, accel_magnitude,
            gyro_x, gyro_y, gyro_z, rotation_magnitude,
            latitude, longitude, speed, satellites
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        """
        
        # Calculate magnitudes
        accel_magnitude = None
        if all(data.get(key) is not None for key in ['accelX', 'accelY', 'accelZ']):
            accel_magnitude = math.sqrt(data['accelX']**2 + data['accelY']**2 + data['accelZ']**2)
        
        rotation_magnitude = None
        if all(data.get(key) is not None for key in ['gyroX', 'gyroY', 'gyroZ']):
            rotation_magnitude = math.sqrt(
                (data['gyroX']/131.0)**2 + (data['gyroY']/131.0)**2 + (data['gyroZ']/131.0)**2
            )
        
        insert_data = (
            datetime.now(),
            data.get('sensor1'), data.get('sensor2'), data.get('sensor3'), data.get('sensor4'),
            data.get('sensor5'), data.get('sensor6'), data.get('sensor7'), data.get('sensor8'),
            data.get('accelX'), data.get('accelY'), data.get('accelZ'), accel_magnitude,
            data.get('gyroX'), data.get('gyroY'), data.get('gyroZ'), rotation_magnitude,
            data.get('latitude'), data.get('longitude'), data.get('speed'), data.get('satellites')
        )
        
        cursor.execute(insert_query, insert_data)
        connection.commit()
        
        print(f"✅ Raw sensor data saved to MySQL (ID: {cursor.lastrowid})")
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
                change = abs(curr_val - prev_val)
                if change >= SURFACE_CHANGE_THRESHOLDS['minor']:
                    changes.append(change)
    
    return {
        'changes': changes,
        'max_change': max(changes) if changes else 0,
        'avg_change': sum(changes) / len(changes) if changes else 0,
        'count': len(changes)
    }

def analyze_vibrations(data_points):
    """Analisis guncangan dari data accelerometer"""
    vibrations = []
    
    for i in range(1, len(data_points)):
        prev_data = data_points[i-1]
        curr_data = data_points[i]
        
        # Calculate acceleration magnitude changes
        if all(key in prev_data and key in curr_data for key in ['accelX', 'accelY', 'accelZ']):
            if all(prev_data[key] is not None and curr_data[key] is not None 
                   for key in ['accelX', 'accelY', 'accelZ']):
                
                prev_mag = math.sqrt(prev_data['accelX']**2 + prev_data['accelY']**2 + prev_data['accelZ']**2)
                curr_mag = math.sqrt(curr_data['accelX']**2 + curr_data['accelY']**2 + curr_data['accelZ']**2)
                
                vibration = abs(curr_mag - prev_mag)
                if vibration >= VIBRATION_THRESHOLDS['light']:
                    vibrations.append(vibration)
    
    return {
        'vibrations': vibrations,
        'max_vibration': max(vibrations) if vibrations else 0,
        'avg_vibration': sum(vibrations) / len(vibrations) if vibrations else 0,
        'count': len(vibrations)
    }

def analyze_rotations(data_points):
    """Analisis rotasi berlebihan dari data gyroscope"""
    rotations = []
    
    for data in data_points:
        if all(key in data and data[key] is not None for key in ['gyroX', 'gyroY', 'gyroZ']):
            # Convert to degrees per second
            rotX = abs(data['gyroX'] / 131.0)
            rotY = abs(data['gyroY'] / 131.0)
            rotZ = abs(data['gyroZ'] / 131.0)
            
            max_rotation = max(rotX, rotY, rotZ)
            if max_rotation >= ROTATION_THRESHOLDS['normal']:
                rotations.append(max_rotation)
    
    return {
        'rotations': rotations,
        'max_rotation': max(rotations) if rotations else 0,
        'avg_rotation': sum(rotations) / len(rotations) if rotations else 0,
        'count': len(rotations)
    }

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
    
    # Analisis guncangan
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
    analysis_duration = 30  # Selalu 30 detik untuk analisis
    
    # 1. Data perubahan permukaan
    if analysis_data['surface_analysis']['changes']:
        # Distribusikan data secara merata dalam 30 detik
        num_changes = len(analysis_data['surface_analysis']['changes'])
        time_points = [i * (analysis_duration / (num_changes - 1)) if num_changes > 1 else 0 
                      for i in range(num_changes)]
        
        ax1.plot(time_points, analysis_data['surface_analysis']['changes'], 
                marker='o', linewidth=2, markersize=4, color='orange', alpha=0.8)
        ax1.axhline(y=analysis_data['surface_analysis']['max_change'], 
                   color='red', linestyle='--', alpha=0.7,
                   label=f'Max: {analysis_data["surface_analysis"]["max_change"]:.1f}cm')
        ax1.axhline(y=analysis_data['surface_analysis']['avg_change'], 
                   color='blue', linestyle=':', alpha=0.7,
                   label=f'Avg: {analysis_data["surface_analysis"]["avg_change"]:.1f}cm')
        
        ax1.fill_between(time_points, analysis_data['surface_analysis']['changes'], 
                        alpha=0.3, color='orange')
        ax1.set_title('Perubahan Permukaan Jalan')
        ax1.set_xlabel('Waktu (detik)')
        ax1.set_ylabel('Perubahan (cm)')
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
    
    # 2. Data guncangan
    if analysis_data['vibration_analysis']['vibrations']:
        # Distribusikan data secara merata dalam 30 detik
        num_vibrations = len(analysis_data['vibration_analysis']['vibrations'])
        time_points = [i * (analysis_duration / (num_vibrations - 1)) if num_vibrations > 1 else 0 
                      for i in range(num_vibrations)]
        
        ax2.plot(time_points, analysis_data['vibration_analysis']['vibrations'], 
                marker='s', linewidth=2, markersize=4, color='red', alpha=0.8)
        ax2.axhline(y=analysis_data['vibration_analysis']['max_vibration'], 
                   color='darkred', linestyle='--', alpha=0.7,
                   label=f'Max: {analysis_data["vibration_analysis"]["max_vibration"]:.0f}')
        ax2.axhline(y=analysis_data['vibration_analysis']['avg_vibration'], 
                   color='blue', linestyle=':', alpha=0.7,
                   label=f'Avg: {analysis_data["vibration_analysis"]["avg_vibration"]:.0f}')
        
        ax2.fill_between(time_points, analysis_data['vibration_analysis']['vibrations'], 
                        alpha=0.3, color='red')
        ax2.set_title('Intensitas Guncangan')
        ax2.set_xlabel('Waktu (detik)')
        ax2.set_ylabel('Guncangan')
        ax2.set_xlim(0, 30)
        ax2.legend()
        ax2.grid(True, alpha=0.3)
    else:
        ax2.text(0.5, 0.5, 'Tidak ada guncangan\nsignifikan', 
                ha='center', va='center', transform=ax2.transAxes, fontsize=14)
        ax2.set_title('Intensitas Guncangan')
        ax2.set_xlabel('Waktu (detik)')
        ax2.set_xlim(0, 30)
        ax2.grid(True, alpha=0.3)
    
    # 3. Info lokasi dan panjang kerusakan
    info_text = f"📏 Panjang Kerusakan: {analysis_data['damage_length']:.1f} meter\n\n"
    info_text += f"🏁 Lokasi Awal:\n"
    if analysis_data['start_location']:
        info_text += f"   Lat: {analysis_data['start_location'][0]:.6f}\n"
        info_text += f"   Lng: {analysis_data['start_location'][1]:.6f}\n\n"
    else:
        info_text += f"   GPS tidak tersedia\n\n"
    
    info_text += f"🏁 Lokasi Akhir:\n"
    if analysis_data['end_location']:
        info_text += f"   Lat: {analysis_data['end_location'][0]:.6f}\n"
        info_text += f"   Lng: {analysis_data['end_location'][1]:.6f}"
    else:
        info_text += f"   GPS tidak tersedia"
    
    ax3.text(0.05, 0.95, info_text, ha='left', va='top', transform=ax3.transAxes, 
            fontsize=11, bbox=dict(boxstyle="round,pad=0.5", facecolor="lightblue", alpha=0.7))
    ax3.set_title('Info Kerusakan Jalan')
    ax3.axis('off')
    
    # 4. Klasifikasi dan anomali
    classification_text = f"🏗️ KLASIFIKASI KERUSAKAN:\n"
    classification_text += f"   {analysis_data['damage_classification'].upper().replace('_', ' ')}\n\n"
    
    classification_text += f"⚠️ ANOMALI TERDETEKSI:\n"
    for anomaly in analysis_data['anomalies']:
        classification_text += f"• {anomaly['type'].replace('_', ' ').title()}: {anomaly['severity']}\n"
    
    if not analysis_data['anomalies']:
        classification_text += "• Tidak ada anomali signifikan\n"
    
    # Color based on classification
    color_map = {
        'rusak_ringan': 'lightgreen',
        'rusak_sedang': 'yellow', 
        'rusak_berat': 'lightcoral'
    }
    bg_color = color_map.get(analysis_data['damage_classification'], 'lightgray')
    
    ax4.text(0.05, 0.95, classification_text, ha='left', va='top', transform=ax4.transAxes, 
            fontsize=11, bbox=dict(boxstyle="round,pad=0.5", facecolor=bg_color, alpha=0.8))
    ax4.set_title('Klasifikasi Kerusakan')
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
    """Menyimpan hasil analisis ke database - HANYA JIKA ADA KERUSAKAN"""
    
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
        
        # Encode image to base64 hanya jika ada gambar
        image_data = None
        if image_path and os.path.exists(image_path):
            with open(image_path, 'rb') as img_file:
                image_data = base64.b64encode(img_file.read()).decode('utf-8')
        
        insert_query = """
        INSERT INTO road_damage_analysis (
            analysis_timestamp, start_latitude, start_longitude, end_latitude, end_longitude,
            damage_classification, damage_length, surface_change_max, surface_change_avg, surface_change_count,
            vibration_max, vibration_avg, vibration_count, anomalies,
            analysis_image, image_filename
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
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
            analysis_data['vibration_analysis']['max_vibration'],
            analysis_data['vibration_analysis']['avg_vibration'],
            analysis_data['vibration_analysis']['count'],
            json.dumps(analysis_data['anomalies']),
            image_data,
            image_filename
        )
        
        cursor.execute(insert_query, insert_data)
        connection.commit()
        
        analysis_id = cursor.lastrowid
        print(f"✅ Kerusakan berhasil disimpan ke MySQL: {analysis_data['damage_classification']} (ID: {analysis_id})")
        
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

def send_analysis_to_thingsboard(analysis_data, analysis_id):
    """Kirim hasil analisis ke ThingsBoard - HANYA JIKA ADA KERUSAKAN"""
    
    # Double check - pastikan ada kerusakan
    if not analysis_data.get('has_damage', False):
        print("💡 Jalan dalam kondisi baik - Tidak ada data yang dikirim ke ThingsBoard")
        return
    
    try:
        # Buat payload untuk ThingsBoard dengan data kerusakan
        thingsboard_payload = {
            "analysis_id": analysis_id,
            "analysis_timestamp": datetime.now().isoformat(),
            "damage_classification": analysis_data['damage_classification'],
            "damage_length": analysis_data['damage_length'],
            "surface_change_max": analysis_data['surface_analysis']['max_change'],
            "surface_change_avg": analysis_data['surface_analysis']['avg_change'],
            "surface_change_count": analysis_data['surface_analysis']['count'],
            "vibration_max": analysis_data['vibration_analysis']['max_vibration'],
            "vibration_avg": analysis_data['vibration_analysis']['avg_vibration'],
            "vibration_count": analysis_data['vibration_analysis']['count'],
            "anomalies_count": len(analysis_data['anomalies']),
            "damage_detected": True  # Flag untuk menandai ada kerusakan
        }
        
        # Add location if available
        if analysis_data['start_location']:
            thingsboard_payload["start_latitude"] = analysis_data['start_location'][0]
            thingsboard_payload["start_longitude"] = analysis_data['start_location'][1]
            
        if analysis_data['end_location']:
            thingsboard_payload["end_latitude"] = analysis_data['end_location'][0]
            thingsboard_payload["end_longitude"] = analysis_data['end_location'][1]
        
        # Add severity level untuk dashboard
        severity_map = {
            'rusak_ringan': 1,
            'rusak_sedang': 2,
            'rusak_berat': 3
        }
        thingsboard_payload["damage_severity"] = severity_map.get(analysis_data['damage_classification'], 0)
        
        # Send to ThingsBoard
        if send_to_thingsboard(thingsboard_payload, "road_damage_detected"):
            print(f"✅ Data kerusakan terkirim ke ThingsBoard: {analysis_data['damage_classification']}")
        else:
            print(f"❌ Gagal mengirim data kerusakan ke ThingsBoard")
        
    except Exception as e:
        print(f"❌ Error sending damage data to ThingsBoard: {e}")

def send_analysis_with_image_to_thingsboard(analysis_id):
    """Kirim data analisis beserta gambar ke ThingsBoard dengan validasi image"""
    connection = get_db_connection()
    if not connection:
        return False
    
    try:
        cursor = connection.cursor(dictionary=True)
        
        query = """
        SELECT * FROM road_damage_analysis 
        WHERE id = %s
        """
        
        cursor.execute(query, (analysis_id,))
        result = cursor.fetchone()
        
        if not result:
            print(f"❌ Analysis ID {analysis_id} not found")
            return False
        
        print(f"🔍 Processing analysis ID {analysis_id}")
        print(f"📊 Has image: {result['analysis_image'] is not None}")
        if result['analysis_image']:
            print(f"📸 Image data length: {len(result['analysis_image'])} characters")
            # Cek format image
            if result['analysis_image'].startswith('iVBORw0KGgo'):
                print(f"✅ Image format: PNG (valid)")
            else:
                print(f"⚠️ Image format: Unknown or corrupt")
                print(f"🔍 Image starts with: {result['analysis_image'][:50]}...")
        
        # Buat payload lengkap dengan image
        thingsboard_payload = {
            "analysis_id": result['id'],
            "analysis_timestamp": result['analysis_timestamp'].isoformat() if result['analysis_timestamp'] else None,
            "damage_classification": result['damage_classification'],
            "damage_length": float(result['damage_length']) if result['damage_length'] else 0,
            "surface_change_max": float(result['surface_change_max']) if result['surface_change_max'] else 0,
            "surface_change_avg": float(result['surface_change_avg']) if result['surface_change_avg'] else 0,
            "surface_change_count": int(result['surface_change_count']) if result['surface_change_count'] else 0,
            "vibration_max": float(result['vibration_max']) if result['vibration_max'] else 0,
            "vibration_avg": float(result['vibration_avg']) if result['vibration_avg'] else 0,
            "vibration_count": int(result['vibration_count']) if result['vibration_count'] else 0,
            "damage_detected": True
        }
        
        # Add location if available
        if result['start_latitude'] and result['start_longitude']:
            thingsboard_payload["start_latitude"] = float(result['start_latitude'])
            thingsboard_payload["start_longitude"] = float(result['start_longitude'])
            
        if result['end_latitude'] and result['end_longitude']:
            thingsboard_payload["end_latitude"] = float(result['end_latitude'])
            thingsboard_payload["end_longitude"] = float(result['end_longitude'])
        
        # VALIDASI DAN ADD IMAGE BASE64
        if result['analysis_image']:
            image_data = result['analysis_image']
            
            # Validasi format base64
            try:
                import base64
                # Test decode untuk memastikan valid
                test_decode = base64.b64decode(image_data[:100])  # Test first 100 chars
                print(f"✅ Base64 validation: PASSED")
                
                # Cek ukuran data untuk ThingsBoard limit
                if len(image_data) > 200000:  # 200KB limit
                    print(f"⚠️ Image data sangat besar ({len(image_data)} chars), akan dipotong")
                    # Ambil sebagian data atau compress
                    thingsboard_payload["analysis_image_base64"] = image_data[:100000] + "...truncated"
                    thingsboard_payload["has_image"] = True
                    thingsboard_payload["image_truncated"] = True
                    thingsboard_payload["image_full_size"] = len(image_data)
                    print(f"📤 Sending truncated image data ({len(thingsboard_payload['analysis_image_base64'])} chars)")
                else:
                    thingsboard_payload["analysis_image_base64"] = image_data
                    thingsboard_payload["has_image"] = True
                    thingsboard_payload["image_truncated"] = False
                    print(f"📤 Sending full image data ({len(image_data)} chars)")
                    
            except Exception as e:
                print(f"❌ Base64 validation failed: {e}")
                thingsboard_payload["has_image"] = False
                thingsboard_payload["image_error"] = str(e)
        else:
            thingsboard_payload["has_image"] = False
            print("📤 No image data to send")
        
        # Add anomalies count
        if result['anomalies']:
            try:
                anomalies_data = json.loads(result['anomalies'])
                thingsboard_payload["anomalies_count"] = len(anomalies_data)
            except json.JSONDecodeError:
                thingsboard_payload["anomalies_count"] = 0
        
        # Debug: Print payload info (without image data to avoid spam)
        debug_payload = {k: v for k, v in thingsboard_payload.items() if k not in ['analysis_image_base64']}
        print(f"📋 Payload keys: {list(debug_payload.keys())}")
        print(f"📋 Has image: {thingsboard_payload.get('has_image', False)}")
        print(f"📋 Image truncated: {thingsboard_payload.get('image_truncated', False)}")
        
        # Send to ThingsBoard
        if send_to_thingsboard(thingsboard_payload, "road_damage_with_image"):
            print(f"✅ Data lengkap dengan gambar terkirim ke ThingsBoard (ID: {analysis_id})")
            return True
        else:
            print(f"❌ Gagal mengirim data lengkap ke ThingsBoard (ID: {analysis_id})")
            return False
            
    except Error as e:
        print(f"❌ Error sending complete data to ThingsBoard: {e}")
        return False
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def perform_30s_analysis():
    """Melakukan analisis komprehensif setiap 30 detik dengan logika AND sederhana"""
    global last_analysis_time
    
    current_time = time.time()
    data_points = data_buffer.get_data()
    
    if len(data_points) < MIN_DATA_POINTS:
        print(f"⏳ Data tidak cukup untuk analisis: {len(data_points)}/{MIN_DATA_POINTS}")
        return
    
    print(f"🔍 Memulai analisis 30 detik dengan {len(data_points)} data points...")
    
    start_time = time.time()
    
    # Analisis berbagai aspek
    surface_analysis = analyze_surface_changes(data_points)
    vibration_analysis = analyze_vibrations(data_points)
    rotation_analysis = analyze_rotations(data_points)
    anomalies = detect_anomalies(data_points)
    
    # Tentukan lokasi awal dan akhir
    start_location = None
    end_location = None
    
    for data in data_points:
        if data.get('latitude') is not None and data.get('longitude') is not None:
            if start_location is None:
                start_location = (data['latitude'], data['longitude'])
            end_location = (data['latitude'], data['longitude'])
    
    # === KLASIFIKASI SEDERHANA DENGAN LOGIKA AND ===
    max_surface_change = surface_analysis['max_change']
    max_vibration = vibration_analysis['max_vibration'] 
    max_rotation = rotation_analysis['max_rotation']
    
    # Gunakan fungsi klasifikasi dari thresholds.py dengan logika AND (ROTASI DIHAPUS)
    damage_classification = classify_damage_or_logic(max_surface_change, max_vibration, max_rotation)
    
    # Hanya hitung panjang kerusakan jika ada kerusakan
    has_damage = damage_classification != 'baik'
    damage_length = calculate_damage_length(data_points, has_damage)
    
    print(f"📊 Parameter Klasifikasi:")
    print(f"   - Perubahan Permukaan Max: {max_surface_change:.2f} cm")
    print(f"   - Getaran Max: {max_vibration:.0f}")
    print(f"   - Rotasi Max: {max_rotation:.0f} deg/s (TIDAK DIGUNAKAN)")
    print(f"   - Hasil Klasifikasi: {damage_classification.upper().replace('_', ' ')}")
    print(f"   - Panjang Kerusakan: {damage_length:.1f}m")
    
    # HANYA PROSES LEBIH LANJUT JIKA ADA KERUSAKAN
    if has_damage:
        print(f"⚠️  KERUSAKAN TERDETEKSI - Memproses dan menyimpan data...")
        
        # Compile analysis data
        analysis_data = {
            'surface_analysis': surface_analysis,
            'vibration_analysis': vibration_analysis,
            'rotation_analysis': rotation_analysis,
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
            print(f"⚠️ Anomali: {len(anomalies)}")
            print(f"💾 Data dikirim ke MySQL dan ThingsBoard")
            
        except Exception as e:
            print(f"❌ Error menyimpan analisis: {e}")
    
    else:
        print(f"✅ JALAN DALAM KONDISI BAIK - Tidak ada data yang disimpan")
        print(f"💡 Resource saved: No MySQL insert, no ThingsBoard data, no image generated")
    
    last_analysis_time = current_time

@app.route('/multisensor', methods=['POST'])
def multisensor():
    """Endpoint untuk menerima data sensor dari ESP32"""
    global last_analysis_time
    
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data received"}), 400
    
    print(f"📩 Data diterima: {datetime.now().strftime('%H:%M:%S')}")
    
    # Simpan data mentah ke database
    save_sensor_data(data)
    
    # Tambahkan ke buffer untuk analisis
    data_buffer.add_data(data)
    
    # Cek apakah sudah waktunya untuk analisis 30 detik
    current_time = time.time()
    if (current_time - last_analysis_time) >= ANALYSIS_INTERVAL:
        # Jalankan analisis di thread terpisah agar tidak blocking
        analysis_thread = threading.Thread(target=perform_30s_analysis)
        analysis_thread.daemon = True
        analysis_thread.start()
    
    return jsonify({
        "status": "success",
        "message": "Data processed successfully",
        "timestamp": datetime.now().isoformat(),
        "data_buffer_count": data_buffer.get_data_count()
    }), 200

@app.route('/status', methods=['GET'])
def status():
    """Endpoint untuk cek status sistem"""
    data_points = data_buffer.get_data()
    
    # Analisis data terbaru
    latest_data = data_points[-1] if data_points else {}
    
    # Status GPS
    gps_status = "active" if latest_data.get('latitude') is not None else "inactive"
    
    # Status sensor ultrasonic
    ultrasonic_active = sum(1 for i in range(1, 9) 
                           if latest_data.get(f'sensor{i}') not in [None, -1])
    
    # Status motion sensor
    motion_status = "active" if any(latest_data.get(key) is not None 
                                  for key in ['accelX', 'accelY', 'accelZ']) else "inactive"
    
    # Test ThingsBoard connection
    test_payload = {"system_status": "testing", "test_timestamp": datetime.now().isoformat()}
    thingsboard_status = "connected" if send_to_thingsboard(test_payload, "status_check") else "disconnected"
    
    return jsonify({
        "system_status": "running",
        "timestamp": datetime.now().isoformat(),
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
        "last_analysis": datetime.fromtimestamp(last_analysis_time).isoformat() if last_analysis_time > 0 else "Never",
        "next_analysis_in": max(0, ANALYSIS_INTERVAL - (time.time() - last_analysis_time))
    })

@app.route('/analysis', methods=['GET'])
def get_analysis():
    """Endpoint untuk mengambil data analisis dari database"""
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
        
        # Parse JSON anomalies
        for analysis in analyses:
            if analysis['anomalies']:
                try:
                    analysis['anomalies'] = json.loads(analysis['anomalies'])
                except json.JSONDecodeError:
                    analysis['anomalies'] = []
        
        return jsonify({
            "total": total_count,
            "count": len(analyses),
            "analyses": analyses
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
    """Endpoint untuk mendapatkan ringkasan data kerusakan jalan"""
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
            MAX(vibration_max) as max_vibration
        FROM road_damage_analysis 
        GROUP BY damage_classification
        """
        
        cursor.execute(stats_query)
        stats = cursor.fetchall()
        
        # Recent activity
        recent_query = """
        SELECT analysis_timestamp, damage_classification, damage_length, 
               start_latitude, start_longitude, end_latitude, end_longitude
        FROM road_damage_analysis 
        ORDER BY analysis_timestamp DESC 
        LIMIT 10
        """
        
        cursor.execute(recent_query)
        recent = cursor.fetchall()
        
        return jsonify({
            "statistics": stats,
            "recent_activity": recent,
            "timestamp": datetime.now().isoformat()
        })
        
    except Error as e:
        print(f"❌ Error fetching summary: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

@app.route('/debug/analysis/<int:analysis_id>', methods=['GET'])
def debug_analysis_data(analysis_id):
    """Debug endpoint untuk cek data analisis"""
    connection = get_db_connection()
    if not connection:
        return jsonify({"error": "Database connection failed"}), 500
    
    try:
        cursor = connection.cursor(dictionary=True)
        
        query = """
        SELECT id, analysis_timestamp, damage_classification, 
               damage_length, analysis_image IS NOT NULL as has_image_in_db,
               LENGTH(analysis_image) as image_size,
               image_filename
        FROM road_damage_analysis 
        WHERE id = %s
        """
        
        cursor.execute(query, (analysis_id,))
        result = cursor.fetchone()
        
        if not result:
            return jsonify({"error": f"Analysis ID {analysis_id} not found"}), 404
        
        return jsonify({
            "analysis_id": result['id'],
            "damage_classification": result['damage_classification'],
            "damage_length": result['damage_length'],
            "has_image_in_database": result['has_image_in_db'],
            "image_size_bytes": result['image_size'],
            "image_filename": result['image_filename'],
            "timestamp": result['analysis_timestamp'].isoformat() if result['analysis_timestamp'] else None
        })
        
    except Error as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

@app.route('/debug/thingsboard/resend/<int:analysis_id>', methods=['POST'])
def debug_resend_to_thingsboard(analysis_id):
    """Debug endpoint untuk mengirim ulang data ke ThingsBoard"""
    try:
        success = send_analysis_with_image_to_thingsboard(analysis_id)
        
        return jsonify({
            "success": success,
            "message": f"Resend to ThingsBoard {'successful' if success else 'failed'}",
            "analysis_id": analysis_id
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "analysis_id": analysis_id
        }), 500

@app.route('/analysis/<int:analysis_id>/image', methods=['GET'])
def get_analysis_image_endpoint(analysis_id):
    """Endpoint untuk mendapatkan gambar analisis berdasarkan ID"""
    connection = get_db_connection()
    if not connection:
        return "Database connection failed", 500
    
    try:
        cursor = connection.cursor(dictionary=True)
        
        query = """
        SELECT analysis_image, damage_classification, analysis_timestamp, image_filename
        FROM road_damage_analysis 
        WHERE id = %s
        """
        
        cursor.execute(query, (analysis_id,))
        result = cursor.fetchone()
        
        if not result or not result['analysis_image']:
            return "Image not found", 404
        
        # Decode base64 image
        from flask import Response
        import base64
        
        image_data = base64.b64decode(result['analysis_image'])
        
        filename = result['image_filename'] or f'analysis_{analysis_id}.png'
        
        return Response(
            image_data,
            mimetype='image/png',
            headers={
                'Content-Disposition': f'inline; filename={filename}',
                'Cache-Control': 'public, max-age=3600',
                'Content-Type': 'image/png'
            }
        )
        
    except Exception as e:
        return f"Error: {str(e)}", 500
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

@app.route('/thingsboard/test', methods=['GET'])
def test_thingsboard():
    """Endpoint untuk test koneksi ThingsBoard"""
    test_payload = {
        "test_message": "Road monitoring test with AND logic",
        "test_timestamp": datetime.now().isoformat(),
        "test_status": "active",
        "mysql_connection": "ok" if get_db_connection() else "failed"
    }
    
    success = send_to_thingsboard(test_payload, "connection_test")
    
    return jsonify({
        "thingsboard_connection": "success" if success else "failed",
        "thingsboard_url": THINGSBOARD_URL,
        "timestamp": datetime.now().isoformat()
    })

if __name__ == '__main__':
    print("🚀 Road Monitoring Flask Server Starting...")
    print("=" * 60)
    print("📡 Available Endpoints:")
    print("   - POST /multisensor       : Receive ESP32 sensor data")
    print("   - GET  /status           : System status")
    print("   - GET  /analysis         : Get analysis results")
    print("   - GET  /summary          : Get damage summary")
    print("   - GET  /thingsboard/test : Test ThingsBoard connection")
    print("=" * 60)
    print("🔗 ThingsBoard Integration:")
    print(f"   - Server: {THINGSBOARD_CONFIG['server']}:{THINGSBOARD_CONFIG['port']}")
    print(f"   - URL: {THINGSBOARD_URL}")
    print(f"   - Data Prefix: fls_ (Flask)")
    print("=" * 60)
    print("📊 PERUBAHAN SISTEM KLASIFIKASI:")
    print("   ✅ ROTASI DIHAPUS dari parameter klasifikasi")
    print("   ✅ Logika OR diubah menjadi AND")
    print("   ✅ Klasifikasi sekarang: Surface Change AND Vibration")
    print("   ✅ KEDUA parameter harus memenuhi threshold untuk deteksi kerusakan")
    print("=" * 60)
    print("🔄 Classification Rules (AND Logic):")
    print("   - RUSAK BERAT: Surface ≥10cm AND Vibration ≥4000")
    print("   - RUSAK SEDANG: Surface ≥5cm AND Vibration ≥3000")
    print("   - RUSAK RINGAN: Surface ≥2cm AND Vibration ≥2000")
    print("   - BAIK: Jika salah satu parameter tidak memenuhi threshold")
    print("=" * 60)
    print("💾 Resource Optimization:")
    print("   - Image saved only when damage detected")
    print("   - MySQL & ThingsBoard: DAMAGE DATA ONLY")
    print("   - Good road conditions: No database insert, no image")
    print("=" * 60)
    
    # Test database connection
    test_conn = get_db_connection()
    if test_conn:
        print("✅ Database connection successful")
        test_conn.close()
    else:
        print("❌ Database connection failed - check configuration")
        exit(1)
    
    # Test ThingsBoard connection
    test_payload = {
        "startup_test": "Flask server starting with AND logic",
        "startup_timestamp": datetime.now().isoformat(),
        "classification_change": "Rotation removed, OR changed to AND"
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