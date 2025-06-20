from flask import Flask, request, jsonify
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import os
import time
import json
from datetime import datetime, timedelta
from collections import deque
import threading
import math
import mysql.connector
from mysql.connector import Error
import base64
from dotenv import load_dotenv
from thresholds import *

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

UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'static')
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Data storage untuk analisis 30 detik
class DataBuffer:
    def __init__(self, max_duration=30):
        self.max_duration = max_duration
        self.data_points = deque()
        self.lock = threading.Lock()
    
    def add_data(self, data):
        with self.lock:
            current_time = datetime.now()
            data['timestamp'] = current_time
            self.data_points.append(data)
            
            # Hapus data yang lebih dari 30 detik
            cutoff_time = current_time - timedelta(seconds=self.max_duration)
            while self.data_points and self.data_points[0]['timestamp'] < cutoff_time:
                self.data_points.popleft()
    
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
    change_counts = 0
    
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
                    change_counts += 1
    
    return {
        'changes': changes,
        'max_change': max(changes) if changes else 0,
        'avg_change': sum(changes) / len(changes) if changes else 0,
        'count': change_counts
    }

def analyze_vibrations(data_points):
    """Analisis guncangan dari data accelerometer"""
    vibrations = []
    vibration_counts = 0
    
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
                    vibration_counts += 1
    
    return {
        'vibrations': vibrations,
        'max_vibration': max(vibrations) if vibrations else 0,
        'avg_vibration': sum(vibrations) / len(vibrations) if vibrations else 0,
        'count': vibration_counts
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

def calculate_damage_length(data_points):
    """Menghitung panjang kerusakan berdasarkan data GPS"""
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
    
    # Analisis rotasi
    rotation_analysis = analyze_rotations(data_points)
    if rotation_analysis['count'] > 0:
        anomalies.append({
            'type': 'rotation',
            'details': rotation_analysis,
            'severity': get_rotation_severity(rotation_analysis['max_rotation'])
        })
    
    return anomalies

def create_analysis_visualization(analysis_data):
    """Membuat visualisasi analisis untuk disimpan"""
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
    
    # 1. Data perubahan permukaan (Time Series Line Chart)
    if analysis_data['surface_analysis']['changes']:
        # Create time index for changes
        time_points = list(range(len(analysis_data['surface_analysis']['changes'])))
        
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
        ax1.set_title('Perubahan Permukaan Jalan (Time Series)')
        ax1.set_xlabel('Urutan Deteksi')
        ax1.set_ylabel('Perubahan (cm)')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
    else:
        ax1.text(0.5, 0.5, 'Tidak ada perubahan\npermukaan signifikan', 
                ha='center', va='center', transform=ax1.transAxes, fontsize=14)
        ax1.set_title('Perubahan Permukaan Jalan (Time Series)')
    
    # 2. Data guncangan (Time Series Line Chart)
    if analysis_data['vibration_analysis']['vibrations']:
        time_points = list(range(len(analysis_data['vibration_analysis']['vibrations'])))
        
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
        ax2.set_title('Intensitas Guncangan (Time Series)')
        ax2.set_xlabel('Urutan Deteksi')
        ax2.set_ylabel('Intensitas Guncangan')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
    else:
        ax2.text(0.5, 0.5, 'Tidak ada guncangan\nsignifikan', 
                ha='center', va='center', transform=ax2.transAxes, fontsize=14)
        ax2.set_title('Intensitas Guncangan (Time Series)')
    
    # 3. Panjang kerusakan dan lokasi
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
        info_text += f"   Lng: {analysis_data['end_location'][1]:.6f}\n\n"
    else:
        info_text += f"   GPS tidak tersedia\n\n"
    
    info_text += f"⏱️ Durasi Analisis: {analysis_data['duration']:.1f} detik\n"
    info_text += f"📊 Jumlah Data: {analysis_data['data_count']} titik"
    
    ax3.text(0.05, 0.95, info_text, ha='left', va='top', transform=ax3.transAxes, 
            fontsize=11, bbox=dict(boxstyle="round,pad=0.5", facecolor="lightblue", alpha=0.7))
    ax3.set_title('Data Panjang Kerusakan Jalan')
    ax3.axis('off')
    
    # 4. Klasifikasi dan anomali dengan trend visualization
    classification_text = f"🏗️ KLASIFIKASI KERUSAKAN:\n"
    classification_text += f"   {analysis_data['damage_classification'].upper().replace('_', ' ')}\n\n"
    classification_text += f"🎯 SKOR KERUSAKAN: {analysis_data['damage_score']:.2f}\n\n"
    
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
    ax4.set_title('Klasifikasi Kerusakan Jalan')
    ax4.axis('off')
    
    plt.tight_layout()
    
    # Save dengan timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'road_analysis_{timestamp}.png'
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    plt.savefig(filepath, dpi=100, bbox_inches='tight')
    plt.close()
    
    return filepath, filename

def save_analysis_to_database(analysis_data, image_path, image_filename):
    """Menyimpan hasil analisis ke database"""
    connection = get_db_connection()
    if not connection:
        return False
    
    try:
        cursor = connection.cursor()
        
        # Encode image to base64
        image_data = None
        if image_path and os.path.exists(image_path):
            with open(image_path, 'rb') as img_file:
                image_data = base64.b64encode(img_file.read()).decode('utf-8')
        
        insert_query = """
        INSERT INTO road_damage_analysis (
            analysis_timestamp, start_latitude, start_longitude, end_latitude, end_longitude,
            damage_classification, damage_length, surface_change_max, surface_change_avg, surface_change_count,
            vibration_max, vibration_avg, vibration_count, anomalies,
            analysis_image, image_filename, data_points_count, analysis_duration
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        """
        
        start_lat = analysis_data['start_location'][0] if analysis_data['start_location'] else None
        start_lng = analysis_data['start_location'][1] if analysis_data['start_location'] else None
        end_lat = analysis_data['end_location'][0] if analysis_data['end_location'] else None
        end_lng = analysis_data['end_location'][1] if analysis_data['end_location'] else None
        
        insert_data = (
            datetime.now(),  # analysis_timestamp
            start_lat, start_lng, end_lat, end_lng,  # locations
            analysis_data['damage_classification'],  # damage_classification
            analysis_data['damage_length'],  # damage_length
            analysis_data['surface_analysis']['max_change'],  # surface_change_max
            analysis_data['surface_analysis']['avg_change'],  # surface_change_avg
            analysis_data['surface_analysis']['count'],  # surface_change_count
            analysis_data['vibration_analysis']['max_vibration'],  # vibration_max
            analysis_data['vibration_analysis']['avg_vibration'],  # vibration_avg
            analysis_data['vibration_analysis']['count'],  # vibration_count
            json.dumps(analysis_data['anomalies']),  # anomalies (JSON)
            image_data,  # analysis_image
            image_filename,  # image_filename
            analysis_data['data_count'],  # data_points_count
            analysis_data['duration']  # analysis_duration
        )
        
        cursor.execute(insert_query, insert_data)
        connection.commit()
        
        print(f"✅ Analisis berhasil disimpan: {analysis_data['damage_classification']}")
        return True
        
    except Error as e:
        print(f"❌ Error saving analysis: {e}")
        return False
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def perform_30s_analysis():
    """Melakukan analisis komprehensif setiap 30 detik"""
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
    damage_length = calculate_damage_length(data_points)
    anomalies = detect_anomalies(data_points)
    
    # Tentukan lokasi awal dan akhir
    start_location = None
    end_location = None
    
    for data in data_points:
        if data.get('latitude') is not None and data.get('longitude') is not None:
            if start_location is None:
                start_location = (data['latitude'], data['longitude'])
            end_location = (data['latitude'], data['longitude'])
    
    # Hitung skor dan klasifikasi kerusakan
    surface_changes = surface_analysis['changes']
    vibrations = vibration_analysis['vibrations']
    rotations = rotation_analysis['rotations']
    frequency_factor = len(anomalies) / len(data_points) if data_points else 0
    
    damage_score = calculate_damage_score(surface_changes, vibrations, rotations, frequency_factor)
    damage_classification = classify_damage(damage_score)
    
    # Compile analysis data
    analysis_data = {
        'surface_analysis': surface_analysis,
        'vibration_analysis': vibration_analysis,
        'rotation_analysis': rotation_analysis,
        'damage_length': damage_length,
        'anomalies': anomalies,
        'damage_score': damage_score,
        'damage_classification': damage_classification,
        'start_location': start_location,
        'end_location': end_location,
        'data_count': len(data_points),
        'duration': time.time() - start_time
    }
    
    # Buat dan simpan visualisasi
    try:
        image_path, image_filename = create_analysis_visualization(analysis_data)
        
        # Simpan ke database
        save_analysis_to_database(analysis_data, image_path, image_filename)
        
        print(f"✅ Analisis selesai - Klasifikasi: {damage_classification}")
        print(f"📊 Skor kerusakan: {damage_score:.2f}")
        print(f"📏 Panjang kerusakan: {damage_length:.1f}m")
        print(f"⚠️ Anomali: {len(anomalies)}")
        
    except Exception as e:
        print(f"❌ Error dalam analisis: {e}")
    
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
                analysis['anomalies'] = json.loads(analysis['anomalies'])
        
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

if __name__ == '__main__':
    print("🚀 Road Monitoring Flask Server Starting...")
    print("=" * 50)
    print("📡 Available Endpoints:")
    print("   - POST /multisensor  : Receive ESP32 sensor data")
    print("   - GET  /status       : System status")
    print("   - GET  /analysis     : Get analysis results")
    print("   - GET  /summary      : Get damage summary")
    print("=" * 50)
    
    # Test database connection
    test_conn = get_db_connection()
    if test_conn:
        print("✅ Database connection successful")
        test_conn.close()
    else:
        print("❌ Database connection failed - check configuration")
        exit(1)
    
    # Start server
    flask_host = os.getenv('FLASK_HOST', '0.0.0.0')
    flask_port = int(os.getenv('FLASK_PORT', 5000))
    flask_debug = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    
    print(f"🌐 Server running on http://{flask_host}:{flask_port}")
    print("=" * 50)
    
    app.run(host=flask_host, port=flask_port, debug=flask_debug)