#include "signing.h"

#include <algorithm>
#include <cstdlib>

#include "crypto.h"

namespace dcg {

std::string formEncode(const std::string& s) {
  static const char* hex = "0123456789ABCDEF";
  std::string out;
  out.reserve(s.size());
  for (unsigned char c : s) {
    bool unreserved = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') ||
                      c == '-' || c == '.' || c == '_' || c == '~';
    if (unreserved) {
      out.push_back(char(c));
    } else if (c == ' ') {
      out.push_back('+');
    } else {
      out.push_back('%');
      out.push_back(hex[c >> 4]);
      out.push_back(hex[c & 0x0f]);
    }
  }
  return out;
}

std::string canonicalQuery(QueryParams params) {
  std::sort(params.begin(), params.end());
  std::string out;
  for (size_t i = 0; i < params.size(); ++i) {
    if (i) out.push_back('&');
    out += formEncode(params[i].first);
    out.push_back('=');
    out += formEncode(params[i].second);
  }
  return out;
}

std::string requestSigningString(const std::string& method, const std::string& path,
                                 const std::string& canonicalQuery, const std::string& timestamp,
                                 const std::string& nonce, const std::string& body) {
  std::string m = method;
  std::transform(m.begin(), m.end(), m.begin(), [](unsigned char c) { return char(toupper(c)); });
  return m + "\n" + path + "\n" + canonicalQuery + "\n" + timestamp + "\n" + nonce + "\n" +
         sha256Hex(body);
}

std::string responseSigningString(const std::string& method, const std::string& path,
                                  const std::string& requestNonce, int httpStatus,
                                  const std::string& timestamp, const std::string& body) {
  std::string m = method;
  std::transform(m.begin(), m.end(), m.begin(), [](unsigned char c) { return char(toupper(c)); });
  return "RESP\n" + m + "\n" + path + "\n" + requestNonce + "\n" + std::to_string(httpStatus) +
         "\n" + timestamp + "\n" + sha256Hex(body);
}

SignedHeaders signRequest(const std::string& secret, const std::string& deviceId,
                          const std::string& method, const std::string& path,
                          const std::string& canonicalQuery, int64_t epochSeconds,
                          const std::string& nonce, const std::string& body) {
  SignedHeaders h;
  h.deviceId = deviceId;
  h.timestamp = std::to_string(epochSeconds);
  h.nonce = nonce;
  h.signature = hmacSha256Hex(
      secret, requestSigningString(method, path, canonicalQuery, h.timestamp, nonce, body));
  return h;
}

static bool parseEpoch(const std::string& s, int64_t& out) {
  if (s.empty() || s.size() > 12) return false;
  int64_t v = 0;
  for (char c : s) {
    if (c < '0' || c > '9') return false;
    v = v * 10 + (c - '0');
  }
  out = v;
  return true;
}

ResponseCheck verifyResponse(const std::string& secret, const std::string& method,
                             const std::string& path, const std::string& requestNonce,
                             int httpStatus, const std::string& timestampHeader,
                             const std::string& signatureHeader, const std::string& body,
                             int64_t deviceEpochSeconds, int64_t skewS) {
  if (signatureHeader.empty()) return ResponseCheck::MISSING_SIGNATURE;
  int64_t ts = 0;
  if (!parseEpoch(timestampHeader, ts)) return ResponseCheck::BAD_TIMESTAMP;
  std::string expected = hmacSha256Hex(
      secret, responseSigningString(method, path, requestNonce, httpStatus, timestampHeader, body));
  if (!hexEqualsConstantTime(expected, signatureHeader)) return ResponseCheck::BAD_SIGNATURE;
  int64_t diff = ts - deviceEpochSeconds;
  if (diff < -skewS || diff > skewS) return ResponseCheck::STALE;
  return ResponseCheck::OK;
}

const char* responseCheckName(ResponseCheck c) {
  switch (c) {
    case ResponseCheck::OK: return "OK";
    case ResponseCheck::MISSING_SIGNATURE: return "MISSING_SIGNATURE";
    case ResponseCheck::BAD_SIGNATURE: return "BAD_SIGNATURE";
    case ResponseCheck::BAD_TIMESTAMP: return "BAD_TIMESTAMP";
    case ResponseCheck::STALE: return "STALE";
  }
  return "?";
}

}  // namespace dcg
