// AccessController (main state machine) with a fake HAL and a scripted backend.
// Each test pins one security invariant: no grant ⇒ no opening, errors ⇒ closed, etc.
#include <unity.h>

#include <deque>
#include <functional>

#include "access_controller.h"

using namespace dcg;

static const std::string kSid = "b6e1c0ffee00112233445566778899aa";
static const std::string kUid = "04A1B2C3";

// ------------------------------------------------------------------ fakes
struct FakeHal : DeviceHal {
  uint32_t now = 1000;
  bool wifi = true;
  SensorSnapshot sensorState{true, 30.0f, false};
  std::deque<std::string> cards;
  DoorController door;
  int opens = 0;
  float threshold = 50;
  std::vector<Feedback> feedbacks;

  uint32_t millis() override { return now; }
  bool networkUp() override { return wifi; }
  int rssi() override { return -60; }
  uint32_t freeHeap() override { return 100000; }
  SensorSnapshot sensor() override { return sensorState; }
  void setPresenceThreshold(float cm) override { threshold = cm; }
  bool readCard(std::string& uid) override {
    if (cards.empty()) return false;
    uid = cards.front();
    cards.pop_front();
    return true;
  }
  bool rfidOk() override { return true; }
  bool openDoor(const OpenGrant& g) override {
    bool ok = door.open(g, now);
    opens += ok ? 1 : 0;
    return ok;
  }
  void closeDoor(CloseReason r) override { door.emergencyClose(now, r); }
  DoorState doorState() override { return door.state(); }
  DoorEvent takeDoorEvent() override { return door.takeEvent(); }
  void feedback(Feedback f, const std::string&) override { feedbacks.push_back(f); }
  void log(const std::string&) override {}
};

struct FakeBackend : Backend {
  ApiResult hbResult = ApiResult::OK;
  HeartbeatReply hbReply;
  int heartbeats = 0;
  ApiResult startResult = ApiResult::OK;
  StartReply startReply;
  int starts = 0;
  std::string lastUid;
  // Scripted poll answers (front first); when empty, keeps answering AWAITING_FACE.
  std::deque<std::pair<ApiResult, DecisionReply>> polls;
  int pollCount = 0;
  std::vector<std::string> confirmations;
  std::vector<std::string> events;
  int presenceCalls = 0;

  FakeBackend() {
    startReply.sessionId = kSid;
    startReply.state = "AWAITING_FACE";
    startReply.pollMs = 500;
    startReply.timeoutS = 30;
  }

  ApiResult heartbeat(const HeartbeatInfo&, const DeviceConfig& cur, HeartbeatReply& out) override {
    ++heartbeats;
    out = hbReply;
    if (!out.hasConfig) out.config = cur;
    hbReply.command = Command::NONE;  // one-shot
    return hbResult;
  }
  ApiResult presence(bool, float, float) override { ++presenceCalls; return ApiResult::OK; }
  ApiResult startAccess(const std::string& uid, float, const std::string&, StartReply& out) override {
    ++starts;
    lastUid = uid;
    out = startReply;
    return startResult;
  }
  ApiResult pollAccess(const std::string&, float, DecisionReply& out) override {
    ++pollCount;
    if (polls.empty()) {
      out.sessionId = kSid;
      out.state = "AWAITING_FACE";
      return ApiResult::OK;
    }
    auto p = polls.front();
    polls.pop_front();
    out = p.second;
    return p.first;
  }
  ApiResult confirmOpened(const std::string& sid, uint32_t ms) override {
    confirmations.push_back("opened:" + sid + ":" + std::to_string(ms));
    return ApiResult::OK;
  }
  ApiResult confirmClosed(const std::string& sid, const char* reason) override {
    confirmations.push_back("closed:" + sid + ":" + reason);
    return ApiResult::OK;
  }
  ApiResult event(const char* type, const std::string&) override {
    events.push_back(type);
    return ApiResult::OK;
  }

  void grant(uint32_t ms = 3000, const std::string& sid = kSid) {
    DecisionReply d;
    d.sessionId = sid;
    d.state = "GRANTED";
    d.openMs = ms;
    polls.push_back({ApiResult::OK, d});
  }
};

static FakeHal* hal;
static FakeBackend* be;
static AccessController* ctl;

void setUp() {
  hal = new FakeHal();
  be = new FakeBackend();
  ctl = new AccessController(*hal, *be, "1.0.0-test");
}
void tearDown() {
  delete ctl;
  delete be;
  delete hal;
}

// Advances time in 20 ms steps, ticking the door like the I/O task does.
static void advance(uint32_t ms) {
  for (uint32_t i = 0; i < ms; i += 20) {
    hal->now += 20;
    hal->door.tick(hal->now);
    ctl->tick();
  }
}

static void boot() {
  ctl->tick();
  TEST_ASSERT_TRUE(ctl->online());
}

