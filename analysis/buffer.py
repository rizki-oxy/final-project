import threading
from datetime import datetime, timedelta

from thresholds import ANALYSIS_INTERVAL

# Data storage untuk analisis 30 detik
class DataBuffer:
    def __init__(self, max_duration=30):
        self.max_duration = max_duration
        self.data_points = []
        self.lock = threading.Lock()
    
    def add_data(self, data):
        with self.lock:
            current_time = datetime.now()
            data['timestamp'] = current_time
            self.data_points.append(data)
            
            # Hapus data yang lebih dari 30 detik
            cutoff_time = current_time - timedelta(seconds=self.max_duration)
            self.data_points = [dp for dp in self.data_points if dp['timestamp'] >= cutoff_time]
    
    def get_data(self):
        with self.lock:
            return list(self.data_points)
    
    def get_data_count(self):
        with self.lock:
            return len(self.data_points)

# Global buffer instance
# data_buffer = None

# def init_buffer(duration):
#     global data_buffer
#     data_buffer = DataBuffer(duration)
    
# Global data buffer
data_buffer = DataBuffer(ANALYSIS_INTERVAL)
last_analysis_time = 0
first_data_received_time = None  # Waktu pertama data diterima dari ESP32
INITIAL_SKIP_PERIOD = 30  # Skip 30 detik pertama setelah data pertama