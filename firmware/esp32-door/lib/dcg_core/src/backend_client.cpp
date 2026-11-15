#include "backend_client.h"

#include "crypto.h"

namespace dcg {

const char* apiResultName(ApiResult r) {
  switch (r) {
    case ApiResult::OK: return "OK";
    case ApiResult::CLOCK_NOT_SYNCED: return "CLOCK_NOT_SYNCED";
    case ApiResult::NETWORK_ERROR: return "NETWORK_ERROR";
    case ApiResult::HTTP_ERROR: return "HTTP_ERROR";
    case ApiResult::BAD_SIGNATURE: return "BAD_SIGNATURE";
    case ApiResult::BAD_PAYLOAD: return "BAD_PAYLOAD";
  }
  return "?";
}

std::string BackendClient::newNonce() {
  uint8_t raw[16];
  rng_.fill(raw, sizeof raw);
  return toHex(raw, sizeof raw);
}

ApiResult BackendClient::call(const std::string& method, const std::string& relPath,
                              const QueryParams& query, const std::string& body,
                              std::string& respBody) {
  respBody.clear();
  if (!clock_.synced()) {
    lastError_ = "clock not synced";
    return ApiResult::CLOCK_NOT_SYNCED;
  }
  const std::string path = s_.apiPrefix + relPath;
  const std::string cq = canonicalQuery(query);
  const std::string nonce = newNonce();
  SignedHeaders sh = signRequest(s_.secret, s_.deviceId, method, path, cq, clock_.epochSeconds(),
                                 nonce, body);
  std::vector<HttpHeader> headers = {
      {"X-Device-Id", sh.deviceId},
      {"X-Timestamp", sh.timestamp},
      {"X-Nonce", sh.nonce},
      {"X-Signature", sh.signature},
  };
  if (!body.empty()) headers.push_back({"Content-Type", "application/json"});

  HttpResponse r = http_.send(method, cq.empty() ? path : path + "?" + cq, headers, body);
  if (r.status <= 0) {
    lastError_ = "transport error " + std::to_string(r.status);
    return ApiResult::NETWORK_ERROR;
  }
  // Authenticate before looking at the content — even error responses.
  ResponseCheck chk = verifyResponse(s_.secret, method, path, nonce, r.status, r.timestamp,
                                     r.signature, r.body, clock_.epochSeconds(), s_.clockSkewS);
  if (chk != ResponseCheck::OK) {
    lastError_ = std::string("response ") + responseCheckName(chk) + " (HTTP " +
                 std::to_string(r.status) + ")";
    return ApiResult::BAD_SIGNATURE;
  }
  if (r.status < 200 || r.status >= 300) {
    lastError_ = "HTTP " + std::to_string(r.status) + ": " + r.body.substr(0, 120);
    return ApiResult::HTTP_ERROR;
  }
  respBody = r.body;
  return ApiResult::OK;
}

ApiResult BackendClient::heartbeat(const HeartbeatInfo& hb, const DeviceConfig& cur,
                                   HeartbeatReply& out) {
  std::string resp;
  ApiResult r = call("POST", "/device/heartbeat", {}, buildHeartbeatBody(hb), resp);
  if (r != ApiResult::OK) return r;
  if (!parseHeartbeatReply(resp, cur, out)) {
    lastError_ = "bad heartbeat payload";
    return ApiResult::BAD_PAYLOAD;
  }
  return ApiResult::OK;
}

ApiResult BackendClient::presence(bool present, float distanceCm, float thresholdCm) {
  std::string resp;
  return call("POST", "/device/presence", {}, buildPresenceBody(present, distanceCm, thresholdCm),
              resp);
}

ApiResult BackendClient::startAccess(const std::string& uid, float distanceCm,
                                     const std::string& fw, StartReply& out) {
  if (!isValidUid(uid)) {
    lastError_ = "invalid uid";
    return ApiResult::BAD_PAYLOAD;
  }
  std::string resp;
  ApiResult r = call("POST", "/device/access/start", {}, buildStartBody(uid, distanceCm, fw), resp);
  if (r != ApiResult::OK) return r;
  if (!parseStartReply(resp, out)) {
    lastError_ = "bad start payload";
    return ApiResult::BAD_PAYLOAD;
  }
  return ApiResult::OK;
}

ApiResult BackendClient::pollAccess(const std::string& sessionId, float distanceCm,
                                    DecisionReply& out) {
  // Never put an unvalidated string into the URL path.
  if (!isValidSessionId(sessionId)) return ApiResult::BAD_PAYLOAD;
  std::string resp;
  ApiResult r = call("GET", "/device/access/" + sessionId,
                     {{"distance_cm", formatDistance(distanceCm)}}, "", resp);
  if (r != ApiResult::OK) return r;
  if (!parseDecisionReply(resp, out)) {
    lastError_ = "bad decision payload";
    return ApiResult::BAD_PAYLOAD;
  }
  return ApiResult::OK;
}

ApiResult BackendClient::confirmOpened(const std::string& sessionId, uint32_t openMs) {
  if (!isValidSessionId(sessionId)) return ApiResult::BAD_PAYLOAD;
  std::string resp;
  return call("POST", "/device/access/" + sessionId + "/opened", {}, buildOpenedBody(openMs), resp);
}

ApiResult BackendClient::confirmClosed(const std::string& sessionId, const char* reason) {
  if (!isValidSessionId(sessionId)) return ApiResult::BAD_PAYLOAD;
  std::string resp;
  return call("POST", "/device/access/" + sessionId + "/closed", {}, buildClosedBody(reason), resp);
}

ApiResult BackendClient::event(const char* type, const std::string& detail) {
  std::string resp;
  return call("POST", "/device/event", {}, buildEventBody(type, detail), resp);
}

}  // namespace dcg