// ------------------------------------------------------------------ tests
void test_happy_path_opens_closes_and_confirms() {
  boot();
  TEST_ASSERT_EQUAL(int(SystemState::PRESENCE), int(ctl->state()));
  be->grant(3000);
  hal->cards.push_back(kUid);
  advance(40);
  TEST_ASSERT_EQUAL(1, be->starts);
  TEST_ASSERT_EQUAL_STRING(kUid.c_str(), be->lastUid.c_str());
  TEST_ASSERT_EQUAL(int(SystemState::WAITING_DECISION), int(ctl->state()));
  advance(600);
  TEST_ASSERT_EQUAL(1, hal->opens);
  TEST_ASSERT_EQUAL(int(SystemState::DOOR_OPEN), int(ctl->state()));
  advance(5000);  // 600 ms opening + 3000 ms hold + 600 ms closing
  TEST_ASSERT_EQUAL(int(DoorState::CLOSED), int(hal->door.state()));
  TEST_ASSERT_EQUAL(int(SystemState::PRESENCE), int(ctl->state()));
  TEST_ASSERT_EQUAL(2, int(be->confirmations.size()));
  TEST_ASSERT_EQUAL_STRING(("opened:" + kSid + ":3000").c_str(), be->confirmations[0].c_str());
  TEST_ASSERT_EQUAL_STRING(("closed:" + kSid + ":TIMER").c_str(), be->confirmations[1].c_str());
}

void test_card_alone_never_opens() {
  boot();
  hal->cards.push_back(kUid);
  advance(40000);  // backend never decides ⇒ local session deadline
  TEST_ASSERT_EQUAL(0, hal->opens);
  TEST_ASSERT_EQUAL(int(SystemState::PRESENCE), int(ctl->state()));
}

void test_denied_keeps_door_closed() {
  boot();
  DecisionReply d;
  d.sessionId = kSid;
  d.state = "DENIED";
  d.reasonCode = "FACE_MISMATCH";
  be->polls.push_back({ApiResult::OK, d});
  hal->cards.push_back(kUid);
  advance(1500);
  TEST_ASSERT_EQUAL(0, hal->opens);
  TEST_ASSERT_TRUE(ctl->sessionId().empty());
}

void test_immediate_denial_from_start() {
  boot();
  be->startReply = StartReply{};
  be->startReply.state = "DENIED";
  be->startReply.reasonCode = "UNKNOWN_CARD";
  hal->cards.push_back(kUid);
  advance(2000);
  TEST_ASSERT_EQUAL(0, be->pollCount);
  TEST_ASSERT_EQUAL(0, hal->opens);
}

void test_no_presence_card_not_sent() {
  hal->sensorState.present = false;
  boot();
  hal->cards.push_back(kUid);
  advance(100);
  TEST_ASSERT_EQUAL(0, be->starts);
}

void test_grant_for_other_session_rejected() {
  boot();
  be->grant(3000, "ffffffffffffffffffffffffffffffff");
  hal->cards.push_back(kUid);
  advance(1500);
  TEST_ASSERT_EQUAL(0, hal->opens);
  TEST_ASSERT_TRUE(ctl->sessionId().empty());
}

void test_grant_after_person_left_rejected() {
  boot();
  hal->cards.push_back(kUid);
  advance(100);
  hal->sensorState.present = false;
  be->grant();
  advance(1500);
  TEST_ASSERT_EQUAL(0, hal->opens);
}

void test_bad_signature_and_network_errors_abort_without_opening() {
  boot();
  DecisionReply none;
  for (int i = 0; i < 3; ++i) be->polls.push_back({ApiResult::BAD_SIGNATURE, none});
  be->grant();  // would arrive after the session is already aborted
  hal->cards.push_back(kUid);
  advance(3000);
  TEST_ASSERT_EQUAL(0, hal->opens);
  TEST_ASSERT_EQUAL(3, int(be->events.size()));
  TEST_ASSERT_EQUAL_STRING("BAD_RESPONSE_SIGNATURE", be->events[0].c_str());
}

void test_start_network_error() {
  boot();
  be->startResult = ApiResult::NETWORK_ERROR;
  hal->cards.push_back(kUid);
  advance(2000);
  TEST_ASSERT_EQUAL(0, be->pollCount);
  TEST_ASSERT_EQUAL(0, hal->opens);
}

void test_wifi_loss_while_waiting_aborts() {
  boot();
  hal->cards.push_back(kUid);
  advance(100);
  hal->wifi = false;
  be->grant();
  advance(1000);
  TEST_ASSERT_EQUAL(0, hal->opens);
  TEST_ASSERT_EQUAL(int(SystemState::OFFLINE), int(ctl->state()));
}

