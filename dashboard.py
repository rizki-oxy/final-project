# ============================================================================
# FILE 1: dashboard.py (Buat file baru)
# ============================================================================

from flask import Blueprint, render_template, request, jsonify, send_file, make_response
import mysql.connector
from mysql.connector import Error
import pandas as pd
import json
from datetime import datetime, timedelta
import os
import io
import base64

# Create Blueprint
dashboard_bp = Blueprint('dashboard', __name__)

# Database config (import dari app.py)
def get_dashboard_db_connection():
    """Koneksi database untuk dashboard"""
    try:
        from app import DB_CONFIG
        connection = mysql.connector.connect(**DB_CONFIG)
        if connection.is_connected():
            return connection
    except Error as e:
        print(f"❌ Dashboard DB Error: {e}")
        return None

@dashboard_bp.route('/')
def dashboard_home():
    """Dashboard utama"""
    return render_template('dashboard.html')

@dashboard_bp.route('/api/tables')
def get_tables():
    """Get available tables"""
    return jsonify({
        'tables': [
            {
                'name': 'road_damage_analysis',
                'display_name': 'Analisis Kerusakan Jalan',
                'description': 'Data hasil analisis kerusakan jalan (30 detik)',
                'icon': ''
            },
            {
                'name': 'sensor_data', 
                'display_name': 'Data Sensor Mentah',
                'description': 'Data sensor real-time (GPS, Ultrasonic, IMU)',
                'icon': ''
            }
        ]
    })

