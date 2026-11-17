#include "protocol.h"

#include <ArduinoJson.h>

#include <cmath>
#include <cstdio>

#include "door.h"
#include "presence.h"

namespace dcg {

namespace {

template <typename T>
T clampT(T v, T lo, T hi) { return v < lo ? lo : (v > hi ? hi : v); }

std::string str(JsonVariantConst v) {
  const char* s = v.as<const char*>();
  return s ? std::string(s) : std::string();
}

std::string serialize(const JsonDocument& doc) {
  std::string out;
  serializeJson(doc, out);
  return out;
}

// Rounds to one decimal so the JSON matches the query string value.
double round1(float cm) { return std::round(double(cm) * 10.0) / 10.0; }

void putDistance(JsonDocument& doc, const char* key, float cm) {
  if (cm >= kMinDistanceCm && cm <= kMaxDistanceCm) doc[key] = round1(cm);
  else doc[key] = -1;
}

}  // namespace

bool isValidSessionId(const std::string& s) {
  if (s.size() != 32) return false;
  for (char c : s)
    if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
  return true;
}

bool isValidUid(const std::string& s) {
  if (s.size() < 2 || s.size() > 20 || s.size() % 2) return false;
  for (char c : s)
    if (!((c >= '0' && c <= '9') || (c >= 'A' && c <= 'F'))) return false;
  return true;
}

std::string uidToHex(const uint8_t* bytes, uint8_t len) {
  static const char* digits = "0123456789ABCDEF";
  std::string s;
  for (uint8_t i = 0; i < len; ++i) {
    s.push_back(digits[bytes[i] >> 4]);
    s.push_back(digits[bytes[i] & 0x0f]);
  }
  return s;
}

std::string formatDistance(float cm) {
  if (!(cm >= kMinDistanceCm && cm <= kMaxDistanceCm)) return "-1";
  char buf[16];
  snprintf(buf, sizeof buf, "%.1f", round1(cm));
  return buf;
}

std::string buildHeartbeatBody(const HeartbeatInfo& hb) {
  JsonDocument doc;
  doc["fw"] = hb.fw;
  doc["state"] = hb.state;
  doc["door"] = hb.door;
  doc["present"] = hb.present;
  putDistance(doc, "distance_cm", hb.distanceCm);
  doc["rssi"] = hb.rssi;
  doc["uptime_s"] = hb.uptimeS;
  doc["free_heap"] = hb.freeHeap;
  if (hb.sessionId.empty()) doc["session_id"] = nullptr;
  else doc["session_id"] = hb.sessionId;
  JsonObject sensors = doc["sensors"].to<JsonObject>();
  sensors["rfid"] = hb.rfidOk ? "OK" : "ERROR";
  sensors["ultrasonic"] = hb.ultrasonicOk ? "OK" : "TIMEOUT";
  sensors["dht"] = hb.dhtOk ? "OK" : "ERROR";
  return serialize(doc);
}

std::string buildPresenceBody(bool present, float distanceCm, float thresholdCm) {
  JsonDocument doc;
  doc["present"] = present;
  putDistance(doc, "distance_cm", distanceCm);
  doc["threshold_cm"] = round1(thresholdCm);
  return serialize(doc);
}

std::string buildStartBody(const std::string& uid, float distanceCm, const std::string& fw) {
  JsonDocument doc;
  doc["uid"] = uid;
  putDistance(doc, "distance_cm", distanceCm);
  doc["fw"] = fw;
  return serialize(doc);
}

std::string buildOpenedBody(uint32_t openMs) {
  JsonDocument doc;
  doc["open_ms"] = openMs;
  return serialize(doc);
}

std::string buildClosedBody(const char* reason) {
  JsonDocument doc;
  doc["reason"] = reason;
  return serialize(doc);
}

std::string buildExitButtonBody() {
  JsonDocument doc;
  doc["source"] = "BUTTON";
  return serialize(doc);
}

std::string buildEnvironmentBody(const EnvReading& r) {
  JsonDocument doc;
  const bool ok = r.sensorOk && std::isfinite(r.temperatureC) && std::isfinite(r.humidityPct);
  if (ok) {
    doc["temperature_c"] = std::round(double(r.temperatureC) * 10.0) / 10.0;
    doc["humidity_pct"] = std::round(double(r.humidityPct) * 10.0) / 10.0;
  } else {
    doc["temperature_c"] = nullptr;
    doc["humidity_pct"] = nullptr;
  }
  doc["sensor"] = ok ? "OK" : "ERROR";
  return serialize(doc);
}

std::string buildEntrancePollBody() { return "{}"; }

std::string buildEntranceAckBody() {
  JsonDocument doc;
  doc["shown"] = true;
  return serialize(doc);
}

bool validTempPair(float highC, float criticalC) {
  return highC >= 15.0f && highC <= 45.0f && criticalC >= 15.0f && criticalC <= 50.0f &&
         criticalC > highC;
}

bool validHumidityPair(float lowPct, float highPct) {
  return lowPct >= 0.0f && lowPct <= 100.0f && highPct >= 0.0f && highPct <= 100.0f &&
         highPct > lowPct;
}

std::string sanitizeLcdText(const std::string& s, size_t maxLen) {
  std::string out;
  for (char c : s) {
    if (out.size() >= maxLen) break;
    if (c >= 0x20 && c < 0x7F) out += c;  // HD44780 ROM A00: plain ASCII only
  }
  return out;
}

std::string buildEventBody(const char* type, const std::string& detail) {
  JsonDocument doc;
  doc["type"] = type;
  doc["detail"] = detail;
  return serialize(doc);
}

bool parseHeartbeatReply(const std::string& body, const DeviceConfig& current, HeartbeatReply& out) {
  JsonDocument doc;
  if (deserializeJson(doc, body) || !doc.is<JsonObject>()) return false;
  out = HeartbeatReply{};
  out.config = current;
  out.serverTime = doc["server_time"] | int64_t(0);

  JsonVariantConst cfg = doc["config"];
  if (cfg.is<JsonObjectConst>()) {
    out.hasConfig = true;
    JsonVariantConst th = cfg["presence_threshold_cm"];
    if (th.is<float>()) {
      float v = th.as<float>();
      if (v >= kMinDistanceCm && v <= kMaxDistanceCm) out.config.presenceThresholdCm = v;
    }
    JsonVariantConst om = cfg["door_open_ms"];
    if (om.is<uint32_t>()) {
      uint32_t v = om.as<uint32_t>();
      if (v >= kMinOpenMs && v <= kMaxOpenMs) out.config.doorOpenMs = v;
    }
    JsonVariantConst hb = cfg["heartbeat_s"];
    if (hb.is<uint32_t>()) {
      uint32_t v = hb.as<uint32_t>();
      if (v >= 5 && v <= 60) out.config.heartbeatS = v;
    }
    // Environment thresholds: each pair is accepted only as a consistent whole.
    EnvThresholds& env = out.config.env;
    auto num = [&](const char* key, float fallback) {
      JsonVariantConst v = cfg[key];
      if (!v.is<float>()) return fallback;
      float f = v.as<float>();
      return std::isfinite(f) ? f : fallback;
    };
    const float hi = num("temp_high_c", env.tempHighC);
    const float crit = num("temp_critical_c", env.tempCriticalC);
    if (validTempPair(hi, crit)) { env.tempHighC = hi; env.tempCriticalC = crit; }
    const float hlo = num("humidity_low_pct", env.humidityLowPct);
    const float hhi = num("humidity_high_pct", env.humidityHighPct);
    if (validHumidityPair(hlo, hhi)) { env.humidityLowPct = hlo; env.humidityHighPct = hhi; }
  }

  // Whitelist: the only remote command is closing. Opening never arrives via heartbeat.
  JsonVariantConst cmd = doc["command"];
  if (!cmd.isNull()) {
    std::string c = str(cmd);
    if (c == "EMERGENCY_CLOSE") out.command = Command::EMERGENCY_CLOSE;
    else out.unknownCommand = true;
  }
  return true;
}

bool parseStartReply(const std::string& body, StartReply& out) {
  JsonDocument doc;
  if (deserializeJson(doc, body) || !doc.is<JsonObject>()) return false;
  out = StartReply{};
  out.state = str(doc["state"]);
  out.reasonCode = str(doc["reason_code"]);
  if (out.state.empty()) return false;
  if (out.state == "DENIED" || out.state == "TIMEOUT") return true;  // no session needed
  out.sessionId = str(doc["session_id"]);
  if (!isValidSessionId(out.sessionId)) return false;
  // A brand-new session can never be GRANTED already (face check pending).
  if (out.state == "GRANTED") return false;
  out.pollMs = clampT<uint32_t>(doc["poll_ms"] | 500u, 300u, 2000u);
  out.timeoutS = clampT<uint32_t>(doc["timeout_s"] | 30u, 5u, 60u);
  return true;
}

bool parsePresenceReply(const std::string& body, PresenceReply& out) {
  JsonDocument doc;
  if (deserializeJson(doc, body) || !doc.is<JsonObject>()) return false;
  out = PresenceReply{};
  out.alarm = doc["alarm"] | false;
  out.alarmMs = clampT<uint32_t>(doc["alarm_s"] | 20u, 5u, 120u) * 1000u;
  return true;
}

bool parseEnvReply(const std::string& body, EnvReply& out) {
  JsonDocument doc;
  if (deserializeJson(doc, body) || !doc.is<JsonObject>()) return false;
  JsonVariantConst fan = doc["fan"];
  JsonVariantConst alarm = doc["alarm"];
  if (!fan.is<bool>() || !alarm.is<bool>()) return false;
  out = EnvReply{};
  out.fan = fan.as<bool>();
  out.alarm = alarm.as<bool>();
  return true;
}

bool parseEntrancePollReply(const std::string& body, EntrancePollReply& out) {
  JsonDocument doc;
  if (deserializeJson(doc, body) || !doc.is<JsonObject>()) return false;
  out = EntrancePollReply{};
  JsonVariantConst sig = doc["signal"];
  if (sig.isNull()) return true;  // nothing pending
  if (!sig.is<JsonObjectConst>()) return false;
  EntranceSignal& s = out.signal;
  s.id = str(sig["id"]);
  if (!isValidSignalId(s.id)) return false;
  s.rawResult = sanitizeLcdText(str(sig["result"]), 20);
  if (s.rawResult == "GRANTED") s.result = EntranceResult::GRANTED;
  else if (s.rawResult == "DENIED") s.result = EntranceResult::DENIED;
  else s.result = EntranceResult::UNKNOWN;
  if (s.result == EntranceResult::GRANTED) {
    JsonVariantConst led = sig["led_ms"];
    if (!led.isNull()) {
      if (!led.is<uint32_t>()) return false;
      s.ledMs = led.as<uint32_t>();
    }
    if (s.ledMs < kMinEntranceLedMs || s.ledMs > kMaxEntranceLedMs) return false;
  }
  s.displayName = sanitizeLcdText(str(sig["display_name"]), 40);
  out.hasSignal = true;
  return true;
}

bool parseDecisionReply(const std::string& body, DecisionReply& out) {
  JsonDocument doc;
  if (deserializeJson(doc, body) || !doc.is<JsonObject>()) return false;
  out = DecisionReply{};
  out.sessionId = str(doc["session_id"]);
  out.state = str(doc["state"]);
  out.reasonCode = str(doc["reason_code"]);
  if (out.state.empty() || !isValidSessionId(out.sessionId)) return false;
  if (out.state == "GRANTED") {
    JsonVariantConst om = doc["open_ms"];
    if (!om.is<uint32_t>()) return false;
    out.openMs = om.as<uint32_t>();
    if (out.openMs < kMinOpenMs || out.openMs > kMaxOpenMs) return false;
    out.greeting = sanitizeLcdText(str(doc["greeting"]), 20);
    out.displayName = sanitizeLcdText(str(doc["display_name"]), 40);
  }
  return true;
}

}  // namespace dcg
