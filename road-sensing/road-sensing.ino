#include <WiFi.h>
#include <TinyGPS++.h>
#include <Wire.h>
#include <HTTPClient.h>
#include <PubSubClient.h>

// WiFi & MQTT Configuration
const char* ssid = "MOMO";
const char* password = "1sampai8";
const char* mqtt_server = "demo.thingsboard.io";
const int mqtt_port = 1883;
const char* access_token = "r7DUFq0R2PXLNNvmSZwp";

WiFiClient espClient;
PubSubClient client(espClient);

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
float accelMagnitude;
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
  Serial.println("=================================");
  
  // Initialize WiFi
  setup_wifi();
  
  // Initialize MQTT
  client.setServer(mqtt_server, mqtt_port);
  
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
  Serial.println();
}

void loop() {
  unsigned long currentTime = millis();
  
  // Maintain MQTT connection
  if (!client.connected()) {
    reconnect();
  }
  client.loop();
  
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

void reconnect() {
  while (!client.connected()) {
    Serial.print("🔄 Hubungkan MQTT...");
    if (client.connect("ESP32MultiSensor", access_token, NULL)) {
      Serial.println(" ✅ MQTT terhubung");
    } else {
      Serial.print(" ❌ Gagal, rc=");
      Serial.print(client.state());
      delay(5000);
    }
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
  // Read accelerometer
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(ACCEL_XOUT_H);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU6050_ADDR, 6, true);
  
  accelX = Wire.read() << 8 | Wire.read();
  accelY = Wire.read() << 8 | Wire.read();
  accelZ = Wire.read() << 8 | Wire.read();
  
  // Read gyroscope
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(GYRO_XOUT_H);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU6050_ADDR, 6, true);
  
  gyroX = Wire.read() << 8 | Wire.read();
  gyroY = Wire.read() << 8 | Wire.read();
  gyroZ = Wire.read() << 8 | Wire.read();
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
  String payload = "{";
  
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
  
  // Motion Sensor Data
  if (sensorDetected) {
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
  
  // Send to Flask server
  HTTPClient http;
  http.begin("http://192.168.18.38:5000/multisensor");
  http.addHeader("Content-Type", "application/json");
  int httpResponseCode = http.POST(payload);
  Serial.print("📡 Flask response: ");
  Serial.println(httpResponseCode);
  http.end();
  
  // Send to MQTT (ThingsBoard)
  Serial.println("📡 Sending to MQTT: " + payload);
  client.publish("v1/devices/me/telemetry", payload.c_str());
  
  Serial.println("=================================");
}