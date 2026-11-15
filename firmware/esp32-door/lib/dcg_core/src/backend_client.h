// Signed HTTP client for the device API. Platform specifics (HTTPClient, NTP, RNG) are
// injected, so the whole request/response pipeline is unit-tested on the PC.
//
// Every response must carry a valid X-Signature bound to the request nonce; otherwise the
// call fails with BAD_SIGNATURE and the caller treats it exactly like a network error.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "protocol.h"
#include "signing.h"

namespace dcg {

struct HttpHeader {
  std::string name;
  std::string value;
};

struct HttpResponse {
  int status = 0;  // <= 0: transport error (no connection, timeout)
  std::string body;
  std::string timestamp;  // X-Timestamp
  std::string signature;  // X-Signature
};

class HttpTransport {
 public:
  virtual ~HttpTransport() = default;
  // `pathAndQuery` is appended to the base URL. Must honor a short timeout.
  virtual HttpResponse send(const std::string& method, const std::string& pathAndQuery,
                            const std::vector<HttpHeader>& headers, const std::string& body) = 0;
};

class Clock {
 public:
  virtual ~Clock() = default;
  virtual bool synced() const = 0;        // NTP time available
  virtual int64_t epochSeconds() const = 0;
};

class RandomSource {
 public:
  virtual ~RandomSource() = default;
  virtual void fill(uint8_t* buf, size_t len) = 0;  // cryptographically secure
};

enum class ApiResult { OK, CLOCK_NOT_SYNCED, NETWORK_ERROR, HTTP_ERROR, BAD_SIGNATURE, BAD_PAYLOAD };
const char* apiResultName(ApiResult r);

struct BackendSettings {
  std::string deviceId;
  std::string secret;
  std::string apiPrefix = "/api/v1";
  int64_t clockSkewS = 30;
};

class Backend {
 public:
  virtual ~Backend() = default;
  virtual ApiResult heartbeat(const HeartbeatInfo& hb, const DeviceConfig& cur, HeartbeatReply& out) = 0;
  virtual ApiResult presence(bool present, float distanceCm, float thresholdCm) = 0;
  virtual ApiResult startAccess(const std::string& uid, float distanceCm, const std::string& fw,
                                StartReply& out) = 0;
  virtual ApiResult pollAccess(const std::string& sessionId, float distanceCm, DecisionReply& out) = 0;
  virtual ApiResult confirmOpened(const std::string& sessionId, uint32_t openMs) = 0;
  virtual ApiResult confirmClosed(const std::string& sessionId, const char* reason) = 0;
  virtual ApiResult event(const char* type, const std::string& detail) = 0;
};

class BackendClient : public Backend {
 public:
  BackendClient(BackendSettings s, HttpTransport& http, Clock& clock, RandomSource& rng)
      : s_(std::move(s)), http_(http), clock_(clock), rng_(rng) {}

  ApiResult heartbeat(const HeartbeatInfo& hb, const DeviceConfig& cur, HeartbeatReply& out) override;
  ApiResult presence(bool present, float distanceCm, float thresholdCm) override;
  ApiResult startAccess(const std::string& uid, float distanceCm, const std::string& fw,
                        StartReply& out) override;
  ApiResult pollAccess(const std::string& sessionId, float distanceCm, DecisionReply& out) override;
  ApiResult confirmOpened(const std::string& sessionId, uint32_t openMs) override;
  ApiResult confirmClosed(const std::string& sessionId, const char* reason) override;
  ApiResult event(const char* type, const std::string& detail) override;

  // Last failure detail, for logs / heartbeat diagnostics.
  const std::string& lastError() const { return lastError_; }
  std::string newNonce();

 private:
  // Signs and sends; on OK `respBody` holds a verified 2xx body.
  ApiResult call(const std::string& method, const std::string& relPath, const QueryParams& query,
                 const std::string& body, std::string& respBody);

  BackendSettings s_;
  HttpTransport& http_;
  Clock& clock_;
  RandomSource& rng_;
  std::string lastError_;
};

}  // namespace dcg
