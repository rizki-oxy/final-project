#include <WiFi.h>
#include <TinyGPS++.h>
#include <Wire.h>
#include <HTTPClient.h>

// WiFi Configuration
const char* ssid = "fff";
const char* password = "halo1234000";
const char* access_token = "0939gxC3IXo3uoCIgAED";

// ThingsBoard HTTP Configuration
const char* thingsboard_server = "192.168.43.18";
const int thingsboard_port = 8081;
const String thingsboard_url = "http://" + String(thingsboard_server) + ":" + String(thingsboard_port) + "/api/v1/" + String(access_token) + "/telemetry";

// Communication status tracking
unsigned long lastReconnectAttempt = 0;
unsigned long httpSuccessCount = 0;
unsigned long httpFailCount = 0;

// GPS Configuration
#define GPS_RX_PIN 16
#define GPS_TX_PIN 17
#define GPS_BAUD 9600

// MPU6050 Configuration
#define MPU6050_ADDR 0x68
#define PWR_MGMT_1 0x6B
#define ACCEL_XOUT_H 0x3B
#define GYRO_XOUT_H 0x43

// Conversion constants untuk MPU6050
const float ACCEL_SCALE_16G = 2048.0;    // LSB/g untuk ±16g range
const float GYRO_SCALE_250DPS = 131.0;   // LSB/(deg/s) untuk ±250 deg/s range
const float GRAVITY_MS2 = 9.81;          // m/s² conversion factor

// ESP32 I2C Pins
#define SDA_PIN 21
#define SCL_PIN 22

// Ultrasonic Sensor Pins
int trigPins[8] = {5, 4, 15, 2, 13, 12, 14, 27};
int echoPins[8] = {18, 19, 23, 25, 26, 33, 32, 35};

// GPS Objects
TinyGPSPlus gps;
HardwareSerial GPSSerial(2);

// GPS Variables
unsigned long lastGPSCheckTime = 0;
const unsigned long gpsCheckInterval = 3000;
unsigned long lastGPSDataTime = 0;
const unsigned long gpsDataTimeout = 5000;
bool gpsHardwareConnected = false;
bool gpsWorking = false;
unsigned long lastCharsProcessed = 0;
unsigned long rawGPSDataCount = 0;

// MPU6050 Variables - RAW DATA
int16_t accelX, accelY, accelZ;
int16_t gyroX, gyroY, gyroZ;

// MPU6050 Variables - CONVERTED DATA
float accelX_g, accelY_g, accelZ_g;           // dalam g
float accelX_ms2, accelY_ms2, accelZ_ms2;     // dalam m/s²
float accelMagnitude_g = 0;                   // magnitude dalam g
float accelMagnitude_ms2 = 0;                 // magnitude dalam m/s²

float gyroX_dps, gyroY_dps, gyroZ_dps;        // dalam deg/s
float rotationMagnitude_dps = 0;              // magnitude dalam deg/s

// ========== TAMBAHAN BARU: KALIBRASI GYROSCOPE ==========
// Offset kalibrasi gyroscope (diisi saat startup)
float gyroOffsetX = 0, gyroOffsetY = 0, gyroOffsetZ = 0;
bool gyroCalibrated = false;
const int CALIBRATION_SAMPLES = 100;

// Threshold untuk dead zone (hapus noise kecil)
const float GYRO_DEAD_ZONE = 1.0;  // deg/s - di bawah ini dianggap 0
// ========== END TAMBAHAN BARU ==========

// VARIABEL BARU UNTUK DETEKSI SHOCK & VIBRATION
float prevAccelMagnitude_ms2 = 0;
float shockMagnitude_ms2 = 0;                 // SHOCK dari accelerometer
float vibrationMagnitude_dps = 0;             // VIBRATION dari gyroscope
float shockThreshold_ms2 = 25.0;              // threshold shock dalam m/s²
float vibrationThreshold_dps = 100.0;         // threshold vibration dalam deg/s

