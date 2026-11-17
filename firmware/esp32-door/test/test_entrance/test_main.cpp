// EntrancePoller (main entrance QR signal): 1 s polling, GRANTED/DENIED shown once, ack,
// fail-closed on unsigned / forged / malformed replies, and NEVER the room servo.
#include <unity.h>

#include <deque>

#include "entrance.h"

using namespace dcg;

static const std::string kId = "0123456789abcdef0123456789abcdef";
static const std::string kId2 = "fedcba9876543210fedcba9876543210";

struct Shown {
  bool granted;
  uint32_t ledMs;
  std::string name;
};

struct FakeHal : DeviceHal {
  uint32_t now = 1000;
  DoorController door;
  int opens = 0, closes = 0;
  std::vector<Shown> shown;

  uint32_t millis() override { return now; }
  bool networkUp() override { return true; }
  int rssi() override { return -60; }
  uint32_t freeHeap() override { return 100000; }
  SensorSnapshot sensor() override { return {}; }
  void setPresenceThreshold(float) override {}
  bool readCard(std::string&) override { return false; }
  bool rfidOk() override { return true; }
  bool openDoor(const OpenGrant& g) override { ++opens; return door.open(g, now); }
  void closeDoor(CloseReason r) override { ++closes; door.emergencyClose(now, r); }
  DoorState doorState() override { return door.state(); }
  DoorEvent takeDoorEvent() override { return door.takeEvent(); }
  void feedback(Feedback, const std::string&) override {}
  void log(const std::string&) override {}
  void onEntranceSignal(bool granted, uint32_t ledMs, const std::string& name) override {
    shown.push_back({granted, ledMs, name});
  }
};

struct FakeBackend : Backend {
  std::deque<std::pair<ApiResult, EntrancePollReply>> polls;  // empty ⇒ {signal:null}
  int pollCount = 0;
  std::vector<std::string> acks;
  ApiResult ackResult = ApiResult::OK;

  ApiResult heartbeat(const HeartbeatInfo&, const DeviceConfig&, HeartbeatReply&) override { return ApiResult::OK; }
  ApiResult presence(bool, float, float, PresenceReply&) override { return ApiResult::OK; }
  ApiResult startAccess(const std::string&, float, const std::string&, StartReply&) override { return ApiResult::NETWORK_ERROR; }
  ApiResult pollAccess(const std::string&, float, DecisionReply&) override { return ApiResult::NETWORK_ERROR; }
  ApiResult confirmOpened(const std::string&, uint32_t) override { return ApiResult::OK; }
  ApiResult confirmClosed(const std::string&, const char*) override { return ApiResult::OK; }
  ApiResult event(const char*, const std::string&) override { return ApiResult::OK; }
  ApiResult exitButton(StartReply&) override { return ApiResult::NETWORK_ERROR; }
  ApiResult entrancePoll(EntrancePollReply& out) override {
    ++pollCount;
    if (polls.empty()) { out = EntrancePollReply{}; return ApiResult::OK; }
    auto p = polls.front();
    polls.pop_front();
    if (p.first == ApiResult::OK) out = p.second;
    return p.first;
  }
  ApiResult entranceAck(const std::string& id) override {
    acks.push_back(id);
    return ackResult;
  }
};

static FakeHal* hal;
static FakeBackend* be;
static EntrancePoller* poller;

void setUp() {
  hal = new FakeHal();
  be = new FakeBackend();
  poller = new EntrancePoller(*hal, *be);
}
void tearDown() {
  delete poller;
  delete be;
  delete hal;
}

static EntrancePollReply signal(const std::string& id, EntranceResult r, uint32_t ledMs = 5000,
                                const std::string& name = "Ana Lopez") {
  EntrancePollReply p;
  p.hasSignal = true;
  p.signal.id = id;
  p.signal.result = r;
  p.signal.ledMs = ledMs;
  p.signal.displayName = name;
  return p;
}

static bool tickAfter(uint32_t ms, bool online = true) {
  hal->now += ms;
  return poller->tick(hal->now, online);
}

void test_polls_every_second() {
  TEST_ASSERT_TRUE(poller->tick(hal->now, true));
  TEST_ASSERT_EQUAL(1, be->pollCount);
  TEST_ASSERT_FALSE(tickAfter(500));
  TEST_ASSERT_EQUAL(1, be->pollCount);
  TEST_ASSERT_TRUE(tickAfter(500));
  TEST_ASSERT_EQUAL(2, be->pollCount);
  for (int i = 0; i < 10; ++i) tickAfter(1000);
  TEST_ASSERT_EQUAL(12, be->pollCount);
  TEST_ASSERT_EQUAL(0, (int)hal->shown.size());
}

void test_offline_does_nothing() {
  TEST_ASSERT_FALSE(poller->tick(hal->now, false));
  TEST_ASSERT_FALSE(tickAfter(1000, false));
  TEST_ASSERT_EQUAL(0, be->pollCount);
}

void test_granted_lights_entrance_led_then_acks() {
  be->polls.push_back({ApiResult::OK, signal(kId, EntranceResult::GRANTED, 4000)});
  poller->tick(hal->now, true);
  TEST_ASSERT_EQUAL(1, (int)hal->shown.size());
  TEST_ASSERT_TRUE(hal->shown[0].granted);
  TEST_ASSERT_EQUAL_UINT32(4000, hal->shown[0].ledMs);
  TEST_ASSERT_EQUAL_STRING("Ana Lopez", hal->shown[0].name.c_str());
  TEST_ASSERT_EQUAL(0, (int)be->acks.size());
  TEST_ASSERT_TRUE(tickAfter(1000));  // the ack goes in the next slot, alone
  TEST_ASSERT_EQUAL(1, (int)be->acks.size());
  TEST_ASSERT_EQUAL_STRING(kId.c_str(), be->acks[0].c_str());
  TEST_ASSERT_EQUAL(1, be->pollCount);
  tickAfter(1000);
  TEST_ASSERT_EQUAL(2, be->pollCount);
  TEST_ASSERT_EQUAL(0, hal->opens);  // the room servo is never involved
}

