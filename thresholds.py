# Konfigurasi threshold untuk deteksi anomali dan klasifikasi kerusakan jalan
# SISTEM KLASIFIKASI SEDERHANA - RULE BASED DENGAN LOGIKA AND
# UPDATED: GY-521 menggunakan m/s² untuk accelerometer

# === THRESHOLD SENSOR ===

# Ultrasonic Sensor Thresholds
SURFACE_CHANGE_THRESHOLDS = {
    'minor': 2.0,      # cm - perubahan kecil
    'moderate': 5.0,   # cm - perubahan sedang
    'major': 10.0      # cm - perubahan besar
}

# GY-521 Accelerometer Thresholds (UPDATED untuk m/s²)
VIBRATION_THRESHOLDS = {
    'light': 2.0,       # m/s² - guncangan ringan
    'moderate': 5.0,    # m/s² - guncangan sedang
    'heavy': 10.0       # m/s² - guncangan berat
}

# GY-521 Gyroscope Thresholds (dalam deg/s - TIDAK DIGUNAKAN untuk klasifikasi)
ROTATION_THRESHOLDS = {
    'normal': 100,      # deg/s - rotasi normal
    'moderate': 300,    # deg/s - rotasi sedang
    'excessive': 500    # deg/s - rotasi berlebihan
}

# === KLASIFIKASI KERUSAKAN JALAN (RULE-BASED DENGAN LOGIKA AND) ===

# Threshold untuk klasifikasi langsung dengan logika AND 
# UPDATED: Vibration threshold dalam m/s²
DAMAGE_CLASSIFICATION_AND = {
    'rusak_berat': {
        'surface_change': 10.0,   # >= 10 cm
        'vibration': 10.0,        # >= 10.0 m/s²
    },
    'rusak_sedang': {
        'surface_change': 5.0,    # >= 5 cm
        'vibration': 5.0,         # >= 5.0 m/s²
    },
    'rusak_ringan': {
        'surface_change': 2.0,    # >= 2 cm
        'vibration': 2.0,         # >= 2.0 m/s²
    }
}

# === PARAMETER ANALISIS ===

# Minimum data points untuk analisis valid
MIN_DATA_POINTS = 5

# Maximum gap antara data points GPS untuk kontinuitas (meter)
MAX_GPS_GAP = 50.0

# === PARAMETER GPS ===

# Radius bumi untuk perhitungan jarak (meter)
EARTH_RADIUS = 6371000

# === PARAMETER WAKTU ===

# Interval analisis (detik)
ANALYSIS_INTERVAL = 30

# === FUNGSI HELPER ===

def get_surface_change_severity(change_value):
    """Mendapatkan tingkat keparahan perubahan permukaan"""
    abs_change = abs(change_value)
    if abs_change >= SURFACE_CHANGE_THRESHOLDS['major']:
        return 'major'
    elif abs_change >= SURFACE_CHANGE_THRESHOLDS['moderate']:
        return 'moderate'
    elif abs_change >= SURFACE_CHANGE_THRESHOLDS['minor']:
        return 'minor'
    return 'normal'

def get_vibration_severity(vibration_value):
    """Mendapatkan tingkat keparahan guncangan (dalam m/s²)"""
    abs_vibration = abs(vibration_value)
    if abs_vibration >= VIBRATION_THRESHOLDS['heavy']:
        return 'heavy'
    elif abs_vibration >= VIBRATION_THRESHOLDS['moderate']:
        return 'moderate'
    elif abs_vibration >= VIBRATION_THRESHOLDS['light']:
        return 'light'
    return 'normal'

def get_rotation_severity(rotation_value):
    """Mendapatkan tingkat keparahan rotasi (dalam deg/s) - TIDAK DIGUNAKAN"""
    abs_rotation = abs(rotation_value)
    if abs_rotation >= ROTATION_THRESHOLDS['excessive']:
        return 'excessive'
    elif abs_rotation >= ROTATION_THRESHOLDS['moderate']:
        return 'moderate'
    elif abs_rotation >= ROTATION_THRESHOLDS['normal']:
        return 'normal'
    return 'minimal'

