// LCD 2004 (HD44780) behind a PCF8574 I2C backpack.
//
// Own minimal driver on top of Wire (no LiquidCrystal_I2C): those libraries call Wire.begin()
// with the default pins (SDA 21 / SCL 22) and GPIO 22 is already the RC522 RST here.
//
// Non-blocking by design:
//  * A dedicated FreeRTOS task ("lcd", core 0, priority 1) renders every 100 ms. The main loop
//    (RFID + HTTP) and the "io" task (servo + HC-SR04) never touch the I2C bus.
//  * Hooks called from other tasks only copy a few bytes under a mutex.
//  * Only the characters that changed are sent (≈0.5 ms per character at 100 kHz).
//  * A missing or unplugged display never affects access control: the task keeps probing it
//    every few seconds and the door logic does not depend on it.
#pragma once

#include <Arduino.h>

#include <atomic>
#include <string>

#include "lcd_view.h"

namespace dcg {

class Esp32Hal;

class Lcd2004 {
 public:
  // addr = 0 ⇒ autodetect 0x27 (PCF8574T) or 0x3F (PCF8574AT).
  Lcd2004(int sda, int scl, uint8_t addr = 0) : sda_(sda), scl_(scl), wantAddr_(addr) {}

  // Initializes Wire and the display. Returns false if no display answers (not fatal).
  bool begin();
  // Starts the render task. `hal` may be null (diagnostics build).
  void startTask(Esp32Hal* hal);

  // Thread-safe hooks (called from the main loop / HAL).
  void onState(SystemState s) { state_.store(s); }
  void onCard(const std::string& uid);
  void onSessionPhase(const std::string& state);
  void onFeedback(Feedback f, const std::string& reason);
  void setThreshold(float cm) { thresholdCm_.store(cm); }
  void setConfigError();

  bool present() const { return present_.load(); }
  uint8_t address() const { return addr_; }
  const char* screenName();

  // Direct output (diagnostics build only; do not mix with the task).
  bool writeLines(const char* const lines[4]);
  static int scan(int sda, int scl, uint8_t* found, int max);  // I2C bus scan

 private:
  static void taskEntry(void* self);
  void taskLoop();
  bool probe();
  bool initController();
  bool expander(const uint8_t* bytes, size_t n);
  bool send(uint8_t value, bool data);
  bool command(uint8_t c) { return send(c, false); }
  bool setCursor(int col, int row);
  bool flush(const char lines[4][21]);

  int sda_, scl_;
  uint8_t wantAddr_;
  uint8_t addr_ = 0;
  std::atomic<bool> present_{false};
  std::atomic<SystemState> state_{SystemState::BOOT};
  std::atomic<float> thresholdCm_{50.0f};

  Esp32Hal* hal_ = nullptr;
  SemaphoreHandle_t mtx_ = nullptr;
  LcdView view_;
  char shadow_[4][21];  // what the display currently shows (0 = unknown)
};

}  // namespace dcg
