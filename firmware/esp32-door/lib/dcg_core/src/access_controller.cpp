#include "access_controller.h"

namespace dcg {

namespace {
// Wrap-around safe "a is at or after b" for millis() timestamps.
inline bool reached(uint32_t now, uint32_t at) { return int32_t(now - at) >= 0; }

bool isPendingState(const std::string& s) {
  return s == "CARD_READ" || s == "AWAITING_FACE" || s == "FACE_OK";
}
}  // namespace

const char* systemStateName(SystemState s) {
  switch (s) {
    case SystemState::BOOT: return "BOOT";
    case SystemState::OFFLINE: return "OFFLINE";
    case SystemState::ERROR: return "ERROR";
    case SystemState::IDLE: return "IDLE";
    case SystemState::PRESENCE: return "PRESENCE";
    case SystemState::CARD_READ: return "CARD_READ";
    case SystemState::WAITING_DECISION: return "WAITING_DECISION";
    case SystemState::DOOR_OPEN: return "DOOR_OPEN";
    case SystemState::DOOR_CLOSING: return "DOOR_CLOSING";
  }
  return "?";
}

const char* dhtStatusName(DhtStatus s) {
  switch (s) {
    case DhtStatus::UNKNOWN: return "UNKNOWN";
    case DhtStatus::OK: return "OK";
    case DhtStatus::ERROR: return "ERROR";
  }
  return "?";
}

void AccessController::setState(SystemState s) {
  if (s == state_) return;
  hal_.log(std::string("state ") + systemStateName(state_) + " -> " + systemStateName(s));
  state_ = s;
  hal_.onStateChange(s);
  switch (s) {
    case SystemState::OFFLINE: hal_.feedback(Feedback::OFFLINE, ""); break;
    case SystemState::ERROR: hal_.feedback(Feedback::ERROR, ""); break;
    case SystemState::IDLE: hal_.feedback(Feedback::READY, ""); break;
    case SystemState::PRESENCE: hal_.feedback(Feedback::PRESENCE, ""); break;
    case SystemState::CARD_READ:
    case SystemState::WAITING_DECISION: hal_.feedback(Feedback::WAITING, ""); break;
    default: break;
  }
}

void AccessController::restingState(const SensorSnapshot& s) {
  if (!online_) setState(SystemState::OFFLINE);
  else if (s.fault || !hal_.rfidOk()) setState(SystemState::ERROR);
  else setState(s.present ? SystemState::PRESENCE : SystemState::IDLE);
}

void AccessController::applyConfig(const DeviceConfig& c) {
  if (c.presenceThresholdCm != cfg_.presenceThresholdCm) {
    hal_.setPresenceThreshold(c.presenceThresholdCm);
    hal_.log("presence threshold = " + std::to_string(int(c.presenceThresholdCm)) + " cm");
  }
  cfg_ = c;
}

void AccessController::abortSession(const char* why, Feedback f) {
  hal_.log(std::string("session aborted: ") + why + " (door stays closed)");
  hal_.feedback(f, why);
  sessionId_.clear();
  pollErrors_ = 0;
  buttonExit_ = false;
  restingState(hal_.sensor());
}

void AccessController::emergencyClose(CloseReason r) {
  hal_.closeDoor(r);
  hal_.cancelEntrance();  // fail-closed for the main entrance too: green LED off now
}

void AccessController::localEmergencyClose() {
  hal_.log("LOCAL emergency close");
  emergencyClose(CloseReason::LOCAL_BUTTON);
  if (state_ == SystemState::WAITING_DECISION || state_ == SystemState::CARD_READ)
    abortSession("LOCAL_EMERGENCY", Feedback::DENIED);
}

void AccessController::requestExitByButton() {
  const uint32_t now = hal_.millis();
  if (!online_) { hal_.log("exit button ignored: OFFLINE (cannot verify)"); hal_.feedback(Feedback::OFFLINE, "OFFLINE"); return; }
  if (!sessionId_.empty() || hal_.doorState() != DoorState::CLOSED) { hal_.log("exit button ignored: busy"); return; }
  hal_.log("exit button -> backend");
  setState(SystemState::CARD_READ);
  StartReply r;
  ApiResult res = backend_.exitButton(r);
  if (res != ApiResult::OK) { abortSession(apiResultName(res), Feedback::ERROR); return; }
  if (r.sessionId.empty() || r.state == "DENIED" || r.state == "TIMEOUT") {
    abortSession(r.reasonCode.empty() ? r.state.c_str() : r.reasonCode.c_str(), Feedback::DENIED);
    return;
  }
  beginSession(now, r, true);
}

void AccessController::beginSession(uint32_t now, const StartReply& r, bool byButton) {
  sessionId_ = r.sessionId;
  buttonExit_ = byButton;
  pollMs_ = r.pollMs;
  pollErrors_ = 0;
  sessionDeadlineMs_ = now + r.timeoutS * 1000 + t_.sessionGraceMs;
  nextPollMs_ = now + pollMs_;
  hal_.log("session " + sessionId_ + " " + r.state + (byButton ? " (exit button)" : ""));
  hal_.onSessionPhase(r.state);
  setState(SystemState::WAITING_DECISION);
}

void AccessController::queueConfirm(bool opened, const std::string& sid, uint32_t openMs,
                                    CloseReason r, uint32_t now) {
  if (sid.empty()) return;
  // Slot 0 is always the oldest so /opened is delivered before /closed.
  int slot = 0;
  if (confirms_[0].active) {
    slot = 1;
    if (confirms_[1].active) {
      hal_.log("confirm queue full, dropping oldest");
      confirms_[0] = confirms_[1];
    }
  }
  PendingConfirm& p = confirms_[slot];
  p = PendingConfirm{};
  p.active = true;
  p.opened = opened;
  p.sessionId = sid;
  p.openMs = openMs;
  p.reason = r;
  p.nextMs = now;
}

void AccessController::handleConfirmations(uint32_t now) {
  PendingConfirm& p = confirms_[0];
  if (!p.active || !online_ || !reached(now, p.nextMs)) return;
  ApiResult r = p.opened ? backend_.confirmOpened(p.sessionId, p.openMs)
                         : backend_.confirmClosed(p.sessionId, closeReasonName(p.reason));
  bool done = r == ApiResult::OK;
  if (!done && ++p.attempts >= t_.confirmMaxAttempts) {
    hal_.log(std::string("giving up confirmation: ") + apiResultName(r));
    done = true;
  }
  if (done) {
    confirms_[0] = confirms_[1];
    confirms_[1] = PendingConfirm{};
  } else {
    p.nextMs = now + t_.confirmRetryMs;
  }
}

void AccessController::handleDoorEvents(uint32_t now) {
  for (DoorEvent ev = hal_.takeDoorEvent(); ev.type != DoorEvent::Type::NONE;
       ev = hal_.takeDoorEvent()) {
    if (ev.type == DoorEvent::Type::OPENED) {
      hal_.log("door OPEN");
      queueConfirm(true, ev.sessionId, ev.holdMs, CloseReason::NONE, now);
    } else {
      hal_.log(std::string("door CLOSED (") + closeReasonName(ev.reason) + ")");
      queueConfirm(false, ev.sessionId, 0, ev.reason, now);
      if (state_ == SystemState::DOOR_OPEN || state_ == SystemState::DOOR_CLOSING) {
        sessionId_.clear();
        buttonExit_ = false;
        restingState(hal_.sensor());
      }
    }
  }
  if (state_ == SystemState::DOOR_OPEN && hal_.doorState() == DoorState::CLOSING)
    setState(SystemState::DOOR_CLOSING);
}

void AccessController::handleHeartbeat(uint32_t now, bool force) {
  const bool doorMoving = hal_.doorState() != DoorState::CLOSED;
  uint32_t due = nextHeartbeatMs_;
  // While the door is not closed, beat fast so a remote EMERGENCY_CLOSE arrives quickly.
  if (doorMoving && int32_t(due - (lastHeartbeatMs_ + t_.heartbeatFastMs)) > 0)
    due = lastHeartbeatMs_ + t_.heartbeatFastMs;
  if (!force && !reached(now, due)) return;
  lastHeartbeatMs_ = now;
  uint32_t interval = doorMoving ? t_.heartbeatFastMs
                                 : (online_ ? cfg_.heartbeatS * 1000 : t_.offlineRetryMs);
  nextHeartbeatMs_ = now + interval;

  SensorSnapshot s = hal_.sensor();
  HeartbeatInfo hb;
  hb.fw = fw_;
  hb.state = systemStateName(state_);
  hb.door = doorStateName(hal_.doorState());
  hb.present = s.present;
  hb.distanceCm = s.distanceCm;
  hb.rssi = hal_.rssi();
  hb.uptimeS = now / 1000;
  hb.freeHeap = hal_.freeHeap();
  hb.sessionId = sessionId_;
  hb.rfidOk = hal_.rfidOk();
  hb.ultrasonicOk = !s.fault;
  hb.dhtOk = dhtOk_;

  HeartbeatReply reply;
  ApiResult r = backend_.heartbeat(hb, cfg_, reply);
  if (r == ApiResult::OK) {
    if (!online_) hal_.log("backend ONLINE");
    online_ = true;
    hbFailures_ = 0;
    if (reply.hasConfig) applyConfig(reply.config);
    if (reply.unknownCommand) hal_.log("ignored unknown/unsupported remote command");
    if (reply.command == Command::EMERGENCY_CLOSE) {
      hal_.log("remote EMERGENCY_CLOSE");
      emergencyClose(CloseReason::EMERGENCY);
      if (state_ == SystemState::WAITING_DECISION) abortSession("EMERGENCY_CLOSE", Feedback::DENIED);
    }
    return;
  }
  ++hbFailures_;
  hal_.log(std::string("heartbeat failed: ") + apiResultName(r));
  const bool fatal = r == ApiResult::CLOCK_NOT_SYNCED;
  if (online_ && (fatal || hbFailures_ >= t_.offlineAfterFailures)) {
    online_ = false;
    hal_.log("backend OFFLINE");
  }
}

void AccessController::handlePresence(const SensorSnapshot& s) {
  if (s.present == lastPresent_) return;
  lastPresent_ = s.present;
  hal_.log(std::string("presence ") + (s.present ? "ON" : "OFF") + " at " +
           formatDistance(s.distanceCm) + " cm (inside the room)");
  const uint32_t now = hal_.millis();
  ApiResult r = ApiResult::NETWORK_ERROR;
  PresenceReply pr;
  if (online_) r = backend_.presence(s.present, s.distanceCm, cfg_.presenceThresholdCm, pr);
  if (!s.present) return;
  if (r == ApiResult::OK) {
    if (pr.alarm) {
      hal_.log("INTRUSION: someone inside and nobody authorized -> alarm " + std::to_string(pr.alarmMs) + " ms");
      hal_.alarm(pr.alarmMs);
    }
    return;
  }
  // Cannot ask the backend who is inside: fail-secure local alarm (except right after boot).
  if (!reached(now, bootMs_ + t_.alarmBootGraceMs)) {
    hal_.log("presence while starting up: no local alarm yet");
    return;
  }
  hal_.log(std::string("INTRUSION (backend unreachable: ") + apiResultName(r) + ") -> local alarm");
  hal_.alarm(t_.localAlarmMs);
}

void AccessController::handleCard(uint32_t now, const SensorSnapshot& s) {
  (void)s;
  std::string uid;
  if (!hal_.readCard(uid)) return;  // the reader is always drained, even when offline
  if (!isValidUid(uid)) return;
  if (uid == lastUid_ && !reached(now, lastUidMs_ + t_.cardDebounceMs)) return;
  lastUid_ = uid;
  lastUidMs_ = now;

  if (!online_) { hal_.log("card ignored: OFFLINE"); hal_.feedback(Feedback::OFFLINE, "OFFLINE"); return; }
  if (state_ == SystemState::ERROR) { hal_.log("card ignored: ERROR"); hal_.feedback(Feedback::ERROR, "SENSOR_ERROR"); return; }
  if (hal_.doorState() != DoorState::CLOSED) return;

  hal_.log("card " + uid + " -> backend");
  hal_.onCardDetected(uid);
  setState(SystemState::CARD_READ);
  StartReply r;
  ApiResult res = backend_.startAccess(uid, s.distanceCm, fw_, r);
  if (res != ApiResult::OK) { abortSession(apiResultName(res), Feedback::ERROR); return; }
  if (r.sessionId.empty() || r.state == "DENIED" || r.state == "TIMEOUT") {
    abortSession(r.reasonCode.empty() ? r.state.c_str() : r.reasonCode.c_str(), Feedback::DENIED);
    return;
  }
  beginSession(now, r, false);
}

void AccessController::handleWaiting(uint32_t now, const SensorSnapshot& s) {
  (void)s;  // the inside HC-SR04 is not an access factor
  if (!online_) { abortSession("OFFLINE", Feedback::OFFLINE); return; }
  if (reached(now, sessionDeadlineMs_)) { abortSession("TIMEOUT", Feedback::DENIED); return; }
  if (!reached(now, nextPollMs_)) return;
  nextPollMs_ = now + pollMs_;

  DecisionReply d;
  ApiResult res = backend_.pollAccess(sessionId_, s.distanceCm, d);
  if (res != ApiResult::OK) {
    if (res == ApiResult::BAD_SIGNATURE) backend_.event("BAD_RESPONSE_SIGNATURE", "poll");
    if (++pollErrors_ >= t_.pollMaxErrors) abortSession(apiResultName(res), Feedback::ERROR);
    return;
  }
  pollErrors_ = 0;
  if (d.sessionId != sessionId_) { abortSession("SESSION_MISMATCH", Feedback::ERROR); return; }

  if (d.state == "GRANTED") {
    if (hal_.doorState() != DoorState::CLOSED) { abortSession("DOOR_BUSY", Feedback::ERROR); return; }
    OpenGrant grant(sessionId_, d.openMs);
    if (!hal_.openDoor(grant)) { abortSession("OPEN_REJECTED", Feedback::ERROR); return; }
    hal_.log("GRANTED -> opening for " + std::to_string(d.openMs) + " ms");
    hal_.onGranted(d.greeting, d.displayName);
    hal_.feedback(Feedback::GRANTED, "");
    setState(SystemState::DOOR_OPEN);
    return;
  }
  if (isPendingState(d.state)) {  // keep polling
    hal_.onSessionPhase(d.state);
    return;
  }
  // DENIED, TIMEOUT or anything unexpected: finish, door closed.
  abortSession(d.reasonCode.empty() ? d.state.c_str() : d.reasonCode.c_str(), Feedback::DENIED);
}

void AccessController::tick() {
  const uint32_t now = hal_.millis();
  if (!booted_) { booted_ = true; bootMs_ = now; }
  handleDoorEvents(now);

  const bool wasOnline = online_;
  if (!hal_.networkUp()) {
    if (online_) hal_.log("WiFi down -> OFFLINE");
    online_ = false;
  } else {
    handleHeartbeat(now, state_ == SystemState::BOOT);
  }
  if (wasOnline && !online_) emergencyClose(CloseReason::EMERGENCY);  // fail-closed

  const SensorSnapshot s = hal_.sensor();
  handlePresence(s);

  switch (state_) {
    case SystemState::BOOT:
    case SystemState::OFFLINE:
    case SystemState::ERROR:
    case SystemState::IDLE:
    case SystemState::PRESENCE:
      restingState(s);
      handleCard(now, s);
      break;
    case SystemState::CARD_READ:  // transient; only reachable if a call was interrupted
      abortSession("INTERRUPTED", Feedback::ERROR);
      break;
    case SystemState::WAITING_DECISION:
      handleWaiting(now, s);
      break;
    case SystemState::DOOR_OPEN:
    case SystemState::DOOR_CLOSING:
      break;  // door events drive these
  }
  handleConfirmations(now);
}

}  // namespace dcg
