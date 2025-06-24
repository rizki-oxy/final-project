# Konfigurasi threshold untuk deteksi anomali dan klasifikasi kerusakan jalan
# SISTEM KLASIFIKASI SEDERHANA - RULE BASED DENGAN LOGIKA OR

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

# === KLASIFIKASI KERUSAKAN JALAN (RULE-BASED DENGAN LOGIKA OR) ===

# Threshold untuk klasifikasi langsung dengan logika OR
DAMAGE_CLASSIFICATION_OR = {
    'rusak_berat': {
        'surface_change': 10.0,   # >= 10 cm
        'vibration': 4000,        # >= 4000
        'rotation': 500           # >= 500 deg/s
    },
    'rusak_sedang': {
        'surface_change': 5.0,    # >= 5 cm
        'vibration': 3000,        # >= 3000
        'rotation': 300           # >= 300 deg/s
    },
    'rusak_ringan': {
        'surface_change': 2.0,    # >= 2 cm
        'vibration': 2000,        # >= 2000
        'rotation': 100           # >= 100 deg/s
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
    Klasifikasi kerusakan jalan dengan metode rule-based sederhana menggunakan LOGIKA OR
    
    Logika OR:
    - Jika SALAH SATU parameter memenuhi threshold RUSAK BERAT → RUSAK BERAT
    - Jika SALAH SATU parameter memenuhi threshold RUSAK SEDANG → RUSAK SEDANG  
    - Jika SALAH SATU parameter memenuhi threshold RUSAK RINGAN → RUSAK RINGAN
    - Jika tidak ada yang memenuhi → BAIK
    
    Args:
        max_surface_change (float): Perubahan permukaan maksimum (cm)
        max_vibration (float): Getaran maksimum
        max_rotation (float): Rotasi maksimum (deg/s)
    
    Returns:
        str: Klasifikasi kerusakan ('rusak_berat', 'rusak_sedang', 'rusak_ringan', 'baik')
    """
    
    # Set default values untuk data yang None
    surface = max_surface_change if max_surface_change is not None else 0
    vibration = max_vibration if max_vibration is not None else 0
    rotation = max_rotation if max_rotation is not None else 0
    
    print(f"🔍 Klasifikasi OR Logic: Surface={surface:.2f}cm, Vibration={vibration:.0f}, Rotation={rotation:.0f}°/s")
    
    # Cek RUSAK BERAT (SALAH SATU parameter memenuhi)
    if (surface >= DAMAGE_CLASSIFICATION_OR['rusak_berat']['surface_change'] or
        vibration >= DAMAGE_CLASSIFICATION_OR['rusak_berat']['vibration'] or
        rotation >= DAMAGE_CLASSIFICATION_OR['rusak_berat']['rotation']):
        
        # Tentukan parameter mana yang memicu
        trigger = []
        if surface >= DAMAGE_CLASSIFICATION_OR['rusak_berat']['surface_change']:
            trigger.append(f"Surface({surface:.1f}cm)")
        if vibration >= DAMAGE_CLASSIFICATION_OR['rusak_berat']['vibration']:
            trigger.append(f"Vibration({vibration:.0f})")
        if rotation >= DAMAGE_CLASSIFICATION_OR['rusak_berat']['rotation']:
            trigger.append(f"Rotation({rotation:.0f}°/s)")
        
        print(f"📊 Klasifikasi: RUSAK BERAT - Trigger: {', '.join(trigger)}")
        return 'rusak_berat'
    
    # Cek RUSAK SEDANG (SALAH SATU parameter memenuhi)
    elif (surface >= DAMAGE_CLASSIFICATION_OR['rusak_sedang']['surface_change'] or
          vibration >= DAMAGE_CLASSIFICATION_OR['rusak_sedang']['vibration'] or
          rotation >= DAMAGE_CLASSIFICATION_OR['rusak_sedang']['rotation']):
        
        # Tentukan parameter mana yang memicu
        trigger = []
        if surface >= DAMAGE_CLASSIFICATION_OR['rusak_sedang']['surface_change']:
            trigger.append(f"Surface({surface:.1f}cm)")
        if vibration >= DAMAGE_CLASSIFICATION_OR['rusak_sedang']['vibration']:
            trigger.append(f"Vibration({vibration:.0f})")
        if rotation >= DAMAGE_CLASSIFICATION_OR['rusak_sedang']['rotation']:
            trigger.append(f"Rotation({rotation:.0f}°/s)")
        
        print(f"📊 Klasifikasi: RUSAK SEDANG - Trigger: {', '.join(trigger)}")
        return 'rusak_sedang'
    
    # Cek RUSAK RINGAN (SALAH SATU parameter memenuhi)
    elif (surface >= DAMAGE_CLASSIFICATION_OR['rusak_ringan']['surface_change'] or
          vibration >= DAMAGE_CLASSIFICATION_OR['rusak_ringan']['vibration'] or
          rotation >= DAMAGE_CLASSIFICATION_OR['rusak_ringan']['rotation']):
        
        # Tentukan parameter mana yang memicu
        trigger = []
        if surface >= DAMAGE_CLASSIFICATION_OR['rusak_ringan']['surface_change']:
            trigger.append(f"Surface({surface:.1f}cm)")
        if vibration >= DAMAGE_CLASSIFICATION_OR['rusak_ringan']['vibration']:
            trigger.append(f"Vibration({vibration:.0f})")
        if rotation >= DAMAGE_CLASSIFICATION_OR['rusak_ringan']['rotation']:
            trigger.append(f"Rotation({rotation:.0f}°/s)")
        
        print(f"📊 Klasifikasi: RUSAK RINGAN - Trigger: {', '.join(trigger)}")
        return 'rusak_ringan'
    
    # Jika tidak ada yang memenuhi, jalan masih dalam kondisi baik
    else:
        print("📊 Klasifikasi: BAIK - Tidak ada parameter yang mencapai threshold kerusakan")
        return 'baik'

# === FUNGSI UNTUK BACKWARD COMPATIBILITY ===

def classify_damage_simple(max_surface_change, max_vibration, max_rotation):
    """Alias untuk kompatibilitas - menggunakan logika OR"""
    return classify_damage_or_logic(max_surface_change, max_vibration, max_rotation)

def classify_damage_flexible(max_surface_change, max_vibration, max_rotation):
    """Alias untuk kompatibilitas - menggunakan logika OR"""
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