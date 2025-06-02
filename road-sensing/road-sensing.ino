#include <WiFi.h>
#include <TinyGPS++.h>
#include <Wire.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// WiFi Configuration
const char* ssid = "MOMO";
const char* password = "1sampai8";

// MQTT Configuration
const char* mqtt_server = "demo.thingsboard.io";
const int mqtt_port = 1883;
const char* thingsboard_token = "r7DUFq0R2PXLNNvmSZwp";

// Flask MQTT Configuration (assuming Flask MQTT broker is running)
const char* flask_mqtt_server = "192.168.18.38";  // IP address of Flask server
const int flask_mqtt_port = 1883;
const char* flask_topic = "sensor/road_monitoring";

WiFiClient espClient;
PubSubClient thingsboard_client(espClient);
WiFiClient flaskClient;
PubSubClient flask_client(flaskClient);

// GPS Configuration
#define GPS_RX_PIN 16
#define GPS_TX_PIN 17
#define GPS_BAUD 9600

// MPU6050 Configuration
#define MPU6050_ADDR 0x68
#define PWR_MGMT_1 0x6B
#define ACCEL_XOUT_H 0x3B
#define GYRO_XOUT_H 0x43

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

// MPU6050 Variables
int16_t accelX, accelY, accelZ;
int16_t gyroX, gyroY, gyroZ;
float accelMagnitude;
float prevAccelMagnitude = 0;
float vibrationThreshold = 2.0;
float rotationThreshold = 500;
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

// Connection status
bool thingsboard_connected = false;
bool flask_connected = false;

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("\n=== ESP32 Multi-Sensor System ===");
  Serial.println("GPS + GY-521 + Ultrasonic Array");
  Serial.println("MQTT Communication Only");
  Serial.println("=================================");
  
  // Initialize WiFi
  setup_wifi();
  
  // Initialize MQTT clients
  setup_mqtt_clients();
  
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
  
  // Maintain MQTT connections
  maintainMQTTConnections();
  
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
    sendAllSensorDataMQTT();
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

void setup_mqtt_clients() {
  // Setup ThingsBoard MQTT client
  thingsboard_client.setServer(mqtt_server, mqtt_port);
  thingsboard_client.setCallback(thingsboard_callback);
  
  // Setup Flask MQTT client
  flask_client.setServer(flask_mqtt_server, flask_mqtt_port);
  flask_client.setCallback(flask_callback);
  
  Serial.println("📡 MQTT clients configured");
}

void maintainMQTTConnections() {
  // Maintain ThingsBoard connection
  if (!thingsboard_client.connected()) {
    reconnect_thingsboard();
  } else {
    thingsboard_client.loop();
  }
  
  // Maintain Flask MQTT connection
  if (!flask_client.connected()) {
    reconnect_flask();
  } else {
    flask_client.loop();
  }
}

void reconnect_thingsboard() {
  static unsigned long lastReconnectAttempt = 0;
  unsigned long now = millis();
  
  if (now - lastReconnectAttempt > 5000) {
    lastReconnectAttempt = now;
    
    Serial.print("🔄 Menghubungkan ke ThingsBoard MQTT...");
    if (thingsboard_client.connect("ESP32MultiSensor", thingsboard_token, NULL)) {
      Serial.println(" ✅ ThingsBoard MQTT terhubung");
      thingsboard_connected = true;
    } else {
      Serial.print(" ❌ Gagal, rc=");
      Serial.println(thingsboard_client.state());
      thingsboard_connected = false;
    }
  }
}

void reconnect_flask() {
  static unsigned long lastReconnectAttempt = 0;
  unsigned long now = millis();
  
  if (now - lastReconnectAttempt > 5000) {
    lastReconnectAttempt = now;
    
    Serial.print("🔄 Menghubungkan ke Flask MQTT...");
    if (flask_client.connect("ESP32FlaskClient")) {
      Serial.println(" ✅ Flask MQTT terhubung");
      flask_connected = true;
      // Subscribe to any response topics if needed
      flask_client.subscribe("sensor/road_monitoring/response");
    } else {
      Serial.print(" ❌ Gagal, rc=");
      Serial.println(flask_client.state());
      flask_connected = false;
    }
  }
}

void thingsboard_callback(char* topic, byte* payload, unsigned int length) {
  Serial.print("📩 ThingsBoard message received: ");
  Serial.println(topic);
  // Handle ThingsBoard responses if needed
}

void flask_callback(char* topic, byte* payload, unsigned int length) {
  Serial.print("📩 Flask message received: ");
  Serial.println(topic);
  
  // Convert payload to string
  String message = "";
  for (int i = 0; i < length; i++) {
    message += (char)payload[i];
  }
  Serial.println("Message: " + message);
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

void sendAllSensorDataMQTT() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("⚠️ WiFi not connected, skipping data send");
    return;
  }
  
  // Create JSON payload using ArduinoJson library
  StaticJsonDocument<1024> doc;
  
  // Add timestamp
  doc["timestamp"] = millis();
  
  // GPS Data
  if (gps.location.isValid()) {
    doc["latitude"] = gps.location.lat();
    doc["longitude"] = gps.location.lng();
  }
  if (gps.speed.isValid()) {
    doc["speed"] = gps.speed.kmph();
  }
  if (gps.satellites.isValid()) {
    doc["satellites"] = gps.satellites.value();
  }
  
  // Motion Sensor Data
  if (sensorDetected) {
    doc["accelX"] = accelX;
    doc["accelY"] = accelY;
    doc["accelZ"] = accelZ;
    doc["gyroX"] = gyroX;
    doc["gyroY"] = gyroY;
    doc["gyroZ"] = gyroZ;
  }
  
  // Ultrasonic Data
  for (int i = 0; i < 8; i++) {
    String sensorKey = "sensor" + String(i + 1);
    doc[sensorKey] = distances[i];
  }
  
  // Convert to string
  String payload;
  serializeJson(doc, payload);
  
  // Send to ThingsBoard
  if (thingsboard_connected) {
    bool tb_success = thingsboard_client.publish("v1/devices/me/telemetry", payload.c_str());
    Serial.print("📡 ThingsBoard MQTT: ");
    Serial.println(tb_success ? "✅ Success" : "❌ Failed");
  }
  
  // Send to Flask via MQTT
  if (flask_connected) {
    bool flask_success = flask_client.publish(flask_topic, payload.c_str());
    Serial.print("📡 Flask MQTT: ");
    Serial.println(flask_success ? "✅ Success" : "❌ Failed");
  }
  
  // Print connection status
  Serial.print("🔗 Connections - TB: ");
  Serial.print(thingsboard_connected ? "✅" : "❌");
  Serial.print(" | Flask: ");
  Serial.println(flask_connected ? "✅" : "❌");
  
  Serial.println("=================================");
}