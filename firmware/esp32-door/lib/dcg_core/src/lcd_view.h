// What the 20x4 LCD shows (pure logic, no Arduino): a small state machine that turns the
// controller state, sensor readings and transient outcomes into four 20-char lines.
//
//   BOOT → WAIT_CARD ⇄ PRESENCE → RFID_READ → VERIFYING ⇄ FACE → GRANTED → DOOR_OPEN
//        → DOOR_CLOSING → DOOR_CLOSED → WAIT_CARD
//   any → DENIED / ACCESS_ERROR (transient, then back to the resting screen)
//   any → CONN_ERROR (WiFi up, backend unreachable) · DISCONNECTED (no WiFi) · SENSOR_ERROR
//
// The view never talks to hardware: the ESP32 driver (src/lcd_esp32.*) renders lines() from
// its own low-priority task, so a slow I2C bus can never delay RFID, HC-SR04 or HTTP.
// HD44780 ROM A00 has no accents: every text here is plain ASCII on purpose.
#pragma once

#include <cstdint>
#include <string>

#include "access_controller.h"
#include "door.h"

namespace dcg {

enum class LcdScreen {
  BOOT,
  CONFIG_ERROR,
  DISCONNECTED,   // 12. Sistema desconectado (no WiFi)
  CONN_ERROR,     // 11. Error de conexion (backend / NTP unreachable)
  SENSOR_ERROR,
  WAIT_CARD,      // 1.  Esperando tarjeta RFID (+ 3. distance)
  PRESENCE,       // 2.  Presencia detectada (+ 3. distance)
  RFID_READ,      // 4.  RFID detectado
  VERIFYING,      // 5.  Verificando autorizacion
  FACE,           // 6.  Reconocimiento facial
  GRANTED,        // 7.  Acceso autorizado
  DENIED,         // 8.  Acceso denegado
  ACCESS_ERROR,   //     attempt aborted by a network/protocol error
  DOOR_OPEN,      // 9.  Puerta abierta
  DOOR_CLOSING,
  DOOR_CLOSED,    // 10. Puerta cerrada
  ALARM,          // intrusion detected inside the room (buzzer + red LED)
  ENTRANCE_GRANTED,  // main entrance: QR accepted (entrance green LED on)
  ENTRANCE_DENIED,   // main entrance: QR rejected
  ENV_ALARM,         // DHT11: critical temperature / humidity out of range
};
const char* lcdScreenName(LcdScreen s);

struct LcdInput {
  SystemState state = SystemState::BOOT;
  bool wifiUp = false;
  DoorState door = DoorState::CLOSED;
  SensorSnapshot sensor;
  bool rfidOk = true;
  float thresholdCm = 50;
  bool alarm = false;  // intrusion alarm running
  EnvStatus env;       // DHT11 reading + fan / environmental alarm
};

struct LcdTiming {
  uint32_t grantedMs = 3000;   // "Acceso autorizado / Bienvenido + nombre" before "Puerta abierta"
  uint32_t deniedMs = 3000;
  uint32_t errorMs = 3000;
  uint32_t closedMs = 2000;    // "Puerta cerrada" after a door cycle
  uint32_t entranceMs = 3000;  // main entrance QR outcome
};

class LcdView {
 public:
  static constexpr int kCols = 20;
  static constexpr int kRows = 4;

  explicit LcdView(LcdTiming t = {}) : t_(t) { clearLines(); }

  // Events from the controller (all optional; the view also works from LcdInput alone).
  void onCard(const std::string& uid) { uid_ = uid; phase_.clear(); greeting_.clear(); name_.clear(); }
  // Greeting and name of the granted person (already sanitized ASCII by the protocol layer).
  void onGranted(const std::string& greeting, const std::string& name) { greeting_ = greeting; name_ = name; }
  void onSessionPhase(const std::string& backendState) { phase_ = backendState; }
  void onFeedback(Feedback f, const std::string& reason, uint32_t nowMs);
  void setConfigError() { configError_ = true; }
  // Main entrance QR outcome. `name` is untrusted: sanitized again here (≤ 40 ASCII chars).
  void onEntrance(bool granted, const std::string& name, uint32_t nowMs);
  void cancelEntrance() { entranceActive_ = false; entranceName_.clear(); }

  // Recomputes the screen and the four lines. Cheap; call every ~100 ms.
  void update(const LcdInput& in, uint32_t nowMs);

  LcdScreen screen() const { return screen_; }
  // Always exactly kCols characters, space padded.
  const char* line(int row) const { return lines_[row]; }

  // Short ASCII explanation (≤ 20 chars) of a backend/firmware reason code.
  static const char* reasonShort(const std::string& code);

 private:
  LcdScreen pick(const LcdInput& in, uint32_t now);
  void render(const LcdInput& in, uint32_t now);
  void clearLines();
  void set(int row, const std::string& text);
  static std::string distanceText(const SensorSnapshot& s);
  static std::string envText(const EnvStatus& e);  // "TEMP 24.5C HUM 45%"
  void setName(int row, const std::string& name, const char* fallback);

  LcdTiming t_;
  LcdScreen screen_ = LcdScreen::BOOT;
  char lines_[kRows][kCols + 1];

  bool configError_ = false;
  std::string uid_;
  std::string phase_;
  std::string greeting_;
  std::string name_;
  // Transient outcome (GRANTED / DENIED / ACCESS_ERROR) shown until flashUntil_.
  LcdScreen flash_ = LcdScreen::BOOT;
  std::string flashReason_;
  uint32_t flashUntil_ = 0;
  bool flashActive_ = false;
  // Main entrance QR outcome, shown until entranceUntil_.
  bool entranceActive_ = false;
  bool entranceGranted_ = false;
  std::string entranceName_;
  uint32_t entranceUntil_ = 0;
  // Door cycle tracking for "Puerta cerrada".
  DoorState lastDoor_ = DoorState::CLOSED;
  uint32_t closedUntil_ = 0;
  bool closedActive_ = false;
};

}  // namespace dcg
