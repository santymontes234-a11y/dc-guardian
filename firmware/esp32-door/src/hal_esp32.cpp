#include "hal_esp32.h"

#include <DHT.h>
#include <ESP32Servo.h>
#include <SPI.h>
#include <WiFi.h>

#include "lcd_esp32.h"
#include "pins.h"
#include "protocol.h"

namespace dcg {

namespace {

Servo servo;
DHT dht(PIN_DHT, DHT11);

class Lock {
 public:
  explicit Lock(SemaphoreHandle_t m) : m_(m) { xSemaphoreTake(m_, portMAX_DELAY); }
  ~Lock() { xSemaphoreGive(m_); }
 private:
  SemaphoreHandle_t m_;
};

constexpr uint32_t kIoPeriodMs = 20;
constexpr uint32_t kPingEveryMs = 60;      // HC-SR04 datasheet: ≥ 60 ms between pings
constexpr uint32_t kEchoTimeoutUs = 25000; // ≈ 4.3 m round trip
constexpr uint32_t kFlashMs = 1500;
constexpr uint32_t kButtonDebounceMs = 50;
constexpr uint32_t kDhtPeriodMs = 2000;          // DHT11: at most one read per second
constexpr uint32_t kEntranceDeniedMs = 1200;     // red blink x3 (200 on / 200 off)
constexpr uint32_t kEntranceBeepMs = 120;        // short beep on QR denied

}  // namespace

Esp32Hal::Esp32Hal(Esp32HalConfig cfg)
    : cfg_(cfg), door_(cfg.door), rfid_(PIN_RFID_SS, PIN_RFID_RST) {}

// Logical door angle → physical servo angle (honours DCG_SERVO_INVERT).
int Esp32Hal::servoAngle(int logical) const {
  if (logical < 0) logical = 0;
  if (logical > 180) logical = 180;
  return cfg_.servoInvert ? 180 - logical : logical;
}

void Esp32Hal::begin() {
  // 1) Door: command the CLOSED position before anything else (fail-closed at boot).
  ESP32PWM::allocateTimer(0);
  servo.setPeriodHertz(50);
  servo.attach(PIN_SERVO, cfg_.servoMinUs, cfg_.servoMaxUs);
  servo.write(servoAngle(cfg_.door.closedAngle));

  // 2) Feedback + button
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_LED_GREEN, LOW);
  digitalWrite(PIN_LED_RED, HIGH);
  digitalWrite(PIN_BUZZER, LOW);
  pinMode(PIN_EMERGENCY_BTN, INPUT_PULLUP);
  pinMode(PIN_LED_ENTRANCE, OUTPUT);
  digitalWrite(PIN_LED_ENTRANCE, LOW);   // main entrance closed at boot
  pinMode(PIN_FAN, OUTPUT);
  digitalWrite(PIN_FAN, LOW);

  // 3) Sensors
  pinMode(PIN_US_TRIG, OUTPUT);
  digitalWrite(PIN_US_TRIG, LOW);
  pinMode(PIN_US_ECHO, INPUT);
  SPI.begin(PIN_RFID_SCK, PIN_RFID_MISO, PIN_RFID_MOSI, PIN_RFID_SS);
  rfid_.PCD_Init();
  checkRfidHealth();

  // 4) I/O task
  mtx_ = xSemaphoreCreateMutex();
  xTaskCreatePinnedToCore(ioTaskEntry, "io", 4096, this, 3, nullptr, 1);
  // DHT11: own low-priority task. A read blocks ~25 ms (20 ms start pulse + 4 ms of bits),
  // so it must not run in the io task (servo / HC-SR04) nor in the main loop.
  dht.begin();
  xTaskCreatePinnedToCore(dhtTaskEntry, "dht", 3072, this, 1, nullptr, 1);
}

// ------------------------------------------------------------------ DHT11 task
void Esp32Hal::dhtTaskEntry(void* self) { static_cast<Esp32Hal*>(self)->dhtLoop(); }

