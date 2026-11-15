// HC-SR04 filtering and presence detection.
//
//  raw ping (cm or invalid) ──► RollingMedian(5) ──► PresenceDetector
//
// * Invalid pings (no echo, < 2 cm, > 400 cm) are kept as "invalid" samples; the median is
//   only valid when at least 3 of the last 5 samples are valid (rejects spikes/dropouts).
// * Presence needs `confirmCount` consecutive filtered values ≤ threshold to turn ON, and
//   `releaseCount` consecutive values > threshold + hysteresis (or invalid) to turn OFF.
// * A permanently silent sensor is reported as a fault: no presence ⇒ no access (fail-closed).
#pragma once

#include <cstdint>

namespace dcg {

constexpr float kMinDistanceCm = 2.0f;
constexpr float kMaxDistanceCm = 400.0f;

class RollingMedian {
 public:
  static constexpr int kWindow = 5;
  static constexpr int kMinValid = 3;

  void push(bool valid, float cm);
  bool valid() const;
  float value() const;  // median of valid samples (only meaningful if valid())
  void reset();

 private:
  float samples_[kWindow] = {};
  bool ok_[kWindow] = {};
  int next_ = 0;
  int count_ = 0;
};

struct PresenceConfig {
  float thresholdCm = 50.0f;
  float hysteresisCm = 5.0f;
  uint8_t confirmCount = 3;   // consecutive filtered values to declare presence
  uint8_t releaseCount = 5;   // consecutive filtered values to declare absence
  uint32_t faultAfterMs = 10000;  // no valid reading for this long ⇒ sensor fault
};

enum class PresenceEvent { NONE, ARRIVED, LEFT };

class PresenceDetector {
 public:
  explicit PresenceDetector(PresenceConfig cfg = {}) : cfg_(cfg) {}

  // Feed one raw ping. Returns ARRIVED/LEFT on a debounced state change.
  PresenceEvent update(bool valid, float rawCm, uint32_t nowMs);

  // Threshold may come from the backend; values outside [2, 400] are rejected.
  bool setThreshold(float cm);
  float threshold() const { return cfg_.thresholdCm; }

  bool present() const { return present_; }
  bool distanceValid() const { return median_.valid(); }
  float distanceCm() const { return median_.valid() ? median_.value() : -1.0f; }
  bool sensorFault() const { return fault_; }

 private:
  PresenceConfig cfg_;
  RollingMedian median_;
  bool present_ = false;
  uint8_t nearStreak_ = 0;
  uint8_t farStreak_ = 0;
  bool fault_ = false;
  bool everValid_ = false;
  uint32_t lastValidMs_ = 0;
  uint32_t firstSampleMs_ = 0;
  bool started_ = false;
};

}  // namespace dcg
