#include <WiFi.h>
#include <TinyGPS++.h>
#include <Wire.h>
#include <EEPROM.h>

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

// Calibration Data Structures
struct MPU6050_Calibration {
  float accelOffsetX, accelOffsetY, accelOffsetZ;
  float gyroOffsetX, gyroOffsetY, gyroOffsetZ;
  float accelScaleX, accelScaleY, accelScaleZ;
  float gyroScale;
  bool isCalibrated;
};

struct UltrasonicCalibration {
  float offset[8];        // Offset untuk setiap sensor
  float scaleFactor[8];   // Scale factor untuk setiap sensor
  float maxDistance[8];   // Max distance yang valid
  bool isCalibrated;
};

// Global calibration variables
MPU6050_Calibration mpuCal;
UltrasonicCalibration ultraCal;

// EEPROM addresses
#define EEPROM_SIZE 512
#define MPU_CAL_ADDR 0
#define ULTRA_CAL_ADDR 100

// Calibration settings
#define CALIBRATION_SAMPLES 1000
#define ULTRASONIC_SAMPLES 50

void setup() {
  Serial.begin(115200);
  delay(2000);
  
  Serial.println("\n🔧 ===== ESP32 MULTI-SENSOR CALIBRATION =====");
  Serial.println("📍 GPS + 🔄 GY-521 + 📏 8x Ultrasonic Sensors");
  Serial.println("============================================");
  
  // Initialize EEPROM
  EEPROM.begin(EEPROM_SIZE);
  
  // Initialize I2C
  Wire.begin(SDA_PIN, SCL_PIN);
  
  // Initialize GPS
  GPSSerial.begin(GPS_BAUD, SERIAL_8N1, GPS_RX_PIN, GPS_TX_PIN);
  
  // Initialize Ultrasonic pins
  for (int i = 0; i < 8; i++) {
    pinMode(trigPins[i], OUTPUT);
    pinMode(echoPins[i], INPUT);
  }
  
  // Check if sensors are connected
  checkSensorConnections();
  
  // Show calibration menu
  showMainMenu();
}

void loop() {
  if (Serial.available()) {
    String input = Serial.readStringUntil('\n');
    input.trim();
    handleMenuInput(input);
  }
  delay(100);
}

void checkSensorConnections() {
  Serial.println("\n🔍 Checking sensor connections...");
  
  // Check MPU6050
  Wire.beginTransmission(MPU6050_ADDR);
  byte error = Wire.endTransmission();
  if (error == 0) {
    Serial.println("✅ GY-521 (MPU6050) detected!");
    // Wake up MPU6050
    Wire.beginTransmission(MPU6050_ADDR);
    Wire.write(PWR_MGMT_1);
    Wire.write(0);
    Wire.endTransmission(true);
  } else {
    Serial.println("❌ GY-521 (MPU6050) NOT detected!");
  }
  
  // Check GPS
  Serial.println("🛰️ GPS Module check (akan dicek saat kalibrasi)");
  
  // Quick check ultrasonic sensors
  Serial.println("📏 Ultrasonic sensors check...");
  for (int i = 0; i < 8; i++) {
    float distance = readUltrasonicDistance(i);
    Serial.print("  Sensor ");
    Serial.print(i + 1);
    Serial.print(": ");
    if (distance > 0) {
      Serial.println("✅ OK");
    } else {
      Serial.println("⚠️ Check connection");
    }
  }
}

void showMainMenu() {
  Serial.println("\n🎯 ===== CALIBRATION MENU =====");
  Serial.println("1. Calibrate GY-521 (MPU6050)");
  Serial.println("2. Calibrate Ultrasonic Sensors");
  Serial.println("3. Calibrate GPS (Info Check)");
  Serial.println("4. Calibrate ALL Sensors");
  Serial.println("5. Show Current Calibration Data");
  Serial.println("6. Save Calibration to EEPROM");
  Serial.println("7. Load Calibration from EEPROM");
  Serial.println("8. Reset All Calibration");
  Serial.println("9. Test Calibrated Values");
  Serial.println("0. Exit Calibration Mode");
  Serial.println("==============================");
  Serial.print("Pilih opsi (0-9): ");
}

