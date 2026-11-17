// Main state machine of the door device (design doc §5.3):
//
//   IDLE → PRESENCE → CARD_READ → WAITING_DECISION → DOOR_OPEN → DOOR_CLOSING → IDLE
//   OFFLINE (no WiFi/NTP/backend) and ERROR (sensor fault) ⇒ cards ignored, door kept closed.
//
// Security invariants (each one has a unit test in test/test_controller):
//  * The door only opens on a GRANTED decision that (a) arrived on a signed response,
//    (b) names the session this device started, (c) carries a valid open_ms, and
//    (d) arrives while the door is CLOSED.
//  * The HC-SR04 is INSIDE the room and is an intrusion detector, not an access factor:
//    someone detected inside ⇒ the backend decides whether nobody authorized is inside
//    (⇒ alarm). Offline, it cannot know ⇒ local alarm (fail-secure).
//  * The UID never authorizes anything locally; it is only forwarded to the backend.
//  * Any error, timeout or disconnection aborts the session ⇒ door stays closed.
//  * Remote commands are whitelisted (EMERGENCY_CLOSE only).
#pragma once

#include <cstdint>
#include <string>

#include "backend_client.h"
#include "door.h"
#include "protocol.h"

namespace dcg {

enum class SystemState { BOOT, OFFLINE, ERROR, IDLE, PRESENCE, CARD_READ, WAITING_DECISION, DOOR_OPEN, DOOR_CLOSING };
const char* systemStateName(SystemState s);

enum class Feedback { NONE, READY, PRESENCE, WAITING, GRANTED, DENIED, ERROR, OFFLINE };

struct SensorSnapshot {
  bool present = false;
  float distanceCm = -1;
  bool fault = false;
};

// One DHT11 read attempt (every 2 s). ok=false: checksum/timeout/NaN.
struct DhtSample {
  bool ok = false;
  float temperatureC = 0;
  float humidityPct = 0;
};

enum class DhtStatus { UNKNOWN, OK, ERROR };  // UNKNOWN: no read finished yet
const char* dhtStatusName(DhtStatus s);

// What the environment logic decided; the HAL drives the fan, the buzzer and the LCD from it.
struct EnvStatus {
  DhtStatus sensor = DhtStatus::UNKNOWN;
  float temperatureC = 0;   // last valid reading (meaningful when sensor == OK)
  float humidityPct = 0;
  bool fan = false;
  bool alarm = false;       // environmental alarm (buzzer pattern distinct from intrusion)
  bool fallback = true;     // true: decided locally (backend unreachable / bad signature)
  EnvThresholds thresholds;
};

// Hardware the controller drives. Implemented with FreeRTOS + drivers on the ESP32 and
// with fakes in the native tests.
class DeviceHal {
 public:
  virtual ~DeviceHal() = default;
  virtual uint32_t millis() = 0;
  virtual bool networkUp() = 0;               // WiFi associated
  virtual int rssi() = 0;
  virtual uint32_t freeHeap() = 0;
  virtual SensorSnapshot sensor() = 0;
  virtual void setPresenceThreshold(float cm) = 0;
  virtual bool readCard(std::string& uidHex) = 0;  // true once per new card presented
  virtual bool rfidOk() = 0;
  virtual bool openDoor(const OpenGrant& grant) = 0;
  virtual void closeDoor(CloseReason reason) = 0;
  virtual DoorState doorState() = 0;
  virtual DoorEvent takeDoorEvent() = 0;
  virtual void feedback(Feedback f, const std::string& reason) = 0;
  virtual void log(const std::string& line) = 0;
  // Display hooks (LCD). Optional: default no-op, must never block.
  virtual void onStateChange(SystemState) {}
  virtual void onCardDetected(const std::string& /*uidHex*/) {}
  virtual void onSessionPhase(const std::string& /*backendState*/) {}
  virtual void onGranted(const std::string& /*greeting*/, const std::string& /*name*/) {}
  // Intrusion alarm: red LED blinking + buzzer for `ms` (never touches the door).
  virtual void alarm(uint32_t /*ms*/) {}
  // DHT11: next finished read since the last call (false = none). Default: no sensor.
  virtual bool takeDhtSample(DhtSample& /*out*/) { return false; }
  // Environment decision changed or refreshed: fan output, env alarm pattern, LCD.
  virtual void onEnvironment(const EnvStatus& /*s*/) {}
  // Main entrance (QR) signal: GRANTED ⇒ entrance green LED for ledMs + LCD 3 s;
  // DENIED ⇒ red LED blinks 3 times + short beep + LCD. NEVER touches the servo.
  virtual void onEntranceSignal(bool /*granted*/, uint32_t /*ledMs*/, const std::string& /*name*/) {}
  // Emergency close (remote EMERGENCY_CLOSE, console `close`, or going OFFLINE): the main
  // entrance green LED goes off at once and the signal being shown is dropped (LCD included).
  virtual void cancelEntrance() {}
};

struct ControllerTiming {
  uint32_t heartbeatFastMs = 2000;       // while the door is not CLOSED
  uint32_t offlineAfterFailures = 3;     // consecutive heartbeat failures
  uint32_t offlineRetryMs = 5000;        // heartbeat retry period while OFFLINE
  uint32_t pollMaxErrors = 3;            // consecutive poll failures ⇒ abort session
  uint32_t sessionGraceMs = 2000;        // added to the backend timeout_s
  uint32_t cardDebounceMs = 3000;        // same UID ignored for this long
  uint32_t confirmRetryMs = 2000;
  uint8_t confirmMaxAttempts = 5;
  uint32_t localAlarmMs = 20000;       // offline intrusion alarm
  uint32_t alarmBootGraceMs = 20000;   // no local alarm right after boot (not yet online)
};

class AccessController {
 public:
  AccessController(DeviceHal& hal, Backend& backend, std::string fw, ControllerTiming t = {})
      : hal_(hal), backend_(backend), fw_(std::move(fw)), t_(t) {}

