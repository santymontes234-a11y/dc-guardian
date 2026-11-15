// Door (servo) state machine: CLOSED → OPENING → OPEN → CLOSING → CLOSED.
//
// * The only way to open is DoorController::open(const OpenGrant&). An OpenGrant can only be
//   built by the AccessController after a verified GRANTED decision (private constructor).
// * Closing is always automatic (hold timer) and also forced by emergencyClose().
// * The servo is swept linearly over travelMs (gentler current draw than an instant jump).
#pragma once

#include <cstdint>
#include <string>

namespace dcg {

enum class DoorState { CLOSED, OPENING, OPEN, CLOSING };
const char* doorStateName(DoorState s);

enum class CloseReason { NONE, TIMER, EMERGENCY, LOCAL_BUTTON };
const char* closeReasonName(CloseReason r);

constexpr uint32_t kMinOpenMs = 1000;
constexpr uint32_t kMaxOpenMs = 30000;

class AccessController;
struct TestGrantFactory;

// Proof that the backend authorized one opening for one session.
class OpenGrant {
 public:
  const std::string& sessionId() const { return sessionId_; }
  uint32_t holdMs() const { return holdMs_; }

 private:
  OpenGrant(std::string sid, uint32_t holdMs) : sessionId_(std::move(sid)), holdMs_(holdMs) {}
  std::string sessionId_;
  uint32_t holdMs_;
  friend class AccessController;
  friend struct TestGrantFactory;  // unit tests only
};

struct DoorConfig {
  int closedAngle = 0;
  int openAngle = 90;
  uint32_t travelMs = 600;
};

struct DoorEvent {
  enum class Type { NONE, OPENED, CLOSED } type = Type::NONE;
  CloseReason reason = CloseReason::NONE;
  std::string sessionId;
  uint32_t holdMs = 0;
};

class DoorController {
 public:
  explicit DoorController(DoorConfig cfg = {}) : cfg_(cfg), angle_(float(cfg.closedAngle)) {}

  // Accepted only from CLOSED and with holdMs in [kMinOpenMs, kMaxOpenMs].
  bool open(const OpenGrant& grant, uint32_t nowMs);
  // From OPENING/OPEN: start closing now. Idempotent.
  void emergencyClose(uint32_t nowMs, CloseReason reason = CloseReason::EMERGENCY);
  // Advances the state machine; call every few ms.
  void tick(uint32_t nowMs);

  // Returns and clears the pending event (at most one per transition).
  DoorEvent takeEvent();

  DoorState state() const { return state_; }
  int angle() const { return int(angle_ + 0.5f); }
  const std::string& sessionId() const { return sessionId_; }

 private:
  void startClosing(uint32_t nowMs, CloseReason r);
  void push(DoorEvent::Type t, CloseReason r);

  DoorConfig cfg_;
  DoorState state_ = DoorState::CLOSED;
  float angle_;
  float fromAngle_ = 0;
  uint32_t phaseStartMs_ = 0;
  uint32_t holdMs_ = 0;
  CloseReason closeReason_ = CloseReason::NONE;
  std::string sessionId_;
  DoorEvent pending_[2];
  int pendingCount_ = 0;
};

}  // namespace dcg
