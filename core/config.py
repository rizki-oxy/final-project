import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Konfigurasi dari .env
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'road_monitoring'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'charset': 'utf8mb4',
    'autocommit': True
}

# ThingsBoard Configuration
THINGSBOARD_CONFIG = {
    'server': os.getenv('THINGSBOARD_SERVER'),
    'port': os.getenv('THINGSBOARD_PORT'),
    'access_token': os.getenv('THINGSBOARD_ACCESS_TOKEN')
}

# Build ThingsBoard URL
THINGSBOARD_URL = f"http://{THINGSBOARD_CONFIG['server']}:{THINGSBOARD_CONFIG['port']}/api/v1/{THINGSBOARD_CONFIG['access_token']}/telemetry"

# Konfigurasi untuk ThingsBoard image compatibility
THINGSBOARD_IMAGE_CONFIG = {
    'max_width': 1024,           # Maksimal lebar untuk ThingsBoard
    'max_height': 768,           # Maksimal tinggi untuk ThingsBoard
    'jpeg_quality': 85,          # Kualitas JPEG yang bagus tapi tidak terlalu besar
    'max_payload_size': 50000,   # 50KB - batas aman untuk ThingsBoard
    'format': 'JPEG'            # Format yang lebih efisien daripada PNG
}

FLASK_CONFIG = {
    'host': os.getenv('FLASK_HOST'),
    'port': int(os.getenv('FLASK_PORT')),
    'debug': os.getenv('FLASK_DEBUG', 'True').lower()=="true",
}

UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'static')
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
