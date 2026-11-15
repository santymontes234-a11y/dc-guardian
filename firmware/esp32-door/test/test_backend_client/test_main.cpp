// BackendClient end-to-end over a fake transport that behaves like the real gateway:
// it verifies the request HMAC and signs its response bound to the request nonce.
// Attack scenarios: forged / replayed / unsigned responses, wrong key, clock not synced.
#include <unity.h>

#include <map>

#include "backend_client.h"
#include "crypto.h"

using namespace dcg;

static const std::string kSecret =
    "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff";
static const std::string kSid = "b6e1c0ffee00112233445566778899aa";

struct FixedClock : Clock {
  bool ok = true;
  int64_t t = 1763130000;
  bool synced() const override { return ok; }
  int64_t epochSeconds() const override { return t; }
};

struct CounterRng : RandomSource {
  uint8_t n = 0;
  void fill(uint8_t* b, size_t len) override {
    for (size_t i = 0; i < len; ++i) b[i] = uint8_t(n + i);
    ++n;
  }
};

enum class Mode { HONEST, UNSIGNED, WRONG_KEY, REPLAY, TAMPER_BODY, STALE, TRANSPORT_DOWN };

struct FakeGateway : HttpTransport {
  Mode mode = Mode::HONEST;
  int status = 200;
  std::string reply = "{}";
  bool requestSignatureOk = false;
  std::string lastMethod, lastPathAndQuery, lastBody;
  std::map<std::string, std::string> lastHeaders;
  // Remembered from the first honest response, for REPLAY.
  std::string savedTs, savedSig, savedBody;

  HttpResponse send(const std::string& method, const std::string& pq,
                    const std::vector<HttpHeader>& headers, const std::string& body) override {
    HttpResponse r;
    if (mode == Mode::TRANSPORT_DOWN) { r.status = -1; return r; }
    lastMethod = method; lastPathAndQuery = pq; lastBody = body; lastHeaders.clear();
    for (auto& h : headers) lastHeaders[h.name] = h.value;

    std::string path = pq, query;
    size_t q = pq.find('?');
    if (q != std::string::npos) { path = pq.substr(0, q); query = pq.substr(q + 1); }
    std::string expected = hmacSha256Hex(
        kSecret, requestSigningString(method, path, query, lastHeaders["X-Timestamp"],
                                      lastHeaders["X-Nonce"], body));
    requestSignatureOk = expected == lastHeaders["X-Signature"];

    r.status = status;
    r.body = reply;
    r.timestamp = mode == Mode::STALE ? "1763120000" : "1763130001";
    std::string key = mode == Mode::WRONG_KEY ? std::string(64, 'f') : kSecret;
    r.signature = hmacSha256Hex(
        key, responseSigningString(method, path, lastHeaders["X-Nonce"], r.status, r.timestamp,
                                   r.body));
    if (mode == Mode::UNSIGNED) r.signature.clear();
    if (mode == Mode::TAMPER_BODY) r.body.replace(r.body.find("3000"), 4, "9000");
    if (mode == Mode::REPLAY) { r.timestamp = savedTs; r.signature = savedSig; r.body = savedBody; }
    if (mode == Mode::HONEST && savedSig.empty()) {
      savedTs = r.timestamp; savedSig = r.signature; savedBody = r.body;
    }
    return r;
  }
};

static FixedClock* clk;
static CounterRng* rng;
static FakeGateway* gw;
static BackendClient* client;

void setUp() {
  clk = new FixedClock();
  rng = new CounterRng();
  gw = new FakeGateway();
  BackendSettings s;
  s.deviceId = "DC-DOOR-01";
  s.secret = kSecret;
  client = new BackendClient(s, *gw, *clk, *rng);
}
void tearDown() {
  delete client; delete gw; delete rng; delete clk;
}

static const char* kGranted =
    R"({"session_id":"b6e1c0ffee00112233445566778899aa","state":"GRANTED","open_ms":3000})";

void test_requests_are_signed_correctly() {
  gw->reply = R"({"session_id":"b6e1c0ffee00112233445566778899aa","state":"AWAITING_FACE","poll_ms":500,"timeout_s":30})";
  StartReply r;
  TEST_ASSERT_EQUAL(int(ApiResult::OK), int(client->startAccess("04A1B2C3", 32.5f, "1.0.0", r)));
  TEST_ASSERT_TRUE(gw->requestSignatureOk);
  TEST_ASSERT_EQUAL_STRING("/api/v1/device/access/start", gw->lastPathAndQuery.c_str());
  TEST_ASSERT_EQUAL_STRING("DC-DOOR-01", gw->lastHeaders["X-Device-Id"].c_str());
  TEST_ASSERT_EQUAL_STRING("1763130000", gw->lastHeaders["X-Timestamp"].c_str());
  TEST_ASSERT_EQUAL(32, int(gw->lastHeaders["X-Nonce"].size()));
  TEST_ASSERT_EQUAL_STRING(kSid.c_str(), r.sessionId.c_str());
}

