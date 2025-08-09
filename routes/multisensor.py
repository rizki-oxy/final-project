from flask import Blueprint, request, jsonify
from datetime import datetime
import time
import threading
from thresholds import MIN_DATA_POINTS

from analysis.buffer import data_buffer
from analysis.analyzer import perform_30s_analysis
# from analysis.saver import save_sensor_data
from filters.shock_filter import process_realtime_shock
from filters.vibration_filter import process_realtime_vibration
from core.thingsboard import send_to_thingsboard
from analysis.buffer import INITIAL_SKIP_PERIOD
from thresholds import ANALYSIS_INTERVAL

multisensor_bp = Blueprint('multisensor', __name__)

@multisensor_bp.route('/multisensor', methods=['POST'])
def multisensor():
    """Endpoint untuk menerima data sensor dari ESP32 - FIXED Warming Up Period"""
    from analysis import buffer
    buffer.first_data_received_time
    buffer.last_analysis_time
    
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data received"}), 400
    
    current_time = time.time()
    
    # SET WAKTU PERTAMA MENERIMA DATA
    if buffer.first_data_received_time is None:
        buffer.first_data_received_time = current_time
        print(f"🔌 ESP32 connected! Hardware warming up started ({INITIAL_SKIP_PERIOD}s)")
        print(f"💡 During warming up: NO data save, NO buffer collection, NO analysis")
    
    # CEK WARMING UP SEBELUM SEMUA OPERASI
    elapsed_since_first_data = current_time - buffer.first_data_received_time
    
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
        buffer.last_analysis_time = current_time
        print("🧹 Buffer cleared after warming up period - Starting fresh data collection")
        print("✅ Hardware stabilized - Normal operations begin")
    
    # OPERASI NORMAL DIMULAI SETELAH WARMING UP SELESAI
    print(f"📩 Data diterima: {datetime.now().strftime('%H:%M:%S')} (Post warming up)")
    
    # Simpan data mentah ke database (HANYA SETELAH WARMING UP)
    # save_sensor_data(data)
    
    # Tambahkan ke buffer untuk analisis (HANYA SETELAH WARMING UP)
    data_buffer.add_data(data)
    
    # Proses shock dan vibration real-time
    shock_result = process_realtime_shock(data)
    vibration_result = process_realtime_vibration(data)
    
    # Kirim payload real-time ke ThingsBoard
    realtime_payload = {}
    
    if shock_result and shock_result['is_road_shock']:
        realtime_payload["realtime_shock_ms2"] = shock_result['filtered_shock']
        print(f"📡 Shock real-time: {shock_result['filtered_shock']:.2f} m/s²")
    
    if vibration_result and vibration_result['is_road_vibration']:
        realtime_payload["realtime_vibration_dps"] = vibration_result['filtered_vibration']
        print(f"📡 Vibration real-time: {vibration_result['filtered_vibration']:.2f} deg/s")
    
    if realtime_payload:
        realtime_payload.update({
            "timestamp": datetime.now().isoformat(),
            # "fls_data_type": "realtime_3param",
            # "fls_shock_filter_enabled": True,
            # "fls_vibration_filter_enabled": True,
            # "fls_post_warming_up": True
        })
        send_to_thingsboard(realtime_payload, "realtime_3param")
    
    # Cek apakah sudah waktunya untuk analisis 30 detik
    if (current_time - buffer.last_analysis_time) >= ANALYSIS_INTERVAL:
        if data_buffer.get_data_count() >= MIN_DATA_POINTS:
            analysis_thread = threading.Thread(target=perform_30s_analysis)
            analysis_thread.daemon = True
            analysis_thread.start()
        else:
            print(f"⚠️ Skip analisis: data belum cukup ({data_buffer.get_data_count()}/{MIN_DATA_POINTS})")
    
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
