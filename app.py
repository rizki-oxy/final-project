from flask import Flask, request, jsonify
import requests
import numpy as np
import matplotlib
matplotlib.use('Agg')  # menggunakan mode non-GUI
import matplotlib.pyplot as plt
import os
import time
from datetime import datetime
from collections import deque
import threading

app = Flask(__name__)

# Konfigurasi ThingsBoard
THINGSBOARD_TOKEN = 'r7DUFq0R2PXLNNvmSZwp'
THINGSBOARD_URL = f"https://demo.thingsboard.io/api/v1/{THINGSBOARD_TOKEN}/telemetry"
UPLOAD_FOLDER = 'static'

# Pastikan folder static ada
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Variabel untuk menyimpan data time series (30 detik terakhir)
MAX_TIME_WINDOW = 30  # 30 detik
sensor_data_history = {f'sensor{i+1}': deque(maxlen=MAX_TIME_WINDOW) for i in range(8)}
timestamp_history = deque(maxlen=MAX_TIME_WINDOW)
last_saved_time = 0
SAVE_COOLDOWN = 5  # minimal jeda 5 detik antara penyimpanan gambar

# Lock untuk thread safety saat akses data history
data_lock = threading.Lock()

@app.route('/ultrasonic', methods=['POST'])
def ultrasonic():
    global last_saved_time
    
    data = request.get_json()
    print("📩 Data diterima dari ESP32:", data)
    
    # Catat waktu penerimaan data
    current_time = time.time()
    current_timestamp = datetime.now().strftime('%H:%M:%S')
    
    # Kirim ke ThingsBoard
    try:
        response = requests.post(THINGSBOARD_URL, json=data)
        print("✅ Kirim ke ThingsBoard:", response.status_code, response.text)
    except Exception as e:
        print("❌ Gagal kirim ke ThingsBoard:", e)
        response = None
    
    # Ambil data sensor terbaru
    current_distances = [data.get(f'sensor{i+1}', -1) for i in range(8)]
    
    # Update history data dengan thread safety
    with data_lock:
        timestamp_history.append(current_timestamp)
        for i in range(8):
            sensor_name = f'sensor{i+1}'
            sensor_data_history[sensor_name].append(current_distances[i])
    
    # Cek apakah ada perubahan permukaan > 2cm
    should_save = False
    if len(list(sensor_data_history.values())[0]) >= 2:  # Minimal 2 data untuk perbandingan
        with data_lock:
            for i in range(8):
                sensor_name = f'sensor{i+1}'
                if len(sensor_data_history[sensor_name]) >= 2:
                    last_idx = len(sensor_data_history[sensor_name]) - 1
                    current = sensor_data_history[sensor_name][last_idx]
                    previous = sensor_data_history[sensor_name][last_idx - 1]
                    if abs(current - previous) > 2:  # Perubahan lebih dari 2cm
                        should_save = True
                        print(f"⚠️ Perubahan signifikan terdeteksi pada {sensor_name}: {previous} -> {current}")
                        break
    
    # Simpan gambar jika kondisi terpenuhi dan cooldown telah lewat
    if should_save and (current_time - last_saved_time) >= SAVE_COOLDOWN:
        try:
            save_time_series_plot()
            last_saved_time = current_time
        except Exception as e:
            print("❌ Gagal menyimpan visualisasi time series:", e)
    
    # Visualisasi data terbaru (bukan time series)
    try:
        # Visualisasi data terbaru sebagai bar chart
        plt.figure(figsize=(8, 4))
        plt.bar(range(1, 9), current_distances, color='skyblue')
        plt.title('Data Sensor Ultrasonik Terbaru')
        plt.xlabel('Sensor ke-')
        plt.ylabel('Jarak (cm)')
        plt.xticks(range(1, 9))
        plt.grid(True, axis='y')
        
        current_chart_path = os.path.join(UPLOAD_FOLDER, 'current_data.png')
        plt.savefig(current_chart_path)
        plt.close()
        print("📷 Data terbaru disimpan:", current_chart_path)
    except Exception as e:
        print("❌ Gagal buat visualisasi data terbaru:", e)
    
    return jsonify({
        "status": "success",
        "thingsboard_response": response.text if response else "Failed to send",
        "current_data_image": "/static/current_data.png",
        "time_series_image": "/static/time_series.png" if should_save and (current_time - last_saved_time) >= SAVE_COOLDOWN else None
    }), 200

def save_time_series_plot():
    """
    Menyimpan plot time series dari 8 sensor selama 30 detik terakhir
    """
    with data_lock:
        # Pastikan ada data sebelum membuat plot
        if len(timestamp_history) < 2:
            print("⚠️ Tidak cukup data untuk membuat time series")
            return
        
        # Buat figure untuk time series
        plt.figure(figsize=(12, 6))
        
        # Daftar warna untuk masing-masing sensor
        colors = ['blue', 'red', 'green', 'orange', 'purple', 'brown', 'pink', 'gray']
        
        # Plot data setiap sensor
        for i in range(8):
            sensor_name = f'sensor{i+1}'
            plt.plot(
                list(timestamp_history), 
                list(sensor_data_history[sensor_name]),
                label=sensor_name,
                color=colors[i],
                marker='o',
                markersize=3,
                linewidth=2
            )
        
        plt.title('Time Series Data Sensor Ultrasonik (30 Detik Terakhir)')
        plt.xlabel('Waktu')
        plt.ylabel('Jarak (cm)')
        plt.grid(True)
        plt.legend(loc='upper right')
        
        # Rotasi label waktu untuk keterbacaan
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        # Simpan gambar
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filepath = os.path.join(UPLOAD_FOLDER, f'time_series_{timestamp}.png')
        plt.savefig(filepath)
        
        # Simpan juga dengan nama tetap untuk referensi API
        fixed_filepath = os.path.join(UPLOAD_FOLDER, 'time_series.png')
        plt.savefig(fixed_filepath)
        
        plt.close()
        print(f"📷 Time series disimpan: {filepath}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