void test_poll_signs_query_and_accepts_signed_grant() {
  gw->reply = kGranted;
  DecisionReply d;
  TEST_ASSERT_EQUAL(int(ApiResult::OK), int(client->pollAccess(kSid, 30.12f, d)));
  TEST_ASSERT_TRUE(gw->requestSignatureOk);
  TEST_ASSERT_EQUAL_STRING(("/api/v1/device/access/" + kSid + "?distance_cm=30.1").c_str(),
                           gw->lastPathAndQuery.c_str());
  TEST_ASSERT_EQUAL_STRING("GRANTED", d.state.c_str());
  TEST_ASSERT_EQUAL(3000, d.openMs);
}

void test_nonces_are_unique() {
  gw->reply = "{}";
  client->presence(true, 30, 50);
  std::string n1 = gw->lastHeaders["X-Nonce"];
  client->presence(false, 90, 50);
  TEST_ASSERT_TRUE(n1 != gw->lastHeaders["X-Nonce"]);
}

static ApiResult pollWith(Mode m) {
  gw->reply = kGranted;
  gw->mode = m;
  DecisionReply d;
  return client->pollAccess(kSid, 30, d);
}

void test_unsigned_response_rejected() { TEST_ASSERT_EQUAL(int(ApiResult::BAD_SIGNATURE), int(pollWith(Mode::UNSIGNED))); }
void test_wrong_key_rejected() { TEST_ASSERT_EQUAL(int(ApiResult::BAD_SIGNATURE), int(pollWith(Mode::WRONG_KEY))); }
void test_tampered_body_rejected() { TEST_ASSERT_EQUAL(int(ApiResult::BAD_SIGNATURE), int(pollWith(Mode::TAMPER_BODY))); }
void test_stale_response_rejected() { TEST_ASSERT_EQUAL(int(ApiResult::BAD_SIGNATURE), int(pollWith(Mode::STALE))); }
void test_transport_error() { TEST_ASSERT_EQUAL(int(ApiResult::NETWORK_ERROR), int(pollWith(Mode::TRANSPORT_DOWN))); }

void test_replayed_grant_rejected() {
  TEST_ASSERT_EQUAL(int(ApiResult::OK), int(pollWith(Mode::HONEST)));  // captured by attacker
  TEST_ASSERT_EQUAL(int(ApiResult::BAD_SIGNATURE), int(pollWith(Mode::REPLAY)));  // new nonce
}

void test_signed_http_error() {
  gw->status = 403;
  gw->reply = R"({"error":{"code":"DEVICE_DISABLED"}})";
  DecisionReply d;
  TEST_ASSERT_EQUAL(int(ApiResult::HTTP_ERROR), int(client->pollAccess(kSid, 30, d)));
}

void test_clock_not_synced_sends_nothing() {
  clk->ok = false;
  gw->lastMethod.clear();
  DecisionReply d;
  TEST_ASSERT_EQUAL(int(ApiResult::CLOCK_NOT_SYNCED), int(client->pollAccess(kSid, 30, d)));
  TEST_ASSERT_TRUE(gw->lastMethod.empty());
}

void test_invalid_ids_never_reach_the_network() {
  DecisionReply d;
  TEST_ASSERT_EQUAL(int(ApiResult::BAD_PAYLOAD), int(client->pollAccess("../heartbeat", 30, d)));
  StartReply s;
  TEST_ASSERT_EQUAL(int(ApiResult::BAD_PAYLOAD), int(client->startAccess("zz", 30, "1", s)));
  TEST_ASSERT_TRUE(gw->lastMethod.empty());
}

void test_heartbeat_reply_parsed() {
  gw->reply = R"({"server_time":1763130001,"config":{"presence_threshold_cm":70,"door_open_ms":4000},"command":"EMERGENCY_CLOSE"})";
  HeartbeatInfo hb;
  HeartbeatReply r;
  TEST_ASSERT_EQUAL(int(ApiResult::OK), int(client->heartbeat(hb, DeviceConfig{}, r)));
  TEST_ASSERT_EQUAL_FLOAT(70, r.config.presenceThresholdCm);
  TEST_ASSERT_EQUAL(int(Command::EMERGENCY_CLOSE), int(r.command));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_requests_are_signed_correctly);
  RUN_TEST(test_poll_signs_query_and_accepts_signed_grant);
  RUN_TEST(test_nonces_are_unique);
  RUN_TEST(test_unsigned_response_rejected);
  RUN_TEST(test_wrong_key_rejected);
  RUN_TEST(test_tampered_body_rejected);
  RUN_TEST(test_stale_response_rejected);
  RUN_TEST(test_transport_error);
  RUN_TEST(test_replayed_grant_rejected);
  RUN_TEST(test_signed_http_error);
  RUN_TEST(test_clock_not_synced_sends_nothing);
  RUN_TEST(test_invalid_ids_never_reach_the_network);
  RUN_TEST(test_heartbeat_reply_parsed);
  return UNITY_END();
}
