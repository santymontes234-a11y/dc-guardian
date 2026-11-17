// JSON payload validation: whitelists and range checks for untrusted backend data.
#include <unity.h>

#include <cmath>
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
  TEST_ASSERT_NOT_NULL(strstr(body.c_str(), R"("dht":"OK")"));
  hb.dhtOk = false;
  TEST_ASSERT_NOT_NULL(strstr(buildHeartbeatBody(hb).c_str(), R"("dht":"ERROR")"));
}

// ------------------------------------------------------------------ DHT11 (§11)
void test_environment_body() {
  EnvReading r;
  r.sensorOk = true;
  r.temperatureC = 24.46f;
  r.humidityPct = 51.04f;
  TEST_ASSERT_EQUAL_STRING(R"({"temperature_c":24.5,"humidity_pct":51,"sensor":"OK"})",
                           buildEnvironmentBody(r).c_str());
  r.sensorOk = false;
  TEST_ASSERT_EQUAL_STRING(R"({"temperature_c":null,"humidity_pct":null,"sensor":"ERROR"})",
                           buildEnvironmentBody(r).c_str());
  r.sensorOk = true;
  r.temperatureC = NAN;  // never send NaN as "OK"
  TEST_ASSERT_EQUAL_STRING(R"({"temperature_c":null,"humidity_pct":null,"sensor":"ERROR"})",
                           buildEnvironmentBody(r).c_str());
}

void test_env_reply_requires_both_booleans() {
  EnvReply e;
  TEST_ASSERT_TRUE(parseEnvReply(R"({"ok":true,"fan":true,"alarm":false})", e));
  TEST_ASSERT_TRUE(e.fan);
  TEST_ASSERT_FALSE(e.alarm);
  TEST_ASSERT_FALSE(parseEnvReply(R"({"ok":true,"fan":true})", e));
  TEST_ASSERT_FALSE(parseEnvReply(R"({"ok":true,"fan":"yes","alarm":false})", e));
  TEST_ASSERT_FALSE(parseEnvReply(R"({"ok":true,"fan":1,"alarm":0})", e));
  TEST_ASSERT_FALSE(parseEnvReply("not json", e));
}

void test_env_thresholds_from_heartbeat() {
  DeviceConfig cur;
  HeartbeatReply r;
  // Defaults
  TEST_ASSERT_EQUAL_FLOAT(27, cur.env.tempHighC);
  TEST_ASSERT_EQUAL_FLOAT(32, cur.env.tempCriticalC);
  TEST_ASSERT_EQUAL_FLOAT(20, cur.env.humidityLowPct);
  TEST_ASSERT_EQUAL_FLOAT(80, cur.env.humidityHighPct);
  // Valid values are applied
  TEST_ASSERT_TRUE(parseHeartbeatReply(
      R"({"config":{"temp_high_c":25,"temp_critical_c":30.5,"humidity_low_pct":30,"humidity_high_pct":70}})",
      cur, r));
  TEST_ASSERT_EQUAL_FLOAT(25, r.config.env.tempHighC);
  TEST_ASSERT_EQUAL_FLOAT(30.5f, r.config.env.tempCriticalC);
  TEST_ASSERT_EQUAL_FLOAT(30, r.config.env.humidityLowPct);
  TEST_ASSERT_EQUAL_FLOAT(70, r.config.env.humidityHighPct);
  // Out of range ⇒ the whole pair keeps the previous values
  TEST_ASSERT_TRUE(parseHeartbeatReply(R"({"config":{"temp_high_c":10,"temp_critical_c":30}})", cur, r));
  TEST_ASSERT_EQUAL_FLOAT(27, r.config.env.tempHighC);
  TEST_ASSERT_EQUAL_FLOAT(32, r.config.env.tempCriticalC);
  TEST_ASSERT_TRUE(parseHeartbeatReply(R"({"config":{"temp_high_c":30,"temp_critical_c":51}})", cur, r));
  TEST_ASSERT_EQUAL_FLOAT(27, r.config.env.tempHighC);
  TEST_ASSERT_TRUE(parseHeartbeatReply(R"({"config":{"temp_high_c":46,"temp_critical_c":48}})", cur, r));
  TEST_ASSERT_EQUAL_FLOAT(27, r.config.env.tempHighC);
  // critical must be greater than high (also when only one of them arrives)
  TEST_ASSERT_TRUE(parseHeartbeatReply(R"({"config":{"temp_high_c":30,"temp_critical_c":30}})", cur, r));
  TEST_ASSERT_EQUAL_FLOAT(27, r.config.env.tempHighC);
  TEST_ASSERT_TRUE(parseHeartbeatReply(R"({"config":{"temp_high_c":33}})", cur, r));
  TEST_ASSERT_EQUAL_FLOAT(27, r.config.env.tempHighC);  // 33 >= current critical 32
  TEST_ASSERT_TRUE(parseHeartbeatReply(R"({"config":{"temp_high_c":28}})", cur, r));
  TEST_ASSERT_EQUAL_FLOAT(28, r.config.env.tempHighC);
  // Humidity: 0..100 and high > low; wrong types ignored
  TEST_ASSERT_TRUE(parseHeartbeatReply(R"({"config":{"humidity_low_pct":-1,"humidity_high_pct":80}})", cur, r));
  TEST_ASSERT_EQUAL_FLOAT(20, r.config.env.humidityLowPct);
  TEST_ASSERT_TRUE(parseHeartbeatReply(R"({"config":{"humidity_low_pct":20,"humidity_high_pct":101}})", cur, r));
  TEST_ASSERT_EQUAL_FLOAT(80, r.config.env.humidityHighPct);
  TEST_ASSERT_TRUE(parseHeartbeatReply(R"({"config":{"humidity_low_pct":60,"humidity_high_pct":50}})", cur, r));
  TEST_ASSERT_EQUAL_FLOAT(20, r.config.env.humidityLowPct);
  TEST_ASSERT_TRUE(parseHeartbeatReply(R"({"config":{"humidity_low_pct":"10","humidity_high_pct":90}})", cur, r));
  TEST_ASSERT_EQUAL_FLOAT(20, r.config.env.humidityLowPct);
  TEST_ASSERT_EQUAL_FLOAT(90, r.config.env.humidityHighPct);
  TEST_ASSERT_TRUE(validTempPair(15, 50));
  TEST_ASSERT_FALSE(validTempPair(14.9f, 30));
  TEST_ASSERT_TRUE(validHumidityPair(0, 100));
  TEST_ASSERT_FALSE(validHumidityPair(50, 50));
}