@dashboard_bp.route('/api/data/<table_name>')
def get_table_data(table_name):
    """Get data from specific table dengan filter"""
    
    # Validasi table name
    if table_name not in ['road_damage_analysis', 'sensor_data']:
        return jsonify({'error': 'Invalid table name'}), 400
    
    # Get parameters
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    search = request.args.get('search', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    
    connection = get_dashboard_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cursor = connection.cursor(dictionary=True)
        
        # Build query berdasarkan table
        if table_name == 'road_damage_analysis':
            base_query = """
                SELECT id, analysis_timestamp, damage_classification, damage_length,
                       surface_change_max, shock_max, vibration_max,
                       start_latitude, start_longitude, end_latitude, end_longitude
                FROM road_damage_analysis
            """
            count_query = "SELECT COUNT(*) as total FROM road_damage_analysis"
            timestamp_col = 'analysis_timestamp'
            search_cols = ['damage_classification']
            
        else:  # sensor_data
            base_query = """
                SELECT id, timestamp, latitude, longitude, speed, satellites,
                       sensor1_distance, sensor2_distance, sensor3_distance, sensor4_distance,
                       accel_magnitude_ms2, rotation_magnitude_dps, shock_magnitude, vibration_magnitude
                FROM sensor_data
            """
            count_query = "SELECT COUNT(*) as total FROM sensor_data"
            timestamp_col = 'timestamp'
            search_cols = ['latitude', 'longitude']
        
        # Build WHERE clause
        where_conditions = []
        params = []
        
        # Date filter
        if date_from:
            where_conditions.append(f"{timestamp_col} >= %s")
            params.append(date_from + ' 00:00:00')
        
        if date_to:
            where_conditions.append(f"{timestamp_col} <= %s")
            params.append(date_to + ' 23:59:59')
        
        # Search filter
        if search:
            search_conditions = []
            for col in search_cols:
                search_conditions.append(f"{col} LIKE %s")
                params.append(f"%{search}%")
            
            if search_conditions:
                where_conditions.append(f"({' OR '.join(search_conditions)})")
        
        # Complete WHERE clause
        where_clause = ""
        if where_conditions:
            where_clause = "WHERE " + " AND ".join(where_conditions)
        
        # Get total count
        cursor.execute(count_query + " " + where_clause, params)
        total_count = cursor.fetchone()['total']
        
        # Get paginated data
        offset = (page - 1) * per_page
        main_query = base_query + " " + where_clause + f" ORDER BY {timestamp_col} DESC LIMIT %s OFFSET %s"
        cursor.execute(main_query, params + [per_page, offset])
        
        data = cursor.fetchall()
        
        # Format timestamps
        for row in data:
            if table_name == 'road_damage_analysis':
                if row['analysis_timestamp']:
                    row['analysis_timestamp'] = row['analysis_timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            else:
                if row['timestamp']:
                    row['timestamp'] = row['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
        
        return jsonify({
            'data': data,
            'total': total_count,
            'page': page,
            'per_page': per_page,
            'total_pages': (total_count + per_page - 1) // per_page,
            'has_next': page * per_page < total_count,
            'has_prev': page > 1
        })
        
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

@dashboard_bp.route('/api/download/<table_name>')
def download_csv(table_name):
    """Download data as CSV file"""
    
    if table_name not in ['road_damage_analysis', 'sensor_data']:
        return jsonify({'error': 'Invalid table name'}), 400
    
    # Get filter parameters
    search = request.args.get('search', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    
    connection = get_dashboard_db_connection()
    if not connection:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cursor = connection.cursor(dictionary=True)
        
        # Build query untuk download (sama seperti sebelumnya)
        if table_name == 'road_damage_analysis':
            base_query = """
                SELECT id, analysis_timestamp, damage_classification, damage_length,
                       surface_change_max, surface_change_avg, surface_change_count,
                       shock_max, shock_avg, shock_count,
                       vibration_max, vibration_avg, vibration_count,
                       start_latitude, start_longitude, end_latitude, end_longitude
                FROM road_damage_analysis
            """
            timestamp_col = 'analysis_timestamp'
            search_cols = ['damage_classification']
            
        else:  # sensor_data
            base_query = """
                SELECT id, timestamp, latitude, longitude, speed, satellites,
                       sensor1_distance, sensor2_distance, sensor3_distance, sensor4_distance,
                       sensor5_distance, sensor6_distance, sensor7_distance, sensor8_distance,
                       accel_x_ms2, accel_y_ms2, accel_z_ms2, accel_magnitude_ms2,
                       gyro_x_dps, gyro_y_dps, gyro_z_dps, rotation_magnitude_dps,
                       shock_magnitude, vibration_magnitude
                FROM sensor_data
            """
            timestamp_col = 'timestamp'
            search_cols = ['latitude', 'longitude']
        
        # Build WHERE clause
        where_conditions = []
        params = []
        
        if date_from:
            where_conditions.append(f"{timestamp_col} >= %s")
            params.append(date_from + ' 00:00:00')
        
        if date_to:
            where_conditions.append(f"{timestamp_col} <= %s")
            params.append(date_to + ' 23:59:59')
        
        if search:
            search_conditions = []
            for col in search_cols:
                search_conditions.append(f"{col} LIKE %s")
                params.append(f"%{search}%")
            
            if search_conditions:
                where_conditions.append(f"({' OR '.join(search_conditions)})")
        
        where_clause = ""
        if where_conditions:
            where_clause = "WHERE " + " AND ".join(where_conditions)
        
        # Execute query
        main_query = base_query + " " + where_clause + f" ORDER BY {timestamp_col} DESC"
        cursor.execute(main_query, params)
        
        data = cursor.fetchall()
        
        if not data:
            return jsonify({'error': 'No data found'}), 404
        
        # Convert to CSV
        output = io.StringIO()
        
        # Write headers
        if data:
            headers = list(data[0].keys())
            output.write(','.join(headers) + '\n')
            
            # Write data rows
            for row in data:
                csv_row = []
                for value in row.values():
                    # Handle None values and escape commas
                    if value is None:
                        csv_row.append('')
                    else:
                        # Convert to string and escape commas/quotes
                        str_val = str(value).replace('"', '""')
                        if ',' in str_val or '"' in str_val or '\n' in str_val:
                            csv_row.append(f'"{str_val}"')
                        else:
                            csv_row.append(str_val)
                
                output.write(','.join(csv_row) + '\n')
        
        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"road_monitoring_{table_name}_{timestamp}.csv"
        
        # Create response
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
        
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()