#include "presence.h"

#include <algorithm>

namespace dcg {

void RollingMedian::push(bool valid, float cm) {
  if (valid && (cm < kMinDistanceCm || cm > kMaxDistanceCm)) valid = false;
  samples_[next_] = cm;
  ok_[next_] = valid;
  next_ = (next_ + 1) % kWindow;
  if (count_ < kWindow) ++count_;
}

bool RollingMedian::valid() const {
  int n = 0;
  for (int i = 0; i < count_; ++i) n += ok_[i] ? 1 : 0;
  return n >= kMinValid;
}

float RollingMedian::value() const {
  float tmp[kWindow];
  int n = 0;
  for (int i = 0; i < count_; ++i)
    if (ok_[i]) tmp[n++] = samples_[i];
  if (n == 0) return -1.0f;
  std::sort(tmp, tmp + n);
  return (n % 2) ? tmp[n / 2] : (tmp[n / 2 - 1] + tmp[n / 2]) / 2.0f;
}

void RollingMedian::reset() {
  next_ = 0;
  count_ = 0;
}

bool PresenceDetector::setThreshold(float cm) {
  if (!(cm >= kMinDistanceCm && cm <= kMaxDistanceCm)) return false;
  cfg_.thresholdCm = cm;
  nearStreak_ = farStreak_ = 0;  // re-confirm against the new threshold
  return true;
}

PresenceEvent PresenceDetector::update(bool valid, float rawCm, uint32_t nowMs) {
  if (!started_) { started_ = true; firstSampleMs_ = nowMs; }
  median_.push(valid, rawCm);

  if (median_.valid()) {
    everValid_ = true;
    lastValidMs_ = nowMs;
    fault_ = false;
  } else {
    uint32_t since = everValid_ ? lastValidMs_ : firstSampleMs_;
    if (nowMs - since >= cfg_.faultAfterMs) fault_ = true;
  }

  const bool near = median_.valid() && median_.value() <= cfg_.thresholdCm;
  const bool far = !median_.valid() || median_.value() > cfg_.thresholdCm + cfg_.hysteresisCm;

  nearStreak_ = near ? uint8_t(std::min<int>(nearStreak_ + 1, 255)) : 0;
  farStreak_ = far ? uint8_t(std::min<int>(farStreak_ + 1, 255)) : 0;

  if (!present_ && nearStreak_ >= cfg_.confirmCount) {
    present_ = true;
    return PresenceEvent::ARRIVED;
  }
  if (present_ && (farStreak_ >= cfg_.releaseCount || fault_)) {
    present_ = false;
    return PresenceEvent::LEFT;
  }
  return PresenceEvent::NONE;
}

}  // namespace dcg
