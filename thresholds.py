# Konfigurasi threshold untuk deteksi anomali dan klasifikasi kerusakan jalan

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
    'moderate': 5000,   # Guncangan sedang
    'heavy': 10000      # Guncangan berat
}

# GY-521 Gyroscope Thresholds (untuk deteksi rotasi)
ROTATION_THRESHOLDS = {
    'normal': 100,      # deg/s - rotasi normal
    'moderate': 300,    # deg/s - rotasi sedang
    'excessive': 500    # deg/s - rotasi berlebihan
}

# GPS Speed Thresholds
SPEED_THRESHOLDS = {
    'normal': 60,       # km/h - kecepatan normal
    'high': 80,         # km/h - kecepatan tinggi
    'excessive': 120    # km/h - kecepatan berlebihan
}

# === KLASIFIKASI KERUSAKAN JALAN ===

# Sistem scoring untuk klasifikasi kerusakan
DAMAGE_CLASSIFICATION_WEIGHTS = {
    'surface_change': 0.4,      # 40% - perubahan permukaan paling penting
    'vibration': 0.3,           # 30% - guncangan
    'rotation': 0.2,            # 20% - rotasi
    'frequency': 0.1            # 10% - frekuensi kejadian
}

# Score thresholds untuk klasifikasi
DAMAGE_SCORE_THRESHOLDS = {
    'rusak_ringan': 0.3,        # Score 0.0 - 0.3
    'rusak_sedang': 0.6,        # Score 0.3 - 0.6
    'rusak_berat': 1.0          # Score 0.6 - 1.0
}

# === PARAMETER ANALISIS ===

# Minimum data points untuk analisis valid
MIN_DATA_POINTS = 5

# Minimum distance untuk menghitung panjang kerusakan (meter)
MIN_DAMAGE_LENGTH = 1.0

# Maximum gap antara data points GPS untuk kontinuitas (meter)
MAX_GPS_GAP = 50.0

# Minimum perubahan untuk dianggap anomali
MIN_ANOMALY_CHANGE = 1.0

# === PARAMETER GPS ===

# Radius bumi untuk perhitungan jarak (meter)
EARTH_RADIUS = 6371000

# Minimum akurasi GPS yang diterima (meter)
MIN_GPS_ACCURACY = 10.0

# === PARAMETER WAKTU ===

# Interval analisis (detik)
ANALYSIS_INTERVAL = 30

# Cooldown untuk penyimpanan gambar (detik)
SAVE_COOLDOWN = 5

# Timeout untuk data GPS (detik)
GPS_TIMEOUT = 10

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

def calculate_damage_score(surface_changes, vibrations, rotations, frequency_factor):
    """Menghitung skor kerusakan berdasarkan semua parameter"""
    
    # Normalisasi nilai ke skala 0-1
    surface_score = min(max(surface_changes) / SURFACE_CHANGE_THRESHOLDS['major'], 1.0) if surface_changes else 0
    vibration_score = min(max(vibrations) / VIBRATION_THRESHOLDS['heavy'], 1.0) if vibrations else 0
    rotation_score = min(max(rotations) / ROTATION_THRESHOLDS['excessive'], 1.0) if rotations else 0
    
    # Hitung weighted score
    total_score = (
        surface_score * DAMAGE_CLASSIFICATION_WEIGHTS['surface_change'] +
        vibration_score * DAMAGE_CLASSIFICATION_WEIGHTS['vibration'] +
        rotation_score * DAMAGE_CLASSIFICATION_WEIGHTS['rotation'] +
        frequency_factor * DAMAGE_CLASSIFICATION_WEIGHTS['frequency']
    )
    
    return min(total_score, 1.0)

def classify_damage(damage_score):
    """Mengklasifikasikan tingkat kerusakan berdasarkan skor"""
    if damage_score >= DAMAGE_SCORE_THRESHOLDS['rusak_berat']:
        return 'rusak_berat'
    elif damage_score >= DAMAGE_SCORE_THRESHOLDS['rusak_sedang']:
        return 'rusak_sedang'
    else:
        return 'rusak_ringan'