# Konfigurasi threshold untuk deteksi anomali dan klasifikasi kerusakan jalan
# SISTEM KLASIFIKASI 3 PARAMETER - RULE BASED
# PARAMETER 1: Surface Change (cm) - Ultrasonic
# PARAMETER 2: Shock (m/s²) - Accelerometer dengan filter kendaraan
# PARAMETER 3: Vibration (deg/s) - Gyroscope dengan filter kendaraan & slope

# === THRESHOLD SENSOR ===

# Ultrasonic Sensor Thresholds
SURFACE_CHANGE_THRESHOLDS = {
    'minor': 2.0,      # cm - perubahan kecil
    'moderate': 6.0,   # cm - perubahan sedang
    'major': 10.0       # cm - perubahan besar
}

# Accelerometer Shock Thresholds (m/s²)
SHOCK_THRESHOLDS = {
    'light': 25.0,     # m/s² - guncangan ringan 
    'moderate': 42.0,  # m/s² - guncangan sedang 
    'heavy': 50.0      # m/s² - guncangan berat
}

# Gyroscope Vibration Thresholds (deg/s)
VIBRATION_THRESHOLDS = {
    'light': 12.0,    # deg/s - getaran ringan
    'moderate': 25.0, # deg/s - getaran sedang
    'heavy': 40.0     # deg/s - getaran berat
}

# === FILTER GUNCANGAN KENDARAAN (SHOCK) ===
# Parameter untuk membedakan guncangan motor vs guncangan jalan rusak
VEHICLE_SHOCK_FILTER = {
    # Range guncangan normal kendaraan bermotor (dalam m/s²)
    'baseline_min': 0.5,    # m/s² - guncangan minimum kendaraan idle
    'baseline_max': 20.0,   # m/s² - guncangan maksimum kendaraan normal
    
    # Toleransi untuk baseline consistency
    'baseline_tolerance': 5.0,  # m/s² - toleransi dari baseline median
    
    # Gradien maksimum untuk guncangan kendaraan (perubahan bertahap)
    'max_gradient': 5.0,    # m/s² - perubahan maksimum antar sample untuk guncangan kendaraan
    
    # Threshold untuk spike jalan rusak (pasti bukan guncangan kendaraan)
    'road_spike_threshold': 25.0,  # m/s² - di atas ini pasti jalan rusak
    
    # Minimum sample untuk analisis pola
    'min_samples': 3        # minimum data point untuk analisis
}

# === FILTER GETARAN KENDARAAN (VIBRATION) ===
# Parameter untuk membedakan getaran motor vs getaran jalan rusak vs tanjakan/turunan
VEHICLE_VIBRATION_FILTER = {
    # Range getaran normal kendaraan bermotor (dalam deg/s) - SETELAH KALIBRASI
    'baseline_min': 0.0,    # TURUN dari 10.0 -> 3.0 (karena noise sudah dihilangkan)
    'baseline_max': 8.0,   # TURUN dari 80.0 -> 70.0
    
    # Toleransi untuk baseline consistency
    'baseline_tolerance': 3.0,  # TURUN dari 20.0 -> 10.0 deg/s
    
    # Gradien maksimum untuk getaran kendaraan (perubahan bertahap)
    'max_gradient': 2.0,    # TURUN dari 15.0 -> 8.0 deg/s
    
    # Threshold untuk spike jalan rusak (pasti bukan getaran kendaraan)
    'road_spike_threshold': 12.0,  # TURUN dari 100.0 -> 80.0 deg/s
    
    # TAMBAHAN BARU: Dead zone untuk noise sensor yang tersisa setelah kalibrasi ESP32
    'dead_zone_threshold': 1.0,  # deg/s - di bawah ini dianggap 0 (backup filter)
    
    # Parameter untuk deteksi tanjakan/turunan
    'slope_trend_threshold': 2.0,   # TURUN dari 5.0 -> 4.0 deg/s
    'slope_amplitude_threshold': 10.0,  # TURUN dari 60.0 -> 50.0 deg/s
    
    # Minimum sample untuk analisis pola
    'min_samples': 3        
}

# === KLASIFIKASI KERUSAKAN JALAN (3 PARAMETER) ===

