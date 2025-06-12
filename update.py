from flask import Flask, request, jsonify
import requests
import numpy as np
import matplotlib
matplotlib.use('Agg')  # menggunakan mode non-GUI
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
import paho.mqtt.client as mqtt_client
from geopy.distance import geodesic

app = Flask(__name__)

# Konfigurasi ThingsBoard
THINGSBOARD_TOKEN = 'r7DUFq0R2PXLNNvmSZwp'
THINGSBOARD_URL = f"https://demo.thingsboard.io/api/v1/{THINGSBOARD_TOKEN}/telemetry"
THINGSBOARD_MQTT_BROKER = "demo.thingsboard.io"
THINGSBOARD_MQTT_PORT = 1883
UPLOAD_FOLDER = 'static'

# Konfigurasi MQTT Broker untuk Flask
FLASK_MQTT_BROKER = "localhost"  # ESP32 akan connect ke sini
FLASK_MQTT_PORT = 1883
FLASK_MQTT_TOPIC = "road_sensor/data"  # Topic dari ESP32
FLASK_RESPONSE_TOPIC = "road_sensor/response"

# Konfigurasi MySQL Database
DB_CONFIG = {
    'host': 'localhost',
    'database': 'road_monitoring_v2',
    'user': 'root',
    'password': '',
    'charset': 'utf8mb4',
    'autocommit': True
}

# Pastikan folder static ada
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Variabel untuk menyimpan data time series (30 detik terakhir)
MAX_TIME_WINDOW = 30  # 30 detik
sensor_data_history = {f'sensor{i+1}': deque(maxlen=MAX_TIME_WINDOW) for i in range(8)}
gps_data_history = {'latitude': deque(maxlen=MAX_TIME_WINDOW), 'longitude': deque(maxlen=MAX_TIME_WINDOW)}
motion_data_history = {
    'accelX': deque(maxlen=MAX_TIME_WINDOW), 'accelY': deque(maxlen=MAX_TIME_WINDOW), 'accelZ': deque(maxlen=MAX_TIME_WINDOW),
    'gyroX': deque(maxlen=MAX_TIME_WINDOW), 'gyroY': deque(maxlen=MAX_TIME_WINDOW), 'gyroZ': deque(maxlen=MAX_TIME_WINDOW)
}
timestamp_history = deque(maxlen=MAX_TIME_WINDOW)
last_evaluation_time = 0
EVALUATION_INTERVAL = 30  # Evaluasi setiap 30 detik

# Lock untuk thread safety
data_lock = threading.Lock()

# Threshold untuk klasifikasi kerusakan jalan
ROAD_DAMAGE_THRESHOLDS = {
    'surface_change': {
        'light': 2.0,    # > 2cm perubahan = kerusakan ringan
        'medium': 5.0,   # > 5cm perubahan = kerusakan sedang  
        'severe': 10.0   # > 10cm perubahan = kerusakan berat
    },
    'vibration': {
        'light': 2000,   # Getaran ringan
        'medium': 5000,  # Getaran sedang
        'severe': 10000  # Getaran berat
    },
    'rotation': {
        'light': 100,    # Rotasi ringan (deg/s)
        'medium': 300,   # Rotasi sedang
        'severe': 500    # Rotasi berat
    }
}

# MQTT Clients
mqtt_client_flask = None
mqtt_client_thingsboard = None
mqtt_connected = False
thingsboard_connected = False

def setup_mqtt_clients():
    """Setup MQTT clients untuk ESP32 dan ThingsBoard"""
    global mqtt_client_flask, mqtt_client_thingsboard, mqtt_connected, thingsboard_connected
    
    # MQTT Client untuk menerima data dari ESP32
    def on_connect_flask(client, userdata, flags, rc):
        global mqtt_connected
        if rc == 0:
            print("✅ MQTT Client (Flask) terhubung ke broker")
            mqtt_connected = True
            client.subscribe(FLASK_MQTT_TOPIC)
            print(f"📡 Subscribed to topic: {FLASK_MQTT_TOPIC}")
        else:
            mqtt_connected = False
    
    def on_message_flask(client, userdata, msg):
        """Callback untuk data dari ESP32"""
        try:
            payload = msg.payload.decode('utf-8')
            print(f"📩 Data diterima dari ESP32: {payload}")
            
            data = json.loads(payload)
            process_esp32_data(data)
            
        except Exception as e:
            print(f"❌ Error processing MQTT message: {e}")
    
    # MQTT Client untuk ThingsBoard
    def on_connect_thingsboard(client, userdata, flags, rc):
        global thingsboard_connected
        if rc == 0:
            print("✅ MQTT Client (ThingsBoard) terhubung")
            thingsboard_connected = True
        else:
            thingsboard_connected = False
    
    # Setup Flask MQTT Client
    mqtt_client_flask = mqtt_client.Client("FlaskServer")
    mqtt_client_flask.on_connect = on_connect_flask
    mqtt_client_flask.on_message = on_message_flask
    
    # Setup ThingsBoard MQTT Client
    mqtt_client_thingsboard = mqtt_client.Client()
    mqtt_client_thingsboard.username_pw_set(THINGSBOARD_TOKEN)
    mqtt_client_thingsboard.on_connect = on_connect_thingsboard
    
    try:
        # Connect to local broker (for ESP32)
        mqtt_client_flask.connect(FLASK_MQTT_BROKER, FLASK_MQTT_PORT, 60)
        mqtt_client_flask.loop_start()
        
        # Connect to ThingsBoard
        mqtt_client_thingsboard.connect(THINGSBOARD_MQTT_BROKER, THINGSBOARD_MQTT_PORT, 60)
        mqtt_client_thingsboard.loop_start()
        
        print("🚀 MQTT Clients dimulai...")
    except Exception as e:
        print(f"❌ Gagal memulai MQTT clients: {e}")

