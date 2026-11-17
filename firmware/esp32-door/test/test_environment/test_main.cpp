// EnvController (DHT11): sensor health, 10 s reporting, signed {fan, alarm} applied,
// local fallback with hysteresis when the backend cannot be trusted, fan off on sensor ERROR.
#include <unity.h>

#include <cmath>
#include <deque>

#include "environment.h"

using namespace dcg;

struct FakeHal : DeviceHal {
  uint32_t now = 1000;
  std::deque<DhtSample> samples;
  EnvStatus last;
  int envCalls = 0;
  int opens = 0;
  DoorController door;

  uint32_t millis() override { return now; }
  bool networkUp() override { return true; }
  int rssi() override { return -60; }
  uint32_t freeHeap() override { return 100000; }
  SensorSnapshot sensor() override { return {}; }
  void setPresenceThreshold(float) override {}
  bool readCard(std::string&) override { return false; }
  bool rfidOk() override { return true; }
  bool openDoor(const OpenGrant&) override { ++opens; return false; }
  void closeDoor(CloseReason) override {}
  DoorState doorState() override { return door.state(); }
  DoorEvent takeDoorEvent() override { return door.takeEvent(); }
  void feedback(Feedback, const std::string&) override {}
  void log(const std::string&) override {}
  bool takeDhtSample(DhtSample& out) override {
    if (samples.empty()) return false;
    out = samples.front();
    samples.pop_front();
    return true;
  }
  void onEnvironment(const EnvStatus& s) override { last = s; ++envCalls; }
};

struct FakeBackend : Backend {
  ApiResult envResult = ApiResult::OK;
  EnvReply envReply;
  std::vector<EnvReading> sent;

  ApiResult heartbeat(const HeartbeatInfo&, const DeviceConfig&, HeartbeatReply&) override { return ApiResult::OK; }
  ApiResult presence(bool, float, float, PresenceReply&) override { return ApiResult::OK; }
  ApiResult startAccess(const std::string&, float, const std::string&, StartReply&) override { return ApiResult::NETWORK_ERROR; }
  ApiResult pollAccess(const std::string&, float, DecisionReply&) override { return ApiResult::NETWORK_ERROR; }
  ApiResult confirmOpened(const std::string&, uint32_t) override { return ApiResult::OK; }
  ApiResult confirmClosed(const std::string&, const char*) override { return ApiResult::OK; }
  ApiResult event(const char*, const std::string&) override { return ApiResult::OK; }
  ApiResult exitButton(StartReply&) override { return ApiResult::NETWORK_ERROR; }
  ApiResult environment(const EnvReading& r, EnvReply& out) override {
    sent.push_back(r);
    if (envResult == ApiResult::OK) out = envReply;
    return envResult;
  }
};

static FakeHal* hal;
static FakeBackend* be;
static EnvController* env;

void setUp() {
  hal = new FakeHal();
  be = new FakeBackend();
  env = new EnvController(*hal, *be);
}
void tearDown() {
  delete env;
  delete be;
  delete hal;
}

static DhtSample ok(float t, float h) { return DhtSample{true, t, h}; }
static DhtSample bad() { return DhtSample{false, NAN, NAN}; }

// One 2 s DHT period: a sample arrives and the controller ticks.
static bool step(const DhtSample& s, bool online = true) {
  hal->now += 2000;
  hal->samples.push_back(s);
  return env->tick(hal->now, online);
}

void test_nothing_sent_before_first_read() {
  TEST_ASSERT_FALSE(env->tick(hal->now, true));
  TEST_ASSERT_EQUAL(0, (int)be->sent.size());
  TEST_ASSERT_EQUAL(int(DhtStatus::UNKNOWN), int(env->status().sensor));
  TEST_ASSERT_TRUE(env->sensorOk());  // not reported as ERROR before it fails
  TEST_ASSERT_FALSE(env->status().fan);
}

void test_sends_every_10_s_with_last_valid_reading() {
  TEST_ASSERT_TRUE(step(ok(24.0f, 50.0f)));  // first reading goes out at once
  TEST_ASSERT_EQUAL(1, (int)be->sent.size());
  TEST_ASSERT_TRUE(be->sent[0].sensorOk);
  TEST_ASSERT_EQUAL_FLOAT(24.0f, be->sent[0].temperatureC);
  for (int i = 0; i < 4; ++i) TEST_ASSERT_FALSE(step(ok(24.5f, 51.0f)));  // 8 s
  TEST_ASSERT_EQUAL(1, (int)be->sent.size());
  TEST_ASSERT_TRUE(step(bad()));  // 10 s: one failure is not ERROR, last valid value is sent
  TEST_ASSERT_EQUAL(2, (int)be->sent.size());
  TEST_ASSERT_TRUE(be->sent[1].sensorOk);
  TEST_ASSERT_EQUAL_FLOAT(24.5f, be->sent[1].temperatureC);
  TEST_ASSERT_EQUAL_FLOAT(51.0f, be->sent[1].humidityPct);
}

