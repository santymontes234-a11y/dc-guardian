// JSON payloads of the device protocol (docs/protocolo-esp32.md §3) and their validation.
// Everything coming from the network is treated as untrusted: out-of-range values are
// rejected, unknown commands are ignored, and a GRANTED decision must be fully well-formed.
#pragma once

#include <cstdint>
#include <string>

namespace dcg {

// ------------------------------------------------------------------ configuration
struct DeviceConfig {
  float presenceThresholdCm = 50.0f;  // default per spec
  uint32_t doorOpenMs = 5000;
  uint32_t heartbeatS = 15;
};

enum class Command { NONE, EMERGENCY_CLOSE };

struct HeartbeatInfo {
  std::string fw;
  std::string state;        // controller state name
  std::string door;         // DoorState name
  bool present = false;
  float distanceCm = -1;    // -1 = no valid reading
  int rssi = 0;
  uint32_t uptimeS = 0;
  uint32_t freeHeap = 0;
  std::string sessionId;    // empty = none
  bool rfidOk = true;
  bool ultrasonicOk = true;
};

struct HeartbeatReply {
  int64_t serverTime = 0;
  bool hasConfig = false;
  DeviceConfig config;      // already validated / merged with the previous one
  Command command = Command::NONE;
  bool unknownCommand = false;
};

// ------------------------------------------------------------------ access session
struct StartReply {
  std::string sessionId;    // empty when denied immediately
  std::string state;        // AWAITING_FACE, CARD_READ, FACE_OK, DENIED, ...
  std::string reasonCode;
  uint32_t pollMs = 500;    // clamped to [300, 2000]
  uint32_t timeoutS = 30;   // clamped to [5, 60]
};

struct DecisionReply {
  std::string sessionId;
  std::string state;
  std::string reasonCode;
  uint32_t openMs = 0;      // only meaningful for GRANTED
};

bool isValidSessionId(const std::string& s);  // 32 lowercase hex chars (uuid4().hex)
bool isValidUid(const std::string& s);        // 2..20 uppercase hex chars, even length
std::string uidToHex(const uint8_t* bytes, uint8_t len);

std::string formatDistance(float cm);         // "%.1f", or "-1" if invalid

// Body builders (compact JSON, the exact bytes are signed).
std::string buildHeartbeatBody(const HeartbeatInfo& hb);
std::string buildPresenceBody(bool present, float distanceCm, float thresholdCm);
std::string buildStartBody(const std::string& uid, float distanceCm, const std::string& fw);
std::string buildOpenedBody(uint32_t openMs);
std::string buildClosedBody(const char* reason);
std::string buildEventBody(const char* type, const std::string& detail);

// Parsers: return false on malformed JSON / missing mandatory fields.
bool parseHeartbeatReply(const std::string& body, const DeviceConfig& current, HeartbeatReply& out);
bool parseStartReply(const std::string& body, StartReply& out);
bool parseDecisionReply(const std::string& body, DecisionReply& out);

}  // namespace dcg
