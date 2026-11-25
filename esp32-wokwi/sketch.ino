// =====================================================
// Fleet Telematics - vehicle V01 (ESP32 in Wokwi)
// Reads simulated sensors, simulates driving, publishes JSON over MQTT
// =====================================================
#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <math.h>
#include <time.h>

// ---------- Settings ----------
const char* WIFI_SSID  = "Wokwi-GUEST";   // Wokwi's virtual WiFi
const char* WIFI_PASS  = "";
const char* MQTT_HOST  = "broker.hivemq.com";
const uint16_t MQTT_PORT = 1883;
const char* PREFIX     = "fleet_demo_CHANGE_ME";
const char* VEHICLE_ID = "V01";

// ---------- Pins ----------
const int PIN_IGN  = 4;    // slide switch = ignition
const int PIN_FUEL = 34;   // potentiometer = fuel level
const int PIN_LED  = 15;   // green LED = MQTT connected
const int PIN_SDA  = 21;   // MPU6050
const int PIN_SCL  = 22;   // MPU6050

// ---------- Globals ----------
Adafruit_MPU6050 mpu;
WiFiClient net;
PubSubClient mqtt(net);

char topicTelemetry[96];
char topicStatus[96];
char clientId[48];

double lat = 30.0444, lon = 31.2357;   // simulated starting point
const double HEADING_DEG = 45.0;       // fixed driving direction
float speedKmh = 0;

bool prevIgn = false;
unsigned long driveStart = 0;
unsigned long lastPublish = 0;
unsigned long lastSim = 0;

// ---------- MPU6050 (Adafruit library) ----------
bool mpuInit() {
  Wire.begin(PIN_SDA, PIN_SCL);
  if (!mpu.begin()) return false;            // default I2C address 0x68
  mpu.setAccelerometerRange(MPU6050_RANGE_2_G);
  return true;
}

// Returns acceleration in g and chip temperature in Celsius.
bool readMpu(float &ax, float &ay, float &az, float &tempC) {
  sensors_event_t a, g, t;
  if (!mpu.getEvent(&a, &g, &t)) return false;
  ax = a.acceleration.x / 9.81f;   // library gives m/s^2, we want g (forward/backward)
  ay = a.acceleration.y / 9.81f;   // left/right
  az = a.acceleration.z / 9.81f;   // up/down
  tempC = t.temperature;
  return true;
}

// ---------- Simple driving simulation ----------
// 60-second cycle: accelerate 0-15s, cruise 15-45s, slow down 45-60s
float targetSpeed(unsigned long sec) {
  unsigned long t = sec % 60;
  if (t < 15) return 4.0f * t;
  if (t < 45) return 60.0f;
  return 60.0f - 4.0f * (t - 45);
}

void updateSimulation(bool ign) {
  unsigned long now = millis();
  float dt = (now - lastSim) / 1000.0f;
  lastSim = now;

  if (ign && !prevIgn) driveStart = now;   // ignition just turned on
  prevIgn = ign;

  speedKmh = ign ? targetSpeed((now - driveStart) / 1000) : 0;

  double d = (speedKmh / 3.6) * dt;        // meters travelled in dt
  double h = HEADING_DEG * M_PI / 180.0;
  lat += (d * cos(h)) / 111320.0;
  lon += (d * sin(h)) / (111320.0 * cos(lat * M_PI / 180.0));
}

// ---------- Connectivity ----------
bool connectWifi(unsigned long timeoutMs) {
  if (WiFi.status() == WL_CONNECTED) return true;
  Serial.print("WiFi");
  WiFi.begin(WIFI_SSID, WIFI_PASS, 6);
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < timeoutMs) {
    delay(300);
    Serial.print(".");
  }
  bool ok = (WiFi.status() == WL_CONNECTED);
  Serial.println(ok ? " connected" : " FAILED");
  return ok;
}

void connectMqtt() {
  while (!mqtt.connected()) {
    if (!connectWifi(10000)) {
      delay(2000);
      continue;
    }
    Serial.print("MQTT connecting...");
    // Last Will: if this device vanishes, the broker publishes "offline"
    if (mqtt.connect(clientId, NULL, NULL, topicStatus, 1, true, "offline")) {
      Serial.println(" ok");
      mqtt.publish(topicStatus, "online", true);   // retained
      digitalWrite(PIN_LED, HIGH);
    } else {
      Serial.print(" failed, state=");
      Serial.println(mqtt.state());
      delay(3000);
    }
  }
}

// ---------- Arduino entry points ----------
void setup() {
  Serial.begin(115200);
  pinMode(PIN_IGN, INPUT);
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);

  Serial.println(mpuInit() ? "MPU6050 ok" : "MPU6050 NOT found");

  snprintf(topicTelemetry, sizeof(topicTelemetry), "%s/%s/telemetry", PREFIX, VEHICLE_ID);
  snprintf(topicStatus,    sizeof(topicStatus),    "%s/%s/status",    PREFIX, VEHICLE_ID);
  snprintf(clientId, sizeof(clientId), "%s-%s-%04X", PREFIX, VEHICLE_ID, (unsigned)random(0xFFFF));

  if (!connectWifi(15000)) {
    Serial.println("No WiFi, restarting...");
    delay(2000);
    ESP.restart();
  }

  configTime(0, 0, "pool.ntp.org");        // real time (UTC) for timestamps
  Serial.print("NTP sync");
  unsigned long t0 = millis();
  while (time(nullptr) < 1700000000 && millis() - t0 < 10000) {
    delay(200);
    Serial.print(".");
  }
  Serial.println(time(nullptr) >= 1700000000 ? " ok" : " FAILED (using uptime)");

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(512);
  mqtt.setKeepAlive(30);
  lastSim = millis();
}

void loop() {
  if (!mqtt.connected()) {
    digitalWrite(PIN_LED, LOW);
    connectMqtt();
  }
  mqtt.loop();

  bool ign = digitalRead(PIN_IGN) == HIGH;
  updateSimulation(ign);

  if (millis() - lastPublish >= 1000) {
    lastPublish = millis();

    float ax = 0, ay = 0, az = 0, chipTemp = 0;
    if (!readMpu(ax, ay, az, chipTemp)) {
      Serial.println("MPU read failed - telemetry skipped");
      return;                                  // never publish fake zeros
    }
    float engineTempSim = chipTemp + 25.0f;    // simulated engine temp = chip temp + offset

    float fuel = analogRead(PIN_FUEL) * 100.0f / 4095.0f;
    int rpm = ign ? (int)(800 + speedKmh * 30) : 0;

    time_t nowT = time(nullptr);
    unsigned long ts = (nowT >= 1700000000) ? (unsigned long)nowT : millis() / 1000;

    char payload[320];
    snprintf(payload, sizeof(payload),
      "{\"ts\":%lu,\"vid\":\"%s\",\"lat\":%.6f,\"lon\":%.6f,"
      "\"speed\":%.1f,\"ax\":%.3f,\"ay\":%.3f,\"temp\":%.1f,"
      "\"rpm\":%d,\"fuel\":%.1f,\"ign\":%d}",
      ts, VEHICLE_ID, lat, lon,
      speedKmh, ax, ay, engineTempSim, rpm, fuel, ign ? 1 : 0);

    if (!mqtt.publish(topicTelemetry, payload)) {
      Serial.println("Telemetry publish failed");
    }
    Serial.println(payload);
  }
}
