import numpy as np
from thresholds import (
    MIN_DATA_POINTS, ANALYSIS_INTERVAL, EARTH_RADIUS, MAX_GPS_GAP,
    SURFACE_CHANGE_THRESHOLDS, SHOCK_THRESHOLDS, VIBRATION_THRESHOLDS,
    VEHICLE_SHOCK_FILTER, VEHICLE_VIBRATION_FILTER
)
from analysis.classifier import (
    classify_damage_three_params, get_surface_change_severity, get_shock_severity, get_vibration_severity
)

def filter_vehicle_shock(shocks, timestamps=None):
    if not shocks or len(shocks) < 3:
        return {
            'filtered_shocks': shocks,
            'vehicle_shocks': [],
            'road_shocks': shocks,
            'filter_applied': False,
            'stats': {
                'total_count': len(shocks),
                'vehicle_count': 0,
                'road_count': len(shocks)
            }
        }
    
    # Konversi ke numpy array untuk analisis
    shock_array = np.array(shocks)
    
    # Hitung baseline guncangan (guncangan konstan kendaraan)
    baseline = np.median(shock_array)
    
    # Variasi guncangan (guncangan motor cenderung konsisten)
    shock_std = np.std(shock_array)
    shock_mean = np.mean(shock_array)
    
    # Deteksi lonjakan guncangan yang tidak wajar (indikasi jalan rusak)
    vehicle_shocks = []
    road_shocks = []
    
    for i, shock in enumerate(shock_array):
        is_vehicle_shock = False
        
        # Kriteria 1: Guncangan dalam range normal kendaraan
        if (VEHICLE_SHOCK_FILTER['baseline_min'] <= shock <= VEHICLE_SHOCK_FILTER['baseline_max']):
            is_vehicle_shock = True
        
        # Kriteria 2: Guncangan konsisten dengan baseline
        if abs(shock - baseline) <= VEHICLE_SHOCK_FILTER['baseline_tolerance']:
            is_vehicle_shock = True
        
        # Kriteria 3: Analisis pola jika ada data sekitar
        if i > 0 and i < len(shock_array) - 1:
            prev_shock = shock_array[i-1]
            next_shock = shock_array[i+1]
            
            # Guncangan motor cenderung gradual, bukan spike tiba-tiba
            gradient_prev = abs(shock - prev_shock)
            gradient_next = abs(shock - next_shock)
            
            if (gradient_prev <= VEHICLE_SHOCK_FILTER['max_gradient'] and 
                gradient_next <= VEHICLE_SHOCK_FILTER['max_gradient']):
                is_vehicle_shock = True
        
        # Kriteria 4: Override untuk spike tinggi (pasti jalan rusak)
        if shock >= VEHICLE_SHOCK_FILTER['road_spike_threshold']:
            is_vehicle_shock = False
        
        # Kategorikan guncangan
        if is_vehicle_shock:
            vehicle_shocks.append(shock)
        else:
            road_shocks.append(shock)
    
    # Hasil filter
    result = {
        'filtered_shocks': road_shocks,  # Hanya guncangan jalan
        'vehicle_shocks': vehicle_shocks,  # Guncangan kendaraan
        'road_shocks': road_shocks,  # Guncangan jalan rusak
        'filter_applied': True,
        'stats': {
            'total_count': len(shocks),
            'vehicle_count': len(vehicle_shocks),
            'road_count': len(road_shocks),
            'baseline': float(baseline),
            'shock_std': float(shock_std),
            'shock_mean': float(shock_mean)
        }
    }
    
    # Log hasil filter
    print(f"🔧 Filter Guncangan Kendaraan:")
    print(f"   Total: {len(shocks)} → Kendaraan: {len(vehicle_shocks)}, Jalan: {len(road_shocks)}")
    print(f"   Baseline: {baseline:.2f} m/s², Std: {shock_std:.2f} m/s²")
    
    return result


def process_realtime_shock(data):
    """Memproses guncangan real-time dari shock_magnitude ESP32"""
    shock = data.get('shock_magnitude')
    
    if shock is not None:
        # Terapkan filter guncangan kendaraan pada single data point
        is_vehicle_shock = (
            VEHICLE_SHOCK_FILTER['baseline_min'] <= shock <= VEHICLE_SHOCK_FILTER['baseline_max']
        )
        if shock >= VEHICLE_SHOCK_FILTER['road_spike_threshold']:
            is_vehicle_shock = False
        
        if not is_vehicle_shock:
            return {
                'filtered_shock': shock,
                'is_road_shock': True
            }
        else:
            return {
                'filtered_shock': 0,
                'is_road_shock': False
            }
    return None
