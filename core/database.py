from debugpy import connect
from mysql.connector import Error
import mysql.connector
from core.config import DB_CONFIG 

def get_db_connection():
    """Membuat koneksi ke database MySQL"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        if connection.is_connected():
            return connection
    except Error as e:
        print(f"❌ Error connecting to MySQL: {e}")
        return None
    
    
# Test database connection
def test_database_connection():
    test_conn = get_db_connection()
    if test_conn:
        print("✅ Database connection successful")
        test_conn.close()
    else:
        print("❌ Database connection failed")
        exit(1)

    