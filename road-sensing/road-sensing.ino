#include <WiFi.h>
#include <TinyGPS++.h>
#include <Wire.h>
#include <HTTPClient.h>
#include <PubSubClient.h>

// WiFi & MQTT Configuration
const char* ssid = "fff";
const char* password = "halo1234000";
const char* mqtt_server = "192.168.43.18";
const int mqtt_port = 1883;
const char* access_token = "0939gxC3IXo3uoCIgAED";

// ThingsBoard HTTP Configuration
const char* thingsboard_server = "192.168.43.18";  // ThingsBoard demo server
const int thingsboard_port = 8081;  // Default ThingsBoard port
const String thingsboard_url = "http://" + String(thingsboard_server) + ":" + String(thingsboard_port) + "/api/v1/" + String(access_token) + "/telemetry";

WiFiClient espClient;
PubSubClient client(espClient);

// Communication status tracking
bool mqttConnected = false;
unsigned long lastMqttAttempt = 0;
const unsigned long mqttRetryInterval = 5000;  // Retry MQTT every 5 seconds
unsigned long mqttFailCount = 0;
unsigned long httpSuccessCount = 0;
unsigned long httpFailCount = 0;

// GPS Configuration
#define GPS_RX_PIN 16  // ESP32 menerima data dari GPS
#define GPS_TX_PIN 17  // ESP32 mengirim data ke GPS
#define GPS_BAUD 9600

// MPU6050 Configuration
#define MPU6050_ADDR 0x68
#define PWR_MGMT_1 0x6B
#define ACCEL_XOUT_H 0x3B
#define GYRO_XOUT_H 0x43

// ESP32 I2C Pins (Reserved for GY-521)
#define SDA_PIN 21
#define SCL_PIN 22

// Ultrasonic Sensor Pins
int trigPins[8] = {5, 4, 15, 2, 13, 12, 14, 27};      // Trigger pins
int echoPins[8] = {18, 19, 23, 25, 26, 33, 32, 35};   // Echo pins

// GPS Objects
TinyGPSPlus gps;
HardwareSerial GPSSerial(2);

// GPS Variables
unsigned long lastGPSCheckTime = 0;
const unsigned long gpsCheckInterval = 3000;  // Check GPS every 3 seconds
unsigned long lastGPSDataTime = 0;
const unsigned long gpsDataTimeout = 5000;
bool gpsHardwareConnected = false;
bool gpsWorking = false;
unsigned long lastCharsProcessed = 0;
unsigned long rawGPSDataCount = 0;

// MPU6050 Variables
int16_t accelX, accelY, accelZ;
int16_t gyroX, gyroY, gyroZ;
float accelMagnitude = 0;        // tambahan untuk magnitudo getaran
float rotationMagnitude = 0;     // tambahan untuk magnitudo rotasi
float prevAccelMagnitude = 0;
float vibrationThreshold = 2.0;
float rotationThreshold = 500;
bool sensorDetected = false;
unsigned long lastSensorCheckTime = 0;
const unsigned long sensorCheckInterval = 1000;  // Check sensor every 1 second

// Ultrasonic Variables
unsigned long lastUltrasonicTime = 0;
const unsigned long ultrasonicInterval = 1000;  // Read ultrasonic every 1 second
float distances[8];

// System Variables
unsigned long lastDataSendTime = 0;
const unsigned long dataSendInterval = 2000;  // Send data every 2 seconds

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("\n=== ESP32 Multi-Sensor System ===");
  Serial.println("GPS + GY-521 + Ultrasonic Array");
  Serial.println("MQTT + HTTP Backup Communication");
  Serial.println("=================================");
  
  // Initialize WiFi
  setup_wifi();
  
  // Initialize MQTT
  client.setServer(mqtt_server, mqtt_port);
  client.setCallback(mqttCallback);
  
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
  }
  
  // Initialize Ultrasonic sensors
  Serial.println("📏 Inisialisasi Ultrasonic sensors...");
  for (int i = 0; i < 8; i++) {
    pinMode(trigPins[i], OUTPUT);
    pinMode(echoPins[i], INPUT);
  }
  Serial.println("✅ Ultrasonic sensors initialized!");
  
  Serial.println("\n--- MULTI-SENSOR MONITORING STARTED ---");
  Serial.println("📡 Communication: MQTT Primary + HTTP Backup");
  Serial.println();
}

