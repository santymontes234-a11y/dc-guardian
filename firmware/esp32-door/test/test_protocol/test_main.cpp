// JSON payload validation: whitelists and range checks for untrusted backend data.
#include <unity.h>

#include <cstring>

#include "protocol.h"

using namespace dcg;

static const std::string kSid = "b6e1c0ffee00112233445566778899aa";

void setUp() {}
void tearDown() {}

void test_ids_and_uid() {
  TEST_ASSERT_TRUE(isValidSessionId(kSid));
  TEST_ASSERT_FALSE(isValidSessionId("B6E1C0FFEE00112233445566778899AA"));
  TEST_ASSERT_FALSE(isValidSessionId("../../admin/xxxxxxxxxxxxxxxxxxxx"));
  TEST_ASSERT_FALSE(isValidSessionId(kSid + "0"));
  uint8_t raw[] = {0x04, 0xa1, 0xb2, 0xc3};
  TEST_ASSERT_EQUAL_STRING("04A1B2C3", uidToHex(raw, 4).c_str());
  TEST_ASSERT_TRUE(isValidUid("04A1B2C3"));
  TEST_ASSERT_FALSE(isValidUid("04a1b2c3"));
  TEST_ASSERT_FALSE(isValidUid("04A1B2C"));
  TEST_ASSERT_FALSE(isValidUid(""));
}

void test_distance_format() {
  TEST_ASSERT_EQUAL_STRING("30.1", formatDistance(30.12f).c_str());
  TEST_ASSERT_EQUAL_STRING("-1", formatDistance(-1).c_str());
  TEST_ASSERT_EQUAL_STRING("-1", formatDistance(999).c_str());
}

void test_bodies() {
  TEST_ASSERT_EQUAL_STRING(R"({"uid":"04A1B2C3","distance_cm":32.5,"fw":"1.0.0"})",
                           buildStartBody("04A1B2C3", 32.5f, "1.0.0").c_str());
  TEST_ASSERT_EQUAL_STRING(R"({"present":true,"distance_cm":-1,"threshold_cm":50})",
                           buildPresenceBody(true, -1, 50).c_str());
  HeartbeatInfo hb;
  hb.fw = "1.0.0"; hb.state = "IDLE"; hb.door = "CLOSED"; hb.distanceCm = 120.04f;
  hb.ultrasonicOk = false;
  std::string body = buildHeartbeatBody(hb);
  TEST_ASSERT_NOT_NULL(strstr(body.c_str(), R"("session_id":null)"));
  TEST_ASSERT_NOT_NULL(strstr(body.c_str(), R"("distance_cm":120)"));
  TEST_ASSERT_NOT_NULL(strstr(body.c_str(), R"("ultrasonic":"TIMEOUT")"));
}

void test_heartbeat_config_validated() {
  DeviceConfig cur;
  HeartbeatReply r;
  TEST_ASSERT_TRUE(parseHeartbeatReply(
      R"({"server_time":1763130000,"config":{"presence_threshold_cm":80,"door_open_ms":7000,"heartbeat_s":10},"command":null})",
      cur, r));
  TEST_ASSERT_TRUE(r.hasConfig);
  TEST_ASSERT_EQUAL_FLOAT(80, r.config.presenceThresholdCm);
  TEST_ASSERT_EQUAL(7000, r.config.doorOpenMs);
  TEST_ASSERT_EQUAL(10, r.config.heartbeatS);
  TEST_ASSERT_EQUAL(int(Command::NONE), int(r.command));

  // Out-of-range values keep the current ones.
  TEST_ASSERT_TRUE(parseHeartbeatReply(
      R"({"config":{"presence_threshold_cm":0,"door_open_ms":600000,"heartbeat_s":1}})", cur, r));
  TEST_ASSERT_EQUAL_FLOAT(50, r.config.presenceThresholdCm);
  TEST_ASSERT_EQUAL(5000, r.config.doorOpenMs);
  TEST_ASSERT_EQUAL(15, r.config.heartbeatS);
  // Wrong types are ignored too.
  TEST_ASSERT_TRUE(parseHeartbeatReply(R"({"config":{"presence_threshold_cm":"10"}})", cur, r));
  TEST_ASSERT_EQUAL_FLOAT(50, r.config.presenceThresholdCm);
}

