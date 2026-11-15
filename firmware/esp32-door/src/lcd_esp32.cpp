#include "lcd_esp32.h"

#include <WiFi.h>
#include <Wire.h>

#include <cstring>

#include "hal_esp32.h"

namespace dcg {

namespace {

// PCF8574 → HD44780 wiring used by the common blue/green 2004 backpacks:
//   P0 RS · P1 RW · P2 EN · P3 backlight · P4..P7 D4..D7
constexpr uint8_t kRs = 0x01;
constexpr uint8_t kEn = 0x04;
constexpr uint8_t kBacklight = 0x08;
constexpr uint8_t kRowOffset[4] = {0x00, 0x40, 0x14, 0x54};  // 20x4 DDRAM layout

constexpr uint32_t kI2cHz = 100000;        // PCF8574 is specified for 100 kHz
constexpr uint16_t kI2cTimeoutMs = 10;     // a stuck bus never stalls the task for long
constexpr uint32_t kRenderPeriodMs = 100;
constexpr uint32_t kReprobeMs = 5000;

class Lock {
 public:
  explicit Lock(SemaphoreHandle_t m) : m_(m) { if (m_) xSemaphoreTake(m_, portMAX_DELAY); }
  ~Lock() { if (m_) xSemaphoreGive(m_); }
 private:
  SemaphoreHandle_t m_;
};

bool answers(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

}  // namespace

// ------------------------------------------------------------------ low level
bool Lcd2004::expander(const uint8_t* bytes, size_t n) {
  Wire.beginTransmission(addr_);
  Wire.write(bytes, n);
  return Wire.endTransmission() == 0;
}

// One I2C transaction per byte sent to the HD44780: [hi|EN, hi, lo|EN, lo].
// Each I2C byte takes ≈ 90 µs, longer than the 37 µs the controller needs per command.
bool Lcd2004::send(uint8_t value, bool data) {
  const uint8_t mode = (data ? kRs : 0) | kBacklight;
  const uint8_t hi = (value & 0xF0) | mode;
  const uint8_t lo = uint8_t(value << 4) | mode;
  const uint8_t seq[4] = {uint8_t(hi | kEn), hi, uint8_t(lo | kEn), lo};
  return expander(seq, sizeof seq);
}

bool Lcd2004::setCursor(int col, int row) { return command(0x80 | (kRowOffset[row] + col)); }

bool Lcd2004::initController() {
  // HD44780 datasheet, "initialization by instruction" for the 4-bit interface.
  vTaskDelay(pdMS_TO_TICKS(50));
  const uint8_t off = kBacklight;
  if (!expander(&off, 1)) return false;
  for (int i = 0; i < 3; ++i) {
    const uint8_t seq[2] = {uint8_t(0x30 | kEn | kBacklight), uint8_t(0x30 | kBacklight)};
    if (!expander(seq, 2)) return false;
    vTaskDelay(pdMS_TO_TICKS(5));
  }
  const uint8_t four[2] = {uint8_t(0x20 | kEn | kBacklight), uint8_t(0x20 | kBacklight)};
  if (!expander(four, 2)) return false;
  bool ok = command(0x28)     // 4-bit, 2 "lines" (a 20x4 is wired as 2x40), 5x8 font
            && command(0x0C)  // display on, cursor off, blink off
            && command(0x06)  // entry mode: increment, no shift
            && command(0x01); // clear
  vTaskDelay(pdMS_TO_TICKS(3));  // clear takes 1.52 ms
  std::memset(shadow_, 0, sizeof shadow_);
  return ok;
}

bool Lcd2004::probe() {
  if (wantAddr_) {
    addr_ = answers(wantAddr_) ? wantAddr_ : 0;
  } else {
    addr_ = answers(0x27) ? 0x27 : answers(0x3F) ? 0x3F : 0;
  }
  return addr_ != 0;
}

bool Lcd2004::begin() {
  if (!mtx_) mtx_ = xSemaphoreCreateMutex();
  Wire.begin(sda_, scl_, kI2cHz);
  Wire.setTimeOut(kI2cTimeoutMs);
  bool ok = probe() && initController();
  present_.store(ok);
  if (ok) Serial.printf("[lcd] LCD 2004 en 0x%02X (SDA %d, SCL %d)\n", addr_, sda_, scl_);
  else Serial.printf("[lcd] no se detecta LCD en SDA %d / SCL %d (se sigue sin pantalla)\n", sda_, scl_);
  return ok;
}

bool Lcd2004::flush(const char lines[4][21]) {
  for (int r = 0; r < 4; ++r) {
    int c = 0;
    while (c < 20) {
      if (shadow_[r][c] == lines[r][c]) { ++c; continue; }
      int end = c;
      while (end < 20 && shadow_[r][end] != lines[r][end]) ++end;  // run of changed chars
      if (!setCursor(c, r)) return false;
      for (int i = c; i < end; ++i) {
        if (!send(uint8_t(lines[r][i]), true)) return false;
        shadow_[r][i] = lines[r][i];
      }
      c = end;
    }
  }
  return true;
}

bool Lcd2004::writeLines(const char* const lines[4]) {
  if (!present_.load()) return false;
  char buf[4][21];
  for (int r = 0; r < 4; ++r) {
    std::memset(buf[r], ' ', 20);
    buf[r][20] = '\0';
    size_t n = strnlen(lines[r], 20);
    std::memcpy(buf[r], lines[r], n);
  }
  return flush(buf);
}

int Lcd2004::scan(int sda, int scl, uint8_t* found, int max) {
  Wire.begin(sda, scl, kI2cHz);
  Wire.setTimeOut(kI2cTimeoutMs);
  int n = 0;
  for (uint8_t a = 0x08; a < 0x78 && n < max; ++a)
    if (answers(a)) found[n++] = a;
  return n;
}

// ------------------------------------------------------------------ hooks
void Lcd2004::onCard(const std::string& uid) {
  Lock l(mtx_);
  view_.onCard(uid);
}

void Lcd2004::onSessionPhase(const std::string& state) {
  Lock l(mtx_);
  view_.onSessionPhase(state);
}

void Lcd2004::onFeedback(Feedback f, const std::string& reason) {
  Lock l(mtx_);
  view_.onFeedback(f, reason, ::millis());
}

void Lcd2004::setConfigError() {
  Lock l(mtx_);
  view_.setConfigError();
}

const char* Lcd2004::screenName() {
  Lock l(mtx_);
  return lcdScreenName(view_.screen());
}

// ------------------------------------------------------------------ render task
void Lcd2004::startTask(Esp32Hal* hal) {
  hal_ = hal;
  if (!mtx_) mtx_ = xSemaphoreCreateMutex();
  xTaskCreatePinnedToCore(taskEntry, "lcd", 4096, this, 1, nullptr, 0);
}

void Lcd2004::taskEntry(void* self) { static_cast<Lcd2004*>(self)->taskLoop(); }

void Lcd2004::taskLoop() {
  TickType_t wake = xTaskGetTickCount();
  uint32_t lastProbe = ::millis();
  char lines[4][21];

  for (;;) {
    const uint32_t now = ::millis();
    if (!present_.load()) {  // hot-plug / loose wire: try again from time to time
      if (now - lastProbe >= kReprobeMs) {
        lastProbe = now;
        if (probe() && initController()) {
          present_.store(true);
          Serial.printf("[lcd] LCD recuperado en 0x%02X\n", addr_);
        }
      }
    } else {
      LcdInput in;
      in.state = state_.load();
      in.wifiUp = WiFi.status() == WL_CONNECTED;
      in.thresholdCm = thresholdCm_.load();
      if (hal_) {
        in.door = hal_->doorState();
        in.sensor = hal_->sensor();
        in.rfidOk = hal_->rfidOk();
      }
      {
        Lock l(mtx_);
        view_.update(in, now);
        for (int r = 0; r < 4; ++r) std::memcpy(lines[r], view_.line(r), 21);
      }
      if (!flush(lines)) {
        present_.store(false);
        lastProbe = now;
        Serial.println("[lcd] LCD sin respuesta (I2C); reintentando cada 5 s");
      }
    }
    vTaskDelayUntil(&wake, pdMS_TO_TICKS(kRenderPeriodMs));
  }
}

}  // namespace dcg