void Esp32Hal::dhtLoop() {
  vTaskDelay(pdMS_TO_TICKS(kDhtPeriodMs));  // the sensor needs ~1 s after power-up
  TickType_t wake = xTaskGetTickCount();
  for (;;) {
    DhtSample s;
    const bool ok = dht.read(true);  // force: our own 2 s period
    s.temperatureC = dht.readTemperature(false, false);
    s.humidityPct = dht.readHumidity(false);
    s.ok = ok && !isnan(s.temperatureC) && !isnan(s.humidityPct);
    {
      Lock l(mtx_);
      dhtSample_ = s;
      dhtNew_ = true;
    }
    vTaskDelayUntil(&wake, pdMS_TO_TICKS(kDhtPeriodMs));
  }
}

// ------------------------------------------------------------------ I/O task
void Esp32Hal::ioTaskEntry(void* self) { static_cast<Esp32Hal*>(self)->ioLoop(); }

float Esp32Hal::pingCm(bool& valid) {
  digitalWrite(PIN_US_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_US_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_US_TRIG, LOW);
  unsigned long us = pulseIn(PIN_US_ECHO, HIGH, kEchoTimeoutUs);
  valid = us > 0;
  return valid ? float(us) * 0.0343f / 2.0f : -1.0f;  // speed of sound ≈ 343 m/s at 20 °C
}

void Esp32Hal::ioLoop() {
  TickType_t wake = xTaskGetTickCount();
  uint32_t lastPing = 0;
  uint32_t btnLowSince = 0;
  bool btnLatched = false;
  int lastAngle = -1;

  for (;;) {
    const uint32_t now = ::millis();

    // Inside exit button: debounced here; the controller asks the backend whether someone is
    // inside before anything opens (the button never moves the servo by itself).
    if (digitalRead(PIN_EMERGENCY_BTN) == LOW) {
      if (!btnLowSince) btnLowSince = now ? now : 1;
      if (!btnLatched && now - btnLowSince >= kButtonDebounceMs) {
        btnLatched = true;
        buttonPressed_ = true;
      }
    } else {
      btnLowSince = 0;
      btnLatched = false;
    }

    // Ultrasonic sampling (outside the lock: pulseIn can take up to 25 ms).
    if (now - lastPing >= kPingEveryMs) {
      lastPing = now;
      bool valid;
      float cm = pingCm(valid);
#if DCG_BENCH_MODE
      if (benchDistance_ >= 0) { cm = benchDistance_; valid = true; }
#endif
      Lock l(mtx_);
      lastRaw_ = cm;
      presence_.update(valid, cm, now);
    }

    int angle;
    {
      Lock l(mtx_);
      door_.tick(now);
      angle = door_.angle();
    }
    if (angle != lastAngle) {
      servo.write(servoAngle(angle));
      lastAngle = angle;
    }
    driveFeedback(now);
    vTaskDelayUntil(&wake, pdMS_TO_TICKS(kIoPeriodMs));
  }
}

void Esp32Hal::alarm(uint32_t ms) {
  uint32_t until = ::millis() + ms;
  alarmUntil_ = until ? until : 1;
  Serial.printf("[alarm] ALARMA DE INTRUSION %lu s\n", (unsigned long)(ms / 1000));
}

bool Esp32Hal::alarmActive() const {
  uint32_t until = alarmUntil_;
  return until != 0 && int32_t(until - ::millis()) > 0;
}

bool Esp32Hal::entranceLedOn() const {
  uint32_t until = entranceLedUntil_;
  return until != 0 && int32_t(until - ::millis()) > 0;
}