void handleMenuInput(String input) {
  int choice = input.toInt();
  
  switch (choice) {
    case 1:
      calibrateMPU6050();
      break;
    case 2:
      calibrateUltrasonicSensors();
      break;
    case 3:
      checkGPSInfo();
      break;
    case 4:
      calibrateAllSensors();
      break;
    case 5:
      showCalibrationData();
      break;
    case 6:
      saveCalibrationToEEPROM();
      break;
    case 7:
      loadCalibrationFromEEPROM();
      break;
    case 8:
      resetAllCalibration();
      break;
    case 9:
      testCalibratedValues();
      break;
    case 0:
      Serial.println("🚪 Exiting calibration mode...");
      Serial.println("Reset ESP32 untuk kembali ke mode normal");
      while(1) delay(1000);
      break;
    default:
      Serial.println("❌ Invalid option!");
      break;
  }
  showMainMenu();
}

void calibrateMPU6050() {
  Serial.println("\n🔄 ===== GY-521 (MPU6050) CALIBRATION =====");
  Serial.println("📌 PENTING: Letakkan sensor di permukaan DATAR dan STABIL");
  Serial.println("⏳ Tunggu 5 detik untuk persiapan...");
  
  for (int i = 5; i > 0; i--) {
    Serial.print(i);
    Serial.print("... ");
    delay(1000);
  }
  Serial.println("\n🔄 Mulai kalibrasi...");
  
  // Reset calibration values
  mpuCal.accelOffsetX = 0;
  mpuCal.accelOffsetY = 0;
  mpuCal.accelOffsetZ = 0;
  mpuCal.gyroOffsetX = 0;
  mpuCal.gyroOffsetY = 0;
  mpuCal.gyroOffsetZ = 0;
  
  long accelSumX = 0, accelSumY = 0, accelSumZ = 0;
  long gyroSumX = 0, gyroSumY = 0, gyroSumZ = 0;
  
  Serial.print("📊 Mengambil ");
  Serial.print(CALIBRATION_SAMPLES);
  Serial.println(" sampel data...");
  
  for (int i = 0; i < CALIBRATION_SAMPLES; i++) {
    int16_t ax, ay, az, gx, gy, gz;
    readRawMPU6050(&ax, &ay, &az, &gx, &gy, &gz);
    
    accelSumX += ax;
    accelSumY += ay;
    accelSumZ += az;
    gyroSumX += gx;
    gyroSumY += gy;
    gyroSumZ += gz;
    
    if (i % 100 == 0) {
      Serial.print(".");
    }
    delay(10);
  }
  
  // Calculate offsets
  mpuCal.accelOffsetX = (float)accelSumX / CALIBRATION_SAMPLES;
  mpuCal.accelOffsetY = (float)accelSumY / CALIBRATION_SAMPLES;
  mpuCal.accelOffsetZ = (float)accelSumZ / CALIBRATION_SAMPLES - 16384; // -1g for Z-axis
  mpuCal.gyroOffsetX = (float)gyroSumX / CALIBRATION_SAMPLES;
  mpuCal.gyroOffsetY = (float)gyroSumY / CALIBRATION_SAMPLES;
  mpuCal.gyroOffsetZ = (float)gyroSumZ / CALIBRATION_SAMPLES;
  
  // Set scale factors (convert to real units)
  mpuCal.accelScaleX = 16384.0; // LSB/g for ±2g range
  mpuCal.accelScaleY = 16384.0;
  mpuCal.accelScaleZ = 16384.0;
  mpuCal.gyroScale = 131.0;     // LSB/(°/s) for ±250°/s range
  
  mpuCal.isCalibrated = true;
  
  // Tampilkan hasil dalam raw values (seperti biasa)
  Serial.println("\n✅ GY-521 Calibration Complete!");
  Serial.println("📊 Raw Calibration Results:");
  Serial.printf("   Accel Offsets: X=%.2f, Y=%.2f, Z=%.2f\n", 
                mpuCal.accelOffsetX, mpuCal.accelOffsetY, mpuCal.accelOffsetZ);
  Serial.printf("   Gyro Offsets: X=%.2f, Y=%.2f, Z=%.2f\n", 
                mpuCal.gyroOffsetX, mpuCal.gyroOffsetY, mpuCal.gyroOffsetZ);
  
  // TAMBAHAN: Konversi ke unit nyata untuk referensi
  Serial.println("\n🔧 Converted to Real Units:");
  Serial.printf("   Accel Offsets: X=%.3fg, Y=%.3fg, Z=%.3fg\n", 
                mpuCal.accelOffsetX / 16384.0, 
                mpuCal.accelOffsetY / 16384.0, 
                mpuCal.accelOffsetZ / 16384.0);
  Serial.printf("   Gyro Offsets: X=%.2f°/s, Y=%.2f°/s, Z=%.2f°/s\n", 
                mpuCal.gyroOffsetX / 131.0, 
                mpuCal.gyroOffsetY / 131.0, 
                mpuCal.gyroOffsetZ / 131.0);
  
  // Test real-time conversion
  Serial.println("\n🧪 Testing Real-time Conversion (5 samples):");
  for (int i = 0; i < 5; i++) {
    delay(500);
    int16_t ax, ay, az, gx, gy, gz;
    readRawMPU6050(&ax, &ay, &az, &gx, &gy, &gz);
    
    // Apply calibration and convert to real units
    float accelX_g = (ax - mpuCal.accelOffsetX) / mpuCal.accelScaleX;
    float accelY_g = (ay - mpuCal.accelOffsetY) / mpuCal.accelScaleY;
    float accelZ_g = (az - mpuCal.accelOffsetZ) / mpuCal.accelScaleZ;
    
    float gyroX_dps = (gx - mpuCal.gyroOffsetX) / mpuCal.gyroScale;
    float gyroY_dps = (gy - mpuCal.gyroOffsetY) / mpuCal.gyroScale;
    float gyroZ_dps = (gz - mpuCal.gyroOffsetZ) / mpuCal.gyroScale;
    
    Serial.printf("   Sample %d - Accel: X=%.3fg Y=%.3fg Z=%.3fg | Gyro: X=%.1f°/s Y=%.1f°/s Z=%.1f°/s\n", 
                  i+1, accelX_g, accelY_g, accelZ_g, gyroX_dps, gyroY_dps, gyroZ_dps);
  }
  
  // Evaluasi hasil kalibrasi
  Serial.println("\n📋 Calibration Quality Check:");
  if (abs(mpuCal.accelOffsetX / 16384.0) < 0.1 && abs(mpuCal.accelOffsetY / 16384.0) < 0.1) {
    Serial.println("   ✅ Horizontal acceleration offsets look good (< 0.1g)");
  } else {
    Serial.println("   ⚠️ High horizontal acceleration offsets - check sensor positioning");
  }
  
  if (abs(mpuCal.gyroOffsetX / 131.0) < 5 && abs(mpuCal.gyroOffsetY / 131.0) < 5 && abs(mpuCal.gyroOffsetZ / 131.0) < 5) {
    Serial.println("   ✅ Gyroscope offsets look good (< 5°/s)");
  } else {
    Serial.println("   ⚠️ High gyroscope offsets - sensor might need to settle more");
  }
}

