from flask import Flask
import matplotlib
matplotlib.use('Agg')
import os
from datetime import datetime
from core.config import (
    DB_CONFIG, THINGSBOARD_URL, THINGSBOARD_IMAGE_CONFIG, UPLOAD_FOLDER, THINGSBOARD_CONFIG
)
from core.database import get_db_connection

from core.thingsboard import (
    send_to_thingsboard, compress_image_for_thingsboard
)
from thresholds import (
    ANALYSIS_INTERVAL
)
from analysis.buffer import init_buffer, INITIAL_SKIP_PERIOD
init_buffer(ANALYSIS_INTERVAL)
from dashboard import dashboard_bp
from routes.multisensor import multisensor_bp
from routes.status import status_bp
from routes.analysis import analysis_bp

app = Flask(__name__)
app.register_blueprint(dashboard_bp, url_prefix='/dashboard')

app.register_blueprint(multisensor_bp)
app.register_blueprint(status_bp)
app.register_blueprint(analysis_bp)

if __name__ == '__main__':
    print("🚀 Road Monitoring Flask Server Starting...")
    print("=" * 60)
    print("⏳ HARDWARE WARMING UP PERIOD:")
    print(f"   - Skip first {INITIAL_SKIP_PERIOD} seconds after ESP32 connects")
    print(f"   - Warming up starts when first data received")
    print("=" * 60)
    print("🔗 ThingsBoard Integration:")
    print(f"   - Server: {THINGSBOARD_CONFIG['server']}:{THINGSBOARD_CONFIG['port']}")
    print(f"   - URL: {THINGSBOARD_URL}")
    print(f"   - Data Prefix: fls_ (Flask)")
    print("=" * 60)

    # Test database connection
    test_conn = get_db_connection()
    if test_conn:
        print("✅ Database connection successful")
        test_conn.close()
    else:
        print("❌ Database connection failed - check configuration")
        exit(1)

    
    # Test ThingsBoard connection
    test_payload = {
        "startup_test": "Flask server starting with 3 parameters",
        "startup_timestamp": datetime.now().isoformat(),
        "parameters": "surface + shock + vibration",
        "shock_unit": "m/s² (filtered)",
        "vibration_unit": "deg/s (filtered)",
        "filters": "shock & vibration filters enabled"
    }
    
    if send_to_thingsboard(test_payload, "startup_test"):
        print("✅ ThingsBoard connection successful")
    else:
        print("⚠️ ThingsBoard connection failed - check configuration")
    
    # Start server
    flask_host = os.getenv('FLASK_HOST', '0.0.0.0')
    flask_port = int(os.getenv('FLASK_PORT', 5000))
    flask_debug = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
       
    print(f"🌐 Server running on http://{flask_host}:{flask_port}")
    print("=" * 60)
    
    app.run(host=flask_host, port=flask_port, debug=flask_debug)