// ESP32 implementation of DeviceHal.
//
// A dedicated FreeRTOS task ("io", core 1, high priority, every 20 ms) owns the time-critical
// hardware: servo (DoorController), HC-SR04 sampling (every 60 ms), emergency button and LEDs.
// So the door keeps closing on time even while the main loop is blocked in an HTTP call.
// The RC522 (SPI) is only used from the main loop.
#pragma once

#include <Arduino.h>
#include <MFRC522.h>

#include "access_controller.h"
#include "door.h"
#include "presence.h"

namespace dcg {

class Lcd2004;

struct Esp32HalConfig {
  DoorConfig door;
  int servoMinUs = 500;
  int servoMaxUs = 2400;
};

class Esp32Hal : public DeviceHal {
 public:
  explicit Esp32Hal(Esp32HalConfig cfg);
  void begin();  // servo to CLOSED first, then sensors, then the I/O task

  // DeviceHal
  uint32_t millis() override;
  bool networkUp() override;
  int rssi() override;
  uint32_t freeHeap() override;
  SensorSnapshot sensor() override;
  void setPresenceThreshold(float cm) override;
  bool readCard(std::string& uidHex) override;
  bool rfidOk() override;
  bool openDoor(const OpenGrant& grant) override;
  void closeDoor(CloseReason reason) override;
  DoorState doorState() override;
  DoorEvent takeDoorEvent() override;
  void feedback(Feedback f, const std::string& reason) override;
  void log(const std::string& line) override;
  void onStateChange(SystemState s) override;
  void onCardDetected(const std::string& uidHex) override;
  void onSessionPhase(const std::string& backendState) override;

  // Optional 20x4 display; every hook is forwarded to it (never blocks).
  void attachLcd(Lcd2004* lcd) { lcd_ = lcd; }

  // Main loop helpers
  bool takeButtonPress();          // emergency button pressed since last call
  void checkRfidHealth();          // re-initializes the RC522 if it stops answering
  int doorAngle();
  float rawDistance();

#if DCG_BENCH_MODE
  void benchInjectCard(const std::string& uid);
  void benchSetDistance(float cm);  // < 0 disables the override
#endif

 private:
  static void ioTaskEntry(void* self);
  void ioLoop();
  float pingCm(bool& valid);
  void driveFeedback(uint32_t now);

  Esp32HalConfig cfg_;
  Lcd2004* lcd_ = nullptr;
  SemaphoreHandle_t mtx_ = nullptr;
  DoorController door_;
  PresenceDetector presence_;
  MFRC522 rfid_;
  bool rfidOk_ = false;
  float lastRaw_ = -1;

  volatile bool buttonPressed_ = false;
  Feedback mode_ = Feedback::OFFLINE;   // persistent pattern
  Feedback flash_ = Feedback::NONE;     // transient pattern (GRANTED/DENIED/ERROR)
  uint32_t flashUntil_ = 0;

#if DCG_BENCH_MODE
  std::string benchUid_;
  float benchDistance_ = -1;
#endif
};

}  // namespace dcg