// Buffer untuk smoothing shock (moving average)
const int SHOCK_BUFFER_SIZE = 5;
float shockBuffer[SHOCK_BUFFER_SIZE];
int shockBufferIndex = 0;
bool shockBufferFull = false;

// Buffer untuk smoothing vibration (moving average)
const int VIBRATION_BUFFER_SIZE = 5;
float vibrationBuffer[VIBRATION_BUFFER_SIZE];
int vibrationBufferIndex = 0;
bool vibrationBufferFull = false;

bool sensorDetected = false;
unsigned long lastSensorCheckTime = 0;
const unsigned long sensorCheckInterval = 1000;

// Ultrasonic Variables
unsigned long lastUltrasonicTime = 0;
const unsigned long ultrasonicInterval = 1000;
float distances[8];

// System Variables
unsigned long lastDataSendTime = 0;
const unsigned long dataSendInterval = 2000;

void setup() {
  Serial.begin(115200);
  setup_wifi();
  delay(1000);
  
  Serial.println("\n=== ESP32 Multi-Sensor System (Shock & Vibration Detection) ===");
  Serial.println("GPS + GY-521 + Ultrasonic Array");
  Serial.println("HTTP Communication");
  Serial.println("GY-521: Raw data + Converted to m/s² and deg/s");
  Serial.println("NEW: Shock (accelerometer) + Vibration (gyroscope) Detection");
  Serial.println("CALIBRATED: Gyroscope offset calibration enabled"); // TAMBAHAN BARU
  Serial.println("================================================================");
  
  // Initialize shock buffer
  for (int i = 0; i < SHOCK_BUFFER_SIZE; i++) {
    shockBuffer[i] = 0.0;
  }
  
  // Initialize vibration buffer
  for (int i = 0; i < VIBRATION_BUFFER_SIZE; i++) {
    vibrationBuffer[i] = 0.0;
  }
  
  // Initialize WiFi
  // setup_wifi();
  
  // Initialize I2C for MPU6050
  Wire.begin(SDA_PIN, SCL_PIN);
  
  // Initialize GPS Serial
  Serial.println("🛰️ Inisialisasi GPS...");
  GPSSerial.begin(GPS_BAUD, SERIAL_8N1, GPS_RX_PIN, GPS_TX_PIN);
  delay(1000);
  lastGPSDataTime = millis();
  
  // Check and initialize MPU6050
  Serial.println("🔄 Checking GY-521 sensor...");
  checkSensorConnection();
  
  if (sensorDetected) {
    // Wake up MPU6050
    Wire.beginTransmission(MPU6050_ADDR);
    Wire.write(PWR_MGMT_1);
    Wire.write(0);
    Wire.endTransmission(true);
    Serial.println("✅ GY-521 sensor initialized!");
    Serial.println("📊 Conversion: ±16g range, ±250°/s range");
    Serial.println("📊 Output: Raw LSB + m/s² + deg/s");
    Serial.println("📳 Shock detection: Accelerometer spikes");
    Serial.println("🔄 Vibration detection: Gyroscope oscillations");
    
    // ========== TAMBAHAN BARU: KALIBRASI GYROSCOPE ==========
    Serial.println("🔧 Kalibrasi gyroscope...");
    calibrateGyroscope();
    Serial.println("✅ Kalibrasi gyroscope selesai!");
    // ========== END TAMBAHAN BARU ==========
  }
  
  // Initialize Ultrasonic sensors
  Serial.println("📏 Inisialisasi Ultrasonic sensors...");
  for (int i = 0; i < 8; i++) {
    pinMode(trigPins[i], OUTPUT);
    pinMode(echoPins[i], INPUT);
  }
  Serial.println("✅ Ultrasonic sensors initialized!");
  
  Serial.println("\n--- MULTI-SENSOR MONITORING STARTED ---");
  Serial.println("📡 Communication: HTTP");
  Serial.println("🔄 GY-521: LSB → g → m/s² conversion enabled");
  Serial.println("📳 Shock: Accelerometer magnitude changes (m/s²)");
  Serial.println("🔄 Vibration: Gyroscope magnitude (deg/s) - CALIBRATED"); // TAMBAHAN BARU
  Serial.println();
}

