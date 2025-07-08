# Konfigurasi threshold untuk deteksi anomali dan klasifikasi kerusakan jalan
# SISTEM KLASIFIKASI SEDERHANA - RULE BASED DENGAN LOGIKA AND
# UPDATED: GY-521 menggunakan m/s² untuk accelerometer
# ADDED: Filter getaran kendaraan untuk membedakan getaran motor vs jalan rusak

# === THRESHOLD SENSOR ===

# Ultrasonic Sensor Thresholds
SURFACE_CHANGE_THRESHOLDS = {
    'minor': 2.5,      # cm - perubahan kecil
    'moderate': 5.0,   # cm - perubahan sedang
    'major': 7.0      # cm - perubahan besar
}

# GY-521 Accelerometer Thresholds (UPDATED untuk m/s²)
VIBRATION_THRESHOLDS = {
    'light': 25.0,       # m/s² - guncangan ringan
    'moderate': 30.0,    # m/s² - guncangan sedang
    'heavy': 40.0       # m/s² - guncangan berat
}

# GY-521 Gyroscope Thresholds (dalam deg/s - TIDAK DIGUNAKAN untuk klasifikasi)
ROTATION_THRESHOLDS = {
    'normal': 100,      # deg/s - rotasi normal
    'moderate': 300,    # deg/s - rotasi sedang
    'excessive': 500    # deg/s - rotasi berlebihan
}

# === FILTER GETARAN KENDARAAN ===
# Parameter untuk membedakan getaran motor vs getaran jalan rusak
VEHICLE_VIBRATION_FILTER = {
    # Range getaran normal kendaraan bermotor (dalam m/s²)
    'baseline_min': 0.5,    # m/s² - getaran minimum kendaraan idle
    'baseline_max': 18.0,    # m/s² - getaran maksimum kendaraan normal
    
    # Toleransi untuk baseline consistency
    'baseline_tolerance': 5.0,  # m/s² - toleransi dari baseline median
    
    # Gradien maksimum untuk getaran kendaraan (perubahan bertahap)
    'max_gradient': 5.0,    # m/s² - perubahan maksimum antar sample untuk getaran kendaraan
    
    # Threshold untuk spike jalan rusak (pasti bukan getaran kendaraan)
    'road_spike_threshold': 25.0,  # m/s² - di atas ini pasti jalan rusak
    
    # Minimum sample untuk analisis pola
    'min_samples': 3        # minimum data point untuk analisis
}

# === KLASIFIKASI KERUSAKAN JALAN (RULE-BASED DENGAN LOGIKA AND) ===

