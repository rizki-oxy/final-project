import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import os
from core.config import (
    DB_CONFIG, THINGSBOARD_URL, THINGSBOARD_IMAGE_CONFIG, UPLOAD_FOLDER, THINGSBOARD_CONFIG
)

def create_analysis_visualization(analysis_data):
    """Membuat visualisasi analisis untuk disimpan - hanya jika ada kerusakan"""
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
    
    # Buat time axis dalam detik (0-30 detik)
    analysis_duration = 30
    
    # 1. Data perubahan permukaan
    if analysis_data['surface_analysis']['changes']:
        num_changes = len(analysis_data['surface_analysis']['changes'])
        time_points = [i * (analysis_duration / (num_changes - 1)) if num_changes > 1 else 0 
                      for i in range(num_changes)]
        
        negative_changes = [-change for change in analysis_data['surface_analysis']['changes']]
        ax1.plot(time_points, negative_changes, 
                marker='o', linewidth=2, markersize=4, color='orange', alpha=0.8)
        ax1.axhline(y=-analysis_data['surface_analysis']['max_change'], 
                color='red', linestyle='--', alpha=0.7,
                label=f'Max Surface Change: {analysis_data["surface_analysis"]["max_change"]:.1f}cm')
        ax1.axhline(y=-analysis_data['surface_analysis']['avg_change'], 
                color='blue', linestyle=':', alpha=0.7,
                label=f'Avg Surface Change: {analysis_data["surface_analysis"]["avg_change"]:.1f}cm')
        
        ax1.fill_between(time_points, negative_changes, 
                alpha=0.3, color='orange')
        ax1.set_title('Perubahan Permukaan Jalan')
        ax1.set_xlabel('Waktu (detik)')
        ax1.set_ylabel('Kedalaman Lubang / Perubahan (cm)')
        ax1.set_xlim(0, 30)
        ax1.legend()
        ax1.grid(True, alpha=0.3)
    else:
        ax1.text(0.5, 0.5, 'Tidak ada perubahan\npermukaan signifikan', 
                ha='center', va='center', transform=ax1.transAxes, fontsize=14)
        ax1.set_title('Perubahan Permukaan Jalan')
        ax1.set_xlabel('Waktu (detik)')
        ax1.set_xlim(0, 30)
        ax1.grid(True, alpha=0.3)
        
        def format_y_label(value, pos):
            return f'{abs(value):.0f}'
        
        from matplotlib.ticker import FuncFormatter
        ax1.yaxis.set_major_formatter(FuncFormatter(format_y_label))
    
    # 2. Data guncangan (shock) - m/s²
    if analysis_data['shock_analysis']['shocks']:
        num_shocks = len(analysis_data['shock_analysis']['shocks'])
        time_points = [i * (analysis_duration / (num_shocks - 1)) if num_shocks > 1 else 0 
                      for i in range(num_shocks)]
        
        ax2.plot(time_points, analysis_data['shock_analysis']['shocks'], 
                marker='s', linewidth=2, markersize=4, color='red', alpha=0.8)
        ax2.axhline(y=analysis_data['shock_analysis']['max_shock'], 
                   color='darkred', linestyle='--', alpha=0.7,
                   label=f'Max: {analysis_data["shock_analysis"]["max_shock"]:.1f}m/s²')
        ax2.axhline(y=analysis_data['shock_analysis']['avg_shock'], 
                   color='blue', linestyle=':', alpha=0.7,
                   label=f'Avg: {analysis_data["shock_analysis"]["avg_shock"]:.1f}m/s²')
        
        ax2.fill_between(time_points, analysis_data['shock_analysis']['shocks'], 
                        alpha=0.3, color='red')
        
        # Tambahkan info filter
        filter_info = analysis_data['shock_analysis'].get('filter_info', {})
        title = f'Guncangan Jalan (Filtered: {filter_info.get("filtered_count", 0)}/{filter_info.get("original_count", 0)})'
        ax2.set_title(title)
        ax2.set_xlabel('Waktu (detik)')
        ax2.set_ylabel('Guncangan (m/s²)')
        ax2.set_xlim(0, 30)
        ax2.legend()
        ax2.grid(True, alpha=0.3)
    else:
        ax2.text(0.5, 0.5, 'Tidak ada guncangan\njalan rusak terdeteksi', 
                ha='center', va='center', transform=ax2.transAxes, fontsize=14)
        ax2.set_title('Guncangan Jalan (Filtered)')
        ax2.set_xlabel('Waktu (detik)')
        ax2.set_xlim(0, 30)
        ax2.grid(True, alpha=0.3)
    
    # 3. Data getaran (vibration) - deg/s
    if analysis_data['vibration_analysis']['vibrations']:
        num_vibrations = len(analysis_data['vibration_analysis']['vibrations'])
        time_points = [i * (analysis_duration / (num_vibrations - 1)) if num_vibrations > 1 else 0 
                      for i in range(num_vibrations)]
        
        ax3.plot(time_points, analysis_data['vibration_analysis']['vibrations'], 
                marker='^', linewidth=2, markersize=4, color='purple', alpha=0.8)
        ax3.axhline(y=analysis_data['vibration_analysis']['max_vibration'], 
                   color='darkmagenta', linestyle='--', alpha=0.7,
                   label=f'Max: {analysis_data["vibration_analysis"]["max_vibration"]:.1f}deg/s')
        ax3.axhline(y=analysis_data['vibration_analysis']['avg_vibration'], 
                   color='blue', linestyle=':', alpha=0.7,
                   label=f'Avg: {analysis_data["vibration_analysis"]["avg_vibration"]:.1f}deg/s')
        
        ax3.fill_between(time_points, analysis_data['vibration_analysis']['vibrations'], 
                        alpha=0.3, color='purple')
        
        # Tambahkan info filter
        filter_info = analysis_data['vibration_analysis'].get('filter_info', {})
        title = f'Getaran Jalan (Filtered: {filter_info.get("filtered_count", 0)}/{filter_info.get("original_count", 0)})'
        ax3.set_title(title)
        ax3.set_xlabel('Waktu (detik)')
        ax3.set_ylabel('Getaran (deg/s)')
        ax3.set_xlim(0, 30)
        ax3.legend()
        ax3.grid(True, alpha=0.3)
    else:
        ax3.text(0.5, 0.5, 'Tidak ada getaran\njalan rusak terdeteksi', 
                ha='center', va='center', transform=ax3.transAxes, fontsize=14)
        ax3.set_title('Getaran Jalan (Filtered)')
        ax3.set_xlabel('Waktu (detik)')
        ax3.set_xlim(0, 30)
        ax3.grid(True, alpha=0.3)
    
    # 4. Info lokasi dan klasifikasi
    info_text = f"KLASIFIKASI KERUSAKAN:\n"
    info_text += f"   {analysis_data['damage_classification'].upper().replace('_', ' ')}\n\n"
    
    info_text += f"PANJANG KERUSAKAN:\n"
    info_text += f"   {analysis_data['damage_length']:.1f} meter\n\n"
    
    info_text += f"PARAMETER UTAMA:\n"
    info_text += f"   Surface: {analysis_data['surface_analysis']['max_change']:.1f}cm\n"
    info_text += f"   Shock: {analysis_data['shock_analysis']['max_shock']:.1f}m/s²\n"
    info_text += f"   Vibration: {analysis_data['vibration_analysis']['max_vibration']:.1f}deg/s\n\n"
    
    # TAMBAH SPEED INFO:
    info_text += f"ESTIMASI KECEPATAN:\n"
    if analysis_data['speed_analysis']['has_speed_data']:
        info_text += f"   {analysis_data['speed_analysis']['speed_range']}\n"
        info_text += f"   Rata-rata: {analysis_data['speed_analysis']['avg_speed']:.1f} km/h\n"
        info_text += f"   Data GPS: {analysis_data['speed_analysis']['count']} points\n\n"
    else:
        info_text += f"   Data GPS tidak tersedia\n\n"
    
    # Tambahkan info lokasi
    if analysis_data['start_location']:
        info_text += f"LOKASI AWAL:\n"
        info_text += f"   Lat: {analysis_data['start_location'][0]:.6f}\n"
        info_text += f"   Lng: {analysis_data['start_location'][1]:.6f}\n\n"
    
    if analysis_data['end_location']:
        info_text += f"LOKASI AKHIR:\n"
        info_text += f"   Lat: {analysis_data['end_location'][0]:.6f}\n"
        info_text += f"   Lng: {analysis_data['end_location'][1]:.6f}"
    
    # Color based on classification
    color_map = {
        'rusak_ringan': 'lightgreen',
        'rusak_sedang': 'yellow', 
        'rusak_berat': 'lightcoral'
    }
    bg_color = color_map.get(analysis_data['damage_classification'], 'lightgray')
    
    ax4.text(0.05, 0.95, info_text, ha='left', va='top', transform=ax4.transAxes, 
            fontsize=9, bbox=dict(boxstyle="round,pad=0.5", facecolor=bg_color, alpha=0.8))
    ax4.set_title('Info Kerusakan')
    ax4.axis('off')
    
    plt.tight_layout()
    
    # Save dengan timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'road_damage_{timestamp}.png'
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    plt.savefig(filepath, dpi=100, bbox_inches='tight')
    plt.close()
    
    return filepath, filename