void calibrateUltrasonicSensors() {
  Serial.println("\n📏 ===== ULTRASONIC SENSORS CALIBRATION =====");
  Serial.println("📌 PENTING: ");
  Serial.println("   1. Pastikan semua sensor menghadap objek yang sama");
  Serial.println("   2. Jarak objek sekitar 10-30 cm dari sensor");
  Serial.println("   3. Objek berupa dinding/permukaan datar");
  Serial.println("⏳ Siapkan posisi sensor, tunggu 5 detik...");
  
  for (int i = 5; i > 0; i--) {
    Serial.print(i);
    Serial.print("... ");
    delay(1000);
  }
  Serial.println("\n📏 Mulai kalibrasi ultrasonic...");
  
  // Get reference distance (manual input)
  Serial.print("📐 Masukkan jarak referensi dalam cm (10-100): ");
  while (!Serial.available()) delay(100);
  float referenceDistance = Serial.readStringUntil('\n').toFloat();
  Serial.println(referenceDistance);
  
  if (referenceDistance < 5 || referenceDistance > 200) {
    Serial.println("❌ Jarak referensi tidak valid!");
    return;
  }
  
  // Calibrate each sensor
  for (int sensor = 0; sensor < 8; sensor++) {
    Serial.print("🔧 Kalibrasi Sensor ");
    Serial.print(sensor + 1);
    Serial.print("...");
    
    float totalDistance = 0;
    int validSamples = 0;
    
    for (int i = 0; i < ULTRASONIC_SAMPLES; i++) {
      float distance = readUltrasonicDistance(sensor);
      if (distance > 0 && distance < 400) {
        totalDistance += distance;
        validSamples++;
      }
      delay(50);
    }
    
    if (validSamples > ULTRASONIC_SAMPLES / 2) {
      float avgDistance = totalDistance / validSamples;
      ultraCal.scaleFactor[sensor] = referenceDistance / avgDistance;
      ultraCal.offset[sensor] = 0; // Can be adjusted if needed
      ultraCal.maxDistance[sensor] = 400; // Maximum valid distance
      Serial.printf(" ✅ (avg: %.2f cm, scale: %.3f)\n", avgDistance, ultraCal.scaleFactor[sensor]);
    } else {
      Serial.println(" ❌ Gagal - data tidak valid");
      ultraCal.scaleFactor[sensor] = 1.0;
      ultraCal.offset[sensor] = 0;
      ultraCal.maxDistance[sensor] = 400;
    }
  }
  
  ultraCal.isCalibrated = true;
  Serial.println("✅ Ultrasonic Calibration Complete!");
}

