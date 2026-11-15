// Door state machine: CLOSED → OPENING → OPEN → CLOSING → CLOSED, emergency close.
#include <unity.h>

#include "door.h"

namespace dcg {
struct TestGrantFactory {
  static OpenGrant make(const std::string& sid, uint32_t ms) { return OpenGrant(sid, ms); }
};
}  // namespace dcg

using namespace dcg;

static const std::string kSid = "b6e1c0ffee00112233445566778899aa";

void setUp() {}
void tearDown() {}

static void run(DoorController& d, uint32_t from, uint32_t to) {
  for (uint32_t t = from; t <= to; t += 10) d.tick(t);
}

void test_full_cycle_and_events() {
  DoorController d;  // 0°..90°, travel 600 ms
  TEST_ASSERT_EQUAL(int(DoorState::CLOSED), int(d.state()));
  TEST_ASSERT_EQUAL(0, d.angle());
  TEST_ASSERT_TRUE(d.open(TestGrantFactory::make(kSid, 3000), 0));
  TEST_ASSERT_EQUAL(int(DoorState::OPENING), int(d.state()));
  run(d, 0, 300);
  TEST_ASSERT_INT_WITHIN(3, 45, d.angle());  // linear sweep
  run(d, 300, 600);
  TEST_ASSERT_EQUAL(int(DoorState::OPEN), int(d.state()));
  TEST_ASSERT_EQUAL(90, d.angle());
  DoorEvent e = d.takeEvent();
  TEST_ASSERT_EQUAL(int(DoorEvent::Type::OPENED), int(e.type));
  TEST_ASSERT_EQUAL_STRING(kSid.c_str(), e.sessionId.c_str());
  TEST_ASSERT_EQUAL(3000, e.holdMs);

  run(d, 600, 3590);
  TEST_ASSERT_EQUAL(int(DoorState::OPEN), int(d.state()));  // hold time not over yet
  run(d, 3600, 3610);
  TEST_ASSERT_EQUAL(int(DoorState::CLOSING), int(d.state()));
  run(d, 3610, 4300);
  TEST_ASSERT_EQUAL(int(DoorState::CLOSED), int(d.state()));
  TEST_ASSERT_EQUAL(0, d.angle());
  e = d.takeEvent();
  TEST_ASSERT_EQUAL(int(DoorEvent::Type::CLOSED), int(e.type));
  TEST_ASSERT_EQUAL(int(CloseReason::TIMER), int(e.reason));
  TEST_ASSERT_EQUAL_STRING(kSid.c_str(), e.sessionId.c_str());
  TEST_ASSERT_EQUAL(int(DoorEvent::Type::NONE), int(d.takeEvent().type));
}

void test_rejects_invalid_grants() {
  DoorController d;
  TEST_ASSERT_FALSE(d.open(TestGrantFactory::make(kSid, 999), 0));
  TEST_ASSERT_FALSE(d.open(TestGrantFactory::make(kSid, 30001), 0));
  TEST_ASSERT_FALSE(d.open(TestGrantFactory::make("", 5000), 0));
  TEST_ASSERT_EQUAL(int(DoorState::CLOSED), int(d.state()));
}

void test_no_reopen_while_moving_or_open() {
  DoorController d;
  TEST_ASSERT_TRUE(d.open(TestGrantFactory::make(kSid, 5000), 0));
  TEST_ASSERT_FALSE(d.open(TestGrantFactory::make(kSid, 5000), 10));
  run(d, 0, 700);
  TEST_ASSERT_FALSE(d.open(TestGrantFactory::make(kSid, 30000), 700));  // cannot extend
}

void test_emergency_close_while_opening_reverses_from_current_angle() {
  DoorController d;
  d.open(TestGrantFactory::make(kSid, 5000), 0);
  run(d, 0, 300);
  int mid = d.angle();
  d.emergencyClose(300);
  TEST_ASSERT_EQUAL(int(DoorState::CLOSING), int(d.state()));
  d.tick(310);
  TEST_ASSERT_TRUE(d.angle() <= mid);  // no jump to 90°
  run(d, 310, 700);
  TEST_ASSERT_EQUAL(int(DoorState::CLOSED), int(d.state()));
  DoorEvent e = d.takeEvent();  // never reached OPEN ⇒ only CLOSED
  TEST_ASSERT_EQUAL(int(DoorEvent::Type::CLOSED), int(e.type));
  TEST_ASSERT_EQUAL(int(CloseReason::EMERGENCY), int(e.reason));
}

void test_emergency_close_while_open() {
  DoorController d;
  d.open(TestGrantFactory::make(kSid, 30000), 0);
  run(d, 0, 1000);
  d.takeEvent();
  d.emergencyClose(1000, CloseReason::LOCAL_BUTTON);
  run(d, 1000, 1700);
  TEST_ASSERT_EQUAL(int(DoorState::CLOSED), int(d.state()));
  TEST_ASSERT_EQUAL(int(CloseReason::LOCAL_BUTTON), int(d.takeEvent().reason));
}

void test_emergency_close_when_closed_is_noop() {
  DoorController d;
  d.emergencyClose(0);
  d.tick(10);
  TEST_ASSERT_EQUAL(int(DoorState::CLOSED), int(d.state()));
  TEST_ASSERT_EQUAL(int(DoorEvent::Type::NONE), int(d.takeEvent().type));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_full_cycle_and_events);
  RUN_TEST(test_rejects_invalid_grants);
  RUN_TEST(test_no_reopen_while_moving_or_open);
  RUN_TEST(test_emergency_close_while_opening_reverses_from_current_angle);
  RUN_TEST(test_emergency_close_while_open);
  RUN_TEST(test_emergency_close_when_closed_is_noop);
  return UNITY_END();
}
