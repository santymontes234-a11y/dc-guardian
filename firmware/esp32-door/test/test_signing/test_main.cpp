// SHA-256 / HMAC and the protocol signing strings.
// Golden values were produced with backend/app/core/security.py (same inputs),
// so a pass here means the firmware and the backend sign byte-identical strings.
#include <unity.h>

#include "crypto.h"
#include "signing.h"

using namespace dcg;

static const std::string kSecret =
    "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff";

void setUp() {}
void tearDown() {}

void test_sha256_known_vectors() {
  TEST_ASSERT_EQUAL_STRING("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                           sha256Hex("").c_str());
  TEST_ASSERT_EQUAL_STRING("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                           sha256Hex("abc").c_str());
  // Two-block message (56 bytes) exercises padding.
  TEST_ASSERT_EQUAL_STRING(
      "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
      sha256Hex("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq").c_str());
}

void test_hmac_rfc4231_case2() {
  TEST_ASSERT_EQUAL_STRING("5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843",
                           hmacSha256Hex("Jefe", "what do ya want for nothing?").c_str());
}

void test_hmac_long_key_is_hashed() {
  // RFC 4231 case 6: 131-byte key.
  std::string key(131, char(0xaa));
  TEST_ASSERT_EQUAL_STRING(
      "60e431591ee0b67f0d8a26aacbf5b77f8e0bc6213728c5140546040f0ee37f54",
      hmacSha256Hex(key, "Test Using Larger Than Block-Size Key - Hash Key First").c_str());
}

void test_canonical_query_matches_python_urlencode() {
  QueryParams q = {{"z", "a b"}, {"a", "x/y&="}, {"m", "\xC3\xB1~.-_"}};
  TEST_ASSERT_EQUAL_STRING("a=x%2Fy%26%3D&m=%C3%B1~.-_&z=a+b", canonicalQuery(q).c_str());
  TEST_ASSERT_EQUAL_STRING("", canonicalQuery({}).c_str());
}

void test_post_signature_matches_backend() {
  std::string body = R"({"uid":"04A1B2C3","distance_cm":32.5,"fw":"1.0.0"})";
  SignedHeaders h = signRequest(kSecret, "DC-DOOR-01", "POST", "/api/v1/device/access/start", "",
                                1763130000, "9f2c00112233445566778899aabbccdd", body);
  TEST_ASSERT_EQUAL_STRING("1763130000", h.timestamp.c_str());
  TEST_ASSERT_EQUAL_STRING("119cce8fc22353d036391ad72d7dd88f6a5ff007ef830b80fed5718ebb6f50e6",
                           h.signature.c_str());
}

void test_get_with_query_signature_matches_backend() {
  SignedHeaders h = signRequest(kSecret, "DC-DOOR-01", "get",
                                "/api/v1/device/access/b6e1c0ffee00112233445566778899aa",
                                canonicalQuery({{"distance_cm", "30.1"}}), 1763130000,
                                "0123456789abcdef0123456789abcdef", "");
  TEST_ASSERT_EQUAL_STRING("db823647540faa5db966883bc8696abc27186c9b9ada2428da58dcc4faf6620b",
                           h.signature.c_str());
}

static const char* kPath = "/api/v1/device/access/b6e1c0ffee00112233445566778899aa";
static const char* kNonce = "0123456789abcdef0123456789abcdef";
static const char* kBody =
    R"({"session_id":"b6e1c0ffee00112233445566778899aa","state":"GRANTED","open_ms":5000})";
static const char* kRespSig = "491802e80a722d236112a9d38db8815721a4d60234e97a47422517ad33d9bacd";

void test_response_signature_ok() {
  TEST_ASSERT_EQUAL(int(ResponseCheck::OK),
                    int(verifyResponse(kSecret, "GET", kPath, kNonce, 200, "1763130001", kRespSig,
                                       kBody, 1763130000, 30)));
  // Upper-case hex is accepted too.
  std::string upper = kRespSig;
  for (auto& c : upper) c = char(toupper(c));
  TEST_ASSERT_EQUAL(int(ResponseCheck::OK),
                    int(verifyResponse(kSecret, "GET", kPath, kNonce, 200, "1763130001", upper,
                                       kBody, 1763130000, 30)));
}

void test_response_tampering_detected() {
  auto check = [](const std::string& nonce, int status, const std::string& body,
                  const std::string& secret) {
    return verifyResponse(secret, "GET", kPath, nonce, status, "1763130001", kRespSig, body,
                          1763130000, 30);
  };
  // Replayed under another request (different nonce).
  TEST_ASSERT_EQUAL(int(ResponseCheck::BAD_SIGNATURE),
                    int(check("ffffffffffffffffffffffffffffffff", 200, kBody, kSecret)));
  // Body modified (open_ms bumped).
  std::string b = kBody;
  b.replace(b.find("5000"), 4, "30000");
  TEST_ASSERT_EQUAL(int(ResponseCheck::BAD_SIGNATURE), int(check(kNonce, 200, b, kSecret)));
  // Status modified.
  TEST_ASSERT_EQUAL(int(ResponseCheck::BAD_SIGNATURE), int(check(kNonce, 201, kBody, kSecret)));
  // Wrong secret.
  TEST_ASSERT_EQUAL(int(ResponseCheck::BAD_SIGNATURE),
                    int(check(kNonce, 200, kBody, std::string(64, '0'))));
}

void test_response_missing_or_stale() {
  TEST_ASSERT_EQUAL(int(ResponseCheck::MISSING_SIGNATURE),
                    int(verifyResponse(kSecret, "GET", kPath, kNonce, 200, "1763130001", "", kBody,
                                       1763130000, 30)));
  TEST_ASSERT_EQUAL(int(ResponseCheck::BAD_TIMESTAMP),
                    int(verifyResponse(kSecret, "GET", kPath, kNonce, 200, "17631x0001", kRespSig,
                                       kBody, 1763130000, 30)));
  // Valid signature but the device clock is 31+ s away.
  TEST_ASSERT_EQUAL(int(ResponseCheck::STALE),
                    int(verifyResponse(kSecret, "GET", kPath, kNonce, 200, "1763130001", kRespSig,
                                       kBody, 1763130040, 30)));
  // Malformed signature (wrong length) never matches.
  TEST_ASSERT_EQUAL(int(ResponseCheck::BAD_SIGNATURE),
                    int(verifyResponse(kSecret, "GET", kPath, kNonce, 200, "1763130001", "abc",
                                       kBody, 1763130000, 30)));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_sha256_known_vectors);
  RUN_TEST(test_hmac_rfc4231_case2);
  RUN_TEST(test_hmac_long_key_is_hashed);
  RUN_TEST(test_canonical_query_matches_python_urlencode);
  RUN_TEST(test_post_signature_matches_backend);
  RUN_TEST(test_get_with_query_signature_matches_backend);
  RUN_TEST(test_response_signature_ok);
  RUN_TEST(test_response_tampering_detected);
  RUN_TEST(test_response_missing_or_stale);
  return UNITY_END();
}
