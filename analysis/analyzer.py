from thresholds import (
    MIN_DATA_POINTS, ANALYSIS_INTERVAL, EARTH_RADIUS, MAX_GPS_GAP,
    SURFACE_CHANGE_THRESHOLDS, SHOCK_THRESHOLDS, VIBRATION_THRESHOLDS,
    VEHICLE_SHOCK_FILTER, VEHICLE_VIBRATION_FILTER
)
from analysis.classifier import (
    classify_damage_three_params, get_surface_change_severity, get_shock_severity, get_vibration_severity
)
from filters.shock_filter import filter_vehicle_shock
from filters.vibration_filter import filter_vehicle_vibration
import math
import time
# from analysis.buffer import first_data_received_time, buffer.INITIAL_SKIP_PERIOD, buffer.data_buffer
from analysis.visualizer import create_analysis_visualization
from analysis.saver import save_analysis_to_database



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

def perform_30s_analysis():
    """Melakukan analisis komprehensif setiap 30 detik dengan 3 parameter - SKIP 30 detik pertama"""
    global last_analysis_time
    import analysis.buffer as buffer
    
    current_time = time.time()
    
    # CEK APAKAH SUDAH MENERIMA DATA DARI ESP32
    if buffer.first_data_received_time is None:
        print(f"⏳ Belum menerima data dari ESP32 - Menunggu koneksi hardware...")
        return
    
    # CEK APAKAH MASIH DALAM PERIODE SKIP 30 DETIK SETELAH DATA PERTAMA
    elapsed_since_first_data = current_time - buffer.first_data_received_time
    if elapsed_since_first_data < buffer.INITIAL_SKIP_PERIOD:
        remaining_time = buffer.INITIAL_SKIP_PERIOD - elapsed_since_first_data
        print(f"⏳ Skipping analysis - Hardware warming up: {remaining_time:.1f}s remaining")
        print(f"💡 Reason: Sensor stabilization, GPS acquisition, initial data settling")
        return
    
    data_points = buffer.data_buffer.get_data()
    print(f"🔎🪲  DEBUG: MIN_DATA_POINTS = {MIN_DATA_POINTS}, data_buffer_count = {len(data_points)}")
    
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
    
    buffer.last_analysis_time = current_time