void Esp32Hal::driveFeedback(uint32_t now) {
  // Main entrance and fan: independent outputs, never affected by the room patterns.
  digitalWrite(PIN_LED_ENTRANCE, entranceLedOn());
  digitalWrite(PIN_FAN, fanOn_);

  // Intrusion alarm wins over every other pattern: red LED + buzzer blinking together.
  if (alarmActive()) {
    const bool on = (now / 250) % 2;
    digitalWrite(PIN_LED_GREEN, LOW);
    digitalWrite(PIN_LED_RED, on);
    digitalWrite(PIN_BUZZER, on);
    return;
  }
  Feedback f = (flash_ != Feedback::NONE && int32_t(flashUntil_ - now) > 0) ? flash_ : mode_;
  bool g = false, r = false, buzz = false;
  const uint32_t ph = now % 2000;
  switch (f) {
    case Feedback::READY: g = ph < 100; break;                          // green heartbeat blink
    case Feedback::PRESENCE: g = true; break;
    case Feedback::WAITING: g = (now / 250) % 2; break;                 // green fast blink
    case Feedback::GRANTED: g = true; buzz = (flashUntil_ - now) > kFlashMs - 150; break;
    case Feedback::DENIED: r = true; buzz = ((flashUntil_ - now) / 150) % 2 && (flashUntil_ - now) > kFlashMs - 900; break;
    case Feedback::ERROR: r = true; break;
    case Feedback::OFFLINE: r = (now / 500) % 2; break;
    case Feedback::NONE: break;
  }
  // Environmental alarm: two short beeps every 2 s (intrusion is a steady 250 ms on/off).
  if (envAlarm_) buzz = buzz || ph < 100 || (ph >= 250 && ph < 350);
  // Main entrance QR denied: red LED blinks 3 times + one short beep.
  const uint32_t deniedAt = entranceDeniedAt_;
  if (deniedAt != 0) {
    const uint32_t el = now - deniedAt;
    if (el < kEntranceDeniedMs) {
      r = (el % 400) < 200;
      buzz = buzz || el < kEntranceBeepMs;
    } else {
      entranceDeniedAt_ = 0;
    }
  }
  digitalWrite(PIN_LED_GREEN, g);
  digitalWrite(PIN_LED_RED, r);
  digitalWrite(PIN_BUZZER, buzz);
}

// ------------------------------------------------------------------ DeviceHal
uint32_t Esp32Hal::millis() { return ::millis(); }
bool Esp32Hal::networkUp() { return WiFi.status() == WL_CONNECTED; }
int Esp32Hal::rssi() { return WiFi.RSSI(); }
uint32_t Esp32Hal::freeHeap() { return ESP.getFreeHeap(); }

SensorSnapshot Esp32Hal::sensor() {
  Lock l(mtx_);
  return SensorSnapshot{presence_.present(), presence_.distanceCm(), presence_.sensorFault()};
}

void Esp32Hal::setPresenceThreshold(float cm) {
  float applied;
  {
    Lock l(mtx_);
    presence_.setThreshold(cm);
    applied = presence_.threshold();
  }
  if (lcd_) lcd_->setThreshold(applied);
}

bool Esp32Hal::readCard(std::string& uidHex) {
#if DCG_BENCH_MODE
  if (!benchUid_.empty()) {
    uidHex = benchUid_;
    benchUid_.clear();
    return true;
  }
#endif
  if (!rfidOk_) return false;
  if (!rfid_.PICC_IsNewCardPresent() || !rfid_.PICC_ReadCardSerial()) return false;
  uidHex = uidToHex(rfid_.uid.uidByte, rfid_.uid.size);
  rfid_.PICC_HaltA();       // one read per presentation
  rfid_.PCD_StopCrypto1();
  return true;
}

void Esp32Hal::checkRfidHealth() {
  byte v = rfid_.PCD_ReadRegister(MFRC522::VersionReg);
  bool ok = v != 0x00 && v != 0xFF;
  if (!ok) {
    rfid_.PCD_Init();  // try to recover (loose wire, brown-out)
    v = rfid_.PCD_ReadRegister(MFRC522::VersionReg);
    ok = v != 0x00 && v != 0xFF;
  }
  if (ok != rfidOk_) Serial.printf("[hal] RC522 %s (version 0x%02X)\n", ok ? "OK" : "ERROR", v);
  rfidOk_ = ok;
}

bool Esp32Hal::rfidOk() {
#if DCG_BENCH_MODE
  return true;
#else
  return rfidOk_;
#endif
}

bool Esp32Hal::openDoor(const OpenGrant& grant) {
  Lock l(mtx_);
  return door_.open(grant, ::millis());
}