def process_esp32_data(data):
    """Memproses data dari ESP32"""
    global last_evaluation_time
    
    current_time = time.time()
    current_timestamp = datetime.now().strftime('%H:%M:%S')
    
    print("📊 Memproses data dari ESP32...")
    
    # Forward ke ThingsBoard
    forward_to_thingsboard(data)
    
    # Parse data ESP32
    parsed_data = parse_esp32_data(data)
    
    # Update history data
    with data_lock:
        timestamp_history.append(current_timestamp)
        
        # Update ultrasonic data
        for i in range(8):
            distance = parsed_data['ultrasonic'].get(f'sensor{i+1}', -1)
            sensor_data_history[f'sensor{i+1}'].append(distance)
        
        # Update GPS data
        if parsed_data['gps']['valid']:
            gps_data_history['latitude'].append(parsed_data['gps']['latitude'])
            gps_data_history['longitude'].append(parsed_data['gps']['longitude'])
        
        # Update motion data
        if parsed_data['motion']['connected']:
            for key in ['accelX', 'accelY', 'accelZ', 'gyroX', 'gyroY', 'gyroZ']:
                motion_data_history[key].append(parsed_data['motion'][key])
    
    # Evaluasi kerusakan jalan setiap 30 detik
    if current_time - last_evaluation_time >= EVALUATION_INTERVAL:
        evaluate_road_damage()
        last_evaluation_time = current_time

def parse_esp32_data(data):
    """Parse data dari ESP32 format JSON"""
    parsed = {
        'ultrasonic': {},
        'gps': {
            'valid': data.get('gps_valid', False),
            'latitude': data.get('latitude', None),
            'longitude': data.get('longitude', None),
            'speed': data.get('speed', 0),
            'satellites': data.get('satellites', 0)
        },
        'motion': {
            'connected': data.get('motion_sensor_connected', False),
            'accelX': data.get('accelX', 0),
            'accelY': data.get('accelY', 0),
            'accelZ': data.get('accelZ', 0),
            'gyroX': data.get('gyroX', 0),
            'gyroY': data.get('gyroY', 0),
            'gyroZ': data.get('gyroZ', 0)
        }
    }
    
    # Parse ultrasonic sensors
    ultrasonic_sensors = data.get('ultrasonic_sensors', [])
    for sensor in ultrasonic_sensors:
        sensor_id = sensor.get('sensor_id')
        distance = sensor.get('distance', -1)
        parsed['ultrasonic'][f'sensor{sensor_id}'] = distance
    
    return parsed

def forward_to_thingsboard(data):
    """Forward data ke ThingsBoard via MQTT"""
    try:
        if thingsboard_connected:
            # Format data untuk ThingsBoard
            thingsboard_data = format_for_thingsboard(data)
            
            # Kirim via MQTT
            result = mqtt_client_thingsboard.publish(
                "v1/devices/me/telemetry", 
                json.dumps(thingsboard_data)
            )
            
            if result.rc == 0:
                print("✅ Data berhasil dikirim ke ThingsBoard via MQTT")
            else:
                print(f"❌ Gagal kirim ke ThingsBoard: {result.rc}")
        else:
            print("⚠️ ThingsBoard MQTT tidak terhubung")
            
    except Exception as e:
        print(f"❌ Error forwarding to ThingsBoard: {e}")