void checkGPSInfo() {
  Serial.println("\n🛰️ ===== GPS MODULE CHECK =====");
  Serial.println("📡 Checking GPS module communication...");
  Serial.println("⏳ Tunggu 30 detik untuk data GPS...");
  
  unsigned long startTime = millis();
  unsigned long lastUpdate = 0;
  int satelliteCount = 0;
  bool locationFound = false;
  
  while (millis() - startTime < 30000) {
    while (GPSSerial.available() > 0) {
      if (gps.encode(GPSSerial.read())) {
        if (millis() - lastUpdate > 2000) {
          lastUpdate = millis();
          
          Serial.print("📊 GPS Status: ");
          if (gps.location.isValid()) {
            if (!locationFound) {
              Serial.println("🛰️ LOCATION ACQUIRED!");
              locationFound = true;
            }
            Serial.printf("   📍 Lat: %.6f, Lng: %.6f\n", 
                         gps.location.lat(), gps.location.lng());
          } else {
            Serial.println("🔍 Searching for satellites...");
          }
          
          if (gps.satellites.isValid()) {
            satelliteCount = gps.satellites.value();
            Serial.printf("   🛰️ Satellites: %d\n", satelliteCount);
          }
          
          if (gps.speed.isValid()) {
            Serial.printf("   🚗 Speed: %.2f km/h\n", gps.speed.kmph());
          }
          
          if (gps.hdop.isValid()) {
            Serial.printf("   📡 HDOP: %.2f\n", gps.hdop.hdop());
          }
        }
      }
    }
    delay(100);
  }
  
  Serial.println("\n📊 GPS Check Results:");
  Serial.printf("   Location Found: %s\n", locationFound ? "✅ YES" : "❌ NO");
  Serial.printf("   Max Satellites: %d\n", satelliteCount);
  Serial.printf("   Characters Processed: %lu\n", gps.charsProcessed());
  Serial.printf("   Failed Checksums: %lu\n", gps.failedChecksum());
  
  if (locationFound && satelliteCount >= 4) {
    Serial.println("✅ GPS Module Working Properly!");
  } else if (gps.charsProcessed() > 0) {
    Serial.println("⚠️ GPS Module Connected but Poor Signal");
  } else {
    Serial.println("❌ GPS Module Not Responding");
  }
}

