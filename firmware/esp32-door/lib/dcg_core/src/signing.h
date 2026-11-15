// HMAC signing of the ESP32 <-> backend protocol (docs/protocolo-esp32.md §2).
// Must produce byte-identical strings to backend/app/core/security.py.
#pragma once

#include <cstdint>
#include <string>
#include <utility>
#include <vector>

namespace dcg {

using QueryParams = std::vector<std::pair<std::string, std::string>>;

// Same as Python's urllib.parse.quote_plus (safe=""): space -> '+', unreserved kept.
std::string formEncode(const std::string& s);

// Sorted "k=v&k2=v2" (Python: urlencode(sorted(pairs))). Empty if no params.
std::string canonicalQuery(QueryParams params);

// METHOD\nPATH\nCANONICAL_QUERY\nTIMESTAMP\nNONCE\nSHA256(BODY)
std::string requestSigningString(const std::string& method, const std::string& path,
                                 const std::string& canonicalQuery, const std::string& timestamp,
                                 const std::string& nonce, const std::string& body);

// RESP\nMETHOD\nPATH\nREQUEST_NONCE\nHTTP_STATUS\nTIMESTAMP\nSHA256(BODY)
// Binding the request nonce means an old (e.g. GRANTED) response cannot be replayed.
std::string responseSigningString(const std::string& method, const std::string& path,
                                  const std::string& requestNonce, int httpStatus,
                                  const std::string& timestamp, const std::string& body);

struct SignedHeaders {
  std::string deviceId;
  std::string timestamp;
  std::string nonce;
  std::string signature;
};

SignedHeaders signRequest(const std::string& secret, const std::string& deviceId,
                          const std::string& method, const std::string& path,
                          const std::string& canonicalQuery, int64_t epochSeconds,
                          const std::string& nonce, const std::string& body);

enum class ResponseCheck { OK, MISSING_SIGNATURE, BAD_SIGNATURE, BAD_TIMESTAMP, STALE };

// Verifies signature and that the response timestamp is within ±skewS of the device clock.
ResponseCheck verifyResponse(const std::string& secret, const std::string& method,
                             const std::string& path, const std::string& requestNonce,
                             int httpStatus, const std::string& timestampHeader,
                             const std::string& signatureHeader, const std::string& body,
                             int64_t deviceEpochSeconds, int64_t skewS);

const char* responseCheckName(ResponseCheck c);

}  // namespace dcg