def classify_damage_or_logic(max_surface_change, max_vibration, max_rotation):
    """
    Klasifikasi kerusakan jalan dengan metode rule-based sederhana menggunakan LOGIKA AND
    ROTASI DIHAPUS DARI KLASIFIKASI
    VIBRATION THRESHOLD DALAM m/s²
    
    Logika AND:
    - Jika KEDUA parameter (surface_change AND vibration) memenuhi threshold RUSAK BERAT → RUSAK BERAT
    - Jika KEDUA parameter (surface_change AND vibration) memenuhi threshold RUSAK SEDANG → RUSAK SEDANG  
    - Jika KEDUA parameter (surface_change AND vibration) memenuhi threshold RUSAK RINGAN → RUSAK RINGAN
    - Jika tidak kedua parameter memenuhi → BAIK
    
    Args:
        max_surface_change (float): Perubahan permukaan maksimum (cm)
        max_vibration (float): Getaran maksimum (m/s²) - UPDATED
        max_rotation (float): DIABAIKAN - tidak digunakan lagi
    
    Returns:
        str: Klasifikasi kerusakan ('rusak_berat', 'rusak_sedang', 'rusak_ringan', 'baik')
    """
    
    # Set default values untuk data yang None
    surface = max_surface_change if max_surface_change is not None else 0
    vibration = max_vibration if max_vibration is not None else 0
    # rotation diabaikan
    
    print(f"🔍 Klasifikasi AND Logic (TANPA ROTASI): Surface={surface:.2f}cm, Vibration={vibration:.2f}m/s²")
    
    # Cek RUSAK BERAT (KEDUA parameter harus memenuhi)
    if (surface >= DAMAGE_CLASSIFICATION_AND['rusak_berat']['surface_change'] and
        vibration >= DAMAGE_CLASSIFICATION_AND['rusak_berat']['vibration']):
        
        print(f"📊 Klasifikasi: RUSAK BERAT - Surface({surface:.1f}cm) AND Vibration({vibration:.1f}m/s²) MEMENUHI")
        return 'rusak_berat'
    
    # Cek RUSAK SEDANG (KEDUA parameter harus memenuhi)
    elif (surface >= DAMAGE_CLASSIFICATION_AND['rusak_sedang']['surface_change'] and
          vibration >= DAMAGE_CLASSIFICATION_AND['rusak_sedang']['vibration']):
        
        print(f"📊 Klasifikasi: RUSAK SEDANG - Surface({surface:.1f}cm) AND Vibration({vibration:.1f}m/s²) MEMENUHI")
        return 'rusak_sedang'
    
    # Cek RUSAK RINGAN (KEDUA parameter harus memenuhi)
    elif (surface >= DAMAGE_CLASSIFICATION_AND['rusak_ringan']['surface_change'] and
          vibration >= DAMAGE_CLASSIFICATION_AND['rusak_ringan']['vibration']):
        
        print(f"📊 Klasifikasi: RUSAK RINGAN - Surface({surface:.1f}cm) AND Vibration({vibration:.1f}m/s²) MEMENUHI")
        return 'rusak_ringan'
    
    # Jika tidak kedua parameter memenuhi, jalan masih dalam kondisi baik
    else:
        print(f"📊 Klasifikasi: BAIK - Tidak kedua parameter memenuhi threshold kerusakan")
        print(f"   Surface: {surface:.1f}cm (perlu ≥{DAMAGE_CLASSIFICATION_AND['rusak_ringan']['surface_change']}cm)")
        print(f"   Vibration: {vibration:.1f}m/s² (perlu ≥{DAMAGE_CLASSIFICATION_AND['rusak_ringan']['vibration']}m/s²)")
        return 'baik'

# === FUNGSI UNTUK BACKWARD COMPATIBILITY ===

def classify_damage_simple(max_surface_change, max_vibration, max_rotation):
    """Alias untuk kompatibilitas - menggunakan logika AND tanpa rotasi"""
    return classify_damage_or_logic(max_surface_change, max_vibration, max_rotation)

def classify_damage_flexible(max_surface_change, max_vibration, max_rotation):
    """Alias untuk kompatibilitas - menggunakan logika AND tanpa rotasi"""
    return classify_damage_or_logic(max_surface_change, max_vibration, max_rotation)

def calculate_damage_score(surface_changes, vibrations, rotations, frequency_factor):
    """
    Fungsi ini masih ada untuk kompatibilitas dengan kode lama,
    tapi sekarang tidak digunakan karena tidak ada scoring
    """
    # Return dummy score 0 karena tidak digunakan lagi
    return 0

def classify_damage(damage_score):
    """
    Fungsi ini masih ada untuk kompatibilitas dengan kode lama,
    tapi sekarang tidak digunakan karena tidak ada scoring
    """
    # Return default 'baik' karena tidak digunakan lagi
    return 'baik'

# # === DEBUGGING FUNCTIONS ===

# def print_conversion_info():
#     """Print informasi tentang konversi satuan untuk debugging"""
#     print("=" * 60)
#     print("🔄 INFORMASI KONVERSI SATUAN GY-521")
#     print("=" * 60)
#     print("📊 ACCELEROMETER:")
#     print("   - Raw Data: LSB (dari sensor)")
#     print("   - Konversi: LSB → g → m/s²")
#     print("   - Scale Factor: 2048 LSB/g (untuk ±16g range)")
#     print("   - Gravity: 9.81 m/s²")
#     print("   - Threshold baru: 2.0, 5.0, 10.0 m/s²")
#     print("")
#     print("📊 GYROSCOPE:")
#     print("   - Raw Data: LSB (dari sensor)")
#     print("   - Konversi: LSB → deg/s")
#     print("   - Scale Factor: 131 LSB/(deg/s) (untuk ±250°/s range)")
#     print("   - Status: TIDAK DIGUNAKAN untuk klasifikasi")
#     print("")
#     print("📊 KLASIFIKASI:")
#     print("   - Logika: AND (Surface AND Vibration)")
#     print("   - Parameter: Surface Change (cm) + Vibration (m/s²)")
#     print("   - Rotasi: DIHAPUS dari kriteria")
#     print("=" * 60)

# if __name__ == "__main__":
#     # Test the conversion info
#     print_conversion_info()
    
#     # Test classification
#     print("\n🧪 TEST KLASIFIKASI:")
#     test_cases = [
#         (15.0, 12.0, 0),  # Rusak berat
#         (7.0, 7.0, 0),    # Rusak sedang
#         (3.0, 3.0, 0),    # Rusak ringan
#         (10.0, 1.0, 0),   # Baik (hanya surface tinggi)
#         (1.0, 10.0, 0),   # Baik (hanya vibration tinggi)
#         (1.0, 1.0, 0),    # Baik (kedua rendah)
#     ]
    
#     for i, (surface, vibration, rotation) in enumerate(test_cases, 1):
#         print(f"\nTest {i}:")
#         result = classify_damage_or_logic(surface, vibration, rotation)
#         print(f"Result: {result}")