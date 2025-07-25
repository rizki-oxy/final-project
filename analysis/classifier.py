from thresholds import (
    MIN_DATA_POINTS, ANALYSIS_INTERVAL, EARTH_RADIUS, MAX_GPS_GAP,
    SURFACE_CHANGE_THRESHOLDS, SHOCK_THRESHOLDS, VIBRATION_THRESHOLDS,
    VEHICLE_SHOCK_FILTER, VEHICLE_VIBRATION_FILTER, DAMAGE_CLASSIFICATION_3PARAM
)

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