// ========== TAMBAHAN BARU: FUNGSI KALIBRASI ==========
void calibrateGyroscope() {
  /*Kalibrasi offset gyroscope dengan 100 sample saat diam*/
  float sumX = 0, sumY = 0, sumZ = 0;
  
  Serial.println("⏳ Jangan gerakkan alat selama kalibrasi (10 detik)...");
  Serial.print("Progress: ");
  
  for (int i = 0; i < CALIBRATION_SAMPLES; i++) {
    // Baca raw data
    Wire.beginTransmission(MPU6050_ADDR);
    Wire.write(GYRO_XOUT_H);
    Wire.endTransmission(false);
    Wire.requestFrom(MPU6050_ADDR, 6, true);
    
    int16_t rawX = Wire.read() << 8 | Wire.read();
    int16_t rawY = Wire.read() << 8 | Wire.read();
    int16_t rawZ = Wire.read() << 8 | Wire.read();
    
    // Konversi ke deg/s
    sumX += (float)rawX / GYRO_SCALE_250DPS;
    sumY += (float)rawY / GYRO_SCALE_250DPS;
    sumZ += (float)rawZ / GYRO_SCALE_250DPS;
    
    delay(100);  // 100ms per sample
    
    if (i % 20 == 0) {
      Serial.print(".");
    }
  }
  
  // Hitung offset rata-rata
  gyroOffsetX = sumX / CALIBRATION_SAMPLES;
  gyroOffsetY = sumY / CALIBRATION_SAMPLES;
  gyroOffsetZ = sumZ / CALIBRATION_SAMPLES;
  
  gyroCalibrated = true;
  
  Serial.println();
  Serial.print("📊 Gyro Offset - X: ");
  Serial.print(gyroOffsetX, 3);
  Serial.print(", Y: ");
  Serial.print(gyroOffsetY, 3);
  Serial.print(", Z: ");
  Serial.println(gyroOffsetZ, 3);
}

// FUNGSI TAMBAHAN: Reset kalibrasi jika diperlukan
void resetGyroCalibration() {
  /*Reset dan kalibrasi ulang gyroscope*/
  gyroCalibrated = false;
  gyroOffsetX = gyroOffsetY = gyroOffsetZ = 0;
  
  Serial.println("🔄 Reset kalibrasi gyroscope...");
  delay(1000);
  calibrateGyroscope();
}
// ========== END TAMBAHAN BARU ==========

void loop() {
  unsigned long currentTime = millis();
  if (currentTime - lastReconnectAttempt > 10000) {
    if (!reconnect_wifi_if_needed()) {
      Serial.println("⚠️ WiFi tidak terhubung, menghentikan pengumpulan data.");
      lastReconnectAttempt = currentTime;
      return; // Keluar dari loop jika WiFi tidak terhubung
    }
    lastReconnectAttempt = currentTime;
  }
  // Process GPS data continuously
  processGPSData(currentTime);
  
  // Check GPS status periodically
  if (currentTime - lastGPSCheckTime >= gpsCheckInterval) {
    checkGPSStatus(currentTime);
    lastGPSCheckTime = currentTime;
  }
  
  // Check motion sensor periodically
  if (currentTime - lastSensorCheckTime >= sensorCheckInterval) {
    processSensorData();
    lastSensorCheckTime = currentTime;
  }
  
  // Read ultrasonic sensors periodically
  if (currentTime - lastUltrasonicTime >= ultrasonicInterval) {
    readAllUltrasonicSensors();
    lastUltrasonicTime = currentTime;
  }
  
  // Send all data periodically
  if (currentTime - lastDataSendTime >= dataSendInterval) {
    sendAllSensorData();
    lastDataSendTime = currentTime;
  }
  
  delay(10);
}

void setup_wifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  
  Serial.print("🔌 Menghubungkan ke WiFi...");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
    
  Serial.println("\n✅ WiFi terhubung!");
  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());
}