void calibrateAllSensors() {
  Serial.println("\n🚀 ===== CALIBRATING ALL SENSORS =====");
  
  Serial.println("\n1️⃣ Starting GPS Check...");
  checkGPSInfo();
  
  Serial.println("\n2️⃣ Starting GY-521 Calibration...");
  calibrateMPU6050();
  
  Serial.println("\n3️⃣ Starting Ultrasonic Calibration...");
  calibrateUltrasonicSensors();
  
  Serial.println("\n🎉 ALL SENSORS CALIBRATED!");
  Serial.println("💾 Don't forget to save calibration data (option 6)");
}

void readRawMPU6050(int16_t* ax, int16_t* ay, int16_t* az, int16_t* gx, int16_t* gy, int16_t* gz) {
  // Read accelerometer
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(ACCEL_XOUT_H);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU6050_ADDR, 6, true);
  
  *ax = Wire.read() << 8 | Wire.read();
  *ay = Wire.read() << 8 | Wire.read();
  *az = Wire.read() << 8 | Wire.read();
  
  // Read gyroscope
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(GYRO_XOUT_H);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU6050_ADDR, 6, true);
  
  *gx = Wire.read() << 8 | Wire.read();
  *gy = Wire.read() << 8 | Wire.read();
  *gz = Wire.read() << 8 | Wire.read();
}

float readUltrasonicDistance(int sensorIndex) {
  if (sensorIndex < 0 || sensorIndex >= 8) return -1;
  
  digitalWrite(trigPins[sensorIndex], LOW);
  delayMicroseconds(2);
  digitalWrite(trigPins[sensorIndex], HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPins[sensorIndex], LOW);
  
  long duration = pulseIn(echoPins[sensorIndex], HIGH, 30000);
  if (duration == 0) return -1;
  
  return duration * 0.034 / 2;
}

void showCalibrationData() {
  Serial.println("\n📊 ===== CURRENT CALIBRATION DATA =====");
  
  // MPU6050 Data
  Serial.println("🔄 GY-521 (MPU6050):");
  Serial.printf("   Status: %s\n", mpuCal.isCalibrated ? "✅ Calibrated" : "❌ Not Calibrated");
  if (mpuCal.isCalibrated) {
    Serial.printf("   Accel Offsets: X=%.2f, Y=%.2f, Z=%.2f\n", 
                  mpuCal.accelOffsetX, mpuCal.accelOffsetY, mpuCal.accelOffsetZ);
    Serial.printf("   Gyro Offsets: X=%.2f, Y=%.2f, Z=%.2f\n", 
                  mpuCal.gyroOffsetX, mpuCal.gyroOffsetY, mpuCal.gyroOffsetZ);
    Serial.printf("   Scales: Accel=%.1f LSB/g, Gyro=%.1f LSB/(°/s)\n", 
                  mpuCal.accelScaleX, mpuCal.gyroScale);
  }
  
  // Ultrasonic Data
  Serial.println("\n📏 Ultrasonic Sensors:");
  Serial.printf("   Status: %s\n", ultraCal.isCalibrated ? "✅ Calibrated" : "❌ Not Calibrated");
  if (ultraCal.isCalibrated) {
    for (int i = 0; i < 8; i++) {
      Serial.printf("   Sensor %d: Scale=%.3f, Offset=%.2f\n", 
                    i+1, ultraCal.scaleFactor[i], ultraCal.offset[i]);
    }
  }
  
  Serial.println("=====================================");
}

void saveCalibrationToEEPROM() {
  Serial.println("\n💾 Saving calibration to EEPROM...");
  
  // Save MPU6050 calibration
  EEPROM.put(MPU_CAL_ADDR, mpuCal);
  
  // Save Ultrasonic calibration
  EEPROM.put(ULTRA_CAL_ADDR, ultraCal);
  
  EEPROM.commit();
  
  Serial.println("✅ Calibration data saved to EEPROM!");
}

