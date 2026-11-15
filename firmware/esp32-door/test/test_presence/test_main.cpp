// HC-SR04 filtering: rolling median, consecutive confirmation, hysteresis, sensor fault.
#include <unity.h>

#include <initializer_list>

#include "presence.h"

using namespace dcg;

void setUp() {}
void tearDown() {}

static uint32_t t = 0;
static PresenceEvent feed(PresenceDetector& d, float cm, bool valid = true) {
  t += 60;
  return d.update(valid, cm, t);
}

void test_median_rejects_single_spike() {
  RollingMedian m;
  for (float v : {40.f, 41.f, 300.f, 39.f, 40.f}) m.push(true, v);
  TEST_ASSERT_TRUE(m.valid());
  TEST_ASSERT_FLOAT_WITHIN(0.01, 40.0, m.value());
}

void test_median_needs_three_valid_samples() {
  RollingMedian m;
  m.push(true, 30); m.push(false, 0); m.push(false, 0); m.push(true, 31); m.push(false, 0);
  TEST_ASSERT_FALSE(m.valid());
  m.push(true, 32);  // overwrites the oldest (30): still 2 valid of 5
  TEST_ASSERT_FALSE(m.valid());
  m.push(true, 33);  // [32, 33, x, 31, x] ⇒ 3 valid
  TEST_ASSERT_TRUE(m.valid());
  TEST_ASSERT_FLOAT_WITHIN(0.01, 32.0, m.value());
}

void test_out_of_range_readings_are_invalid() {
  RollingMedian m;
  for (int i = 0; i < 5; ++i) m.push(true, i % 2 ? 1.0f : 500.0f);
  TEST_ASSERT_FALSE(m.valid());
}

void test_presence_requires_consecutive_readings() {
  PresenceDetector d;  // threshold 50, confirm 3
  for (int i = 0; i < 5; ++i) TEST_ASSERT_EQUAL(int(PresenceEvent::NONE), int(feed(d, 120)));
  // The median needs a majority of near samples before it drops below the threshold,
  // then 3 consecutive confirmations.
  int arrivedAt = -1;
  for (int i = 0; i < 10 && arrivedAt < 0; ++i)
    if (feed(d, 30) == PresenceEvent::ARRIVED) arrivedAt = i;
  TEST_ASSERT_TRUE(arrivedAt >= 4);  // 3 to flip the median + 3 confirmations - overlap
  TEST_ASSERT_TRUE(d.present());
}

void test_spikes_do_not_trigger_presence() {
  PresenceDetector d;
  for (int i = 0; i < 50; ++i) {
    // One close echo every 4 readings (noise / reflection).
    PresenceEvent e = feed(d, (i % 4 == 0) ? 10.0f : 150.0f);
    TEST_ASSERT_EQUAL(int(PresenceEvent::NONE), int(e));
  }
  TEST_ASSERT_FALSE(d.present());
}

void test_hysteresis_keeps_presence_near_threshold() {
  PresenceDetector d;
  for (int i = 0; i < 10; ++i) feed(d, 45);
  TEST_ASSERT_TRUE(d.present());
  // 52 cm: above the threshold but inside the 5 cm hysteresis band ⇒ still present.
  for (int i = 0; i < 20; ++i) TEST_ASSERT_EQUAL(int(PresenceEvent::NONE), int(feed(d, 52)));
  TEST_ASSERT_TRUE(d.present());
  int leftAt = -1;
  for (int i = 0; i < 20 && leftAt < 0; ++i)
    if (feed(d, 80) == PresenceEvent::LEFT) leftAt = i;
  TEST_ASSERT_TRUE(leftAt >= 4);  // release needs 5 consecutive far values
  TEST_ASSERT_FALSE(d.present());
}

void test_threshold_from_backend() {
  PresenceDetector d;
  TEST_ASSERT_FALSE(d.setThreshold(1.0f));
  TEST_ASSERT_FALSE(d.setThreshold(401.0f));
  TEST_ASSERT_EQUAL_FLOAT(50.0f, d.threshold());
  TEST_ASSERT_TRUE(d.setThreshold(100.0f));
  for (int i = 0; i < 10; ++i) feed(d, 80);
  TEST_ASSERT_TRUE(d.present());
}

void test_silent_sensor_is_fault_and_not_present() {
  PresenceDetector d;
  for (int i = 0; i < 10; ++i) feed(d, 30);
  TEST_ASSERT_TRUE(d.present());
  bool left = false;
  for (int i = 0; i < 200; ++i) left |= feed(d, 0, false) == PresenceEvent::LEFT;
  TEST_ASSERT_TRUE(left);
  TEST_ASSERT_FALSE(d.present());
  TEST_ASSERT_TRUE(d.sensorFault());  // 200 × 60 ms = 12 s > 10 s
  TEST_ASSERT_EQUAL_FLOAT(-1.0f, d.distanceCm());
  for (int i = 0; i < 5; ++i) feed(d, 100);
  TEST_ASSERT_FALSE(d.sensorFault());
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_median_rejects_single_spike);
  RUN_TEST(test_median_needs_three_valid_samples);
  RUN_TEST(test_out_of_range_readings_are_invalid);
  RUN_TEST(test_presence_requires_consecutive_readings);
  RUN_TEST(test_spikes_do_not_trigger_presence);
  RUN_TEST(test_hysteresis_keeps_presence_near_threshold);
  RUN_TEST(test_threshold_from_backend);
  RUN_TEST(test_silent_sensor_is_fault_and_not_present);
  return UNITY_END();
}
