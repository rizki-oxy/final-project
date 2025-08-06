from datetime import datetime, timedelta
import io
from PIL import Image
import base64
import requests
import os
from core.database import get_db_connection
from core.config import UPLOAD_FOLDER, THINGSBOARD_IMAGE_CONFIG, THINGSBOARD_CONFIG, THINGSBOARD_URL

def test_thingsboard_conn():
    # Test ThingsBoard connection
    test_payload = {
        "startup_test": "Flask server starting with 3 parameters",
        "startup_timestamp": datetime.now().isoformat(),
        "parameters": "surface + shock + vibration",
        "shock_unit": "m/s² (filtered)",
        "vibration_unit": "deg/s (filtered)",
        "filters": "shock & vibration filters enabled"
    }
    
    if send_to_thingsboard(test_payload, "startup_test"):
        print("✅ ThingsBoard connection successful")
    else:
        print("⚠️ ThingsBoard connection failed - check configuration")
    

def send_to_thingsboard(payload_data, data_type="analysis"):
    """Mengirim data ke ThingsBoard via HTTP"""
    try:
        # Add prefix to identify data source
        prefixed_payload = {}
        for key, value in payload_data.items():
            prefixed_payload[f"fls_{key}"] = value
        
        # Add metadata
        prefixed_payload["fls_data_source"] = "flask_server"
        prefixed_payload["fls_data_type"] = data_type
        prefixed_payload["fls_timestamp"] = datetime.now().isoformat()
        
        headers = {
            'Content-Type': 'application/json'
        }
        
        response = requests.post(
            THINGSBOARD_URL, 
            json=prefixed_payload, 
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            print(f"✅ ThingsBoard: {data_type} data sent successfully")
            return True
        else:
            print(f"⚠️ ThingsBoard: HTTP {response.status_code} - {response.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ ThingsBoard connection error: {e}")
        return False
    except Exception as e:
        print(f"❌ ThingsBoard error: {e}")
        return False

def compress_image_for_thingsboard(image_path):
    """
    Kompres gambar PNG menjadi JPEG yang kompatibel dengan ThingsBoard
    Fokus pada mengatasi masalah payload size dan format compatibility
    """
    try:
        print(f"📸 Processing image for ThingsBoard: {image_path}")
        
        # Buka gambar asli
        with Image.open(image_path) as img:
            original_size = os.path.getsize(image_path)
            print(f"   Original PNG size: {original_size} bytes ({original_size/1024:.1f}KB)")
            
            # Convert RGBA ke RGB jika perlu (PNG dengan transparency)
            if img.mode in ('RGBA', 'LA', 'P'):
                # Buat background putih
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'RGBA':
                    background.paste(img, mask=img.split()[-1])
                elif img.mode == 'P':
                    img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1])
                else:
                    background.paste(img)
                img = background
                print(f"   Converted {img.mode} to RGB")
            
            # Resize jika terlalu besar
            original_dimensions = (img.width, img.height)
            if img.width > THINGSBOARD_IMAGE_CONFIG['max_width'] or img.height > THINGSBOARD_IMAGE_CONFIG['max_height']:
                img.thumbnail((
                    THINGSBOARD_IMAGE_CONFIG['max_width'], 
                    THINGSBOARD_IMAGE_CONFIG['max_height']
                ), Image.Resampling.LANCZOS)
                print(f"   Resized: {original_dimensions} → {img.size}")
            
            # Simpan sebagai JPEG dengan kompresi optimal
            img_buffer = io.BytesIO()
            img.save(img_buffer, 
                    format=THINGSBOARD_IMAGE_CONFIG['format'], 
                    quality=THINGSBOARD_IMAGE_CONFIG['jpeg_quality'], 
                    optimize=True)
            
            compressed_data = img_buffer.getvalue()
            compressed_size = len(compressed_data)
            
            print(f"   JPEG compressed size: {compressed_size} bytes ({compressed_size/1024:.1f}KB)")
            print(f"   Compression ratio: {compressed_size/original_size*100:.1f}%")
            
            # Convert ke base64
            base64_string = base64.b64encode(compressed_data).decode('utf-8')
            base64_size = len(base64_string)
            
            print(f"   Base64 size: {base64_size} bytes ({base64_size/1024:.1f}KB)")
            
            # Cek apakah ukuran sudah sesuai untuk ThingsBoard
            if base64_size <= THINGSBOARD_IMAGE_CONFIG['max_payload_size']:
                print(f"   ✅ ThingsBoard compatible ({base64_size} ≤ {THINGSBOARD_IMAGE_CONFIG['max_payload_size']})")
                return base64_string, base64_size, True
            else:
                print(f"   ⚠️ Still too large for ThingsBoard ({base64_size} > {THINGSBOARD_IMAGE_CONFIG['max_payload_size']})")
                # Coba dengan kualitas lebih rendah
                return try_further_compression(img, compressed_size)
                
    except Exception as e:
        print(f"❌ Error compressing image for ThingsBoard: {e}")
        return None, 0, False

