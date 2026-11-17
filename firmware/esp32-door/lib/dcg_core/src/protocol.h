// JSON payloads of the device protocol (docs/protocolo-esp32.md §3) and their validation.
// Everything coming from the network is treated as untrusted: out-of-range values are
// rejected, unknown commands are ignored, and a GRANTED decision must be fully well-formed.
#pragma once

#include <cstdint>
#include <string>

namespace dcg {

// ------------------------------------------------------------------ configuration
// Environment thresholds (contrato-qr-dht11.md §4). Only accepted from the heartbeat when in
// range and consistent (critical > high, humidity high > low); otherwise the previous pair stays.
struct EnvThresholds {
  float tempHighC = 27.0f;        // 15..45: fan ON at or above, OFF below (high - 1)
  float tempCriticalC = 32.0f;    // 15..50 and > tempHighC: environmental alarm
  float humidityLowPct = 20.0f;   // 0..100
  float humidityHighPct = 80.0f;  // 0..100 and > humidityLowPct
};
bool validTempPair(float highC, float criticalC);
bool validHumidityPair(float lowPct, float highPct);

struct DeviceConfig {
  float presenceThresholdCm = 50.0f;  // default per spec
  uint32_t doorOpenMs = 5000;
  uint32_t heartbeatS = 15;
  EnvThresholds env;
};

enum class Command { NONE, EMERGENCY_CLOSE };

// Reply to POST /device/presence. The HC-SR04 is INSIDE the room: the backend asks for the
// intrusion alarm when someone is detected and nobody authorized is inside.
struct PresenceReply {
  bool alarm = false;
  uint32_t alarmMs = 20000;  // alarm_s clamped to [5, 120] s
};

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
  bool dhtOk = true;        // sensors.dht: "OK" | "ERROR" (3 failed reads in a row)
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
  // Optional, only on GRANTED, for the LCD. Untrusted text: sanitized to printable ASCII.
  std::string greeting;     // "Bienvenido" / "Hasta pronto" (≤ 20 chars)
  std::string displayName;  // engineer's name (≤ 40 chars = two LCD lines); may be empty
};

// ------------------------------------------------------------------ DHT11 (§11)
struct EnvReading {
  bool sensorOk = false;    // false ⇒ "sensor":"ERROR" and null values
  float temperatureC = 0;
  float humidityPct = 0;
};

// Reply to POST /device/environment. Both flags are mandatory booleans.
struct EnvReply {
  bool fan = false;
  bool alarm = false;
};

// ------------------------------------------------------------------ entrance signal (§10)
constexpr uint32_t kMinEntranceLedMs = 1000;
constexpr uint32_t kMaxEntranceLedMs = 10000;

enum class EntranceResult { NONE, GRANTED, DENIED, UNKNOWN };

struct EntranceSignal {
  std::string id;            // 32 lowercase hex chars
  EntranceResult result = EntranceResult::NONE;
  std::string rawResult;     // for the log when UNKNOWN (sanitized, ≤ 20 chars)
  uint32_t ledMs = 5000;     // 1000..10000, only meaningful for GRANTED
  std::string displayName;   // untrusted: printable ASCII, ≤ 40 chars
};

struct EntrancePollReply {
  bool hasSignal = false;
  EntranceSignal signal;
};

bool isValidSessionId(const std::string& s);  // 32 lowercase hex chars (uuid4().hex)
inline bool isValidSignalId(const std::string& s) { return isValidSessionId(s); }
bool isValidUid(const std::string& s);        // 2..20 uppercase hex chars, even length
std::string uidToHex(const uint8_t* bytes, uint8_t len);

std::string formatDistance(float cm);         // "%.1f", or "-1" if invalid
std::string sanitizeLcdText(const std::string& s, size_t maxLen);  // printable ASCII only

// Body builders (compact JSON, the exact bytes are signed).
std::string buildHeartbeatBody(const HeartbeatInfo& hb);
std::string buildPresenceBody(bool present, float distanceCm, float thresholdCm);
std::string buildStartBody(const std::string& uid, float distanceCm, const std::string& fw);
std::string buildOpenedBody(uint32_t openMs);
std::string buildClosedBody(const char* reason);
std::string buildEventBody(const char* type, const std::string& detail);
std::string buildExitButtonBody();
std::string buildEnvironmentBody(const EnvReading& r);
std::string buildEntrancePollBody();
std::string buildEntranceAckBody();

// Parsers: return false on malformed JSON / missing mandatory fields.
bool parseHeartbeatReply(const std::string& body, const DeviceConfig& current, HeartbeatReply& out);
bool parseStartReply(const std::string& body, StartReply& out);
bool parseDecisionReply(const std::string& body, DecisionReply& out);
bool parsePresenceReply(const std::string& body, PresenceReply& out);
bool parseEnvReply(const std::string& body, EnvReply& out);
// false = malformed payload / signal (ignored entirely, fail-closed: the LED stays off).
bool parseEntrancePollReply(const std::string& body, EntrancePollReply& out);

}  // namespace dcg