bool reconnect_wifi_if_needed() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("⚠️ WiFi terputus! Mencoba reconnect...");
    WiFi.disconnect();  
    WiFi.begin(ssid, password);

    unsigned long startAttemptTime = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - startAttemptTime < 10000) {
      delay(500);
      Serial.print(".");
    }

    if (WiFi.status() == WL_CONNECTED) {
      Serial.println("\n✅ WiFi tersambung ulang!");
      Serial.print("IP Address: ");
      Serial.println(WiFi.localIP());
      return true;
    } else {
      Serial.println("\n❌ Gagal reconnect. Akan coba lagi nanti.");
      return false;
    }
  }
  return true;
}

void processSensorData() {
  if (!sensorDetected) return;
  
  readSensorData();
  convertSensorData();
  calculateShockMagnitude();      // FUNGSI BARU UNTUK SHOCK
  calculateVibrationMagnitude();  // FUNGSI BARU UNTUK VIBRATION
  checkShock();
  checkVibration();
}

void checkSensorConnection() {
  Wire.beginTransmission(MPU6050_ADDR);
  byte error = Wire.endTransmission();
  
  if (error == 0) {
    sensorDetected = true;
    Serial.println("✅ GY-521 sensor detected!");
  } else {
    sensorDetected = false;
    Serial.println("❌ GY-521 sensor NOT detected!");
  }
}

void readSensorData() {
  // Baca data akselerometer (RAW)
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(ACCEL_XOUT_H);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU6050_ADDR, 6, true);
  
  accelX = Wire.read() << 8 | Wire.read();
  accelY = Wire.read() << 8 | Wire.read();
  accelZ = Wire.read() << 8 | Wire.read();
  
  // Baca data gyroskop (RAW)
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(GYRO_XOUT_H);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU6050_ADDR, 6, true);
  
  gyroX = Wire.read() << 8 | Wire.read();
  gyroY = Wire.read() << 8 | Wire.read();
  gyroZ = Wire.read() << 8 | Wire.read();
}

void convertSensorData() {
  // Konversi Accelerometer: LSB → g → m/s²
  accelX_g = (float)accelX / ACCEL_SCALE_16G;
  accelY_g = (float)accelY / ACCEL_SCALE_16G;
  accelZ_g = (float)accelZ / ACCEL_SCALE_16G;
  
  accelX_ms2 = accelX_g * GRAVITY_MS2;
  accelY_ms2 = accelY_g * GRAVITY_MS2;
  accelZ_ms2 = accelZ_g * GRAVITY_MS2;
  
  // Hitung magnitudo accelerometer
  accelMagnitude_g = sqrt(accelX_g * accelX_g + accelY_g * accelY_g + accelZ_g * accelZ_g);
  accelMagnitude_ms2 = sqrt(accelX_ms2 * accelX_ms2 + accelY_ms2 * accelY_ms2 + accelZ_ms2 * accelZ_ms2);
  
  // ========== MODIFIKASI: Konversi Gyroscope dengan KALIBRASI dan DEAD ZONE ==========
  // Konversi raw ke deg/s
  float rawGyroX_dps = (float)gyroX / GYRO_SCALE_250DPS;
  float rawGyroY_dps = (float)gyroY / GYRO_SCALE_250DPS;
  float rawGyroZ_dps = (float)gyroZ / GYRO_SCALE_250DPS;
  
  // Terapkan offset kalibrasi
  if (gyroCalibrated) {
    gyroX_dps = rawGyroX_dps - gyroOffsetX;
    gyroY_dps = rawGyroY_dps - gyroOffsetY;
    gyroZ_dps = rawGyroZ_dps - gyroOffsetZ;
  } else {
    gyroX_dps = rawGyroX_dps;
    gyroY_dps = rawGyroY_dps;
    gyroZ_dps = rawGyroZ_dps;
  }
  
  // Terapkan dead zone (hapus noise kecil)
  if (abs(gyroX_dps) < GYRO_DEAD_ZONE) gyroX_dps = 0;
  if (abs(gyroY_dps) < GYRO_DEAD_ZONE) gyroY_dps = 0;
  if (abs(gyroZ_dps) < GYRO_DEAD_ZONE) gyroZ_dps = 0;
  
  // Hitung magnitudo rotasi yang sudah dikalibrasi
  rotationMagnitude_dps = sqrt(gyroX_dps * gyroX_dps + gyroY_dps * gyroY_dps + gyroZ_dps * gyroZ_dps);
  // ========== END MODIFIKASI ==========
}