void Esp32Hal::closeDoor(CloseReason reason) {
  Lock l(mtx_);
  door_.emergencyClose(::millis(), reason);
}

DoorState Esp32Hal::doorState() {
  Lock l(mtx_);
  return door_.state();
}

DoorEvent Esp32Hal::takeDoorEvent() {
  Lock l(mtx_);
  return door_.takeEvent();
}

void Esp32Hal::feedback(Feedback f, const std::string& reason) {
  if (f == Feedback::GRANTED || f == Feedback::DENIED || f == Feedback::ERROR) {
    flash_ = f;
    flashUntil_ = ::millis() + kFlashMs;
    if (!reason.empty()) Serial.printf("[ui] %s\n", reason.c_str());
  }
  if (f != Feedback::GRANTED && f != Feedback::DENIED) mode_ = f;
  if (lcd_) lcd_->onFeedback(f, reason);
}

void Esp32Hal::onStateChange(SystemState s) {
  if (lcd_) lcd_->onState(s);
}

void Esp32Hal::onCardDetected(const std::string& uidHex) {
  if (lcd_) lcd_->onCard(uidHex);
}

void Esp32Hal::onSessionPhase(const std::string& backendState) {
  if (lcd_) lcd_->onSessionPhase(backendState);
}

void Esp32Hal::onGranted(const std::string& greeting, const std::string& name) {
  if (!name.empty()) Serial.printf("[ui] %s, %s\n", greeting.c_str(), name.c_str());
  if (lcd_) lcd_->onGranted(greeting, name);
}

bool Esp32Hal::takeDhtSample(DhtSample& out) {
  Lock l(mtx_);
  if (!dhtNew_) return false;
  out = dhtSample_;
  dhtNew_ = false;
  return true;
}

void Esp32Hal::onEnvironment(const EnvStatus& s) {
  {
    Lock l(mtx_);
    env_ = s;
  }
  fanOn_ = s.fan;
  envAlarm_ = s.alarm;  // the LCD task reads envStatus() itself
}

EnvStatus Esp32Hal::envStatus() {
  Lock l(mtx_);
  return env_;
}

void Esp32Hal::onEntranceSignal(bool granted, uint32_t ledMs, const std::string& name) {
  // Only LEDs, buzzer and LCD: the room servo is never touched from here.
  const uint32_t now = ::millis();
  if (granted) {
    const uint32_t until = now + ledMs;
    entranceLedUntil_ = until ? until : 1;
    Serial.printf("[entrada] QR OK %s (LED %lu ms)\n", name.c_str(), (unsigned long)ledMs);
  } else {
    entranceLedUntil_ = 0;
    entranceDeniedAt_ = now ? now : 1;
    Serial.println("[entrada] QR DENEGADO");
  }
  if (lcd_) lcd_->onEntrance(granted, name);
}

void Esp32Hal::cancelEntrance() {
  const bool wasOn = entranceLedOn() || entranceDeniedAt_ != 0;
  entranceLedUntil_ = 0;
  entranceDeniedAt_ = 0;
  digitalWrite(PIN_LED_ENTRANCE, LOW);  // now, not on the next io tick
  if (wasOn) Serial.println("[entrada] señal cancelada por cierre de emergencia");
  if (lcd_) lcd_->cancelEntrance();
}

void Esp32Hal::log(const std::string& line) {
  Serial.printf("[%10lu] %s\n", (unsigned long)::millis(), line.c_str());
}

bool Esp32Hal::takeButtonPress() {
  bool p = buttonPressed_;
  buttonPressed_ = false;
  return p;
}

int Esp32Hal::doorAngle() {
  Lock l(mtx_);
  return door_.angle();
}

float Esp32Hal::rawDistance() {
  Lock l(mtx_);
  return lastRaw_;
}

#if DCG_BENCH_MODE
void Esp32Hal::benchInjectCard(const std::string& uid) { benchUid_ = uid; }
void Esp32Hal::benchSetDistance(float cm) { benchDistance_ = cm; }
#endif

}  // namespace dcg
