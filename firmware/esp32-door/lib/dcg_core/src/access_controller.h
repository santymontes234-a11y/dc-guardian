// Main state machine of the door device (design doc §5.3):
//
//   IDLE → PRESENCE → CARD_READ → WAITING_DECISION → DOOR_OPEN → DOOR_CLOSING → IDLE
//   OFFLINE (no WiFi/NTP/backend) and ERROR (sensor fault) ⇒ cards ignored, door kept closed.
//
// Security invariants (each one has a unit test in test/test_controller):
//  * The door only opens on a GRANTED decision that (a) arrived on a signed response,
//    (b) names the session this device started, (c) carries a valid open_ms, and
//    (d) arrives while a person is still present and the door is CLOSED.
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
};

class AccessController {
 public:
  AccessController(DeviceHal& hal, Backend& backend, std::string fw, ControllerTiming t = {})
      : hal_(hal), backend_(backend), fw_(std::move(fw)), t_(t) {}

  void tick();

  // Local (physical button / serial) emergency close. Never opens anything.
  void localEmergencyClose();

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
  void handleWaiting(uint32_t now, const SensorSnapshot& s);
  void handleConfirmations(uint32_t now);
  void abortSession(const char* why, Feedback f);
  void restingState(const SensorSnapshot& s);
  void applyConfig(const DeviceConfig& c);

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

  std::string sessionId_;
  uint32_t sessionDeadlineMs_ = 0;
  uint32_t nextPollMs_ = 0;
  uint32_t pollMs_ = 500;
  uint32_t pollErrors_ = 0;

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
