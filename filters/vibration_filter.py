import numpy as np
from thresholds import (
    MIN_DATA_POINTS, ANALYSIS_INTERVAL, EARTH_RADIUS, MAX_GPS_GAP,
    SURFACE_CHANGE_THRESHOLDS, SHOCK_THRESHOLDS, VIBRATION_THRESHOLDS,
    VEHICLE_SHOCK_FILTER, VEHICLE_VIBRATION_FILTER
)
from analysis.classifier import (
    classify_damage_three_params, get_surface_change_severity, get_shock_severity, get_vibration_severity
)

def filter_vehicle_vibration(vibrations, timestamps=None):
    """
    Filter getaran kendaraan bermotor dari getaran jalan rusak
    Untuk gyroscope dalam deg/s dengan filter untuk tanjakan/turunan
    
    Args:
        vibrations (list): List getaran dalam deg/s
        timestamps (list): List timestamp untuk analisis pola (optional)
    
    Returns:
        dict: Hasil filter dengan getaran yang sudah dibersihkan
    """
    if not vibrations or len(vibrations) < 3:
        return {
            'filtered_vibrations': vibrations,
            'vehicle_vibrations': [],
            'slope_vibrations': [],
            'road_vibrations': vibrations,
            'filter_applied': False,
            'stats': {
                'total_count': len(vibrations),
                'vehicle_count': 0,
                'slope_count': 0,
                'road_count': len(vibrations)
            }
        }
    
    # Konversi ke numpy array untuk analisis
    vib_array = np.array(vibrations)
    
    # Hitung baseline getaran
    baseline = np.median(vib_array)
    
    # Variasi getaran
    vib_std = np.std(vib_array)
    vib_mean = np.mean(vib_array)
    
    # Deteksi berbagai jenis getaran
    vehicle_vibrations = []
    slope_vibrations = []
    road_vibrations = []
    
    for i, vib in enumerate(vib_array):
        is_vehicle_vibration = False
        is_slope_vibration = False
        
        # Kriteria 1: Getaran dalam range normal kendaraan
        if (VEHICLE_VIBRATION_FILTER['baseline_min'] <= vib <= VEHICLE_VIBRATION_FILTER['baseline_max']):
            is_vehicle_vibration = True
        
        # Kriteria 2: Getaran konsisten dengan baseline
        if abs(vib - baseline) <= VEHICLE_VIBRATION_FILTER['baseline_tolerance']:
            is_vehicle_vibration = True
        
        # Kriteria 3: Deteksi pola tanjakan/turunan (rotasi konstan dalam satu arah)
        if i >= 2 and i < len(vib_array) - 2:
            # Ambil 5 point sekitar untuk analisis tren
            window = vib_array[i-2:i+3]
            
            # Cek apakah ada tren konstan (tanjakan/turunan)
            if len(window) >= 5:
                # Hitung tren linear
                trend = np.polyfit(range(len(window)), window, 1)[0]
                
                # Jika tren konstan dan dalam range slope
                if abs(trend) <= VEHICLE_VIBRATION_FILTER['slope_trend_threshold']:
                    # Cek apakah amplitudo dalam range slope
                    if abs(vib) <= VEHICLE_VIBRATION_FILTER['slope_amplitude_threshold']:
                        is_slope_vibration = True
        
        # Kriteria 4: Analisis gradien untuk getaran motor
        if i > 0 and i < len(vib_array) - 1:
            prev_vib = vib_array[i-1]
            next_vib = vib_array[i+1]
            
            # Getaran motor cenderung gradual
            gradient_prev = abs(vib - prev_vib)
            gradient_next = abs(vib - next_vib)
            
            if (gradient_prev <= VEHICLE_VIBRATION_FILTER['max_gradient'] and 
                gradient_next <= VEHICLE_VIBRATION_FILTER['max_gradient']):
                is_vehicle_vibration = True
        
        # Kriteria 5: Override untuk spike tinggi (pasti jalan rusak)
        if abs(vib) >= VEHICLE_VIBRATION_FILTER['road_spike_threshold']:
            is_vehicle_vibration = False
            is_slope_vibration = False
        
        # Kategorikan getaran
        if is_slope_vibration:
            slope_vibrations.append(vib)
        elif is_vehicle_vibration:
            vehicle_vibrations.append(vib)
        else:
            road_vibrations.append(vib)
    
    # Hasil filter
    result = {
        'filtered_vibrations': road_vibrations,  # Hanya getaran jalan
        'vehicle_vibrations': vehicle_vibrations,  # Getaran kendaraan
        'slope_vibrations': slope_vibrations,  # Getaran tanjakan/turunan
        'road_vibrations': road_vibrations,  # Getaran jalan rusak
        'filter_applied': True,
        'stats': {
            'total_count': len(vibrations),
            'vehicle_count': len(vehicle_vibrations),
            'slope_count': len(slope_vibrations),
            'road_count': len(road_vibrations),
            'baseline': float(baseline),
            'vib_std': float(vib_std),
            'vib_mean': float(vib_mean)
        }
    }
    
    # Log hasil filter
    print(f"🔧 Filter Getaran Gyroscope:")
    print(f"   Total: {len(vibrations)} → Kendaraan: {len(vehicle_vibrations)}, Slope: {len(slope_vibrations)}, Jalan: {len(road_vibrations)}")
    print(f"   Baseline: {baseline:.2f} deg/s, Std: {vib_std:.2f} deg/s")
    
    return result


def process_realtime_vibration(data):
    """Memproses getaran real-time dari vibration_magnitude ESP32"""
    vibration = data.get('vibration_magnitude')
    
    if vibration is not None:
        abs_vibration = abs(vibration)
        
        # Terapkan filter getaran kendaraan pada single data point
        is_vehicle_vibration = (
            VEHICLE_VIBRATION_FILTER['baseline_min'] <= abs_vibration <= VEHICLE_VIBRATION_FILTER['baseline_max']
        )
        if abs_vibration >= VEHICLE_VIBRATION_FILTER['road_spike_threshold']:
            is_vehicle_vibration = False
        
        if not is_vehicle_vibration:
            return {
                'filtered_vibration': abs_vibration,
                'is_road_vibration': True
            }
        else:
            return {
                'filtered_vibration': 0,
                'is_road_vibration': False
            }
    return None