void test_denied_blinks_red_and_acks() {
  be->polls.push_back({ApiResult::OK, signal(kId, EntranceResult::DENIED, 0, "")});
  poller->tick(hal->now, true);
  TEST_ASSERT_EQUAL(1, (int)hal->shown.size());
  TEST_ASSERT_FALSE(hal->shown[0].granted);
  tickAfter(1000);
  TEST_ASSERT_EQUAL(1, (int)be->acks.size());
}

void test_unknown_result_ignored_not_acked() {
  be->polls.push_back({ApiResult::OK, signal(kId, EntranceResult::UNKNOWN)});
  poller->tick(hal->now, true);
  tickAfter(1000);
  TEST_ASSERT_EQUAL(0, (int)hal->shown.size());
  TEST_ASSERT_EQUAL(0, (int)be->acks.size());
}

void test_bad_signature_or_payload_ignored_entirely() {
  // BackendClient never fills the reply on these results; a hostile double does, to prove the
  // poller does not look at it.
  be->polls.push_back({ApiResult::BAD_SIGNATURE, {}});
  be->polls.push_back({ApiResult::BAD_PAYLOAD, {}});
  be->polls.push_back({ApiResult::HTTP_ERROR, {}});
  struct Liar : FakeBackend {
    ApiResult entrancePoll(EntrancePollReply& out) override {
      ++pollCount;
      out.hasSignal = true;
      out.signal.id = kId;
      out.signal.result = EntranceResult::GRANTED;
      return ApiResult::BAD_SIGNATURE;
    }
  } liar;
  EntrancePoller p2(*hal, liar);
  for (int i = 0; i < 5; ++i) {
    poller->tick(hal->now, true);
    p2.tick(hal->now, true);
    hal->now += 5000;
  }
  TEST_ASSERT_EQUAL(0, (int)hal->shown.size());
  TEST_ASSERT_EQUAL(0, (int)be->acks.size());
  TEST_ASSERT_EQUAL(0, (int)liar.acks.size());
  TEST_ASSERT_EQUAL(0, hal->opens);
}

void test_error_backs_off() {
  be->polls.push_back({ApiResult::NETWORK_ERROR, {}});
  poller->tick(hal->now, true);
  TEST_ASSERT_FALSE(tickAfter(1000));
  TEST_ASSERT_FALSE(tickAfter(3000));
  TEST_ASSERT_TRUE(tickAfter(1000));  // 5 s after the failure
  TEST_ASSERT_EQUAL(2, be->pollCount);
}

void test_same_signal_never_shown_twice() {
  be->polls.push_back({ApiResult::OK, signal(kId, EntranceResult::GRANTED)});
  be->polls.push_back({ApiResult::OK, signal(kId, EntranceResult::GRANTED)});
  be->polls.push_back({ApiResult::OK, signal(kId2, EntranceResult::DENIED)});
  poller->tick(hal->now, true);  // poll → shown
  tickAfter(1000);               // ack
  tickAfter(1000);               // poll → same id again: ignored
  tickAfter(1000);               // poll → new id
  TEST_ASSERT_EQUAL(2, (int)hal->shown.size());
  TEST_ASSERT_TRUE(hal->shown[0].granted);
  TEST_ASSERT_FALSE(hal->shown[1].granted);
  TEST_ASSERT_EQUAL(2u, poller->shown());
}

void test_ack_retried_then_given_up() {
  be->ackResult = ApiResult::NETWORK_ERROR;
  be->polls.push_back({ApiResult::OK, signal(kId, EntranceResult::GRANTED)});
  poller->tick(hal->now, true);
  tickAfter(1000);
  tickAfter(1000);
  tickAfter(1000);
  TEST_ASSERT_EQUAL(3, (int)be->acks.size());
  tickAfter(1000);  // gave up: back to polling
  TEST_ASSERT_EQUAL(3, (int)be->acks.size());
  TEST_ASSERT_EQUAL(2, be->pollCount);
  TEST_ASSERT_EQUAL(1, (int)hal->shown.size());  // showing is never repeated
}

void test_entrance_never_moves_the_servo() {
  for (int i = 0; i < 20; ++i) {
    std::string id = kId;
    id[31] = "0123456789abcdef"[i % 16];
    id[30] = "0123456789abcdef"[i / 16];
    be->polls.push_back({ApiResult::OK, signal(id, i % 2 ? EntranceResult::DENIED : EntranceResult::GRANTED, 10000)});
  }
  for (int i = 0; i < 60; ++i) tickAfter(1000);
  TEST_ASSERT_EQUAL(20, (int)hal->shown.size());
  TEST_ASSERT_EQUAL(0, hal->opens);
  TEST_ASSERT_EQUAL(0, hal->closes);
  TEST_ASSERT_EQUAL(int(DoorState::CLOSED), int(hal->door.state()));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_polls_every_second);
  RUN_TEST(test_offline_does_nothing);
  RUN_TEST(test_granted_lights_entrance_led_then_acks);
  RUN_TEST(test_denied_blinks_red_and_acks);
  RUN_TEST(test_unknown_result_ignored_not_acked);
  RUN_TEST(test_bad_signature_or_payload_ignored_entirely);
  RUN_TEST(test_error_backs_off);
  RUN_TEST(test_same_signal_never_shown_twice);
  RUN_TEST(test_ack_retried_then_given_up);
  RUN_TEST(test_entrance_never_moves_the_servo);
  return UNITY_END();
}