void test_offline_ignores_cards_and_closes_open_door() {
  boot();
  be->grant(30000);
  hal->cards.push_back(kUid);
  advance(1200);
  TEST_ASSERT_EQUAL(int(DoorState::OPEN), int(hal->door.state()));
  hal->wifi = false;  // disconnection while open ⇒ close at once
  advance(1000);
  TEST_ASSERT_EQUAL(int(DoorState::CLOSED), int(hal->door.state()));
  int startsBefore = be->starts;
  hal->cards.push_back("AABBCCDD");
  advance(500);
  TEST_ASSERT_EQUAL(startsBefore, be->starts);
  TEST_ASSERT_EQUAL(1, hal->opens);
}

void test_heartbeat_failures_go_offline_then_recover() {
  boot();
  be->hbResult = ApiResult::NETWORK_ERROR;
  advance(16000 * 3);
  TEST_ASSERT_FALSE(ctl->online());
  TEST_ASSERT_EQUAL(int(SystemState::OFFLINE), int(ctl->state()));
  be->hbResult = ApiResult::OK;
  advance(6000);
  TEST_ASSERT_TRUE(ctl->online());
  TEST_ASSERT_EQUAL(int(SystemState::PRESENCE), int(ctl->state()));
}

void test_clock_not_synced_is_offline() {
  be->hbResult = ApiResult::CLOCK_NOT_SYNCED;
  ctl->tick();
  TEST_ASSERT_FALSE(ctl->online());
  hal->cards.push_back(kUid);
  advance(100);
  TEST_ASSERT_EQUAL(0, be->starts);
}

void test_remote_config_applied() {
  be->hbReply.hasConfig = true;
  be->hbReply.config.presenceThresholdCm = 80;
  be->hbReply.config.doorOpenMs = 8000;
  boot();
  TEST_ASSERT_EQUAL_FLOAT(80, hal->threshold);
  TEST_ASSERT_EQUAL(8000, ctl->config().doorOpenMs);
}

void test_remote_emergency_close() {
  boot();
  be->grant(30000);
  hal->cards.push_back(kUid);
  advance(1500);
  TEST_ASSERT_EQUAL(int(DoorState::OPEN), int(hal->door.state()));
  be->hbReply.command = Command::EMERGENCY_CLOSE;
  advance(3000);  // fast heartbeat (2 s) while the door is open
  TEST_ASSERT_EQUAL(int(DoorState::CLOSED), int(hal->door.state()));
  TEST_ASSERT_EQUAL_STRING(("closed:" + kSid + ":EMERGENCY").c_str(),
                           be->confirmations.back().c_str());
}

void test_local_emergency_close() {
  boot();
  be->grant(30000);
  hal->cards.push_back(kUid);
  advance(1500);
  ctl->localEmergencyClose();
  advance(1000);
  TEST_ASSERT_EQUAL(int(DoorState::CLOSED), int(hal->door.state()));
  TEST_ASSERT_EQUAL_STRING(("closed:" + kSid + ":LOCAL_BUTTON").c_str(),
                           be->confirmations.back().c_str());
}

void test_card_debounce_and_no_restart_while_waiting() {
  boot();
  hal->cards.push_back(kUid);
  advance(100);
  hal->cards.push_back(kUid);
  hal->cards.push_back("AABBCCDD");
  advance(400);
  TEST_ASSERT_EQUAL(1, be->starts);  // new cards ignored while a session is in progress
}

void test_sensor_fault_is_error_state() {
  boot();
  hal->sensorState = SensorSnapshot{false, -1, true};
  advance(100);
  TEST_ASSERT_EQUAL(int(SystemState::ERROR), int(ctl->state()));
  hal->cards.push_back(kUid);
  advance(100);
  TEST_ASSERT_EQUAL(0, be->starts);
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_happy_path_opens_closes_and_confirms);
  RUN_TEST(test_card_alone_never_opens);
  RUN_TEST(test_denied_keeps_door_closed);
  RUN_TEST(test_immediate_denial_from_start);
  RUN_TEST(test_no_presence_card_not_sent);
  RUN_TEST(test_grant_for_other_session_rejected);
  RUN_TEST(test_grant_after_person_left_rejected);
  RUN_TEST(test_bad_signature_and_network_errors_abort_without_opening);
  RUN_TEST(test_start_network_error);
  RUN_TEST(test_wifi_loss_while_waiting_aborts);
  RUN_TEST(test_offline_ignores_cards_and_closes_open_door);
  RUN_TEST(test_heartbeat_failures_go_offline_then_recover);
  RUN_TEST(test_clock_not_synced_is_offline);
  RUN_TEST(test_remote_config_applied);
  RUN_TEST(test_remote_emergency_close);
  RUN_TEST(test_local_emergency_close);
  RUN_TEST(test_card_debounce_and_no_restart_while_waiting);
  RUN_TEST(test_sensor_fault_is_error_state);
  return UNITY_END();
}