// FUNGSI BARU: Hitung magnitude shock dari accelerometer
void calculateShockMagnitude() {
  // Hitung perubahan accelerometer magnitude (shock detection)
  float rawShock = abs(accelMagnitude_ms2 - prevAccelMagnitude_ms2);
  
  // Masukkan ke buffer untuk smoothing
  shockBuffer[shockBufferIndex] = rawShock;
  shockBufferIndex = (shockBufferIndex + 1) % SHOCK_BUFFER_SIZE;
  
  if (shockBufferIndex == 0) {
    shockBufferFull = true;
  }
  
  // Hitung moving average untuk smoothing
  float sum = 0;
  int count = shockBufferFull ? SHOCK_BUFFER_SIZE : shockBufferIndex;
  
  for (int i = 0; i < count; i++) {
    sum += shockBuffer[i];
  }
  
  shockMagnitude_ms2 = sum / count;
  
  // Update previous magnitude
  prevAccelMagnitude_ms2 = accelMagnitude_ms2;
}

// ========== MODIFIKASI: FUNGSI VIBRATION MENGGUNAKAN DATA YANG SUDAH DIKALIBRASI ==========
void calculateVibrationMagnitude() {
  // Gunakan rotationMagnitude_dps yang sudah dikalibrasi dan di-dead zone
  float rawVibration = rotationMagnitude_dps;
  
  // Masukkan ke buffer untuk smoothing
  vibrationBuffer[vibrationBufferIndex] = rawVibration;
  vibrationBufferIndex = (vibrationBufferIndex + 1) % VIBRATION_BUFFER_SIZE;
  
  if (vibrationBufferIndex == 0) {
    vibrationBufferFull = true;
  }
  
  // Hitung moving average untuk smoothing
  float sum = 0;
  int count = vibrationBufferFull ? VIBRATION_BUFFER_SIZE : vibrationBufferIndex;
  
  for (int i = 0; i < count; i++) {
    sum += vibrationBuffer[i];
  }
  
  vibrationMagnitude_dps = sum / count;
}
// ========== END MODIFIKASI ==========

void checkShock() {
  if (shockMagnitude_ms2 > shockThreshold_ms2) {
    Serial.println("📳 SHOCK DETECTED!");
    Serial.print("Shock magnitude: "); 
    Serial.print(shockMagnitude_ms2); 
    Serial.println(" m/s²");
  }
}

void checkVibration() {
  if (vibrationMagnitude_dps > vibrationThreshold_dps) {
    Serial.println("🔄 VIBRATION DETECTED!");
    Serial.print("Vibration magnitude: "); 
    Serial.print(vibrationMagnitude_dps); 
    Serial.println(" deg/s");
  }
}

void processGPSData(unsigned long currentTime) {
  while (GPSSerial.available() > 0) {
    char c = GPSSerial.read();
    rawGPSDataCount++;
    gps.encode(c);
    lastGPSDataTime = currentTime;
  }
}