void loop() {
  unsigned long currentTime = millis();
  
  // Handle MQTT connection with retry logic
  handleMqttConnection();
  
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
  Serial.print("🔌 Menghubungkan ke WiFi...");
  WiFi.begin(ssid, password);
  
  unsigned long wifiStartTime = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - wifiStartTime < 15000) {
    delay(500);
    Serial.print(".");
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n✅ WiFi terhubung!");
    Serial.print("IP Address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\n⚠️ WiFi gagal terhubung!");
  }
}

void handleMqttConnection() {
  if (!client.connected()) {
    mqttConnected = false;
    unsigned long currentTime = millis();
    
    // Only try to reconnect after retry interval
    if (currentTime - lastMqttAttempt >= mqttRetryInterval) {
      Serial.print("🔄 Mencoba koneksi MQTT...");
      if (client.connect("ESP32MultiSensor", access_token, NULL)) {
        Serial.println(" ✅ MQTT terhubung");
        mqttConnected = true;
        mqttFailCount = 0;
      } else {
        Serial.print(" ❌ MQTT gagal, rc=");
        Serial.println(client.state());
        mqttFailCount++;
        Serial.println("⚠️ Akan menggunakan HTTP backup");
      }
      lastMqttAttempt = currentTime;
    }
  } else {
    mqttConnected = true;
    client.loop();
  }
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  // Handle MQTT messages if needed
}

bool sendDataViaMqtt(String payload) {
  if (!mqttConnected || !client.connected()) {
    return false;
  }
  
  bool success = client.publish("v1/devices/me/telemetry", payload.c_str());
  if (success) {
    Serial.println("✅ MQTT: Data terkirim");
  } else {
    Serial.println("❌ MQTT: Gagal kirim data");
    mqttConnected = false;
  }
  return success;
}

bool sendDataViaHttp(String payload) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("❌ HTTP: WiFi tidak terhubung");
    return false;
  }
  
  HTTPClient http;
  http.begin(thingsboard_url);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(5000);  // 5 second timeout
  
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

void processSensorData() {
  if (!sensorDetected) return;
  
  readSensorData();
  checkRotation();
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
  // Baca data akselerometer
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(ACCEL_XOUT_H);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU6050_ADDR, 6, true);
  
  accelX = Wire.read() << 8 | Wire.read();
  accelY = Wire.read() << 8 | Wire.read();
  accelZ = Wire.read() << 8 | Wire.read();
  
  // Hitung magnitudo akselerometer
  accelMagnitude = sqrt((float)accelX * accelX + (float)accelY * accelY + (float)accelZ * accelZ);
  
  // Baca data gyroskop
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(GYRO_XOUT_H);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU6050_ADDR, 6, true);
  
  gyroX = Wire.read() << 8 | Wire.read();
  gyroY = Wire.read() << 8 | Wire.read();
  gyroZ = Wire.read() << 8 | Wire.read();
  
  // Hitung magnitudo gyroskop (dalam deg/s)
  float rotX = gyroX / 131.0;
  float rotY = gyroY / 131.0;
  float rotZ = gyroZ / 131.0;
  rotationMagnitude = sqrt(rotX * rotX + rotY * rotY + rotZ * rotZ);
}

void checkRotation() {
  float rotX = gyroX / 131.0;
  float rotY = gyroY / 131.0;
  float rotZ = gyroZ / 131.0;
  
  if (abs(rotX) > rotationThreshold || abs(rotY) > rotationThreshold || abs(rotZ) > rotationThreshold) {
    Serial.println("🔄 ROTATION DETECTED!");
    Serial.print("Rotation - X: "); Serial.print(rotX); 
    Serial.print(" | Y: "); Serial.print(rotY); 
    Serial.print(" | Z: "); Serial.print(rotZ); Serial.println(" deg/s");
  }
}

void checkVibration() {
  accelMagnitude = sqrt(accelX*accelX + accelY*accelY + accelZ*accelZ);
  float accelChange = abs(accelMagnitude - prevAccelMagnitude);
  
  if (accelChange > vibrationThreshold * 1000) {
    Serial.println("📳 VIBRATION/SHOCK DETECTED!");
    Serial.print("Acceleration change: "); Serial.println(accelChange);
  }
  
  prevAccelMagnitude = accelMagnitude;
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
  
  // Create comprehensive JSON payload
  String payload = createJsonPayload();
  
  // Send to Flask server (original)
  sendToFlaskServer(payload);
  
  // Send to ThingsBoard with fallback logic
  bool mqttSuccess = false;
  bool httpSuccess = false;
  
  // Try MQTT first
  if (mqttConnected) {
    mqttSuccess = sendDataViaMqtt(payload);
  }
  
  // If MQTT failed or not connected, use HTTP backup
  if (!mqttSuccess) {
    Serial.println("📡 Menggunakan HTTP backup...");
    httpSuccess = sendDataViaHttp(payload);
  }
  
  // Status reporting
  if (mqttSuccess) {
    Serial.println("📊 Status: MQTT ✅");
  } else if (httpSuccess) {
    Serial.println("📊 Status: HTTP Backup ✅");
  } else {
    Serial.println("📊 Status: Semua komunikasi gagal ❌");
  }
  
  // Print communication statistics every 10 sends
  static int sendCount = 0;
  sendCount++;
  if (sendCount % 10 == 0) {
    printCommunicationStats();
  }
  
  Serial.println("=================================");
}

