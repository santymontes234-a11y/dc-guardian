#include "environment.h"

#include <cmath>
#include <cstdio>
#include <string>

namespace dcg {

namespace {
inline bool reached(uint32_t now, uint32_t at) { return int32_t(now - at) >= 0; }

// DHT11 datasheet range is 0–50 °C / 20–90 %RH; anything far outside is a bad read.
bool plausible(const DhtSample& s) {
  return s.ok && std::isfinite(s.temperatureC) && std::isfinite(s.humidityPct) &&
         s.temperatureC >= -20.0f && s.temperatureC <= 80.0f && s.humidityPct >= 0.0f &&
         s.humidityPct <= 100.0f;
}

bool sameStatus(const EnvStatus& a, const EnvStatus& b) {
  return a.sensor == b.sensor && a.temperatureC == b.temperatureC &&
         a.humidityPct == b.humidityPct && a.fan == b.fan && a.alarm == b.alarm &&
         a.fallback == b.fallback && a.thresholds.tempHighC == b.thresholds.tempHighC &&
         a.thresholds.tempCriticalC == b.thresholds.tempCriticalC &&
         a.thresholds.humidityLowPct == b.thresholds.humidityLowPct &&
         a.thresholds.humidityHighPct == b.thresholds.humidityHighPct;
}
}  // namespace

void EnvController::setThresholds(const EnvThresholds& th) {
  // Defensive: the parser already validated them, but never accept an inconsistent pair.
  EnvThresholds next = st_.thresholds;
  if (validTempPair(th.tempHighC, th.tempCriticalC)) {
    next.tempHighC = th.tempHighC;
    next.tempCriticalC = th.tempCriticalC;
  }
  if (validHumidityPair(th.humidityLowPct, th.humidityHighPct)) {
    next.humidityLowPct = th.humidityLowPct;
    next.humidityHighPct = th.humidityHighPct;
  }
  st_.thresholds = next;
}

void EnvController::updateLocalFan() {
  if (st_.sensor != DhtStatus::OK) { localFanOn_ = false; return; }
  const float t = st_.temperatureC;
  if (t >= st_.thresholds.tempHighC) localFanOn_ = true;
  else if (t < st_.thresholds.tempHighC - t_.fanHysteresisC) localFanOn_ = false;
  // in between: keep the previous state (hysteresis)
}

bool EnvController::localFan() const { return st_.sensor == DhtStatus::OK && localFanOn_; }

bool EnvController::localAlarm() const {
  if (st_.sensor != DhtStatus::OK) return false;
  const EnvThresholds& th = st_.thresholds;
  return st_.temperatureC >= th.tempCriticalC || st_.humidityPct < th.humidityLowPct ||
         st_.humidityPct > th.humidityHighPct;
}

void EnvController::onSample(const DhtSample& s, uint32_t now) {
  anySample_ = true;
  lastSampleMs_ = now;
  if (plausible(s)) {
    failures_ = 0;
    hasValid_ = true;
    if (st_.sensor == DhtStatus::ERROR) hal_.log("DHT11 OK again");
    st_.sensor = DhtStatus::OK;
    st_.temperatureC = s.temperatureC;
    st_.humidityPct = s.humidityPct;
  } else {
    if (failures_ < 255) ++failures_;
    if (failures_ >= t_.failuresForError && st_.sensor != DhtStatus::ERROR) {
      hal_.log("DHT11 ERROR (" + std::to_string(failures_) + " failed reads in a row)");
      st_.sensor = DhtStatus::ERROR;
    }
  }
  updateLocalFan();
}

void EnvController::recompute(uint32_t now) {
  // A stalled sampling task is a sensor failure too.
  if (anySample_ && st_.sensor != DhtStatus::ERROR && reached(now, lastSampleMs_ + t_.staleMs)) {
    hal_.log("DHT11 ERROR (no reads)");
    st_.sensor = DhtStatus::ERROR;
    updateLocalFan();
  }
  if (remoteOk_ && reached(now, remoteAtMs_ + t_.remoteValidMs)) remoteOk_ = false;

  st_.fallback = !remoteOk_;
  if (st_.sensor == DhtStatus::ERROR) {
    st_.fan = false;  // contract: sensor ERROR ⇒ fan off
    st_.alarm = remoteOk_ ? remote_.alarm : false;
  } else if (remoteOk_) {
    st_.fan = remote_.fan || localFan();  // when in doubt, cool
    st_.alarm = remote_.alarm;
  } else {
    st_.fan = localFan();
    st_.alarm = localAlarm();
  }
}

void EnvController::publish() {
  if (everPublished_ && sameStatus(published_, st_)) return;
  if (!everPublished_ || published_.fan != st_.fan)
    hal_.log(std::string("fan ") + (st_.fan ? "ON" : "OFF") + (st_.fallback ? " (local)" : ""));
  if (!everPublished_ || published_.alarm != st_.alarm)
    hal_.log(std::string("environment alarm ") + (st_.alarm ? "ON" : "OFF") +
             (st_.fallback ? " (local)" : ""));
  published_ = st_;
  everPublished_ = true;
  hal_.onEnvironment(st_);
}

bool EnvController::tick(uint32_t now, bool online, bool mayCall) {
  DhtSample s;
  while (hal_.takeDhtSample(s)) onSample(s, now);

  bool called = false;
  if (!online) {
    remoteOk_ = false;  // offline: decide locally
  } else if (mayCall && st_.sensor != DhtStatus::UNKNOWN &&
             (!started_ || reached(now, nextSendMs_))) {
    started_ = true;
    nextSendMs_ = now + t_.sendEveryMs;
    EnvReading r;
    r.sensorOk = st_.sensor == DhtStatus::OK && hasValid_;
    r.temperatureC = st_.temperatureC;
    r.humidityPct = st_.humidityPct;
    EnvReply reply;
    ApiResult res = backend_.environment(r, reply);
    called = true;
    if (res == ApiResult::OK) {
      remote_ = reply;
      remoteOk_ = true;
      remoteAtMs_ = now;
    } else {
      if (remoteOk_ || !st_.fallback)
        hal_.log(std::string("environment: ") + apiResultName(res) + " -> local fan/alarm");
      remoteOk_ = false;  // unsigned / bad signature / malformed ⇒ ignored entirely
    }
  }
  recompute(now);
  publish();
  return called;
}

}  // namespace dcg