  void tick();

  // Serial "close" command: emergency close. Never opens anything.
  void localEmergencyClose();

  // Inside exit button: asks the backend, which opens only if someone is inside this door.
  // Ignored while offline (cannot be verified ⇒ stays closed) or during another attempt.
  void requestExitByButton();

  // DHT11 health reported in heartbeat.sensors.dht (set by the environment logic).
  void setDhtOk(bool ok) { dhtOk_ = ok; }

  SystemState state() const { return state_; }
  bool online() const { return online_; }
  const DeviceConfig& config() const { return cfg_; }
  const std::string& sessionId() const { return sessionId_; }

 private:
  void setState(SystemState s);
  void handleDoorEvents(uint32_t now);
  void handleHeartbeat(uint32_t now, bool force);
  void handlePresence(const SensorSnapshot& s);
  void handleCard(uint32_t now, const SensorSnapshot& s);
  void beginSession(uint32_t now, const StartReply& r, bool byButton);
  void handleWaiting(uint32_t now, const SensorSnapshot& s);
  void handleConfirmations(uint32_t now);
  void abortSession(const char* why, Feedback f);
  void restingState(const SensorSnapshot& s);
  void applyConfig(const DeviceConfig& c);
  void emergencyClose(CloseReason r);  // closes the room door AND cancels the entrance signal

  DeviceHal& hal_;
  Backend& backend_;
  std::string fw_;
  ControllerTiming t_;
  DeviceConfig cfg_;

  SystemState state_ = SystemState::BOOT;
  bool online_ = false;
  uint32_t hbFailures_ = 0;
  uint32_t nextHeartbeatMs_ = 0;
  uint32_t lastHeartbeatMs_ = 0;
  bool lastPresent_ = false;
  bool booted_ = false;
  uint32_t bootMs_ = 0;
  bool dhtOk_ = true;

  std::string sessionId_;
  uint32_t sessionDeadlineMs_ = 0;
  uint32_t nextPollMs_ = 0;
  uint32_t pollMs_ = 500;
  uint32_t pollErrors_ = 0;
  bool buttonExit_ = false;  // session started by the inside button: no outside presence needed

  std::string lastUid_;
  uint32_t lastUidMs_ = 0;

  struct PendingConfirm {
    bool active = false;
    bool opened = false;  // true: /opened, false: /closed
    std::string sessionId;
    uint32_t openMs = 0;
    CloseReason reason = CloseReason::NONE;
    uint8_t attempts = 0;
    uint32_t nextMs = 0;
  };
  PendingConfirm confirms_[2];
  void queueConfirm(bool opened, const std::string& sid, uint32_t openMs, CloseReason r, uint32_t now);
};

}  // namespace dcg