# Threshold untuk klasifikasi dengan 3 parameter
DAMAGE_CLASSIFICATION_3PARAM = {
    'rusak_berat': {
        'surface_change': 10.0,   # >= 10 cm
        'shock': 50.0,           # >= 40.0 m/s² (filtered)
        'vibration': 40.0,      # TURUN dari 200.0 -> 180.0 deg/s (calibrated + filtered)
    },
    'rusak_sedang': {
        'surface_change': 6.0,   # >= 6 cm
        'shock': 42.0,           # >= 30.0 m/s² (filtered)
        'vibration': 25.0,      # TURUN dari 150.0 -> 120.0 deg/s (calibrated + filtered)
    },
    'rusak_ringan': {
        'surface_change': 2.0,   # >= 2.0 cm
        'shock': 25.0,           # >= 25.0 m/s² (filtered)
        'vibration': 12.0,       # TURUN dari 100.0 -> 80.0 deg/s (calibrated + filtered)
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

def get_shock_severity(shock_value):
    """Mendapatkan tingkat keparahan guncangan (dalam m/s² - sudah difilter)"""
    abs_shock = abs(shock_value)
    if abs_shock >= SHOCK_THRESHOLDS['heavy']:
        return 'heavy'
    elif abs_shock >= SHOCK_THRESHOLDS['moderate']:
        return 'moderate'
    elif abs_shock >= SHOCK_THRESHOLDS['light']:
        return 'light'
    return 'normal'

def get_vibration_severity(vibration_value):
    """Mendapatkan tingkat keparahan getaran (dalam deg/s - sudah dikalibrasi dan difilter)"""
    abs_vibration = abs(vibration_value)
    if abs_vibration >= VIBRATION_THRESHOLDS['heavy']:
        return 'heavy'
    elif abs_vibration >= VIBRATION_THRESHOLDS['moderate']:
        return 'moderate'
    elif abs_vibration >= VIBRATION_THRESHOLDS['light']:
        return 'light'
    return 'normal'

def classify_damage_three_params(max_surface_change, max_shock, max_vibration):
    """
    Klasifikasi kerusakan jalan dengan 3 parameter: Surface + Shock + Vibration
    
    UPDATED: Threshold vibration telah disesuaikan dengan kalibrasi gyroscope ESP32
    
    Logika Klasifikasi:
    - Menggunakan kombinasi threshold dari ketiga parameter
    - Shock dan Vibration sudah difilter dari noise kendaraan
    - Vibration sudah dikalibrasi di ESP32 untuk menghilangkan offset sensor
    - Prioritas berdasarkan tingkat keparahan parameter
    
    Args:
        max_surface_change (float): Perubahan permukaan maksimum (cm)
        max_shock (float): Guncangan maksimum (m/s²) - SUDAH DIFILTER
        max_vibration (float): Getaran maksimum (deg/s) - SUDAH DIKALIBRASI & DIFILTER
    
    Returns:
        str: Klasifikasi kerusakan ('rusak_berat', 'rusak_sedang', 'rusak_ringan', 'baik')
    """
    
    # Set default values untuk data yang None
    surface = max_surface_change if max_surface_change is not None else 0
    shock = max_shock if max_shock is not None else 0
    vibration = max_vibration if max_vibration is not None else 0
    
    print(f"🔍 Klasifikasi 3 Parameter (CALIBRATED): Surface={surface:.2f}cm, Shock={shock:.2f}m/s², Vibration={vibration:.2f}deg/s")
    
    # Hitung score berdasarkan berapa parameter yang memenuhi threshold
    rusak_berat_score = 0
    rusak_sedang_score = 0
    rusak_ringan_score = 0
    
    # Cek parameter untuk RUSAK BERAT
    if surface >= DAMAGE_CLASSIFICATION_3PARAM['rusak_berat']['surface_change']:
        rusak_berat_score += 1
    if shock >= DAMAGE_CLASSIFICATION_3PARAM['rusak_berat']['shock']:
        rusak_berat_score += 1
    if vibration >= DAMAGE_CLASSIFICATION_3PARAM['rusak_berat']['vibration']:
        rusak_berat_score += 1
    
    # Cek parameter untuk RUSAK SEDANG
    if surface >= DAMAGE_CLASSIFICATION_3PARAM['rusak_sedang']['surface_change']:
        rusak_sedang_score += 1
    if shock >= DAMAGE_CLASSIFICATION_3PARAM['rusak_sedang']['shock']:
        rusak_sedang_score += 1
    if vibration >= DAMAGE_CLASSIFICATION_3PARAM['rusak_sedang']['vibration']:
        rusak_sedang_score += 1
    
    # Cek parameter untuk RUSAK RINGAN
    if surface >= DAMAGE_CLASSIFICATION_3PARAM['rusak_ringan']['surface_change']:
        rusak_ringan_score += 1
    if shock >= DAMAGE_CLASSIFICATION_3PARAM['rusak_ringan']['shock']:
        rusak_ringan_score += 1
    if vibration >= DAMAGE_CLASSIFICATION_3PARAM['rusak_ringan']['vibration']:
        rusak_ringan_score += 1
    
    # Logika klasifikasi berdasarkan score
    # Minimal 2 dari 3 parameter harus memenuhi threshold
    
    if rusak_berat_score >= 2:
        print(f"📊 Klasifikasi: RUSAK BERAT - {rusak_berat_score}/3 parameter memenuhi threshold (CALIBRATED)")
        return 'rusak_berat'
    elif rusak_sedang_score >= 2:
        print(f"📊 Klasifikasi: RUSAK SEDANG - {rusak_sedang_score}/3 parameter memenuhi threshold (CALIBRATED)")
        return 'rusak_sedang'
    elif rusak_ringan_score >= 2:
        print(f"📊 Klasifikasi: RUSAK RINGAN - {rusak_ringan_score}/3 parameter memenuhi threshold (CALIBRATED)")
        return 'rusak_ringan'
    else:
        print(f"📊 Klasifikasi: BAIK - Tidak cukup parameter memenuhi threshold (CALIBRATED)")
        print(f"   Berat: {rusak_berat_score}/3, Sedang: {rusak_sedang_score}/3, Ringan: {rusak_ringan_score}/3")
        print(f"   Vibration sudah dikalibrasi di ESP32, Shock & Vibration sudah difilter dari noise kendaraan")
        return 'baik'

# === FUNGSI UNTUK BACKWARD COMPATIBILITY ===

def classify_damage_or_logic(max_surface_change, max_shock, max_vibration):
    """Alias untuk kompatibilitas - sekarang menggunakan 3 parameter dengan kalibrasi"""
    return classify_damage_three_params(max_surface_change, max_shock, max_vibration)

def classify_damage_simple(max_surface_change, max_shock, max_vibration):
    """Alias untuk kompatibilitas - sekarang menggunakan 3 parameter dengan kalibrasi"""
    return classify_damage_three_params(max_surface_change, max_shock, max_vibration)

def classify_damage_flexible(max_surface_change, max_shock, max_vibration):
    """Alias untuk kompatibilitas - sekarang menggunakan 3 parameter dengan kalibrasi"""
    return classify_damage_three_params(max_surface_change, max_shock, max_vibration)

# Legacy functions untuk kompatibilitas
def calculate_damage_score(surface_changes, shocks, vibrations, frequency_factor):
    """Fungsi legacy - tidak digunakan lagi"""
    return 0

def classify_damage(damage_score):
    """Fungsi legacy - tidak digunakan lagi"""
    return 'baik'

# === DEBUGGING FUNCTIONS ===

# def print_classification_info():
#     """Print informasi tentang sistem klasifikasi 3 parameter"""
#     print("=" * 60)
#     print("🔍 SISTEM KLASIFIKASI 3 PARAMETER")
#     print("=" * 60)
#     print("📊 PARAMETER:")
#     print("   1. Surface Change (cm) - Ultrasonic sensors")
#     print("   2. Shock (m/s²) - Accelerometer (filtered)")
#     print("   3. Vibration (deg/s) - Gyroscope (filtered)")
#     print("")
#     print("📊 THRESHOLD:")
#     print(f"   RUSAK BERAT: Surface≥{DAMAGE_CLASSIFICATION_3PARAM['rusak_berat']['surface_change']}cm, Shock≥{DAMAGE_CLASSIFICATION_3PARAM['rusak_berat']['shock']}m/s², Vibration≥{DAMAGE_CLASSIFICATION_3PARAM['rusak_berat']['vibration']}deg/s")
#     print(f"   RUSAK SEDANG: Surface≥{DAMAGE_CLASSIFICATION_3PARAM['rusak_sedang']['surface_change']}cm, Shock≥{DAMAGE_CLASSIFICATION_3PARAM['rusak_sedang']['shock']}m/s², Vibration≥{DAMAGE_CLASSIFICATION_3PARAM['rusak_sedang']['vibration']}deg/s")
#     print(f"   RUSAK RINGAN: Surface≥{DAMAGE_CLASSIFICATION_3PARAM['rusak_ringan']['surface_change']}cm, Shock≥{DAMAGE_CLASSIFICATION_3PARAM['rusak_ringan']['shock']}m/s², Vibration≥{DAMAGE_CLASSIFICATION_3PARAM['rusak_ringan']['vibration']}deg/s")
#     print("")
#     print("📊 LOGIKA:")
#     print("   - Minimal 2 dari 3 parameter harus memenuhi threshold")
#     print("   - Shock & Vibration sudah difilter dari noise kendaraan")
#     print("   - Vibration difilter dari noise tanjakan/turunan")
#     print("=" * 60)

# def print_filter_info():
#     """Print informasi tentang filter kendaraan"""
#     print("=" * 60)
#     print("🔧 FILTER KENDARAAN & SLOPE")
#     print("=" * 60)
#     print("📊 SHOCK FILTER (m/s²):")
#     print(f"   - Baseline Range: {VEHICLE_SHOCK_FILTER['baseline_min']}-{VEHICLE_SHOCK_FILTER['baseline_max']} m/s²")
#     print(f"   - Tolerance: ±{VEHICLE_SHOCK_FILTER['baseline_tolerance']} m/s²")
#     print(f"   - Spike Threshold: {VEHICLE_SHOCK_FILTER['road_spike_threshold']} m/s²")
#     print("")
#     print("📊 VIBRATION FILTER (deg/s):")
#     print(f"   - Baseline Range: {VEHICLE_VIBRATION_FILTER['baseline_min']}-{VEHICLE_VIBRATION_FILTER['baseline_max']} deg/s")
#     print(f"   - Tolerance: ±{VEHICLE_VIBRATION_FILTER['baseline_tolerance']} deg/s")
#     print(f"   - Spike Threshold: {VEHICLE_VIBRATION_FILTER['road_spike_threshold']} deg/s")
#     print(f"   - Slope Trend Threshold: {VEHICLE_VIBRATION_FILTER['slope_trend_threshold']} deg/s")
#     print(f"   - Slope Amplitude Threshold: {VEHICLE_VIBRATION_FILTER['slope_amplitude_threshold']} deg/s")
#     print("")
#     print("📊 FILTER LOGIC:")
#     print("   - Shock: Filters vehicle engine vibrations")
#     print("   - Vibration: Filters vehicle + slope/incline patterns")
#     print("   - Only road damage signals are analyzed")
#     print("=" * 60)

# if __name__ == "__main__":
#     # Print system info
#     print_classification_info()
#     print()
#     print_filter_info()
    
#     # Test classification
#     print("\n🧪 TEST KLASIFIKASI 3 PARAMETER:")
#     test_cases = [
#         (8.0, 45.0, 220.0),   # Rusak berat (3/3 parameter)
#         (6.0, 35.0, 180.0),   # Rusak sedang (3/3 parameter)
#         (3.0, 28.0, 120.0),   # Rusak ringan (3/3 parameter)
#         (8.0, 45.0, 50.0),    # Rusak sedang (2/3 parameter - surface + shock)
#         (3.0, 15.0, 180.0),   # Rusak ringan (2/3 parameter - surface + vibration)
#         (1.0, 35.0, 180.0),   # Rusak ringan (2/3 parameter - shock + vibration)
#         (8.0, 15.0, 50.0),    # Baik (1/3 parameter - hanya surface)
#         (1.0, 45.0, 50.0),    # Baik (1/3 parameter - hanya shock)
#         (1.0, 15.0, 220.0),   # Baik (1/3 parameter - hanya vibration)
#         (1.0, 15.0, 50.0),    # Baik (0/3 parameter)
#     ]
    
#     for i, (surface, shock, vibration) in enumerate(test_cases, 1):
#         print(f"\nTest {i}: Surface={surface}cm, Shock={shock}m/s², Vibration={vibration}deg/s")
#         result = classify_damage_three_params(surface, shock, vibration)
#         print(f"Result: {result}")
        
#     print("\n" + "=" * 60)
#     print("💡 CATATAN PENTING:")
#     print("   - Shock & Vibration yang digunakan sudah difilter dari noise kendaraan")
#     print("   - Vibration juga difilter dari noise tanjakan/turunan")
#     print("   - Minimal 2 dari 3 parameter harus memenuhi threshold")
#     print("   - Klasifikasi lebih akurat dengan 3 parameter")
#     print("=" * 60)