void test_mayCall_false_defers_the_send() {
  hal->now += 2000;
  hal->samples.push_back(ok(24, 50));
  TEST_ASSERT_FALSE(env->tick(hal->now, true, false));
  TEST_ASSERT_EQUAL(0, (int)be->sent.size());
  TEST_ASSERT_EQUAL(int(DhtStatus::OK), int(env->status().sensor));  // sample still drained
  TEST_ASSERT_TRUE(env->tick(hal->now + 10, true, true));
  TEST_ASSERT_EQUAL(1, (int)be->sent.size());
}

void test_three_failures_in_a_row_is_error_and_fan_off() {
  be->envReply = EnvReply{true, false};
  step(ok(30.0f, 50.0f));
  TEST_ASSERT_TRUE(env->status().fan);
  step(bad());
  step(bad());
  TEST_ASSERT_EQUAL(int(DhtStatus::OK), int(env->status().sensor));
  step(bad());
  TEST_ASSERT_EQUAL(int(DhtStatus::ERROR), int(env->status().sensor));
  TEST_ASSERT_FALSE(env->sensorOk());
  TEST_ASSERT_FALSE(env->status().fan);  // contract: sensor ERROR ⇒ fan off, even if asked
  TEST_ASSERT_FALSE(hal->last.fan);
  // Next report carries the ERROR with null values
  for (int i = 0; i < 5 && be->sent.size() < 2; ++i) step(bad());
  TEST_ASSERT_EQUAL(2, (int)be->sent.size());
  TEST_ASSERT_FALSE(be->sent[1].sensorOk);
  // A good read recovers immediately
  step(ok(25.0f, 50.0f));
  TEST_ASSERT_EQUAL(int(DhtStatus::OK), int(env->status().sensor));
}

void test_failures_must_be_consecutive() {
  step(ok(24, 50));
  for (int i = 0; i < 6; ++i) step(i % 3 == 2 ? ok(24, 50) : bad());
  TEST_ASSERT_EQUAL(int(DhtStatus::OK), int(env->status().sensor));
}

void test_implausible_values_count_as_failures() {
  step(ok(24, 50));
  step(ok(NAN, 50));
  step(ok(24, 150));
  step(ok(-100, 50));
  TEST_ASSERT_EQUAL(int(DhtStatus::ERROR), int(env->status().sensor));
}

void test_no_samples_at_all_is_error() {
  step(ok(24, 50));
  hal->now += 12000;  // sampling task stalled
  env->tick(hal->now, true);
  TEST_ASSERT_EQUAL(int(DhtStatus::ERROR), int(env->status().sensor));
}

void test_signed_reply_is_applied() {
  be->envReply = EnvReply{true, true};
  step(ok(24.0f, 50.0f));  // locally neither fan nor alarm, but the backend asks for both
  TEST_ASSERT_TRUE(env->status().fan);
  TEST_ASSERT_TRUE(env->status().alarm);
  TEST_ASSERT_FALSE(env->status().fallback);
  TEST_ASSERT_TRUE(hal->last.fan);
  TEST_ASSERT_TRUE(hal->last.alarm);
  be->envReply = EnvReply{false, false};
  for (int i = 0; i < 5; ++i) step(ok(24.0f, 50.0f));
  TEST_ASSERT_FALSE(env->status().fan);
  TEST_ASSERT_FALSE(env->status().alarm);
}

void test_when_in_doubt_cool_backend_cannot_switch_off_a_needed_fan() {
  be->envReply = EnvReply{false, false};
  step(ok(29.0f, 50.0f));  // >= temp_high_c (27)
  TEST_ASSERT_TRUE(env->status().fan);
  TEST_ASSERT_FALSE(env->status().alarm);  // alarm follows the backend when it answers
}

void test_bad_signature_falls_back_to_local_hysteresis() {
  be->envResult = ApiResult::BAD_SIGNATURE;
  be->envReply = EnvReply{false, false};
  step(ok(26.0f, 50.0f));
  TEST_ASSERT_TRUE(env->status().fallback);
  TEST_ASSERT_FALSE(env->status().fan);
  step(ok(27.0f, 50.0f));  // reaches temp_high_c ⇒ ON
  TEST_ASSERT_TRUE(env->status().fan);
  step(ok(26.5f, 50.0f));  // inside the 1 °C band ⇒ stays ON
  TEST_ASSERT_TRUE(env->status().fan);
  step(ok(26.0f, 50.0f));  // exactly high - 1 ⇒ still ON (OFF only below)
  TEST_ASSERT_TRUE(env->status().fan);
  step(ok(25.9f, 50.0f));  // below high - 1 ⇒ OFF
  TEST_ASSERT_FALSE(env->status().fan);
  step(ok(26.5f, 50.0f));  // rising inside the band ⇒ stays OFF
  TEST_ASSERT_FALSE(env->status().fan);
}