def try_further_compression(img, current_size):
    """
    Coba kompresi lebih lanjut jika masih terlalu besar
    """
    print(f"   🔄 Trying further compression...")
    
    # Coba dengan kualitas yang lebih rendah
    for quality in [75, 65, 55, 45]:
        try:
            img_buffer = io.BytesIO()
            img.save(img_buffer, 
                    format='JPEG', 
                    quality=quality, 
                    optimize=True)
            
            compressed_data = img_buffer.getvalue()
            base64_string = base64.b64encode(compressed_data).decode('utf-8')
            base64_size = len(base64_string)
            
            print(f"   Quality {quality}%: {base64_size} bytes ({base64_size/1024:.1f}KB)")
            
            if base64_size <= THINGSBOARD_IMAGE_CONFIG['max_payload_size']:
                print(f"   ✅ Success with quality {quality}%")
                return base64_string, base64_size, True
                
        except Exception as e:
            print(f"   ❌ Failed at quality {quality}%: {e}")
            continue
    
    # Jika masih gagal, coba resize lebih kecil
    print(f"   🔄 Trying smaller dimensions...")
    for scale in [0.8, 0.6, 0.4]:
        try:
            new_width = int(img.width * scale)
            new_height = int(img.height * scale)
            resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            img_buffer = io.BytesIO()
            resized_img.save(img_buffer, format='JPEG', quality=75, optimize=True)
            
            compressed_data = img_buffer.getvalue()
            base64_string = base64.b64encode(compressed_data).decode('utf-8')
            base64_size = len(base64_string)
            
            print(f"   Scale {scale}: {new_width}x{new_height}, {base64_size} bytes")
            
            if base64_size <= THINGSBOARD_IMAGE_CONFIG['max_payload_size']:
                print(f"   ✅ Success with scale {scale}")
                return base64_string, base64_size, True
                
        except Exception as e:
            print(f"   ❌ Failed at scale {scale}: {e}")
            continue
    
    print(f"   ❌ All compression attempts failed")
    return None, 0, False

def send_analysis_with_optimized_image_to_thingsboard(analysis_id):
    """
    Kirim data analisis dengan gambar yang dioptimasi untuk ThingsBoard
    UPDATED: Kompres dari file lokal, bukan dari database
    """
    connection = get_db_connection()
    if not connection:
        return False
    
    try:
        cursor = connection.cursor(dictionary=True)
        
        query = "SELECT * FROM road_damage_analysis WHERE id = %s"
        cursor.execute(query, (analysis_id,))
        result = cursor.fetchone()
        
        if not result:
            print(f"❌ Analysis ID {analysis_id} not found")
            return False
        
        print(f"🔍 Sending analysis ID {analysis_id} to ThingsBoard with image compression")
        
        # Buat payload dasar (tanpa gambar dulu)
        thingsboard_payload = {
            "analysis_id": result['id'],
            "analysis_timestamp": result['analysis_timestamp'].isoformat() if result['analysis_timestamp'] else None,
            "damage_classification": result['damage_classification'],
            "damage_length": float(result['damage_length']) if result['damage_length'] else 0,
            "surface_change_max": float(result['surface_change_max']) if result['surface_change_max'] else 0,
            "shock_max_ms2": float(result['shock_max']) if result['shock_max'] else 0,
            "vibration_max_dps": float(result['vibration_max']) if result['vibration_max'] else 0,
            "speed_min_kmh": float(result['speed_min']) if result['speed_min'] else None,
    "speed_max_kmh": float(result['speed_max']) if result['speed_max'] else None,
    "speed_avg_kmh": float(result['speed_avg']) if result['speed_avg'] else None,
    "speed_range": result['speed_range'] if result['speed_range'] else "No GPS data",
    "speed_data_points": int(result['speed_data_count']) if result['speed_data_count'] else 0,
            "damage_detected": True,
            "compression_strategy": "file_to_thingsboard_only"
        }
        
        # Add location if available
        if result['start_latitude'] and result['start_longitude']:
            thingsboard_payload["start_latitude"] = float(result['start_latitude'])
            thingsboard_payload["start_longitude"] = float(result['start_longitude'])
        
        # Proses gambar: Kompres dari file PNG asli untuk ThingsBoard
        image_success = False
        
        if result['image_filename']:
            image_path = os.path.join(UPLOAD_FOLDER, result['image_filename'])
            
            if os.path.exists(image_path):
                print(f"📸 Compressing PNG file for ThingsBoard: {result['image_filename']}")
                
                # Kompres dari file PNG asli (bukan dari database)
                compressed_base64, base64_size, success = compress_image_for_thingsboard(image_path)
                
                if success and compressed_base64:
                    # Kirim gambar terkompresi ke ThingsBoard
                    thingsboard_payload.update({
                        "analysis_image_base64": compressed_base64,
                        "has_image": True,
                        "image_format": "JPEG_compressed_from_PNG",
                        "image_size_bytes": base64_size,
                        "database_has_original": True,
                        "compression_applied": True
                    })
                    image_success = True
                    print(f"✅ Compressed image sent to ThingsBoard: {base64_size} bytes")
                    print(f"💾 Database tetap menyimpan PNG asli")
                    
                else:
                    # Jika kompresi gagal, kirim metadata saja
                    thingsboard_payload.update({
                        "has_image": False,
                        "image_error": "compression_failed",
                        "image_too_complex": True,
                        "database_has_original": True,
                        "original_filename": result['image_filename']
                    })
                    print(f"⚠️ Image too complex for ThingsBoard - sending metadata only")
                    print(f"💾 Original PNG tetap tersimpan di database")
            else:
                thingsboard_payload.update({
                    "has_image": False,
                    "image_error": "file_not_found",
                    "database_has_original": True
                })
                print(f"❌ PNG file not found: {image_path}")
        else:
            thingsboard_payload.update({
                "has_image": False,
                "image_error": "no_filename"
            })
        
        # Send ke ThingsBoard
        success = send_to_thingsboard(thingsboard_payload, "road_damage_compressed")
        
        if success:
            status = "with compressed image" if image_success else "metadata only"
            print(f"✅ Analysis data sent to ThingsBoard ({status}) - ID: {analysis_id}")
            return True
        else:
            print(f"❌ Failed to send data to ThingsBoard - ID: {analysis_id}")
            return False
            
    except Exception as e:
        print(f"❌ Error in ThingsBoard transmission: {e}")
        return False
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