# Threshold untuk klasifikasi langsung dengan logika AND 
# UPDATED: Vibration threshold dalam m/s² (setelah difilter)
DAMAGE_CLASSIFICATION_AND = {
    'rusak_berat': {
        'surface_change': 7.0,   # >= 10 cm
        'vibration': 40.0,        # >= 10.0 m/s² (filtered)
    },
    'rusak_sedang': {
        'surface_change': 5.0,    # >= 5 cm
        'vibration': 30.0,         # >= 5.0 m/s² (filtered)
    },
    'rusak_ringan': {
        'surface_change': 2.5,    # >= 2 cm
        'vibration': 25.0,         # >= 2.0 m/s² (filtered)
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
    """Mendapatkan tingkat keparahan guncangan (dalam m/s² - sudah difilter)"""
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
    VIBRATION THRESHOLD DALAM m/s² (SUDAH DIFILTER DARI GETARAN KENDARAAN)
    
    Logika AND:
    - Jika KEDUA parameter (surface_change AND vibration) memenuhi threshold RUSAK BERAT → RUSAK BERAT
    - Jika KEDUA parameter (surface_change AND vibration) memenuhi threshold RUSAK SEDANG → RUSAK SEDANG  
    - Jika KEDUA parameter (surface_change AND vibration) memenuhi threshold RUSAK RINGAN → RUSAK RINGAN
    - Jika tidak kedua parameter memenuhi → BAIK
    
    Args:
        max_surface_change (float): Perubahan permukaan maksimum (cm)
        max_vibration (float): Getaran maksimum (m/s²) - SUDAH DIFILTER
        max_rotation (float): DIABAIKAN - tidak digunakan lagi
    
    Returns:
        str: Klasifikasi kerusakan ('rusak_berat', 'rusak_sedang', 'rusak_ringan', 'baik')
    """
    
    # Set default values untuk data yang None
    surface = max_surface_change if max_surface_change is not None else 0
    vibration = max_vibration if max_vibration is not None else 0
    # rotation diabaikan
    
    print(f"🔍 Klasifikasi AND Logic (FILTERED): Surface={surface:.2f}cm, Vibration={vibration:.2f}m/s²")
    
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
        print(f"   Note: Vibration sudah difilter dari getaran kendaraan")
        return 'baik'

# === FUNGSI UNTUK BACKWARD COMPATIBILITY ===

def classify_damage_simple(max_surface_change, max_vibration, max_rotation):
    """Alias untuk kompatibilitas - menggunakan logika AND dengan vibration filter"""
    return classify_damage_or_logic(max_surface_change, max_vibration, max_rotation)

def classify_damage_flexible(max_surface_change, max_vibration, max_rotation):
    """Alias untuk kompatibilitas - menggunakan logika AND dengan vibration filter"""
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

# === DEBUGGING FUNCTIONS ===

# def print_vibration_filter_info():
#     """Print informasi tentang filter getaran kendaraan"""
#     print("=" * 60)
#     print("🔧 INFORMASI FILTER GETARAN KENDARAAN")
#     print("=" * 60)
#     print("📊 PARAMETER FILTER:")
#     print(f"   - Baseline Range: {VEHICLE_VIBRATION_FILTER['baseline_min']}-{VEHICLE_VIBRATION_FILTER['baseline_max']} m/s²")
#     print(f"   - Baseline Tolerance: ±{VEHICLE_VIBRATION_FILTER['baseline_tolerance']} m/s²")
#     print(f"   - Max Gradient: {VEHICLE_VIBRATION_FILTER['max_gradient']} m/s²")
#     print(f"   - Road Spike Threshold: {VEHICLE_VIBRATION_FILTER['road_spike_threshold']} m/s²")
#     print("")
#     print("📊 CARA KERJA:")
#     print("   1. Hitung baseline (median) getaran")
#     print("   2. Filter getaran dalam range normal kendaraan")
#     print("   3. Deteksi gradien halus (getaran kendaraan)")
#     print("   4. Identifikasi spike tinggi (jalan rusak)")
#     print("   5. Hanya analisis getaran jalan rusak")
#     print("")
#     print("📊 LOGIKA FILTER:")
#     print("   - Getaran Kendaraan: Konsisten, dalam range baseline")
#     print("   - Getaran Jalan Rusak: Spike mendadak, di atas threshold")
#     print("   - Hasil: Hanya getaran jalan rusak yang dianalisis")
#     print("=" * 60)

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
#     print("   - FILTER: Getaran kendaraan dihapus")
#     print("")
#     print("📊 GYROSCOPE:")
#     print("   - Raw Data: LSB (dari sensor)")
#     print("   - Konversi: LSB → deg/s")
#     print("   - Scale Factor: 131 LSB/(deg/s) (untuk ±250°/s range)")
#     print("   - Status: TIDAK DIGUNAKAN untuk klasifikasi")
#     print("")
#     print("📊 KLASIFIKASI:")
#     print("   - Logika: AND (Surface AND Vibration)")
#     print("   - Parameter: Surface Change (cm) + Vibration (m/s² filtered)")
#     print("   - Rotasi: DIHAPUS dari kriteria")
#     print("   - Filter: Getaran kendaraan diabaikan")
#     print("=" * 60)

# if __name__ == "__main__":
#     # Test the conversion info
#     print_conversion_info()
#     print()
#     print_vibration_filter_info()
    
#     # Test classification
#     print("\n🧪 TEST KLASIFIKASI (DENGAN FILTER):")
#     test_cases = [
#         (15.0, 12.0, 0),  # Rusak berat
#         (7.0, 7.0, 0),    # Rusak sedang
#         (3.0, 3.0, 0),    # Rusak ringan
#         (10.0, 1.0, 0),   # Baik (hanya surface tinggi)
#         (1.0, 10.0, 0),   # Baik (hanya vibration tinggi)
#         (1.0, 1.0, 0),    # Baik (kedua rendah)
#         (5.0, 2.5, 0),    # Baik (surface memenuhi tapi vibration tidak)
#         (2.5, 5.0, 0),    # Baik (vibration memenuhi tapi surface tidak)
#     ]
    
#     for i, (surface, vibration, rotation) in enumerate(test_cases, 1):
#         print(f"\nTest {i}: Surface={surface}cm, Vibration={vibration}m/s² (filtered)")
#         result = classify_damage_or_logic(surface, vibration, rotation)
#         print(f"Result: {result}")
        
#     print("\n" + "=" * 60)
#     print("💡 CATATAN PENTING:")
#     print("   - Vibration yang digunakan sudah difilter dari getaran kendaraan")
#     print("   - Hanya getaran akibat jalan rusak yang dianalisis")
#     print("   - Threshold vibration berlaku untuk getaran jalan, bukan kendaraan")
#     print("   - Klasifikasi lebih akurat karena noise kendaraan dihilangkan")
#     print("=" * 60)