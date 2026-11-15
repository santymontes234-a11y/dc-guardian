#include "door.h"

namespace dcg {

const char* doorStateName(DoorState s) {
  switch (s) {
    case DoorState::CLOSED: return "CLOSED";
    case DoorState::OPENING: return "OPENING";
    case DoorState::OPEN: return "OPEN";
    case DoorState::CLOSING: return "CLOSING";
  }
  return "?";
}

const char* closeReasonName(CloseReason r) {
  switch (r) {
    case CloseReason::NONE: return "NONE";
    case CloseReason::TIMER: return "TIMER";
    case CloseReason::EMERGENCY: return "EMERGENCY";
    case CloseReason::LOCAL_BUTTON: return "LOCAL_BUTTON";
  }
  return "?";
}

bool DoorController::open(const OpenGrant& grant, uint32_t nowMs) {
  if (state_ != DoorState::CLOSED) return false;
  if (grant.holdMs() < kMinOpenMs || grant.holdMs() > kMaxOpenMs) return false;
  if (grant.sessionId().empty()) return false;
  sessionId_ = grant.sessionId();
  holdMs_ = grant.holdMs();
  closeReason_ = CloseReason::NONE;
  state_ = DoorState::OPENING;
  fromAngle_ = angle_;
  phaseStartMs_ = nowMs;
  return true;
}

void DoorController::emergencyClose(uint32_t nowMs, CloseReason reason) {
  if (state_ == DoorState::OPENING || state_ == DoorState::OPEN) startClosing(nowMs, reason);
}

void DoorController::startClosing(uint32_t nowMs, CloseReason r) {
  state_ = DoorState::CLOSING;
  closeReason_ = r;
  fromAngle_ = angle_;
  phaseStartMs_ = nowMs;
}

void DoorController::push(DoorEvent::Type t, CloseReason r) {
  if (pendingCount_ >= 2) {  // keep the most recent; drop the oldest
    pending_[0] = pending_[1];
    pendingCount_ = 1;
  }
  DoorEvent& e = pending_[pendingCount_++];
  e.type = t;
  e.reason = r;
  e.sessionId = sessionId_;
  e.holdMs = holdMs_;
}

DoorEvent DoorController::takeEvent() {
  if (pendingCount_ == 0) return DoorEvent{};
  DoorEvent e = pending_[0];
  pending_[0] = pending_[1];
  --pendingCount_;
  return e;
}

void DoorController::tick(uint32_t nowMs) {
  const uint32_t elapsed = nowMs - phaseStartMs_;
  auto sweep = [&](float target) {
    // Time-proportional travel from the angle where the phase started.
    float full = float(cfg_.openAngle - cfg_.closedAngle);
    float dist = target - fromAngle_;
    float span = full != 0 ? (dist < 0 ? -dist : dist) / (full < 0 ? -full : full) : 1.0f;
    float dur = float(cfg_.travelMs) * span;
    if (dur <= 0 || float(elapsed) >= dur) {
      angle_ = target;
      return true;
    }
    angle_ = fromAngle_ + dist * (float(elapsed) / dur);
    return false;
  };

  switch (state_) {
    case DoorState::CLOSED:
      angle_ = float(cfg_.closedAngle);  // keep commanding the closed position
      break;
    case DoorState::OPENING:
      if (sweep(float(cfg_.openAngle))) {
        state_ = DoorState::OPEN;
        phaseStartMs_ = nowMs;
        push(DoorEvent::Type::OPENED, CloseReason::NONE);
      }
      break;
    case DoorState::OPEN:
      if (elapsed >= holdMs_) startClosing(nowMs, CloseReason::TIMER);
      break;
    case DoorState::CLOSING:
      if (sweep(float(cfg_.closedAngle))) {
        state_ = DoorState::CLOSED;
        push(DoorEvent::Type::CLOSED, closeReason_);
        sessionId_.clear();
      }
      break;
  }
}

}  // namespace dcg
