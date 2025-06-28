# Konfigurasi threshold untuk deteksi anomali dan klasifikasi kerusakan jalan
# SISTEM KLASIFIKASI SEDERHANA - RULE BASED DENGAN LOGIKA AND

# === THRESHOLD SENSOR ===

# Ultrasonic Sensor Thresholds
SURFACE_CHANGE_THRESHOLDS = {
    'minor': 2.0,      # cm - perubahan kecil
    'moderate': 5.0,   # cm - perubahan sedang
    'major': 10.0      # cm - perubahan besar
}

# GY-521 Accelerometer Thresholds (untuk deteksi guncangan)
VIBRATION_THRESHOLDS = {
    'light': 2000,      # Guncangan ringan
    'moderate': 3000,   # Guncangan sedang
    'heavy': 4000       # Guncangan berat
}

# GY-521 Gyroscope Thresholds (untuk deteksi rotasi)
ROTATION_THRESHOLDS = {
    'normal': 100,      # deg/s - rotasi normal
    'moderate': 300,    # deg/s - rotasi sedang
    'excessive': 500    # deg/s - rotasi berlebihan
}

# === KLASIFIKASI KERUSAKAN JALAN (RULE-BASED DENGAN LOGIKA AND) ===

# Threshold untuk klasifikasi langsung dengan logika AND 
DAMAGE_CLASSIFICATION_AND = {
    'rusak_berat': {
        'surface_change': 10.0,   # >= 10 cm
        'vibration': 4000,        # >= 4000
    },
    'rusak_sedang': {
        'surface_change': 5.0,    # >= 5 cm
        'vibration': 3000,        # >= 3000
    },
    'rusak_ringan': {
        'surface_change': 2.0,    # >= 2 cm
        'vibration': 2000,        # >= 2000
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
    """Mendapatkan tingkat keparahan guncangan"""
    abs_vibration = abs(vibration_value)
    if abs_vibration >= VIBRATION_THRESHOLDS['heavy']:
        return 'heavy'
    elif abs_vibration >= VIBRATION_THRESHOLDS['moderate']:
        return 'moderate'
    elif abs_vibration >= VIBRATION_THRESHOLDS['light']:
        return 'light'
    return 'normal'

def get_rotation_severity(rotation_value):
    """Mendapatkan tingkat keparahan rotasi"""
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
    
    Logika AND:
    - Jika KEDUA parameter (surface_change AND vibration) memenuhi threshold RUSAK BERAT → RUSAK BERAT
    - Jika KEDUA parameter (surface_change AND vibration) memenuhi threshold RUSAK SEDANG → RUSAK SEDANG  
    - Jika KEDUA parameter (surface_change AND vibration) memenuhi threshold RUSAK RINGAN → RUSAK RINGAN
    - Jika tidak kedua parameter memenuhi → BAIK
    
    Args:
        max_surface_change (float): Perubahan permukaan maksimum (cm)
        max_vibration (float): Getaran maksimum
        max_rotation (float): DIABAIKAN - tidak digunakan lagi
    
    Returns:
        str: Klasifikasi kerusakan ('rusak_berat', 'rusak_sedang', 'rusak_ringan', 'baik')
    """
    
    # Set default values untuk data yang None
    surface = max_surface_change if max_surface_change is not None else 0
    vibration = max_vibration if max_vibration is not None else 0
    # rotation diabaikan
    
    print(f"🔍 Klasifikasi AND Logic (TANPA ROTASI): Surface={surface:.2f}cm, Vibration={vibration:.0f}")
    
    # Cek RUSAK BERAT (KEDUA parameter harus memenuhi)
    if (surface >= DAMAGE_CLASSIFICATION_AND['rusak_berat']['surface_change'] and
        vibration >= DAMAGE_CLASSIFICATION_AND['rusak_berat']['vibration']):
        
        print(f"📊 Klasifikasi: RUSAK BERAT - Surface({surface:.1f}cm) AND Vibration({vibration:.0f}) MEMENUHI")
        return 'rusak_berat'
    
    # Cek RUSAK SEDANG (KEDUA parameter harus memenuhi)
    elif (surface >= DAMAGE_CLASSIFICATION_AND['rusak_sedang']['surface_change'] and
          vibration >= DAMAGE_CLASSIFICATION_AND['rusak_sedang']['vibration']):
        
        print(f"📊 Klasifikasi: RUSAK SEDANG - Surface({surface:.1f}cm) AND Vibration({vibration:.0f}) MEMENUHI")
        return 'rusak_sedang'
    
    # Cek RUSAK RINGAN (KEDUA parameter harus memenuhi)
    elif (surface >= DAMAGE_CLASSIFICATION_AND['rusak_ringan']['surface_change'] and
          vibration >= DAMAGE_CLASSIFICATION_AND['rusak_ringan']['vibration']):
        
        print(f"📊 Klasifikasi: RUSAK RINGAN - Surface({surface:.1f}cm) AND Vibration({vibration:.0f}) MEMENUHI")
        return 'rusak_ringan'
    
    # Jika tidak kedua parameter memenuhi, jalan masih dalam kondisi baik
    else:
        print("📊 Klasifikasi: BAIK - Tidak kedua parameter memenuhi threshold kerusakan")
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