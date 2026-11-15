// LCD 2004 view: screen selection (state machine) and the exact text of each line.
#include <unity.h>

#include <cstring>
#include <string>

#include "lcd_view.h"

using namespace dcg;

void setUp() {}
void tearDown() {}

static LcdInput online(SystemState s, float cm = -1) {
  LcdInput in;
  in.state = s;
  in.wifiUp = true;
  in.sensor.distanceCm = cm;
  in.sensor.present = cm >= 0 && cm <= 50;
  return in;
}

static bool lineIs(const LcdView& v, int row, const char* text) {
  char want[21];
  std::memset(want, ' ', 20);
  want[20] = '\0';
  std::memcpy(want, text, std::strlen(text));
  return std::strcmp(v.line(row), want) == 0;
}

static void assertWellFormed(const LcdView& v) {
  for (int r = 0; r < 4; ++r) {
    TEST_ASSERT_EQUAL(20, (int)std::strlen(v.line(r)));
    for (int c = 0; c < 20; ++c) TEST_ASSERT_TRUE(v.line(r)[c] >= 0x20 && v.line(r)[c] < 0x7F);
  }
}

void test_idle_waits_for_card_and_shows_distance() {
  LcdView v;
  v.update(online(SystemState::IDLE, 123.4f), 1000);
  TEST_ASSERT_EQUAL(LcdScreen::WAIT_CARD, v.screen());
  TEST_ASSERT_TRUE(lineIs(v, 1, "Esperando tarjeta"));
  TEST_ASSERT_TRUE(lineIs(v, 3, "Dist: 123.4 cm"));
  v.update(online(SystemState::IDLE, -1), 1100);
  TEST_ASSERT_TRUE(lineIs(v, 3, "Dist: --- cm"));
}

void test_presence_screen_shows_distance_and_threshold() {
  LcdView v;
  LcdInput in = online(SystemState::PRESENCE, 34.5f);
  in.thresholdCm = 60;
  v.update(in, 1000);
  TEST_ASSERT_EQUAL(LcdScreen::PRESENCE, v.screen());
  TEST_ASSERT_TRUE(lineIs(v, 0, "PRESENCIA DETECTADA"));
  TEST_ASSERT_TRUE(lineIs(v, 2, "Umbral: 60 cm"));
  TEST_ASSERT_TRUE(lineIs(v, 3, "Dist: 34.5 cm"));
}

void test_no_wifi_is_disconnected_backend_down_is_connection_error() {
  LcdView v;
  LcdInput in = online(SystemState::OFFLINE);
  in.wifiUp = false;
  v.update(in, 1000);
  TEST_ASSERT_EQUAL(LcdScreen::DISCONNECTED, v.screen());
  TEST_ASSERT_TRUE(lineIs(v, 0, "SISTEMA DESCONECTADO"));
  v.update(online(SystemState::OFFLINE), 1100);
  TEST_ASSERT_EQUAL(LcdScreen::CONN_ERROR, v.screen());
  TEST_ASSERT_TRUE(lineIs(v, 0, "ERROR DE CONEXION"));
}

void test_boot_screen_before_first_tick() {
  LcdView v;
  LcdInput in;  // BOOT, no WiFi yet: not "disconnected"
  v.update(in, 0);
  TEST_ASSERT_EQUAL(LcdScreen::BOOT, v.screen());
}

void test_card_read_then_verifying_then_face() {
  LcdView v;
  v.onCard("04A1B2C3");
  v.update(online(SystemState::CARD_READ, 30), 1000);
  TEST_ASSERT_EQUAL(LcdScreen::RFID_READ, v.screen());
  TEST_ASSERT_TRUE(lineIs(v, 1, "UID 04A1B2C3"));

  v.onSessionPhase("CARD_READ");
  v.update(online(SystemState::WAITING_DECISION, 30), 1200);
  TEST_ASSERT_EQUAL(LcdScreen::VERIFYING, v.screen());
  TEST_ASSERT_TRUE(lineIs(v, 1, "AUTORIZACION"));

  v.onSessionPhase("AWAITING_FACE");
  v.update(online(SystemState::WAITING_DECISION, 30), 1400);
  TEST_ASSERT_EQUAL(LcdScreen::FACE, v.screen());
  TEST_ASSERT_TRUE(lineIs(v, 2, "Mire a la camara"));
}

