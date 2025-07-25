from flask import Blueprint, request, jsonify
from datetime import datetime
import os
from mysql.connector import Error
import json

from core.database import get_db_connection
from core.config import UPLOAD_FOLDER, THINGSBOARD_IMAGE_CONFIG
from core.thingsboard import (
    compress_image_for_thingsboard,
    send_analysis_with_optimized_image_to_thingsboard
)

analysis_bp = Blueprint('analysis', __name__)

@analysis_bp.route('/analysis', methods=['GET'])
def get_analysis():
    """Ambil data analisis dari database"""
    ...

@analysis_bp.route('/summary', methods=['GET'])
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