void checkGPSStatus(unsigned long currentTime) {
  // Check hardware connection
  if (rawGPSDataCount > 0 && !gpsHardwareConnected) {
    gpsHardwareConnected = true;
    Serial.println("✅ GPS Hardware Connected!");
  }
  
  // Check GPS functionality
  if (gpsHardwareConnected && gps.charsProcessed() > lastCharsProcessed) {
    if (!gpsWorking) {
      gpsWorking = true;
      Serial.println("✅ GPS Module Working!");
    }
    lastCharsProcessed = gps.charsProcessed();
    
    if (gps.location.isValid()) {
      Serial.println("🛰️ GPS SIGNAL ACQUIRED!");
      Serial.print("📍 Location: ");
      Serial.print(gps.location.lat(), 6);
      Serial.print(", ");
      Serial.print(gps.location.lng(), 6);
      
      if (gps.satellites.isValid()) {
        Serial.print(" | 🛰️ Satellites: ");
        Serial.print(gps.satellites.value());
      }
      
      if (gps.speed.isValid()) {
        Serial.print(" | 🚗 Speed: ");
        Serial.print(gps.speed.kmph());
        Serial.print(" km/h");
      }
      Serial.println();
    }
  }
  
  // Handle timeout
  if (currentTime - lastGPSDataTime >= gpsDataTimeout && !gpsHardwareConnected) {
    Serial.println("❌ GPS Timeout - Check connections!");
    lastGPSDataTime = currentTime;
  }
}

float readDistance(int trigPin, int echoPin) {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  long duration = pulseIn(echoPin, HIGH, 30000);
  float distance = duration * 0.034 / 2;
  if (distance == 0 || distance > 400) return -1;
  return distance;
}

void readAllUltrasonicSensors() {
  Serial.println("📏 Reading Ultrasonic Sensors:");
  for (int i = 0; i < 8; i++) {
    distances[i] = readDistance(trigPins[i], echoPins[i]);
    Serial.print("Sensor ");
    Serial.print(i + 1);
    Serial.print(": ");
    if (distances[i] == -1) {
      Serial.println("Error/Out of range");
    } else {
      Serial.print(distances[i]);
      Serial.println(" cm");
    }
  }
}

void sendAllSensorData() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("⚠️ WiFi not connected, skipping data send");
    return;
  }
  
  // Create comprehensive JSON payload untuk ThingsBoard
  String tbPayload = createThingsBoardPayload();
  
  // Create payload untuk Flask (data mentah + konversi)
  String flaskPayload = createFlaskPayload();
  
  // Send to Flask server
  sendToFlaskServer(flaskPayload);
  
  // Send to ThingsBoard with fallback logic
  bool httpSuccess = false;
  
  httpSuccess = sendDataViaHttp(tbPayload);
  
  // Status reporting
  if (httpSuccess) {
    Serial.println("📊 Status: HTTP ✅");
  } else {
    Serial.println("📊 Status: HTTP gagal ❌");
  }
  
  // Print communication statistics every 10 sends
  static int sendCount = 0;
  sendCount++;
  if (sendCount % 10 == 0) {
    printCommunicationStats();
  }
  
  Serial.println("=================================");
}

String createThingsBoardPayload() {
  String payload = "{";
  
  // Add timestamp
  payload += "\"timestamp\":" + String(millis()) + ",";
  
  // GPS Data
  if (gps.location.isValid()) {
    payload += "\"latitude\":" + String(gps.location.lat(), 6) + ",";
    payload += "\"longitude\":" + String(gps.location.lng(), 6) + ",";
  }
  if (gps.speed.isValid()) {
    payload += "\"speed\":" + String(gps.speed.kmph()) + ",";
  }
  if (gps.satellites.isValid()) {
    payload += "\"satellites\":" + String(gps.satellites.value()) + ",";
  }
  
  // Motion Sensor Data - TERMASUK SHOCK & VIBRATION MAGNITUDE
  if (sensorDetected) {
    // NILAI SHOCK & VIBRATION UTAMA UNTUK WIDGET
    payload += "\"shock_magnitude\":" + String(shockMagnitude_ms2, 2) + ",";
    payload += "\"vibration_magnitude\":" + String(vibrationMagnitude_dps, 2) + ",";
    
    // Converted accelerometer data (m/s²)
    payload += "\"accel_magnitude_ms2\":" + String(accelMagnitude_ms2, 2) + ",";
    payload += "\"accel_x_ms2\":" + String(accelX_ms2, 2) + ",";
    payload += "\"accel_y_ms2\":" + String(accelY_ms2, 2) + ",";
    payload += "\"accel_z_ms2\":" + String(accelZ_ms2, 2) + ",";
    
    // Converted gyroscope data (deg/s) - SUDAH DIKALIBRASI
    payload += "\"rotation_magnitude_dps\":" + String(rotationMagnitude_dps, 2) + ",";
    payload += "\"gyro_x_dps\":" + String(gyroX_dps, 2) + ",";
    payload += "\"gyro_y_dps\":" + String(gyroY_dps, 2) + ",";
    payload += "\"gyro_z_dps\":" + String(gyroZ_dps, 2) + ",";
    
    // ========== TAMBAHAN BARU: INFO KALIBRASI ==========
    payload += "\"gyro_calibrated\":" + String(gyroCalibrated ? "true" : "false") + ",";
    payload += "\"gyro_offset_x\":" + String(gyroOffsetX, 3) + ",";
    payload += "\"gyro_offset_y\":" + String(gyroOffsetY, 3) + ",";
    payload += "\"gyro_offset_z\":" + String(gyroOffsetZ, 3) + ",";
    payload += "\"gyro_dead_zone\":" + String(GYRO_DEAD_ZONE, 1) + ",";
    // ========== END TAMBAHAN BARU ==========
  }
  
  // Ultrasonic Data
  for (int i = 0; i < 8; i++) {
    payload += "\"sensor" + String(i + 1) + "\":" + String(distances[i]);
    if (i < 7) payload += ",";
  }
  
  payload += "}";
  return payload;
}

