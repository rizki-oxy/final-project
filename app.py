from flask import Flask, request, jsonify
import requests
import numpy as np
import matplotlib
matplotlib.use('Agg')  # menggunakan mode non-GUI
import matplotlib.pyplot as plt
import os
import time
import json
from datetime import datetime
from collections import deque
import threading
import math
import mysql.connector
from mysql.connector import Error
import base64
import paho.mqtt.client as mqtt_client

app = Flask(__name__)

# Konfigurasi ThingsBoard
THINGSBOARD_TOKEN = 'r7DUFq0R2PXLNNvmSZwp'
THINGSBOARD_URL = f"https://demo.thingsboard.io/api/v1/{THINGSBOARD_TOKEN}/telemetry"
UPLOAD_FOLDER = 'static'

# Konfigurasi MQTT Broker untuk Flask
FLASK_MQTT_BROKER = "localhost"  # Ganti dengan IP server Flask jika berbeda
FLASK_MQTT_PORT = 1883
FLASK_MQTT_TOPIC = "sensor/road_monitoring"
FLASK_RESPONSE_TOPIC = "sensor/road_monitoring/response"

# Konfigurasi MySQL Database
DB_CONFIG = {
    'host': 'localhost',
    'database': 'road_monitoring',
    'user': 'root',  # sesuaikan dengan username MySQL Anda
    'password': '',  # sesuaikan dengan password MySQL Anda
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
last_saved_time = 0
SAVE_COOLDOWN = 5  # minimal jeda 5 detik antara penyimpanan gambar

# Lock untuk thread safety saat akses data history
data_lock = threading.Lock()

# Threshold untuk deteksi anomali
VIBRATION_THRESHOLD = 2000  # Threshold untuk deteksi getaran
ROTATION_THRESHOLD = 500    # Threshold untuk deteksi rotasi
DISTANCE_CHANGE_THRESHOLD = 2  # Threshold perubahan jarak (cm)

# MQTT Client untuk Flask
mqtt_client_flask = None
mqtt_connected = False

def setup_mqtt_client():
    """Setup MQTT client untuk menerima data dari ESP32"""
    global mqtt_client_flask, mqtt_connected
    
    def on_connect(client, userdata, flags, rc):
        global mqtt_connected
        if rc == 0:
            print("✅ MQTT Client terhubung ke broker")
            mqtt_connected = True
            client.subscribe(FLASK_MQTT_TOPIC)
            print(f"📡 Subscribed to topic: {FLASK_MQTT_TOPIC}")
        else:
            print(f"❌ Gagal terhubung ke MQTT broker, return code {rc}")
            mqtt_connected = False
    
    def on_disconnect(client, userdata, rc):
        global mqtt_connected
        mqtt_connected = False
        print(f"🔌 MQTT Client terputus, return code {rc}")
    
    def on_message(client, userdata, msg):
        """Callback ketika menerima pesan MQTT dari ESP32"""
        try:
            # Decode pesan JSON
            payload = msg.payload.decode('utf-8')
            print(f"📩 MQTT Data diterima dari ESP32: {payload}")
            
            data = json.loads(payload)
            process_sensor_data(data)
            
            # Kirim response ke ESP32 (opsional)
            response = {
                "status": "received",
                "timestamp": datetime.now().isoformat(),
                "data_processed": True
            }
            client.publish(FLASK_RESPONSE_TOPIC, json.dumps(response))
            
        except json.JSONDecodeError as e:
            print(f"❌ Error parsing JSON dari MQTT: {e}")
        except Exception as e:
            print(f"❌ Error processing MQTT message: {e}")
    
    # Setup MQTT client
    mqtt_client_flask = mqtt_client.Client()
    mqtt_client_flask.on_connect = on_connect
    mqtt_client_flask.on_disconnect = on_disconnect
    mqtt_client_flask.on_message = on_message
    
    try:
        mqtt_client_flask.connect(FLASK_MQTT_BROKER, FLASK_MQTT_PORT, 60)
        mqtt_client_flask.loop_start()  # Start loop in background thread
        print("🚀 MQTT Client dimulai...")
    except Exception as e:
        print(f"❌ Gagal memulai MQTT client: {e}")

def process_sensor_data(data):
    """Memproses data sensor yang diterima dari ESP32 (via MQTT atau HTTP)"""
    global last_saved_time
    
    print("📊 Memproses data sensor...")
    
    # Catat waktu penerimaan data
    current_time = time.time()
    current_timestamp = datetime.now().strftime('%H:%M:%S')
    
    # Kirim ke ThingsBoard (backup/redundancy)
    try:
        response = requests.post(THINGSBOARD_URL, json=data, timeout=5)
        print("✅ Kirim ke ThingsBoard:", response.status_code)
    except Exception as e:
        print("❌ Gagal kirim ke ThingsBoard:", e)
        response = None
    
    # Proses data ultrasonic
    current_distances = [data.get(f'sensor{i+1}', -1) for i in range(8)]
    
    # Proses data GPS
    gps_data = {
        'latitude': data.get('latitude', None),
        'longitude': data.get('longitude', None),
        'speed': data.get('speed', None),
        'satellites': data.get('satellites', None)
    }
    
    # Proses data motion sensor (MPU6050)
    motion_data = {
        'accelX': data.get('accelX', None),
        'accelY': data.get('accelY', None),
        'accelZ': data.get('accelZ', None),
        'gyroX': data.get('gyroX', None),
        'gyroY': data.get('gyroY', None),
        'gyroZ': data.get('gyroZ', None)
    }
    
    # Update history data dengan thread safety
    with data_lock:
        timestamp_history.append(current_timestamp)
        
        # Update ultrasonic data history
        for i in range(8):
            sensor_name = f'sensor{i+1}'
            sensor_data_history[sensor_name].append(current_distances[i])
        
        # Update GPS data history
        if gps_data['latitude'] is not None:
            gps_data_history['latitude'].append(gps_data['latitude'])
            gps_data_history['longitude'].append(gps_data['longitude'])
        
        # Update motion data history
        for key in motion_data:
            if motion_data[key] is not None:
                motion_data_history[key].append(motion_data[key])
    
    # Deteksi anomali
    anomalies = detect_anomalies(current_distances, motion_data, gps_data)
    
    # Cek apakah perlu menyimpan visualisasi
    should_save = len(anomalies) > 0
    comprehensive_plot_path = None
    
    # Simpan gambar jika kondisi terpenuhi dan cooldown telah lewat
    if should_save and (current_time - last_saved_time) >= SAVE_COOLDOWN:
        try:
            comprehensive_plot_path = save_comprehensive_plots(anomalies)
            last_saved_time = current_time
            
            # Simpan setiap anomali ke database
            for anomaly in anomalies:
                save_anomaly_to_database(
                    anomaly, 
                    current_distances, 
                    motion_data, 
                    gps_data, 
                    comprehensive_plot_path
                )
                
        except Exception as e:
            print("❌ Gagal menyimpan visualisasi:", e)
    
    # Visualisasi data terbaru
    try:
        create_current_data_visualization(current_distances, motion_data, gps_data)
    except Exception as e:
        print("❌ Gagal buat visualisasi data terbaru:", e)
    
    print(f"✅ Data berhasil diproses. Anomali: {len(anomalies)}")

def get_db_connection():
    """Membuat koneksi ke database MySQL"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        if connection.is_connected():
            return connection
    except Error as e:
        print(f"❌ Error connecting to MySQL: {e}")
        return None

def save_anomaly_to_database(anomaly_data, sensor_data, motion_data, gps_data, image_path=None):
    """Menyimpan data anomali ke database MySQL"""
    connection = get_db_connection()
    if not connection:
        return False
    
    try:
        cursor = connection.cursor()
        
        # Encode gambar ke base64 jika ada
        image_data = None
        if image_path and os.path.exists(image_path):
            with open(image_path, 'rb') as img_file:
                image_data = base64.b64encode(img_file.read()).decode('utf-8')
        
        # Prepare data untuk insert
        insert_query = """
        INSERT INTO anomaly_records (
            timestamp, anomaly_type, anomaly_details,
            sensor1_distance, sensor2_distance, sensor3_distance, sensor4_distance,
            sensor5_distance, sensor6_distance, sensor7_distance, sensor8_distance,
            accel_x, accel_y, accel_z, accel_magnitude,
            gyro_x, gyro_y, gyro_z, rotation_magnitude,
            latitude, longitude, speed, satellites,
            image_data, image_filename
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        """
        
        # Hitung magnitude untuk motion data
        accel_magnitude = None
        rotation_magnitude = None
        
        if all(motion_data.get(key) is not None for key in ['accelX', 'accelY', 'accelZ']):
            accel_magnitude = math.sqrt(
                motion_data['accelX']**2 + 
                motion_data['accelY']**2 + 
                motion_data['accelZ']**2
            )
        
        if all(motion_data.get(key) is not None for key in ['gyroX', 'gyroY', 'gyroZ']):
            rotation_magnitude = math.sqrt(
                (motion_data['gyroX']/131.0)**2 + 
                (motion_data['gyroY']/131.0)**2 + 
                (motion_data['gyroZ']/131.0)**2
            )
        
        # Data untuk insert
        insert_data = (
            datetime.now(),  # timestamp
            anomaly_data.get('type', 'unknown'),  # anomaly_type
            json.dumps(anomaly_data),  # anomaly_details (JSON string)
            
            # Ultrasonic sensor data (8 sensors)
            sensor_data[0] if len(sensor_data) > 0 else None,
            sensor_data[1] if len(sensor_data) > 1 else None,
            sensor_data[2] if len(sensor_data) > 2 else None,
            sensor_data[3] if len(sensor_data) > 3 else None,
            sensor_data[4] if len(sensor_data) > 4 else None,
            sensor_data[5] if len(sensor_data) > 5 else None,
            sensor_data[6] if len(sensor_data) > 6 else None,
            sensor_data[7] if len(sensor_data) > 7 else None,
            
            # Motion sensor data
            motion_data.get('accelX'),
            motion_data.get('accelY'),
            motion_data.get('accelZ'),
            accel_magnitude,
            motion_data.get('gyroX'),
            motion_data.get('gyroY'),
            motion_data.get('gyroZ'),
            rotation_magnitude,
            
            # GPS data
            gps_data.get('latitude'),
            gps_data.get('longitude'),
            gps_data.get('speed'),
            gps_data.get('satellites'),
            
            # Image data
            image_data,
            os.path.basename(image_path) if image_path else None
        )
        
        cursor.execute(insert_query, insert_data)
        connection.commit()
        
        print(f"✅ Data anomali berhasil disimpan ke database: {anomaly_data.get('type')}")
        return True
        
    except Error as e:
        print(f"❌ Error saving to database: {e}")
        return False
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

# Endpoint HTTP untuk backward compatibility dan testing
@app.route('/multisensor', methods=['POST'])
def multisensor():
    """Endpoint HTTP untuk backward compatibility"""
    data = request.get_json()
    print("📩 HTTP Multi-sensor data diterima:", data)
    
    process_sensor_data(data)
    
    return jsonify({
        "status": "success",
        "message": "Data processed via HTTP",
        "mqtt_connected": mqtt_connected,
        "current_data_image": "/static/current_data.png",
        "comprehensive_plot": "/static/comprehensive_plot.png"
    }), 200

# Endpoint untuk backward compatibility
@app.route('/ultrasonic', methods=['POST'])
def ultrasonic():
    """Endpoint untuk kompatibilitas dengan kode lama"""
    return multisensor()

def detect_anomalies(distances, motion_data, gps_data):
    """Deteksi berbagai jenis anomali berdasarkan data sensor"""
    anomalies = []
    
    # 1. Deteksi perubahan permukaan jalan (ultrasonic)
    with data_lock:
        if len(list(sensor_data_history.values())[0]) >= 2:
            for i in range(8):
                sensor_name = f'sensor{i+1}'
                if len(sensor_data_history[sensor_name]) >= 2:
                    last_idx = len(sensor_data_history[sensor_name]) - 1
                    current = sensor_data_history[sensor_name][last_idx]
                    previous = sensor_data_history[sensor_name][last_idx - 1]
                    if abs(current - previous) > DISTANCE_CHANGE_THRESHOLD:
                        anomalies.append({
                            'type': 'surface_change',
                            'sensor': sensor_name,
                            'change': abs(current - previous),
                            'previous': previous,
                            'current': current,
                            'severity': 'high' if abs(current - previous) > 5 else 'medium'
                        })
                        print(f"⚠️ Perubahan permukaan pada {sensor_name}: {previous} -> {current}")
    
    # 2. Deteksi getaran/guncangan (accelerometer)
    if all(motion_data[key] is not None for key in ['accelX', 'accelY', 'accelZ']):
        accel_magnitude = math.sqrt(motion_data['accelX']**2 + motion_data['accelY']**2 + motion_data['accelZ']**2)
        
        with data_lock:
            if len(motion_data_history['accelX']) >= 2:
                prev_accelX = motion_data_history['accelX'][-2]
                prev_accelY = motion_data_history['accelY'][-2] 
                prev_accelZ = motion_data_history['accelZ'][-2]
                prev_magnitude = math.sqrt(prev_accelX**2 + prev_accelY**2 + prev_accelZ**2)
                
                accel_change = abs(accel_magnitude - prev_magnitude)
                if accel_change > VIBRATION_THRESHOLD:
                    anomalies.append({
                        'type': 'vibration',
                        'magnitude': accel_magnitude,
                        'change': accel_change,
                        'severity': 'critical' if accel_change > 5000 else 'high'
                    })
                    print(f"📳 Getaran terdeteksi: {accel_change}")
    
    # 3. Deteksi rotasi berlebihan (gyroscope)
    if all(motion_data[key] is not None for key in ['gyroX', 'gyroY', 'gyroZ']):
        # Konversi ke degrees per second
        rotX = motion_data['gyroX'] / 131.0
        rotY = motion_data['gyroY'] / 131.0
        rotZ = motion_data['gyroZ'] / 131.0
        
        if abs(rotX) > ROTATION_THRESHOLD or abs(rotY) > ROTATION_THRESHOLD or abs(rotZ) > ROTATION_THRESHOLD:
            max_rotation = max(abs(rotX), abs(rotY), abs(rotZ))
            anomalies.append({
                'type': 'excessive_rotation',
                'rotX': rotX,
                'rotY': rotY,
                'rotZ': rotZ,
                'max_rotation': max_rotation,
                'severity': 'critical' if max_rotation > 1000 else 'high'
            })
            print(f"🔄 Rotasi berlebihan: X={rotX}, Y={rotY}, Z={rotZ}")
    
    # 4. Deteksi kecepatan tinggi (GPS)
    if gps_data.get('speed') is not None and gps_data['speed'] > 80:  # > 80 km/h
        anomalies.append({
            'type': 'high_speed',
            'speed': gps_data['speed'],
            'severity': 'critical' if gps_data['speed'] > 120 else 'medium'
        })
        print(f"🚗 Kecepatan tinggi: {gps_data['speed']} km/h")
    
    return anomalies

def create_current_data_visualization(distances, motion_data, gps_data):
    """Membuat visualisasi komprehensif data terbaru"""
    
    # Buat subplot untuk berbagai jenis data
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 10))
    
    # 1. Ultrasonic sensor data
    ax1.bar(range(1, 9), distances, color='skyblue')
    ax1.set_title('Data Sensor Ultrasonik Terbaru')
    ax1.set_xlabel('Sensor ke-')
    ax1.set_ylabel('Jarak (cm)')
    ax1.set_xticks(range(1, 9))
    ax1.grid(True, axis='y')
    
    # 2. Accelerometer data
    if all(motion_data[key] is not None for key in ['accelX', 'accelY', 'accelZ']):
        accel_values = [motion_data['accelX'], motion_data['accelY'], motion_data['accelZ']]
        ax2.bar(['X', 'Y', 'Z'], accel_values, color=['red', 'green', 'blue'])
        ax2.set_title('Data Accelerometer')
        ax2.set_ylabel('Nilai Raw')
        ax2.grid(True, axis='y')
    else:
        ax2.text(0.5, 0.5, 'Motion Sensor\nTidak Tersedia', ha='center', va='center', transform=ax2.transAxes)
        ax2.set_title('Data Accelerometer')
    
    # 3. Gyroscope data
    if all(motion_data[key] is not None for key in ['gyroX', 'gyroY', 'gyroZ']):
        gyro_values = [motion_data['gyroX']/131.0, motion_data['gyroY']/131.0, motion_data['gyroZ']/131.0]
        ax3.bar(['X', 'Y', 'Z'], gyro_values, color=['orange', 'purple', 'brown'])
        ax3.set_title('Data Gyroscope')
        ax3.set_ylabel('Derajat/detik')
        ax3.grid(True, axis='y')
    else:
        ax3.text(0.5, 0.5, 'Gyroscope\nTidak Tersedia', ha='center', va='center', transform=ax3.transAxes)
        ax3.set_title('Data Gyroscope')
    
    # 4. GPS info
    if gps_data.get('latitude') is not None:
        info_text = f"📍 Lat: {gps_data['latitude']:.6f}\n"
        info_text += f"📍 Lng: {gps_data['longitude']:.6f}\n"
        if gps_data.get('speed') is not None:
            info_text += f"🚗 Speed: {gps_data['speed']:.1f} km/h\n"
        if gps_data.get('satellites') is not None:
            info_text += f"🛰️ Satellites: {gps_data['satellites']}"
        
        ax4.text(0.1, 0.5, info_text, ha='left', va='center', transform=ax4.transAxes, fontsize=12)
        ax4.set_title('Data GPS')
        ax4.axis('off')
    else:
        ax4.text(0.5, 0.5, 'GPS\nTidak Tersedia', ha='center', va='center', transform=ax4.transAxes)
        ax4.set_title('Data GPS')
        ax4.axis('off')
    
    plt.tight_layout()
    current_chart_path = os.path.join(UPLOAD_FOLDER, 'current_data.png')
    plt.savefig(current_chart_path, dpi=100, bbox_inches='tight')
    plt.close()
    print("📷 Visualisasi data terbaru disimpan:", current_chart_path)

def save_comprehensive_plots(anomalies):
    """Menyimpan plot komprehensif saat ada anomali"""
    
    with data_lock:
        if len(timestamp_history) < 2:
            print("⚠️ Tidak cukup data untuk membuat time series")
            return None
        
        # Buat figure dengan multiple subplots
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        
        # 1. Time series ultrasonic sensors
        colors = ['blue', 'red', 'green', 'orange', 'purple', 'brown', 'pink', 'gray']
        for i in range(8):
            sensor_name = f'sensor{i+1}'
            if len(sensor_data_history[sensor_name]) > 0:
                ax1.plot(
                    list(timestamp_history), 
                    list(sensor_data_history[sensor_name]),
                    label=sensor_name,
                    color=colors[i],
                    marker='o',
                    markersize=2,
                    linewidth=1
                )
        
        ax1.set_title('Time Series - Sensor Ultrasonik (30s Terakhir)')
        ax1.set_xlabel('Waktu')
        ax1.set_ylabel('Jarak (cm)')
        ax1.grid(True)
        ax1.legend(loc='upper right', fontsize=8)
        ax1.tick_params(axis='x', rotation=45)
        
        # 2. Accelerometer time series
        if len(motion_data_history['accelX']) > 0:
            ax2.plot(list(timestamp_history)[-len(motion_data_history['accelX']):], 
                    list(motion_data_history['accelX']), 'r-', label='AccelX')
            ax2.plot(list(timestamp_history)[-len(motion_data_history['accelY']):], 
                    list(motion_data_history['accelY']), 'g-', label='AccelY')
            ax2.plot(list(timestamp_history)[-len(motion_data_history['accelZ']):], 
                    list(motion_data_history['accelZ']), 'b-', label='AccelZ')
            ax2.set_title('Time Series - Accelerometer')
            ax2.set_xlabel('Waktu')
            ax2.set_ylabel('Nilai Raw')
            ax2.legend()
            ax2.grid(True)
            ax2.tick_params(axis='x', rotation=45)
        else:
            ax2.text(0.5, 0.5, 'Data Accelerometer\nTidak Tersedia', ha='center', va='center', transform=ax2.transAxes)
            ax2.set_title('Time Series - Accelerometer')
        
        # 3. Gyroscope time series
        if len(motion_data_history['gyroX']) > 0:
            # Konversi ke degrees per second
            gyroX_dps = [x/131.0 for x in motion_data_history['gyroX']]
            gyroY_dps = [y/131.0 for y in motion_data_history['gyroY']]
            gyroZ_dps = [z/131.0 for z in motion_data_history['gyroZ']]
            
            ax3.plot(list(timestamp_history)[-len(gyroX_dps):], gyroX_dps, 'r-', label='GyroX')
            ax3.plot(list(timestamp_history)[-len(gyroY_dps):], gyroY_dps, 'g-', label='GyroY')
            ax3.plot(list(timestamp_history)[-len(gyroZ_dps):], gyroZ_dps, 'b-', label='GyroZ')
            ax3.set_title('Time Series - Gyroscope')
            ax3.set_xlabel('Waktu')
            ax3.set_ylabel('Derajat/detik')
            ax3.legend()
            ax3.grid(True)
            ax3.tick_params(axis='x', rotation=45)
        else:
            ax3.text(0.5, 0.5, 'Data Gyroscope\nTidak Tersedia', ha='center', va='center', transform=ax3.transAxes)
            ax3.set_title('Time Series - Gyroscope')
        
        # 4. Anomaly summary
        anomaly_text = "🚨 ANOMALI TERDETEKSI:\n\n"
        for i, anomaly in enumerate(anomalies):
            if anomaly['type'] == 'surface_change':
                anomaly_text += f"• Perubahan permukaan {anomaly['sensor']}: {anomaly['change']:.1f}cm\n"
            elif anomaly['type'] == 'vibration':
                anomaly_text += f"• Getaran: {anomaly['change']:.0f}\n"
            elif anomaly['type'] == 'excessive_rotation':
                anomaly_text += f"• Rotasi berlebihan: X={anomaly['rotX']:.1f}°/s\n"
            elif anomaly['type'] == 'high_speed':
                anomaly_text += f"• Kecepatan tinggi: {anomaly['speed']:.1f} km/h\n"
        
        ax4.text(0.05, 0.95, anomaly_text, ha='left', va='top', transform=ax4.transAxes, 
                fontsize=10, bbox=dict(boxstyle="round,pad=0.3", facecolor="yellow", alpha=0.7))
        ax4.set_title('Ringkasan Anomali')
        ax4.axis('off')
        
        plt.tight_layout()
        
        # Simpan dengan timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filepath = os.path.join(UPLOAD_FOLDER, f'comprehensive_plot_{timestamp}.png')
        plt.savefig(filepath, dpi=100, bbox_inches='tight')
        
        # Simpan juga dengan nama tetap untuk referensi API
        fixed_filepath = os.path.join(UPLOAD_FOLDER, 'comprehensive_plot.png')
        plt.savefig(fixed_filepath, dpi=100, bbox_inches='tight')
        
        plt.close()
        print(f"📷 Plot komprehensif disimpan: {filepath}")
        
        return filepath

@app.route('/status', methods=['GET'])
def status():
    """Endpoint untuk cek status sistem"""
    with data_lock:
        return jsonify({
            "system_status": "running",
            "data_points": len(timestamp_history),
            "mqtt_connected": mqtt_connected,
            "sensors_active": {
                "ultrasonic": len([s for s in sensor_data_history.values() if len(s) > 0]),
                "gps": len(gps_data_history['latitude']) > 0,
                "motion": len(motion_data_history['accelX']) > 0
            },
            "last_update": list(timestamp_history)[-1] if len(timestamp_history) > 0 else "Never"
        })
        
@app.route('/anomalies', methods=['GET'])
def get_anomalies():
    """Endpoint untuk mengambil data anomali dari database"""
    connection = get_db_connection()
    if not connection:
        return jsonify({"error": "Database connection failed"}), 500
    
    try:
        cursor = connection.cursor(dictionary=True)
        
        # Parameter untuk pagination
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        anomaly_type = request.args.get('type', None)
        
        # Query dasar
        base_query = "SELECT * FROM anomaly_records"
        count_query = "SELECT COUNT(*) as total FROM anomaly_records"
        
        # Filter berdasarkan tipe anomali jika ada
        where_clause = ""
        params = []
        if anomaly_type:
            where_clause = " WHERE anomaly_type = %s"
            params = [anomaly_type]
        
        # Query untuk menghitung total
        cursor.execute(count_query + where_clause, params)
        total_count = cursor.fetchone()['total']
        
        # Query untuk data dengan pagination
        main_query = base_query + where_clause + " ORDER BY timestamp DESC LIMIT %s OFFSET %s"
        cursor.execute(main_query, params + [limit, offset])
        
        anomalies = cursor.fetchall()
        
        # Convert JSON strings back to objects
        for anomaly in anomalies:
            if anomaly['anomaly_details']:
                anomaly['anomaly_details'] = json.loads(anomaly['anomaly_details'])
        
        return jsonify({
            "total": total_count,
            "count": len(anomalies),
            "anomalies": anomalies
        })
        
    except Error as e:
        print(f"❌ Error fetching anomalies: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

if __name__ == '__main__':
    print("🚀 Multi-Sensor Flask Server with MySQL Starting...")
    print("📡 Endpoints available:")
    print("   - POST /multisensor  : Main endpoint for ESP32 data")
    print("   - POST /ultrasonic   : Backward compatibility endpoint")
    print("   - GET  /status       : System status check")
    print("   - GET  /anomalies    : Get anomaly records from database")
    print("🌐 Server running on http://0.0.0.0:5000")
    
    # Setup MQTT client sebelum menjalankan server
    setup_mqtt_client()
    
    # Test database connection
    test_conn = get_db_connection()
    if test_conn:
        print("✅ Database connection successful")
        test_conn.close()
    else:
        print("❌ Database connection failed - please check configuration")
    
    app.run(host='0.0.0.0', port=5000, debug=True)