// ------------------------------------------------------------------ entrance signal (§10)
static const std::string kSig = "0123456789abcdef0123456789abcdef";

void test_entrance_poll_reply_empty() {
  EntrancePollReply r;
  TEST_ASSERT_TRUE(parseEntrancePollReply(R"({"signal":null})", r));
  TEST_ASSERT_FALSE(r.hasSignal);
  TEST_ASSERT_TRUE(parseEntrancePollReply(R"({})", r));
  TEST_ASSERT_FALSE(r.hasSignal);
  TEST_ASSERT_FALSE(parseEntrancePollReply(R"({"signal":"GRANTED"})", r));
  TEST_ASSERT_FALSE(parseEntrancePollReply("[]", r));
  TEST_ASSERT_EQUAL_STRING("{}", buildEntrancePollBody().c_str());
  TEST_ASSERT_EQUAL_STRING(R"({"shown":true})", buildEntranceAckBody().c_str());
}

void test_entrance_poll_reply_granted_and_denied() {
  EntrancePollReply r;
  TEST_ASSERT_TRUE(parseEntrancePollReply(
      R"({"signal":{"id":")" + kSig + R"(","result":"GRANTED","led_ms":4000,"display_name":"Ana Lopez"}})", r));
  TEST_ASSERT_TRUE(r.hasSignal);
  TEST_ASSERT_EQUAL(int(EntranceResult::GRANTED), int(r.signal.result));
  TEST_ASSERT_EQUAL_UINT32(4000, r.signal.ledMs);
  TEST_ASSERT_EQUAL_STRING("Ana Lopez", r.signal.displayName.c_str());
  TEST_ASSERT_TRUE(parseEntrancePollReply(
      R"({"signal":{"id":")" + kSig + R"(","result":"DENIED","led_ms":null,"display_name":null}})", r));
  TEST_ASSERT_EQUAL(int(EntranceResult::DENIED), int(r.signal.result));
  // Missing led_ms on GRANTED: the contract default (5000)
  TEST_ASSERT_TRUE(parseEntrancePollReply(R"({"signal":{"id":")" + kSig + R"(","result":"GRANTED"}})", r));
  TEST_ASSERT_EQUAL_UINT32(5000, r.signal.ledMs);
  // Unknown result: parsed (to be logged and ignored), never GRANTED
  TEST_ASSERT_TRUE(parseEntrancePollReply(R"({"signal":{"id":")" + kSig + R"(","result":"OPEN"}})", r));
  TEST_ASSERT_EQUAL(int(EntranceResult::UNKNOWN), int(r.signal.result));
  TEST_ASSERT_TRUE(parseEntrancePollReply(R"({"signal":{"id":")" + kSig + R"(","result":"granted"}})", r));
  TEST_ASSERT_EQUAL(int(EntranceResult::UNKNOWN), int(r.signal.result));
}