String createFlaskPayload() {
  String payload = "{";
  
  // GPS Data untuk Flask
  if (gps.location.isValid()) {
    payload += "\"latitude\":" + String(gps.location.lat(), 6) + ",";
    payload += "\"longitude\":" + String(gps.location.lng(), 6) + ",";
  }
  if (gps.speed.isValid()) {
    payload += "\"speed\":" + String(gps.speed.kmph()) + ",";
  }
  if (gps.satellites.isValid()) {
    payload += "\"satellites\":" + String(gps.satellites.value()) + ",";
  }
  
  // Data GY-521 untuk Flask (RAW + CONVERTED + SHOCK + VIBRATION)
  if (sensorDetected) {
    // Raw data (untuk backup/debugging)
    payload += "\"accelX\":" + String(accelX) + ",";
    payload += "\"accelY\":" + String(accelY) + ",";
    payload += "\"accelZ\":" + String(accelZ) + ",";
    payload += "\"gyroX\":" + String(gyroX) + ",";
    payload += "\"gyroY\":" + String(gyroY) + ",";
    payload += "\"gyroZ\":" + String(gyroZ) + ",";
    
    // Converted data (untuk analisis)
    payload += "\"accelX_ms2\":" + String(accelX_ms2, 2) + ",";
    payload += "\"accelY_ms2\":" + String(accelY_ms2, 2) + ",";
    payload += "\"accelZ_ms2\":" + String(accelZ_ms2, 2) + ",";
    payload += "\"accel_magnitude_ms2\":" + String(accelMagnitude_ms2, 2) + ",";
    payload += "\"gyroX_dps\":" + String(gyroX_dps, 2) + ",";
    payload += "\"gyroY_dps\":" + String(gyroY_dps, 2) + ",";
    payload += "\"gyroZ_dps\":" + String(gyroZ_dps, 2) + ",";
    payload += "\"rotation_magnitude_dps\":" + String(rotationMagnitude_dps, 2) + ",";
    
    // SHOCK & VIBRATION MAGNITUDE untuk Flask
    payload += "\"shock_magnitude\":" + String(shockMagnitude_ms2, 2) + ",";
    payload += "\"vibration_magnitude\":" + String(vibrationMagnitude_dps, 2) + ",";
    
    // ========== TAMBAHAN BARU: INFO KALIBRASI UNTUK FLASK ==========
    payload += "\"gyro_calibrated\":" + String(gyroCalibrated ? "true" : "false") + ",";
    payload += "\"gyro_offset_x\":" + String(gyroOffsetX, 3) + ",";
    payload += "\"gyro_offset_y\":" + String(gyroOffsetY, 3) + ",";
    payload += "\"gyro_offset_z\":" + String(gyroOffsetZ, 3) + ",";
    // ========== END TAMBAHAN BARU ==========
  }
  
  // Ultrasonic data untuk Flask
  for (int i = 0; i < 8; i++) {
    payload += "\"sensor" + String(i + 1) + "\":" + String(distances[i]);
    if (i < 7) payload += ",";
  }
  payload += "}";
  
  return payload;
}