def format_for_thingsboard(data):
    """Format data untuk ThingsBoard"""
    formatted = {}
    
    # GPS data
    if data.get('gps_valid'):
        formatted['latitude'] = data.get('latitude')
        formatted['longitude'] = data.get('longitude')
        formatted['speed'] = data.get('speed', 0)
        formatted['satellites'] = data.get('satellites', 0)
    
    # Motion data  
    if data.get('motion_sensor_connected'):
        formatted['accelX'] = data.get('accelX', 0)
        formatted['accelY'] = data.get('accelY', 0)
        formatted['accelZ'] = data.get('accelZ', 0)
        formatted['gyroX'] = data.get('gyroX', 0)
        formatted['gyroY'] = data.get('gyroY', 0)
        formatted['gyroZ'] = data.get('gyroZ', 0)
    
    # Ultrasonic data
    ultrasonic_sensors = data.get('ultrasonic_sensors', [])
    for sensor in ultrasonic_sensors:
        sensor_id = sensor.get('sensor_id')
        distance = sensor.get('distance', -1)
        formatted[f'sensor{sensor_id}'] = distance
        
    return formatted

def evaluate_road_damage():
    """Evaluasi kerusakan jalan berdasarkan data 30 detik terakhir"""
    print("🔍 Evaluating road damage...")
    
    with data_lock:
        if len(timestamp_history) < 5:  # Minimal 5 data point
            print("⚠️ Tidak cukup data untuk evaluasi")
            return
        
        # Analisis perubahan permukaan
        surface_anomalies = analyze_surface_changes()
        
        # Analisis getaran/guncangan
        vibration_anomalies = analyze_vibrations()
        
        # Analisis rotasi berlebihan
        rotation_anomalies = analyze_rotations()
        
        # Hitung panjang kerusakan (estimasi berdasarkan GPS)
        damage_length = calculate_damage_length()
        
        # Klasifikasi tingkat kerusakan
        damage_classification = classify_road_damage(
            surface_anomalies, vibration_anomalies, rotation_anomalies
        )
        
        # Jika ada kerusakan terdeteksi, simpan ke database
        if damage_classification['level'] != 'normal':
            current_location = get_current_location()
            
            # Buat visualisasi komprehensif
            image_path = create_road_damage_visualization(
                surface_anomalies, vibration_anomalies, rotation_anomalies,
                damage_classification, damage_length, current_location
            )
            
            # Simpan ke database
            save_road_damage_to_database(
                damage_classification, current_location, damage_length,
                surface_anomalies, vibration_anomalies, rotation_anomalies,
                image_path
            )

def analyze_surface_changes():
    """Analisis perubahan permukaan jalan"""
    anomalies = []
    
    for i in range(8):
        sensor_name = f'sensor{i+1}'
        sensor_data = list(sensor_data_history[sensor_name])
        
        if len(sensor_data) < 2:
            continue
            
        # Hitung perubahan maksimum dalam 30 detik
        valid_data = [d for d in sensor_data if d > 0]
        if len(valid_data) < 2:
            continue
            
        max_change = max(valid_data) - min(valid_data)
        
        if max_change > ROAD_DAMAGE_THRESHOLDS['surface_change']['light']:
            severity = 'severe' if max_change > ROAD_DAMAGE_THRESHOLDS['surface_change']['severe'] else \
                      'medium' if max_change > ROAD_DAMAGE_THRESHOLDS['surface_change']['medium'] else 'light'
            
            anomalies.append({
                'sensor': sensor_name,
                'max_change': max_change,
                'severity': severity,
                'min_distance': min(valid_data),
                'max_distance': max(valid_data)
            })
    
    return anomalies

def analyze_vibrations():
    """Analisis getaran/guncangan"""
    anomalies = []
    
    if len(motion_data_history['accelX']) < 2:
        return anomalies
    
    accel_data = {
        'X': list(motion_data_history['accelX']),
        'Y': list(motion_data_history['accelY']),
        'Z': list(motion_data_history['accelZ'])
    }
    
    # Hitung magnitude acceleration
    magnitudes = []
    for i in range(len(accel_data['X'])):
        mag = math.sqrt(
            accel_data['X'][i]**2 + 
            accel_data['Y'][i]**2 + 
            accel_data['Z'][i]**2
        )
        magnitudes.append(mag)
    
    if len(magnitudes) >= 2:
        # Hitung perubahan getaran maksimum
        max_vibration = max([abs(magnitudes[i] - magnitudes[i-1]) 
                           for i in range(1, len(magnitudes))])
        
        if max_vibration > ROAD_DAMAGE_THRESHOLDS['vibration']['light']:
            severity = 'severe' if max_vibration > ROAD_DAMAGE_THRESHOLDS['vibration']['severe'] else \
                      'medium' if max_vibration > ROAD_DAMAGE_THRESHOLDS['vibration']['medium'] else 'light'
            
            anomalies.append({
                'max_vibration': max_vibration,
                'severity': severity,
                'avg_magnitude': sum(magnitudes) / len(magnitudes)
            })
    
    return anomalies

