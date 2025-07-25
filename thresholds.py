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

# FILTER GUNCANGAN KENDARAAN (SHOCK)
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

# FILTER GETARAN KENDARAAN (VIBRATION)
# Parameter untuk membedakan getaran motor vs getaran jalan rusak vs tanjakan/turunan
VEHICLE_VIBRATION_FILTER = {
    # Range getaran normal kendaraan bermotor (dalam deg/s)
    'baseline_min': 0.0,    
    'baseline_max': 8.0,   
    
    # Toleransi untuk baseline consistency
    'baseline_tolerance': 3.0,  
    
    # Gradien maksimum untuk getaran kendaraan (perubahan bertahap)
    'max_gradient': 2.0,    
    
    # Threshold untuk spike jalan rusak (pasti bukan getaran kendaraan)
    'road_spike_threshold': 12.0,  
    
    # Dead zone untuk noise sensor yang tersisa setelah kalibrasi ESP32
    'dead_zone_threshold': 1.0,  # deg/s - di bawah ini dianggap 0 (backup filter)
    
    # Parameter untuk deteksi tanjakan/turunan
    'slope_trend_threshold': 2.0,   
    'slope_amplitude_threshold': 10.0,  
    
    # Minimum sample untuk analisis pola
    'min_samples': 3        
}

# KLASIFIKASI KERUSAKAN JALAN (3 PARAMETER)

# Threshold untuk klasifikasi dengan 3 parameter
DAMAGE_CLASSIFICATION_3PARAM = {
    'rusak_berat': {
        'surface_change': 10.0,  
        'shock': 50.0,           # m/s² (filtered)
        'vibration': 40.0,      # deg/s (filtered)
    },
    'rusak_sedang': {
        'surface_change': 6.0,   
        'shock': 42.0,           # m/s² (filtered)
        'vibration': 25.0,      # deg/s (filtered)
    },
    'rusak_ringan': {
        'surface_change': 2.0,   
        'shock': 25.0,           # m/s² (filtered)
        'vibration': 12.0,       # deg/s (filtered)
    }
}

# PARAMETER ANALISIS

MIN_DATA_POINTS = 5  # Minimum data points untuk analisis valid

MAX_GPS_GAP = 50.0  # Maximum gap antara data points GPS untuk kontinuitas (meter)


# PARAMETER GPS
EARTH_RADIUS = 6371000  # Radius bumi untuk perhitungan jarak (meter)

# PARAMETER WAKTU
ANALYSIS_INTERVAL = 30  # Interval analisis (detik)