void test_forged_reply_never_applied() {
  // The client returns BAD_SIGNATURE/BAD_PAYLOAD without filling the reply; even if a fake
  // filled it, the controller must not use it.
  struct Liar : FakeBackend {
    ApiResult environment(const EnvReading& r, EnvReply& out) override {
      sent.push_back(r);
      out = EnvReply{true, true};
      return ApiResult::BAD_SIGNATURE;
    }
  } liar;
  EnvController c(*hal, liar);
  hal->samples.push_back(ok(22.0f, 50.0f));
  c.tick(hal->now += 2000, true);
  TEST_ASSERT_FALSE(c.status().fan);
  TEST_ASSERT_FALSE(c.status().alarm);
  TEST_ASSERT_TRUE(c.status().fallback);
}

void test_offline_local_alarm_and_fan() {
  step(ok(33.0f, 50.0f), false);  // >= critical 32
  TEST_ASSERT_EQUAL(0, (int)be->sent.size());  // offline: no calls
  TEST_ASSERT_TRUE(env->status().fallback);
  TEST_ASSERT_TRUE(env->status().fan);
  TEST_ASSERT_TRUE(env->status().alarm);
  step(ok(24.0f, 10.0f), false);  // humidity below 20 %
  TEST_ASSERT_FALSE(env->status().fan);
  TEST_ASSERT_TRUE(env->status().alarm);
  step(ok(24.0f, 85.0f), false);  // above 80 %
  TEST_ASSERT_TRUE(env->status().alarm);
  step(ok(24.0f, 50.0f), false);
  TEST_ASSERT_FALSE(env->status().alarm);
}

void test_remote_decision_expires() {
  be->envReply = EnvReply{true, true};
  step(ok(24.0f, 50.0f));
  TEST_ASSERT_TRUE(env->status().alarm);
  // The backend stops answering only for the env endpoint... but sends keep failing silently:
  be->envResult = ApiResult::NETWORK_ERROR;
  for (int i = 0; i < 5; ++i) step(ok(24.0f, 50.0f));
  TEST_ASSERT_TRUE(env->status().fallback);
  TEST_ASSERT_FALSE(env->status().alarm);
  TEST_ASSERT_FALSE(env->status().fan);
}

void test_going_offline_drops_the_remote_decision() {
  be->envReply = EnvReply{true, true};
  step(ok(24.0f, 50.0f));
  TEST_ASSERT_TRUE(env->status().fan);
  step(ok(24.0f, 50.0f), false);
  TEST_ASSERT_TRUE(env->status().fallback);
  TEST_ASSERT_FALSE(env->status().fan);
}

void test_thresholds_follow_config_and_reject_inconsistent() {
  be->envResult = ApiResult::NETWORK_ERROR;
  EnvThresholds th;
  th.tempHighC = 22;
  th.tempCriticalC = 25;
  env->setThresholds(th);
  step(ok(23.0f, 50.0f));
  TEST_ASSERT_TRUE(env->status().fan);
  TEST_ASSERT_FALSE(env->status().alarm);
  step(ok(25.0f, 50.0f));
  TEST_ASSERT_TRUE(env->status().alarm);
  EnvThresholds broken = th;
  broken.tempHighC = 40;
  broken.tempCriticalC = 30;  // critical below high: ignored
  env->setThresholds(broken);
  TEST_ASSERT_EQUAL_FLOAT(22, env->status().thresholds.tempHighC);
}

void test_environment_never_touches_the_door() {
  be->envReply = EnvReply{true, true};
  for (int i = 0; i < 20; ++i) step(i % 2 ? ok(45, 95) : bad());
  TEST_ASSERT_EQUAL(0, hal->opens);
  TEST_ASSERT_EQUAL(int(DoorState::CLOSED), int(hal->door.state()));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_nothing_sent_before_first_read);
  RUN_TEST(test_sends_every_10_s_with_last_valid_reading);
  RUN_TEST(test_mayCall_false_defers_the_send);
  RUN_TEST(test_three_failures_in_a_row_is_error_and_fan_off);
  RUN_TEST(test_failures_must_be_consecutive);
  RUN_TEST(test_implausible_values_count_as_failures);
  RUN_TEST(test_no_samples_at_all_is_error);
  RUN_TEST(test_signed_reply_is_applied);
  RUN_TEST(test_when_in_doubt_cool_backend_cannot_switch_off_a_needed_fan);
  RUN_TEST(test_bad_signature_falls_back_to_local_hysteresis);
  RUN_TEST(test_forged_reply_never_applied);
  RUN_TEST(test_offline_local_alarm_and_fan);
  RUN_TEST(test_remote_decision_expires);
  RUN_TEST(test_going_offline_drops_the_remote_decision);
  RUN_TEST(test_thresholds_follow_config_and_reject_inconsistent);
  RUN_TEST(test_environment_never_touches_the_door);
  return UNITY_END();
}