String createJsonPayload() {
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
  
  // Motion Sensor Data - Kirim data olahan (magnitudo) ke ThingsBoard
  if (sensorDetected) {
    payload += "\"accelMagnitude\":" + String(accelMagnitude) + ",";
    payload += "\"rotationMagnitude\":" + String(rotationMagnitude) + ",";
    // Tetap kirim data raw untuk backup/debugging
    payload += "\"accelX\":" + String(accelX) + ",";
    payload += "\"accelY\":" + String(accelY) + ",";
    payload += "\"accelZ\":" + String(accelZ) + ",";
    payload += "\"gyroX\":" + String(gyroX) + ",";
    payload += "\"gyroY\":" + String(gyroY) + ",";
    payload += "\"gyroZ\":" + String(gyroZ) + ",";
  }
  
  // Ultrasonic Data
  for (int i = 0; i < 8; i++) {
    payload += "\"sensor" + String(i + 1) + "\":" + String(distances[i]);
    if (i < 7) payload += ",";
  }
  
  payload += "}";
  return payload;
}

void sendToFlaskServer(String payload) {
  // Buat payload terpisah untuk Flask (data mentah)
  String flaskPayload = "{";
  
  // GPS Data untuk Flask
  if (gps.location.isValid()) {
    flaskPayload += "\"latitude\":" + String(gps.location.lat(), 6) + ",";
    flaskPayload += "\"longitude\":" + String(gps.location.lng(), 6) + ",";
  }
  if (gps.speed.isValid()) {
    flaskPayload += "\"speed\":" + String(gps.speed.kmph()) + ",";
  }
  if (gps.satellites.isValid()) {
    flaskPayload += "\"satellites\":" + String(gps.satellites.value()) + ",";
  }
  
  // Data raw sensor untuk Flask
  if (sensorDetected) {
    flaskPayload += "\"accelX\":" + String(accelX) + ",";
    flaskPayload += "\"accelY\":" + String(accelY) + ",";
    flaskPayload += "\"accelZ\":" + String(accelZ) + ",";
    flaskPayload += "\"gyroX\":" + String(gyroX) + ",";
    flaskPayload += "\"gyroY\":" + String(gyroY) + ",";
    flaskPayload += "\"gyroZ\":" + String(gyroZ) + ",";
  }
  
  // Ultrasonic data untuk Flask
  for (int i = 0; i < 8; i++) {
    flaskPayload += "\"sensor" + String(i + 1) + "\":" + String(distances[i]);
    if (i < 7) flaskPayload += ",";
  }
  flaskPayload += "}";
  
  HTTPClient http;
  http.begin("http://192.168.43.18:5000/multisensor");
  http.addHeader("Content-Type", "application/json");
  int httpResponseCode = http.POST(flaskPayload);
  Serial.print("📡 Flask response: ");
  Serial.println(httpResponseCode);
  http.end();
}

void printCommunicationStats() {
  Serial.println("\n📊 === COMMUNICATION STATISTICS ===");
  Serial.print("MQTT Status: ");
  Serial.println(mqttConnected ? "✅ Connected" : "❌ Disconnected");
  Serial.print("MQTT Fail Count: ");
  Serial.println(mqttFailCount);
  Serial.print("HTTP Success Count: ");
  Serial.println(httpSuccessCount);
  Serial.print("HTTP Fail Count: ");
  Serial.println(httpFailCount);
  Serial.print("WiFi Status: ");
  Serial.println(WiFi.status() == WL_CONNECTED ? "✅ Connected" : "❌ Disconnected");
  Serial.print("Free Heap: ");
  Serial.print(ESP.getFreeHeap());
  Serial.println(" bytes");
  Serial.println("=====================================\n");
}