void test_granted_open_closing_closed_cycle() {
  LcdView v;
  v.onFeedback(Feedback::GRANTED, "", 1000);
  LcdInput in = online(SystemState::DOOR_OPEN, 30);
  in.door = DoorState::OPENING;
  v.update(in, 1000);
  TEST_ASSERT_EQUAL(LcdScreen::GRANTED, v.screen());
  TEST_ASSERT_TRUE(lineIs(v, 0, "ACCESO AUTORIZADO"));

  in.door = DoorState::OPEN;
  v.update(in, 2600);  // grantedMs (1500) elapsed
  TEST_ASSERT_EQUAL(LcdScreen::DOOR_OPEN, v.screen());
  TEST_ASSERT_TRUE(lineIs(v, 0, "PUERTA ABIERTA"));

  in.state = SystemState::DOOR_CLOSING;
  in.door = DoorState::CLOSING;
  v.update(in, 7000);
  TEST_ASSERT_EQUAL(LcdScreen::DOOR_CLOSING, v.screen());

  v.update(online(SystemState::PRESENCE, 30), 7600);
  TEST_ASSERT_EQUAL(LcdScreen::DOOR_CLOSED, v.screen());
  TEST_ASSERT_TRUE(lineIs(v, 0, "PUERTA CERRADA"));

  v.update(online(SystemState::PRESENCE, 30), 9700);  // closedMs (2000) elapsed
  TEST_ASSERT_EQUAL(LcdScreen::PRESENCE, v.screen());
}

void test_denied_shows_reason_then_returns_to_resting_screen() {
  LcdView v;
  v.onFeedback(Feedback::DENIED, "NO_VALID_AUTH", 1000);
  v.update(online(SystemState::PRESENCE, 30), 1000);
  TEST_ASSERT_EQUAL(LcdScreen::DENIED, v.screen());
  TEST_ASSERT_TRUE(lineIs(v, 0, "ACCESO DENEGADO"));
  TEST_ASSERT_TRUE(lineIs(v, 1, "Sin autorizacion"));
  v.update(online(SystemState::PRESENCE, 30), 4100);
  TEST_ASSERT_EQUAL(LcdScreen::PRESENCE, v.screen());
}

void test_unknown_reason_is_shown_truncated() {
  LcdView v;
  v.onFeedback(Feedback::DENIED, "SOME_VERY_LONG_UNKNOWN_REASON", 0);
  v.update(online(SystemState::IDLE), 0);
  TEST_ASSERT_TRUE(lineIs(v, 1, "SOME_VERY_LONG_UNKNO"));
}

void test_network_error_during_attempt() {
  LcdView v;
  v.onFeedback(Feedback::ERROR, "NETWORK_ERROR", 1000);
  v.update(online(SystemState::IDLE), 1000);
  TEST_ASSERT_EQUAL(LcdScreen::ACCESS_ERROR, v.screen());
  TEST_ASSERT_TRUE(lineIs(v, 2, "Sin respuesta red"));
}

void test_persistent_feedback_does_not_flash() {
  LcdView v;
  v.onFeedback(Feedback::ERROR, "", 1000);   // setState(ERROR) sends no reason
  v.onFeedback(Feedback::READY, "", 1000);
  v.update(online(SystemState::IDLE), 1000);
  TEST_ASSERT_EQUAL(LcdScreen::WAIT_CARD, v.screen());
}

void test_new_card_clears_previous_outcome() {
  LcdView v;
  v.onFeedback(Feedback::DENIED, "TIMEOUT", 1000);
  v.onCard("0A0B");
  v.update(online(SystemState::CARD_READ, 30), 1100);
  TEST_ASSERT_EQUAL(LcdScreen::RFID_READ, v.screen());
  v.update(online(SystemState::PRESENCE, 30), 1200);  // attempt ended without outcome
  TEST_ASSERT_EQUAL(LcdScreen::PRESENCE, v.screen());
}

