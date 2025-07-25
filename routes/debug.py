from flask import Blueprint, jsonify, request
from datetime import datetime
import os
import json
from mysql.connector import Error

from core.config import THINGSBOARD_URL, THINGSBOARD_IMAGE_CONFIG, UPLOAD_FOLDER
from core.database import get_db_connection
from core.thingsboard import (
    send_to_thingsboard,
    compress_image_for_thingsboard,
    send_analysis_with_optimized_image_to_thingsboard
)
from filters.shock_filter import filter_vehicle_shock
from filters.vibration_filter import filter_vehicle_vibration
from thresholds import VEHICLE_SHOCK_FILTER, VEHICLE_VIBRATION_FILTER

debug_bp = Blueprint('debug', __name__)

@debug_bp.route('/debug/thingsboard/image/retry/<int:analysis_id>', methods=['POST'])
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


@debug_bp.route('/debug/filters/test', methods=['GET'])
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

@debug_bp.route('/thingsboard/test', methods=['GET'])
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

@debug_bp.route('/debug/thingsboard/test-compression/<int:analysis_id>', methods=['GET'])
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


@debug_bp.route('/debug/thingsboard/image/test/<int:analysis_id>', methods=['GET'])
def test_thingsboard_image_fix(analysis_id):
    """Test image compression untuk ThingsBoard"""
    ...

@debug_bp.route('/debug/thingsboard/image/retry/<int:analysis_id>', methods=['POST'])
def retry_send_analysis(analysis_id):
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
            
@debug_bp.route('/debug/thingsboard/image/test/<int:analysis_id>', methods=['GET'])
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