bool sendDataViaHttp(String payload) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("❌ HTTP: WiFi tidak terhubung");
    return false;
  }
  
  HTTPClient http;
  http.begin(thingsboard_url);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(5000);
  
  int httpResponseCode = http.POST(payload);
  
  if (httpResponseCode > 0) {
    if (httpResponseCode == 200) {
      Serial.println("✅ HTTP: Data terkirim ke ThingsBoard");
      httpSuccessCount++;
      http.end();
      return true;
    } else {
      Serial.print("⚠️ HTTP: Response code ");
      Serial.println(httpResponseCode);
    }
  } else {
    Serial.print("❌ HTTP: Error ");
    Serial.println(http.errorToString(httpResponseCode));
  }
  
  httpFailCount++;
  http.end();
  return false;
}

void sendToFlaskServer(String payload) {
  HTTPClient http;
  http.begin("http://192.168.43.18:5000/multisensor");
  http.addHeader("Content-Type", "application/json");
  int httpResponseCode = http.POST(payload);
  Serial.print("📡 Flask response: ");
  Serial.println(httpResponseCode);
  http.end();
}

void printCommunicationStats() {
  Serial.println("\n📊 === COMMUNICATION STATISTICS ===");
  Serial.print("HTTP Success Count: ");
  Serial.println(httpSuccessCount);
  Serial.print("HTTP Fail Count: ");
  Serial.println(httpFailCount);
  Serial.print("WiFi Status: ");
  Serial.println(WiFi.status() == WL_CONNECTED ? "✅ Connected" : "❌ Disconnected");
  Serial.print("Free Heap: ");
  Serial.print(ESP.getFreeHeap());
  Serial.println(" bytes");
  
  // Print conversion info + SHOCK & VIBRATION INFO + KALIBRASI INFO
  if (sensorDetected) {
    Serial.println("🔄 === GY-521 CONVERSION STATUS ===");
    Serial.print("Accel Magnitude: ");
    Serial.print(accelMagnitude_ms2);
    Serial.println(" m/s²");
    Serial.print("Shock Magnitude: ");
    Serial.print(shockMagnitude_ms2);
    Serial.print(" m/s² (Accelerometer Changes)");
    Serial.println();
    Serial.print("Vibration Magnitude: ");
    Serial.print(vibrationMagnitude_dps);
    Serial.print(" deg/s (Gyroscope Rotations - CALIBRATED)");
    Serial.println();
    Serial.print("Rotation Magnitude: ");
    Serial.print(rotationMagnitude_dps);
    Serial.println(" deg/s");
    
    // ========== TAMBAHAN BARU: STATUS KALIBRASI ==========
    Serial.println("🔧 === GYROSCOPE CALIBRATION STATUS ===");
    Serial.print("Calibrated: ");
    Serial.println(gyroCalibrated ? "✅ YES" : "❌ NO");
    if (gyroCalibrated) {
      Serial.print("Offset X: ");
      Serial.print(gyroOffsetX, 3);
      Serial.println(" deg/s");
      Serial.print("Offset Y: ");
      Serial.print(gyroOffsetY, 3);
      Serial.println(" deg/s");
      Serial.print("Offset Z: ");
      Serial.print(gyroOffsetZ, 3);
      Serial.println(" deg/s");
      Serial.print("Dead Zone: ±");
      Serial.print(GYRO_DEAD_ZONE, 1);
      Serial.println(" deg/s");
    }
    // ========== END TAMBAHAN BARU ==========
  }
  Serial.println("=====================================\n");
}