void test_sensor_error_screen() {
  LcdView v;
  LcdInput in = online(SystemState::ERROR);
  in.sensor.fault = true;
  in.rfidOk = true;
  v.update(in, 0);
  TEST_ASSERT_EQUAL(LcdScreen::SENSOR_ERROR, v.screen());
  TEST_ASSERT_TRUE(lineIs(v, 1, "RFID:    OK"));
  TEST_ASSERT_TRUE(lineIs(v, 2, "HC-SR04: FALLO"));
}

void test_config_error_wins() {
  LcdView v;
  v.setConfigError();
  v.update(online(SystemState::IDLE), 0);
  TEST_ASSERT_EQUAL(LcdScreen::CONFIG_ERROR, v.screen());
}

void test_every_screen_is_twenty_ascii_chars_per_line() {
  const char* codes[] = {"UNKNOWN_CARD", "CARD_NOT_ACTIVE", "CARD_LOCKED", "CARD_NOT_LINKED",
                         "ENGINEER_INACTIVE", "NO_VALID_AUTH", "REQUEST_PENDING", "AUTH_EXPIRED",
                         "AUTH_REVOKED", "AUTH_NOT_STARTED", "AUTH_REJECTED", "NO_FACE_ENROLLED",
                         "FACE_MISMATCH", "LIVENESS_FAILED", "FACE_NOT_DETECTED", "MULTIPLE_FACES",
                         "MODEL_MISMATCH", "BIOMETRIC_ERROR", "PRESENCE_LOST", "NO_PRESENCE",
                         "SENSOR_ERROR", "DEVICE_DISABLED", "TIMEOUT", "SESSION_SUPERSEDED",
                         "NETWORK_ERROR", "HTTP_ERROR", "BAD_SIGNATURE", "BAD_PAYLOAD",
                         "CLOCK_NOT_SYNCED", "SESSION_MISMATCH", "DOOR_BUSY", "OPEN_REJECTED",
                         "INTERRUPTED", "OFFLINE", "LOCAL_EMERGENCY", "EMERGENCY_CLOSE"};
  for (const char* c : codes) {
    const char* t = LcdView::reasonShort(c);
    TEST_ASSERT_NOT_NULL_MESSAGE(t, c);
    TEST_ASSERT_TRUE_MESSAGE(std::strlen(t) <= 20, c);
  }
  LcdView v;
  v.onCard("0102030405060708090A");  // longest valid UID (20 hex chars)
  const SystemState states[] = {SystemState::BOOT, SystemState::OFFLINE, SystemState::ERROR,
                                SystemState::IDLE, SystemState::PRESENCE, SystemState::CARD_READ,
                                SystemState::WAITING_DECISION, SystemState::DOOR_OPEN,
                                SystemState::DOOR_CLOSING};
  uint32_t t = 0;
  for (SystemState s : states) {
    v.update(online(s, 399.9f), t += 100);
    assertWellFormed(v);
  }
  v.onFeedback(Feedback::DENIED, "SESSION_SUPERSEDED", t);
  v.update(online(SystemState::IDLE), t);
  assertWellFormed(v);
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_idle_waits_for_card_and_shows_distance);
  RUN_TEST(test_presence_screen_shows_distance_and_threshold);
  RUN_TEST(test_no_wifi_is_disconnected_backend_down_is_connection_error);
  RUN_TEST(test_boot_screen_before_first_tick);
  RUN_TEST(test_card_read_then_verifying_then_face);
  RUN_TEST(test_granted_open_closing_closed_cycle);
  RUN_TEST(test_denied_shows_reason_then_returns_to_resting_screen);
  RUN_TEST(test_unknown_reason_is_shown_truncated);
  RUN_TEST(test_network_error_during_attempt);
  RUN_TEST(test_persistent_feedback_does_not_flash);
  RUN_TEST(test_new_card_clears_previous_outcome);
  RUN_TEST(test_sensor_error_screen);
  RUN_TEST(test_config_error_wins);
  RUN_TEST(test_every_screen_is_twenty_ascii_chars_per_line);
  return UNITY_END();
}
