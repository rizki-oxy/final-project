import math
from datetime import datetime, timedelta
from mysql.connector import Error
import base64
import os
import io
import json
import threading
import requests
from PIL import Image
from core.database import get_db_connection
from core.config import (
    DB_CONFIG, THINGSBOARD_URL, THINGSBOARD_IMAGE_CONFIG, UPLOAD_FOLDER, THINGSBOARD_CONFIG
)
from core.thingsboard import send_analysis_with_optimized_image_to_thingsboard


# def save_sensor_data(data):
#     """Menyimpan data sensor mentah ke database"""
#     connection = get_db_connection()
#     if not connection:
#         return False
    
#     try:
#         cursor = connection.cursor()
        
#         insert_query = """
#         INSERT INTO sensor_data (
#             timestamp, 
#             sensor1_distance, sensor2_distance, sensor3_distance, sensor4_distance,
#             sensor5_distance, sensor6_distance, sensor7_distance, sensor8_distance,
#             accel_x, accel_y, accel_z, accel_magnitude,
#             accel_x_ms2, accel_y_ms2, accel_z_ms2, accel_magnitude_ms2,
#             gyro_x, gyro_y, gyro_z, rotation_magnitude,
#             gyro_x_dps, gyro_y_dps, gyro_z_dps, rotation_magnitude_dps,
#             shock_magnitude, vibration_magnitude,
#             latitude, longitude, speed, satellites
#         ) VALUES (
#             %s, %s, %s, %s, %s, %s, %s, %s, %s,
#             %s, %s, %s, %s, %s, %s, %s, %s,
#             %s, %s, %s, %s, %s, %s, %s, %s,
#             %s, %s, %s, %s, %s, %s
#         )
#         """
        
#         # Calculate magnitudes dari raw data jika belum ada
#         accel_magnitude = None
#         if all(data.get(key) is not None for key in ['accelX', 'accelY', 'accelZ']):
#             accel_magnitude = math.sqrt(data['accelX']**2 + data['accelY']**2 + data['accelZ']**2)
        
#         rotation_magnitude = None
#         if all(data.get(key) is not None for key in ['gyroX', 'gyroY', 'gyroZ']):
#             rotation_magnitude = math.sqrt(
#                 (data['gyroX']/131.0)**2 + (data['gyroY']/131.0)**2 + (data['gyroZ']/131.0)**2
#             )
        
#         # Calculate converted magnitudes
#         accel_magnitude_ms2 = None
#         if all(data.get(key) is not None for key in ['accelX_ms2', 'accelY_ms2', 'accelZ_ms2']):
#             accel_magnitude_ms2 = math.sqrt(
#                 data['accelX_ms2']**2 + data['accelY_ms2']**2 + data['accelZ_ms2']**2
#             )
#         elif data.get('accel_magnitude_ms2') is not None:
#             accel_magnitude_ms2 = data['accel_magnitude_ms2']
        
#         rotation_magnitude_dps = None
#         if all(data.get(key) is not None for key in ['gyroX_dps', 'gyroY_dps', 'gyroZ_dps']):
#             rotation_magnitude_dps = math.sqrt(
#                 data['gyroX_dps']**2 + data['gyroY_dps']**2 + data['gyroZ_dps']**2
#             )
#         elif data.get('rotation_magnitude_dps') is not None:
#             rotation_magnitude_dps = data['rotation_magnitude_dps']
        
#         insert_data = (
#             datetime.now(),
#             # Ultrasonic data
#             data.get('sensor1'), data.get('sensor2'), data.get('sensor3'), data.get('sensor4'),
#             data.get('sensor5'), data.get('sensor6'), data.get('sensor7'), data.get('sensor8'),
#             # Raw accelerometer data
#             data.get('accelX'), data.get('accelY'), data.get('accelZ'), accel_magnitude,
#             # Converted accelerometer data (m/s²)
#             data.get('accelX_ms2'), data.get('accelY_ms2'), data.get('accelZ_ms2'), accel_magnitude_ms2,
#             # Raw gyroscope data  
#             data.get('gyroX'), data.get('gyroY'), data.get('gyroZ'), rotation_magnitude,
#             # Converted gyroscope data (deg/s)
#             data.get('gyroX_dps'), data.get('gyroY_dps'), data.get('gyroZ_dps'), rotation_magnitude_dps,
#             # Shock & Vibration magnitude dari ESP32
#             data.get('shock_magnitude'),      # m/s² (dari accelerometer)
#             data.get('vibration_magnitude'),  # deg/s (dari gyroscope)
#             # GPS data
#             data.get('latitude'), data.get('longitude'), data.get('speed'), data.get('satellites')
#         )
        
#         cursor.execute(insert_query, insert_data)
#         connection.commit()
        
#         shock_val = data.get('shock_magnitude', 0)
#         vibration_val = data.get('vibration_magnitude', 0)
#         print(f"✅ Raw sensor data saved to MySQL (ID: {cursor.lastrowid})")
#         print(f"📊 Shock: {shock_val:.2f} m/s², Vibration: {vibration_val:.2f} deg/s")
#         return True
        
#     except Error as e:
#         print(f"❌ Error saving sensor data: {e}")
#         return False
#     finally:
#         if connection.is_connected():
#             cursor.close()
#             connection.close()

def save_analysis_to_database(analysis_data, image_path=None, image_filename=None):
    """Menyimpan hasil analisis ke database"""
    
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
        
        # Database simpan PNG
        image_data = None
        if image_path and os.path.exists(image_path):
            print(f"📸 Saving original PNG to database: {image_filename}")
            
            # Simpan PNG asli ke database
            with open(image_path, 'rb') as img_file:
                image_data = base64.b64encode(img_file.read()).decode('utf-8')
            
            original_size = len(image_data)
            print(f"💾 Original PNG saved to database: {original_size} bytes ({original_size/1024:.1f}KB)")
            print(f"📡 ThingsBoard akan menerima versi terkompresi")
        
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

def send_analysis_with_image_to_thingsboard(analysis_id):
    """
    Gunakan fungsi dengan image fix untuk ThingsBoard
    """
    return send_analysis_with_optimized_image_to_thingsboard(analysis_id)