def analyze_rotations():
    """Analisis rotasi berlebihan"""
    anomalies = []
    
    if len(motion_data_history['gyroX']) < 1:
        return anomalies
    
    gyro_data = {
        'X': list(motion_data_history['gyroX']),
        'Y': list(motion_data_history['gyroY']),
        'Z': list(motion_data_history['gyroZ'])
    }
    
    # Konversi ke degrees per second dan cari rotasi maksimum
    max_rotations = {
        'X': max([abs(x/131.0) for x in gyro_data['X']]),
        'Y': max([abs(y/131.0) for y in gyro_data['Y']]),
        'Z': max([abs(z/131.0) for z in gyro_data['Z']])
    }
    
    overall_max = max(max_rotations.values())
    
    if overall_max > ROAD_DAMAGE_THRESHOLDS['rotation']['light']:
        severity = 'severe' if overall_max > ROAD_DAMAGE_THRESHOLDS['rotation']['severe'] else \
                  'medium' if overall_max > ROAD_DAMAGE_THRESHOLDS['rotation']['medium'] else 'light'
        
        anomalies.append({
            'max_rotation': overall_max,
            'severity': severity,
            'axis_rotations': max_rotations
        })
    
    return anomalies

def calculate_damage_length():
    """Estimasi panjang kerusakan berdasarkan GPS"""
    if len(gps_data_history['latitude']) < 2:
        return 0
    
    latitudes = list(gps_data_history['latitude'])
    longitudes = list(gps_data_history['longitude'])
    
    if len(latitudes) < 2:
        return 0
    
    # Hitung jarak antara titik pertama dan terakhir
    start_point = (latitudes[0], longitudes[0])
    end_point = (latitudes[-1], longitudes[-1])
    
    distance = geodesic(start_point, end_point).meters
    return round(distance, 2)

def classify_road_damage(surface_anomalies, vibration_anomalies, rotation_anomalies):
    """Klasifikasi tingkat kerusakan jalan"""
    
    # Hitung skor kerusakan
    damage_score = 0
    damage_factors = []
    
    # Skor dari perubahan permukaan
    for anomaly in surface_anomalies:
        if anomaly['severity'] == 'severe':
            damage_score += 3
            damage_factors.append(f"Perubahan permukaan berat ({anomaly['max_change']:.1f}cm)")
        elif anomaly['severity'] == 'medium':
            damage_score += 2
            damage_factors.append(f"Perubahan permukaan sedang ({anomaly['max_change']:.1f}cm)")
        else:
            damage_score += 1
            damage_factors.append(f"Perubahan permukaan ringan ({anomaly['max_change']:.1f}cm)")
    
    # Skor dari getaran
    for anomaly in vibration_anomalies:
        if anomaly['severity'] == 'severe':
            damage_score += 3
            damage_factors.append("Getaran berat")
        elif anomaly['severity'] == 'medium':
            damage_score += 2
            damage_factors.append("Getaran sedang")
        else:
            damage_score += 1
            damage_factors.append("Getaran ringan")
    
    # Skor dari rotasi
    for anomaly in rotation_anomalies:
        if anomaly['severity'] == 'severe':
            damage_score += 2
            damage_factors.append("Rotasi berlebihan berat")
        elif anomaly['severity'] == 'medium':
            damage_score += 1.5
            damage_factors.append("Rotasi berlebihan sedang")
        else:
            damage_score += 1
            damage_factors.append("Rotasi berlebihan ringan")
    
    # Klasifikasi berdasarkan skor
    if damage_score == 0:
        level = 'normal'
        description = 'Jalan dalam kondisi normal'
    elif damage_score <= 2:
        level = 'light'
        description = 'Kerusakan jalan ringan'
    elif damage_score <= 5:
        level = 'medium'
        description = 'Kerusakan jalan sedang'
    else:
        level = 'severe'
        description = 'Kerusakan jalan berat'
    
    return {
        'level': level,
        'score': damage_score,
        'description': description,
        'factors': damage_factors
    }

def get_current_location():
    """Ambil lokasi GPS terbaru"""
    if len(gps_data_history['latitude']) > 0:
        return {
            'latitude': list(gps_data_history['latitude'])[-1],
            'longitude': list(gps_data_history['longitude'])[-1]
        }
    return {'latitude': None, 'longitude': None}

