#include "hal_esp32.h"

#include <ESP32Servo.h>
#include <SPI.h>
#include <WiFi.h>

#include "lcd_esp32.h"
#include "pins.h"
#include "protocol.h"

namespace dcg {

namespace {

Servo servo;

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

}  // namespace

Esp32Hal::Esp32Hal(Esp32HalConfig cfg)
    : cfg_(cfg), door_(cfg.door), rfid_(PIN_RFID_SS, PIN_RFID_RST) {}

void Esp32Hal::begin() {
  // 1) Door: command the CLOSED position before anything else (fail-closed at boot).
  ESP32PWM::allocateTimer(0);
  servo.setPeriodHertz(50);
  servo.attach(PIN_SERVO, cfg_.servoMinUs, cfg_.servoMaxUs);
  servo.write(cfg_.door.closedAngle);

  // 2) Feedback + button
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_LED_GREEN, LOW);
  digitalWrite(PIN_LED_RED, HIGH);
  digitalWrite(PIN_BUZZER, LOW);
  pinMode(PIN_EMERGENCY_BTN, INPUT_PULLUP);

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

    // Emergency button: debounced, acts on the door directly (no network involved).
    if (digitalRead(PIN_EMERGENCY_BTN) == LOW) {
      if (!btnLowSince) btnLowSince = now ? now : 1;
      if (!btnLatched && now - btnLowSince >= kButtonDebounceMs) {
        btnLatched = true;
        buttonPressed_ = true;
        Lock l(mtx_);
        door_.emergencyClose(now, CloseReason::LOCAL_BUTTON);
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
      servo.write(angle);
      lastAngle = angle;
    }
    driveFeedback(now);
    vTaskDelayUntil(&wake, pdMS_TO_TICKS(kIoPeriodMs));
  }
}

void Esp32Hal::driveFeedback(uint32_t now) {
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