void test_heartbeat_commands_whitelisted() {
  DeviceConfig cur;
  HeartbeatReply r;
  TEST_ASSERT_TRUE(parseHeartbeatReply(R"({"command":"EMERGENCY_CLOSE"})", cur, r));
  TEST_ASSERT_EQUAL(int(Command::EMERGENCY_CLOSE), int(r.command));
  for (const char* bad : {R"({"command":"OPEN"})", R"({"command":"open_door"})",
                          R"({"command":{"type":"OPEN"}})", R"({"command":"REBOOT"})"}) {
    TEST_ASSERT_TRUE(parseHeartbeatReply(bad, cur, r));
    TEST_ASSERT_EQUAL(int(Command::NONE), int(r.command));
    TEST_ASSERT_TRUE(r.unknownCommand);
  }
  TEST_ASSERT_FALSE(parseHeartbeatReply("not json", cur, r));
  TEST_ASSERT_FALSE(parseHeartbeatReply("[1,2]", cur, r));
}

void test_start_reply() {
  StartReply r;
  TEST_ASSERT_TRUE(parseStartReply(
      R"({"session_id":"b6e1c0ffee00112233445566778899aa","state":"AWAITING_FACE","poll_ms":50,"timeout_s":999})", r));
  TEST_ASSERT_EQUAL_STRING(kSid.c_str(), r.sessionId.c_str());
  TEST_ASSERT_EQUAL(300, r.pollMs);    // clamped
  TEST_ASSERT_EQUAL(60, r.timeoutS);   // clamped
  TEST_ASSERT_TRUE(parseStartReply(R"({"state":"DENIED","reason_code":"UNKNOWN_CARD"})", r));
  TEST_ASSERT_TRUE(r.sessionId.empty());
  TEST_ASSERT_EQUAL_STRING("UNKNOWN_CARD", r.reasonCode.c_str());
  TEST_ASSERT_FALSE(parseStartReply(R"({"session_id":"x","state":"AWAITING_FACE"})", r));
  // A fresh session can never be GRANTED: reject.
  TEST_ASSERT_FALSE(parseStartReply(
      R"({"session_id":"b6e1c0ffee00112233445566778899aa","state":"GRANTED","open_ms":5000})", r));
}

void test_decision_reply() {
  DecisionReply d;
  TEST_ASSERT_TRUE(parseDecisionReply(
      R"({"session_id":"b6e1c0ffee00112233445566778899aa","state":"GRANTED","open_ms":5000})", d));
  TEST_ASSERT_EQUAL(5000, d.openMs);
  // GRANTED without open_ms or out of range ⇒ malformed (door stays closed).
  TEST_ASSERT_FALSE(parseDecisionReply(
      R"({"session_id":"b6e1c0ffee00112233445566778899aa","state":"GRANTED"})", d));
  TEST_ASSERT_FALSE(parseDecisionReply(
      R"({"session_id":"b6e1c0ffee00112233445566778899aa","state":"GRANTED","open_ms":60000})", d));
  TEST_ASSERT_FALSE(parseDecisionReply(
      R"({"session_id":"b6e1c0ffee00112233445566778899aa","state":"GRANTED","open_ms":"5000"})", d));
  TEST_ASSERT_FALSE(parseDecisionReply(R"({"state":"GRANTED","open_ms":5000})", d));
  TEST_ASSERT_TRUE(parseDecisionReply(
      R"({"session_id":"b6e1c0ffee00112233445566778899aa","state":"DENIED","reason_code":"FACE_MISMATCH"})", d));
  TEST_ASSERT_EQUAL_STRING("FACE_MISMATCH", d.reasonCode.c_str());
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_ids_and_uid);
  RUN_TEST(test_distance_format);
  RUN_TEST(test_bodies);
  RUN_TEST(test_heartbeat_config_validated);
  RUN_TEST(test_heartbeat_commands_whitelisted);
  RUN_TEST(test_start_reply);
  RUN_TEST(test_decision_reply);
  return UNITY_END();
}