void loadCalibrationFromEEPROM() {
  Serial.println("\n📂 Loading calibration from EEPROM...");
  
  // Load MPU6050 calibration
  EEPROM.get(MPU_CAL_ADDR, mpuCal);
  
  // Load Ultrasonic calibration
  EEPROM.get(ULTRA_CAL_ADDR, ultraCal);
  
  Serial.println("✅ Calibration data loaded from EEPROM!");
  showCalibrationData();
}

void resetAllCalibration() {
  Serial.println("\n🔄 Resetting all calibration data...");
  
  // Reset MPU6050
  mpuCal.accelOffsetX = 0;
  mpuCal.accelOffsetY = 0;
  mpuCal.accelOffsetZ = 0;
  mpuCal.gyroOffsetX = 0;
  mpuCal.gyroOffsetY = 0;
  mpuCal.gyroOffsetZ = 0;
  mpuCal.accelScaleX = 16384.0;
  mpuCal.accelScaleY = 16384.0;
  mpuCal.accelScaleZ = 16384.0;
  mpuCal.gyroScale = 131.0;
  mpuCal.isCalibrated = false;
  
  // Reset Ultrasonic
  for (int i = 0; i < 8; i++) {
    ultraCal.scaleFactor[i] = 1.0;
    ultraCal.offset[i] = 0;
    ultraCal.maxDistance[i] = 400;
  }
  ultraCal.isCalibrated = false;
  
  Serial.println("✅ All calibration data reset!");
}

void testCalibratedValues() {
  Serial.println("\n🧪 ===== TESTING CALIBRATED VALUES =====");
  Serial.println("📊 Press any key to stop test...");
  
  unsigned long lastPrint = 0;
  
  while (!Serial.available()) {
    if (millis() - lastPrint > 1000) {
      lastPrint = millis();
      
      // Test MPU6050
      if (mpuCal.isCalibrated) {
        int16_t ax, ay, az, gx, gy, gz;
        readRawMPU6050(&ax, &ay, &az, &gx, &gy, &gz);
        
        // Apply calibration
        float accelX_g = (ax - mpuCal.accelOffsetX) / mpuCal.accelScaleX;
        float accelY_g = (ay - mpuCal.accelOffsetY) / mpuCal.accelScaleY;
        float accelZ_g = (az - mpuCal.accelOffsetZ) / mpuCal.accelScaleZ;
        
        float gyroX_dps = (gx - mpuCal.gyroOffsetX) / mpuCal.gyroScale;
        float gyroY_dps = (gy - mpuCal.gyroOffsetY) / mpuCal.gyroScale;
        float gyroZ_dps = (gz - mpuCal.gyroOffsetZ) / mpuCal.gyroScale;
        
        Serial.println("🔄 GY-521 Calibrated Values:");
        Serial.printf("   Accel: X=%.3fg, Y=%.3fg, Z=%.3fg\n", accelX_g, accelY_g, accelZ_g);
        Serial.printf("   Gyro: X=%.2f°/s, Y=%.2f°/s, Z=%.2f°/s\n", gyroX_dps, gyroY_dps, gyroZ_dps);
      }
      
      // Test Ultrasonic
      if (ultraCal.isCalibrated) {
        Serial.println("📏 Ultrasonic Calibrated Values:");
        for (int i = 0; i < 8; i++) {
          float rawDistance = readUltrasonicDistance(i);
          float calibratedDistance = (rawDistance * ultraCal.scaleFactor[i]) + ultraCal.offset[i];
          Serial.printf("   S%d: %.1f cm (raw: %.1f)\n", i+1, calibratedDistance, rawDistance);
        }
      }
      
      Serial.println("---");
    }
    delay(100);
  }
  
  // Clear serial buffer
  while (Serial.available()) Serial.read();
  Serial.println("🛑 Test stopped.");
}