def create_road_damage_visualization(surface_anomalies, vibration_anomalies, 
                                   rotation_anomalies, damage_classification, 
                                   damage_length, location):
    """Buat visualisasi komprehensif kerusakan jalan"""
    
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
    
    # 1. Perubahan permukaan jalan
    if surface_anomalies:
        sensors = [a['sensor'] for a in surface_anomalies]
        changes = [a['max_change'] for a in surface_anomalies]
        colors = ['red' if a['severity'] == 'severe' else 
                 'orange' if a['severity'] == 'medium' else 'yellow' 
                 for a in surface_anomalies]
        
        ax1.bar(sensors, changes, color=colors)
        ax1.set_title('Perubahan Permukaan Jalan')
        ax1.set_ylabel('Perubahan Maksimum (cm)')
        ax1.tick_params(axis='x', rotation=45)
    else:
        ax1.text(0.5, 0.5, 'Tidak ada perubahan\npermukaan signifikan', 
                ha='center', va='center', transform=ax1.transAxes)
        ax1.set_title('Perubahan Permukaan Jalan')
    
    # 2. Data guncangan
    if vibration_anomalies:
        vib_data = vibration_anomalies[0]  # Ambil yang pertama
        ax2.bar(['Getaran Maksimum'], [vib_data['max_vibration']], 
               color='red' if vib_data['severity'] == 'severe' else
                     'orange' if vib_data['severity'] == 'medium' else 'yellow')
        ax2.set_title('Intensitas Guncangan')
        ax2.set_ylabel('Magnitude')
    else:
        ax2.text(0.5, 0.5, 'Tidak ada guncangan\nsignifikan', 
                ha='center', va='center', transform=ax2.transAxes)
        ax2.set_title('Intensitas Guncangan')
    
    # 3. Time series sensor ultrasonik
    with data_lock:
        colors = ['blue', 'red', 'green', 'orange', 'purple', 'brown', 'pink', 'gray']
        for i, anomaly in enumerate(surface_anomalies[:4]):  # Hanya 4 sensor pertama yang bermasalah
            sensor_name = anomaly['sensor']
            if len(sensor_data_history[sensor_name]) > 0:
                ax3.plot(list(timestamp_history), list(sensor_data_history[sensor_name]),
                        label=sensor_name, color=colors[i], marker='o', markersize=2)
        
        ax3.set_title('Time Series - Sensor Bermasalah')
        ax3.set_xlabel('Waktu')
        ax3.set_ylabel('Jarak (cm)')
        ax3.legend()
        ax3.grid(True)
        ax3.tick_params(axis='x', rotation=45)
    
    # 4. Ringkasan klasifikasi
    classification_text = f"🚨 KLASIFIKASI KERUSAKAN JALAN\n\n"
    classification_text += f"Tingkat: {damage_classification['description'].upper()}\n"
    classification_text += f"Skor Kerusakan: {damage_classification['score']}\n\n"
    
    if damage_length > 0:
        classification_text += f"📏 Panjang Estimasi: {damage_length} meter\n\n"
    
    if location['latitude']:
        classification_text += f"📍 Lokasi:\n"
        classification_text += f"  Lat: {location['latitude']:.6f}\n"
        classification_text += f"  Lng: {location['longitude']:.6f}\n\n"
    
    classification_text += "🔍 Faktor Kerusakan:\n"
    for factor in damage_classification['factors'][:5]:  # Maksimal 5 faktor
        classification_text += f"• {factor}\n"
    
    # Warna background berdasarkan tingkat kerusakan
    bg_color = 'lightcoral' if damage_classification['level'] == 'severe' else \
               'lightsalmon' if damage_classification['level'] == 'medium' else \
               'lightblue' if damage_classification['level'] == 'light' else 'lightgreen'
    
    ax4.text(0.05, 0.95, classification_text, ha='left', va='top', 
            transform=ax4.transAxes, fontsize=10,
            bbox=dict(boxstyle="round,pad=0.3", facecolor=bg_color, alpha=0.8))
    ax4.set_title('Klasifikasi & Analisis Kerusakan')
    ax4.axis('off')
    
    plt.tight_layout()
    
    # Simpan dengan timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filepath = os.path.join(UPLOAD_FOLDER, f'road_damage_{timestamp}.png')
    plt.savefig(filepath, dpi=100, bbox_inches='tight')
    plt.close()
    
    print(f"📷 Visualisasi kerusakan jalan disimpan: {filepath}")
    return filepath