void test_entrance_poll_reply_rejects_bad_fields() {
  EntrancePollReply r;
  // id: exactly 32 lowercase hex chars (it goes into the ack URL)
  TEST_ASSERT_FALSE(parseEntrancePollReply(R"({"signal":{"id":"../../device/heartbeat0000000000","result":"GRANTED","led_ms":5000}})", r));
  TEST_ASSERT_FALSE(parseEntrancePollReply(R"({"signal":{"id":"0123456789ABCDEF0123456789ABCDEF","result":"GRANTED","led_ms":5000}})", r));
  TEST_ASSERT_FALSE(parseEntrancePollReply(R"({"signal":{"id":")" + kSig + R"(0","result":"GRANTED","led_ms":5000}})", r));
  TEST_ASSERT_FALSE(parseEntrancePollReply(R"({"signal":{"result":"GRANTED","led_ms":5000}})", r));
  // led_ms: integer in 1000..10000
  TEST_ASSERT_FALSE(parseEntrancePollReply(R"({"signal":{"id":")" + kSig + R"(","result":"GRANTED","led_ms":999}})", r));
  TEST_ASSERT_FALSE(parseEntrancePollReply(R"({"signal":{"id":")" + kSig + R"(","result":"GRANTED","led_ms":10001}})", r));
  TEST_ASSERT_FALSE(parseEntrancePollReply(R"({"signal":{"id":")" + kSig + R"(","result":"GRANTED","led_ms":-5000}})", r));
  TEST_ASSERT_FALSE(parseEntrancePollReply(R"({"signal":{"id":")" + kSig + R"(","result":"GRANTED","led_ms":"5000"}})", r));
  TEST_ASSERT_FALSE(parseEntrancePollReply(R"({"signal":{"id":")" + kSig + R"(","result":"GRANTED","led_ms":5000.5}})", r));
  TEST_ASSERT_TRUE(parseEntrancePollReply(R"({"signal":{"id":")" + kSig + R"(","result":"GRANTED","led_ms":1000}})", r));
  TEST_ASSERT_TRUE(parseEntrancePollReply(R"({"signal":{"id":")" + kSig + R"(","result":"GRANTED","led_ms":10000}})", r));
}

void test_entrance_display_name_is_untrusted() {
  EntrancePollReply r;
  const std::string evil = "\u001b[2JJos\u00e9\nNu\u00f1ez " + std::string(60, 'X');
  TEST_ASSERT_TRUE(parseEntrancePollReply(
      R"({"signal":{"id":")" + kSig + R"(","result":"GRANTED","led_ms":5000,"display_name":")" + evil + R"("}})", r));
  TEST_ASSERT_TRUE(r.signal.displayName.size() <= 40);
  for (char c : r.signal.displayName) TEST_ASSERT_TRUE(c >= 0x20 && c < 0x7F);
  TEST_ASSERT_EQUAL_STRING("[2JJosNuez XXXXXXXXXXXXXXXXXXXXXXXXXXXXX", r.signal.displayName.c_str());
  // A number instead of a string: just empty
  TEST_ASSERT_TRUE(parseEntrancePollReply(
      R"({"signal":{"id":")" + kSig + R"(","result":"GRANTED","led_ms":5000,"display_name":42}})", r));
  TEST_ASSERT_EQUAL_STRING("", r.signal.displayName.c_str());
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

void test_decision_reply_lcd_text_is_sanitized() {
  DecisionReply d;
  TEST_ASSERT_TRUE(parseDecisionReply(
      "{\"session_id\":\"b6e1c0ffee00112233445566778899aa\",\"state\":\"GRANTED\",\"open_ms\":5000,"
      "\"greeting\":\"Bienvenido\",\"display_name\":\"Jos\u00e9\\n\\u0007Ana\"}", d));
  TEST_ASSERT_EQUAL_STRING("Bienvenido", d.greeting.c_str());
  TEST_ASSERT_EQUAL_STRING("JosAna", d.displayName.c_str());  // only printable ASCII survives
  TEST_ASSERT_EQUAL(size_t(40), sanitizeLcdText(std::string(80, 'x'), 40).size());
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
  RUN_TEST(test_decision_reply_lcd_text_is_sanitized);
  RUN_TEST(test_environment_body);
  RUN_TEST(test_env_reply_requires_both_booleans);
  RUN_TEST(test_env_thresholds_from_heartbeat);
  RUN_TEST(test_entrance_poll_reply_empty);
  RUN_TEST(test_entrance_poll_reply_granted_and_denied);
  RUN_TEST(test_entrance_poll_reply_rejects_bad_fields);
  RUN_TEST(test_entrance_display_name_is_untrusted);
  return UNITY_END();
}
