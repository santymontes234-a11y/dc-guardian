#include "net.h"

#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <esp_random.h>
#include <time.h>

namespace dcg {

// ------------------------------------------------------------------ WiFi
void wifiBegin(const char* ssid, const char* password) {
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.setSleep(false);  // lower latency for polling
  WiFi.begin(ssid, password);
}

bool wifiUp() { return WiFi.status() == WL_CONNECTED; }

// ------------------------------------------------------------------ clock
void NtpClock::begin(const char* server1, const char* server2) {
  configTime(0, 0, server1, server2);  // UTC; SNTP keeps re-syncing in the background
}

bool NtpClock::synced() const {
  return time(nullptr) > 1700000000;  // anything before Nov 2023 means "not synced yet"
}

int64_t NtpClock::epochSeconds() const { return int64_t(time(nullptr)); }

// ------------------------------------------------------------------ RNG
void HardwareRandom::fill(uint8_t* buf, size_t len) { esp_fill_random(buf, len); }

// ------------------------------------------------------------------ HTTP
bool Esp32HttpTransport::begin(const std::string& baseUrl, const char* caPem) {
  base_ = baseUrl;
  while (!base_.empty() && base_.back() == '/') base_.pop_back();
  tls_ = base_.rfind("https://", 0) == 0;
  ca_ = caPem;
  if (tls_ && !ca_) return false;  // no TLS without certificate validation
  return tls_ || base_.rfind("http://", 0) == 0;
}

HttpResponse Esp32HttpTransport::send(const std::string& method, const std::string& pathAndQuery,
                                      const std::vector<HttpHeader>& headers,
                                      const std::string& body) {
  HttpResponse r;
  WiFiClient plain;
  WiFiClientSecure secure;
  HTTPClient http;
  http.setReuse(false);
  http.setTimeout(kTimeoutMs);
  http.setConnectTimeout(kTimeoutMs);
  http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);  // never follow: path is signed

  const String url = String(base_.c_str()) + pathAndQuery.c_str();
  bool ok;
  if (tls_) {
    secure.setCACert(ca_);
    ok = http.begin(secure, url);
  } else {
    ok = http.begin(plain, url);
  }
  if (!ok) { r.status = -100; return r; }

  for (const auto& h : headers) http.addHeader(h.name.c_str(), h.value.c_str());
  const char* wanted[] = {"X-Timestamp", "X-Signature"};
  http.collectHeaders(wanted, 2);

  int code;
  if (method == "GET") code = http.GET();
  else code = http.sendRequest(method.c_str(), (uint8_t*)body.data(), body.size());

  r.status = code;
  if (code > 0) {
    int size = http.getSize();
    if (size > int(kMaxBody)) {
      r.status = -101;
    } else {
      String payload = http.getString();
      if (payload.length() > kMaxBody) r.status = -101;
      else r.body.assign(payload.c_str(), payload.length());
      r.timestamp = http.header("X-Timestamp").c_str();
      r.signature = http.header("X-Signature").c_str();
    }
  }
  http.end();
  return r;
}

}  // namespace dcg