def get_db_connection():
    """Membuat koneksi ke database MySQL"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        if connection.is_connected():
            return connection
    except Error as e:
        print(f"❌ Error connecting to MySQL: {e}")
        return None

def save_road_damage_to_database(damage_classification, location, damage_length,
                                surface_anomalies, vibration_anomalies, rotation_anomalies,
                                image_path):
    """Simpan data kerusakan jalan ke database"""
    connection = get_db_connection()
    if not connection:
        return False
    
    try:
        cursor = connection.cursor()
        
        # Encode gambar ke base64
        image_data = None
        if image_path and os.path.exists(image_path):
            with open(image_path, 'rb') as img_file:
                image_data = base64.b64encode(img_file.read()).decode('utf-8')
        
        # Ambil data sensor dan motion terbaru
        with data_lock:
            latest_sensor_data = {}
            for i in range(8):
                sensor_name = f'sensor{i+1}'
                if len(sensor_data_history[sensor_name]) > 0:
                    latest_sensor_data[sensor_name] = list(sensor_data_history[sensor_name])[-1]
                else:
                    latest_sensor_data[sensor_name] = None
            
            latest_motion_data = {}
            for key in ['accelX', 'accelY', 'accelZ', 'gyroX', 'gyroY', 'gyroZ']:
                if len(motion_data_history[key]) > 0:
                    latest_motion_data[key] = list(motion_data_history[key])[-1]
                else:
                    latest_motion_data[key] = None
        
        # SQL Insert
        insert_query = """
        INSERT INTO road_damage_records (
            timestamp, damage_level, damage_score, damage_description,
            damage_length, latitude, longitude,
            surface_anomalies, vibration_anomalies, rotation_anomalies,
            sensor1_distance, sensor2_distance, sensor3_distance, sensor4_distance,
            sensor5_distance, sensor6_distance, sensor7_distance, sensor8_distance,
            accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z,
            image_data, image_filename
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s
        )
        """
        
        insert_data = (
            datetime.now(),
            damage_classification['level'],
            damage_classification['score'],
            damage_classification['description'],
            damage_length,
            location.get('latitude'),
            location.get('longitude'),
            json.dumps(surface_anomalies),
            json.dumps(vibration_anomalies),
            json.dumps(rotation_anomalies),
            latest_sensor_data.get('sensor1'),
            latest_sensor_data.get('sensor2'),
            latest_sensor_data.get('sensor3'),
            latest_sensor_data.get('sensor4'),
            latest_sensor_data.get('sensor5'),
            latest_sensor_data.get('sensor6'),
            latest_sensor_data.get('sensor7'),
            latest_sensor_data.get('sensor8'),
            latest_motion_data.get('accelX'),
            latest_motion_data.get('accelY'),
            latest_motion_data.get('accelZ'),
            latest_motion_data.get('gyroX'),
            latest_motion_data.get('gyroY'),
            latest_motion_data.get('gyroZ'),
            image_data,
            os.path.basename(image_path) if image_path else None
        )
        
        cursor.execute(insert_query, insert_data)
        connection.commit()
        
        print(f"✅ Data kerusakan jalan berhasil disimpan ke database")
        print(f"   - Level: {damage_classification['level']}")
        print(f"   - Score: {damage_classification['score']}")
        print(f"   - Location: {location.get('latitude')}, {location.get('longitude')}")
        print(f"   - Length: {damage_length}m")
        
        return True
        
    except Error as e:
        print(f"❌ Error saving to database: {e}")
        return False
    
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

@app.route('/api/sensor-data', methods=['POST'])
def receive_sensor_data():
    """Endpoint untuk menerima data sensor (backup HTTP)"""
    try:
        data = request.get_json()
        print(f"📩 HTTP Data diterima: {data}")
        
        process_esp32_data(data)
        
        return jsonify({
            'status': 'success',
            'message': 'Data received and processed',
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        print(f"❌ Error processing HTTP data: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/road-damage-history', methods=['GET'])
def get_road_damage_history():
    """API untuk mengambil riwayat kerusakan jalan"""
    connection = get_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cursor = connection.cursor(dictionary=True)
        
        # Parameter query
        limit = request.args.get('limit', 50, type=int)
        damage_level = request.args.get('level', None)
        
        query = """
        SELECT id, timestamp, damage_level, damage_score, damage_description,
               damage_length, latitude, longitude, surface_anomalies,
               vibration_anomalies, rotation_anomalies, image_filename
        FROM road_damage_records
        """
        
        params = []
        if damage_level:
            query += " WHERE damage_level = %s"
            params.append(damage_level)
        
        query += " ORDER BY timestamp DESC LIMIT %s"
        params.append(limit)
        
        cursor.execute(query, params)
        records = cursor.fetchall()
        
        # Convert datetime to string
        for record in records:
            if record['timestamp']:
                record['timestamp'] = record['timestamp'].isoformat()
            
            # Parse JSON fields
            try:
                record['surface_anomalies'] = json.loads(record['surface_anomalies']) if record['surface_anomalies'] else []
                record['vibration_anomalies'] = json.loads(record['vibration_anomalies']) if record['vibration_anomalies'] else []
                record['rotation_anomalies'] = json.loads(record['rotation_anomalies']) if record['rotation_anomalies'] else []
            except:
                record['surface_anomalies'] = []
                record['vibration_anomalies'] = []
                record['rotation_anomalies'] = []
        
        return jsonify({
            'status': 'success',
            'data': records,
            'count': len(records)
        })
        
    except Error as e:
        return jsonify({'error': str(e)}), 500
    
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

@app.route('/api/current-sensors', methods=['GET'])
def get_current_sensors():
    """API untuk mengambil data sensor terkini"""
    with data_lock:
        current_data = {
            'timestamp': list(timestamp_history)[-1] if timestamp_history else None,
            'ultrasonic_sensors': {},
            'motion_sensor': {},
            'gps': {}
        }
        
        # Data ultrasonik
        for i in range(8):
            sensor_name = f'sensor{i+1}'
            if len(sensor_data_history[sensor_name]) > 0:
                current_data['ultrasonic_sensors'][sensor_name] = {
                    'current': list(sensor_data_history[sensor_name])[-1],
                    'history': list(sensor_data_history[sensor_name])
                }
        
        # Data motion
        for key in ['accelX', 'accelY', 'accelZ', 'gyroX', 'gyroY', 'gyroZ']:
            if len(motion_data_history[key]) > 0:
                current_data['motion_sensor'][key] = {
                    'current': list(motion_data_history[key])[-1],
                    'history': list(motion_data_history[key])
                }
        
        # Data GPS
        if len(gps_data_history['latitude']) > 0:
            current_data['gps'] = {
                'latitude': list(gps_data_history['latitude'])[-1],
                'longitude': list(gps_data_history['longitude'])[-1]
            }
    
    return jsonify(current_data)

@app.route('/api/force-evaluation', methods=['POST'])
def force_evaluation():
    """API untuk memaksa evaluasi kerusakan jalan"""
    try:
        evaluate_road_damage()
        return jsonify({
            'status': 'success',
            'message': 'Road damage evaluation completed'
        })
    except Exception as e:
        return jsonify({
            'status': 'error', 
            'message': str(e)
        }), 500

@app.route('/static/<filename>')
def serve_static(filename):
    """Serve file statis (gambar)"""
    return app.send_static_file(filename)

@app.route('/')
def index():
    """Dashboard sederhana"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Road Monitoring System</title>
        <meta charset="utf-8">
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            .container { max-width: 1200px; margin: 0 auto; }
            .card { background: #f5f5f5; padding: 20px; margin: 20px 0; border-radius: 8px; }
            .status { padding: 10px; border-radius: 4px; margin: 10px 0; }
            .connected { background: #d4edda; color: #155724; }
            .disconnected { background: #f8d7da; color: #721c24; }
            button { padding: 10px 20px; margin: 10px 5px; border: none; border-radius: 4px; cursor: pointer; }
            .btn-primary { background: #007bff; color: white; }
            .btn-success { background: #28a745; color: white; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🛣️ Road Monitoring System</h1>
            
            <div class="card">
                <h2>System Status</h2>
                <div id="mqtt-status" class="status disconnected">MQTT: Disconnected</div>
                <div id="thingsboard-status" class="status disconnected">ThingsBoard: Disconnected</div>
            </div>
            
            <div class="card">
                <h2>Controls</h2>
                <button class="btn-primary" onclick="forceEvaluation()">Force Road Evaluation</button>
                <button class="btn-success" onclick="getCurrentData()">Get Current Sensor Data</button>
            </div>
            
            <div class="card">
                <h2>Recent Road Damage Records</h2>
                <div id="damage-records">Loading...</div>
            </div>
        </div>
        
        <script>
            // Update status
            function updateStatus() {
                // Status MQTT dan ThingsBoard bisa diupdate via API terpisah
                document.getElementById('mqtt-status').textContent = 'MQTT: ' + (true ? 'Connected' : 'Disconnected');
                document.getElementById('mqtt-status').className = 'status ' + (true ? 'connected' : 'disconnected');
                
                document.getElementById('thingsboard-status').textContent = 'ThingsBoard: ' + (true ? 'Connected' : 'Disconnected');
                document.getElementById('thingsboard-status').className = 'status ' + (true ? 'connected' : 'disconnected');
            }
            
            function forceEvaluation() {
                fetch('/api/force-evaluation', { method: 'POST' })
                    .then(response => response.json())
                    .then(data => {
                        alert('Evaluation: ' + data.message);
                        loadDamageRecords();
                    })
                    .catch(error => alert('Error: ' + error));
            }
            
            function getCurrentData() {
                fetch('/api/current-sensors')
                    .then(response => response.json())
                    .then(data => {
                        console.log('Current sensor data:', data);
                        alert('Check console for current sensor data');
                    })
                    .catch(error => alert('Error: ' + error));
            }
            
            function loadDamageRecords() {
                fetch('/api/road-damage-history?limit=10')
                    .then(response => response.json())
                    .then(data => {
                        let html = '<table border="1" style="width:100%; border-collapse: collapse;">';
                        html += '<tr><th>Timestamp</th><th>Level</th><th>Description</th><th>Length (m)</th><th>Location</th></tr>';
                        
                        if (data.data && data.data.length > 0) {
                            data.data.forEach(record => {
                                html += '<tr>';
                                html += '<td>' + new Date(record.timestamp).toLocaleString() + '</td>';
                                html += '<td>' + record.damage_level + '</td>';
                                html += '<td>' + record.damage_description + '</td>';
                                html += '<td>' + (record.damage_length || 'N/A') + '</td>';
                                html += '<td>' + (record.latitude ? record.latitude.toFixed(6) + ', ' + record.longitude.toFixed(6) : 'N/A') + '</td>';
                                html += '</tr>';
                            });
                        } else {
                            html += '<tr><td colspan="5">No records found</td></tr>';
                        }
                        
                        html += '</table>';
                        document.getElementById('damage-records').innerHTML = html;
                    })
                    .catch(error => {
                        document.getElementById('damage-records').innerHTML = 'Error loading records: ' + error;
                    });
            }
            
            // Load initial data
            updateStatus();
            loadDamageRecords();
            
            // Refresh every 30 seconds
            setInterval(() => {
                updateStatus();
                loadDamageRecords();
            }, 30000);
        </script>
    </body>
    </html>
    """

def init_database():
    """Inisialisasi database dan tabel"""
    connection = get_db_connection()
    if not connection:
        print("❌ Tidak dapat terhubung ke database untuk inisialisasi")
        return False
    
    try:
        cursor = connection.cursor()
        
        # Buat database jika belum ada
        cursor.execute("CREATE DATABASE IF NOT EXISTS road_monitoring_v2")
        cursor.execute("USE road_monitoring_v2")
        
        # Buat tabel road_damage_records
        create_table_query = """
        CREATE TABLE IF NOT EXISTS road_damage_records (
            id INT AUTO_INCREMENT PRIMARY KEY,
            timestamp DATETIME NOT NULL,
            damage_level ENUM('normal', 'light', 'medium', 'severe') NOT NULL,
            damage_score FLOAT NOT NULL,
            damage_description TEXT,
            damage_length FLOAT DEFAULT 0,
            latitude DECIMAL(10, 8) NULL,
            longitude DECIMAL(11, 8) NULL,
            surface_anomalies JSON,
            vibration_anomalies JSON,
            rotation_anomalies JSON,
            sensor1_distance FLOAT NULL,
            sensor2_distance FLOAT NULL,
            sensor3_distance FLOAT NULL,
            sensor4_distance FLOAT NULL,
            sensor5_distance FLOAT NULL,
            sensor6_distance FLOAT NULL,
            sensor7_distance FLOAT NULL,
            sensor8_distance FLOAT NULL,
            accel_x FLOAT NULL,
            accel_y FLOAT NULL,
            accel_z FLOAT NULL,
            gyro_x FLOAT NULL,
            gyro_y FLOAT NULL,
            gyro_z FLOAT NULL,
            image_data LONGTEXT NULL,
            image_filename VARCHAR(255) NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_timestamp (timestamp),
            INDEX idx_damage_level (damage_level),
            INDEX idx_location (latitude, longitude)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
        
        cursor.execute(create_table_query)
        
        # Buat tabel untuk log sensor (opsional, untuk debugging)
        sensor_log_query = """
        CREATE TABLE IF NOT EXISTS sensor_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sensor_type ENUM('ultrasonic', 'gps', 'motion') NOT NULL,
            sensor_data JSON NOT NULL,
            raw_data TEXT,
            INDEX idx_timestamp (timestamp),
            INDEX idx_sensor_type (sensor_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
        
        cursor.execute(sensor_log_query)
        
        connection.commit()
        print("✅ Database dan tabel berhasil diinisialisasi")
        return True
        
    except Error as e:
        print(f"❌ Error initializing database: {e}")
        return False
    
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

if __name__ == '__main__':
    print("🚀 Starting Road Monitoring System...")
    
    # Inisialisasi database
    print("📊 Initializing database...")
    if not init_database():
        print("⚠️ Database initialization failed, but continuing...")
    
    # Setup MQTT clients
    print("📡 Setting up MQTT clients...")
    setup_mqtt_clients()
    
    # Give some time for MQTT to connect
    time.sleep(2)
    
    print("🌐 Starting Flask server...")
    print("📍 Dashboard available at: http://localhost:5000")
    print("📡 MQTT Topic (ESP32): " + FLASK_MQTT_TOPIC)
    print("📊 ThingsBoard URL: https://demo.thingsboard.io")
    print()
    print("=== ROAD DAMAGE THRESHOLDS ===")
    print("Surface Change: Light >2cm, Medium >5cm, Severe >10cm")
    print("Vibration: Light >2000, Medium >5000, Severe >10000")
    print("Rotation: Light >100°/s, Medium >300°/s, Severe >500°/s")
    print("Evaluation Interval: 30 seconds")
    print("=====================================")
    
    # Jalankan Flask app
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)