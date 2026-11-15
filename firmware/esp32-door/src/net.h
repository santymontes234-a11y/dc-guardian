// WiFi, NTP clock, hardware RNG and the HTTPClient transport.
#pragma once

#include <string>

#include "backend_client.h"

namespace dcg {

class NtpClock : public Clock {
 public:
  void begin(const char* server1, const char* server2);
  bool synced() const override;
  int64_t epochSeconds() const override;
};

class HardwareRandom : public RandomSource {
 public:
  void fill(uint8_t* buf, size_t len) override;  // esp_fill_random (true RNG with RF on)
};

class Esp32HttpTransport : public HttpTransport {
 public:
  // caPem may be nullptr for plain HTTP. Returns false if the URL/TLS setup is unsafe.
  bool begin(const std::string& baseUrl, const char* caPem);
  HttpResponse send(const std::string& method, const std::string& pathAndQuery,
                    const std::vector<HttpHeader>& headers, const std::string& body) override;

  static constexpr uint16_t kTimeoutMs = 3000;   // short: the loop must keep moving
  static constexpr size_t kMaxBody = 4096;       // larger responses are rejected

 private:
  std::string base_;
  const char* ca_ = nullptr;
  bool tls_ = false;
};

// One WiFi network the device may join. An empty or null password means an open network.
struct WifiNetwork {
  const char* ssid;
  const char* password;
};

// Non-blocking failover across up to kMaxWifiNetworks networks, tried in order. The list must
// outlive the program (static storage). wifiTick() must be called from loop().
constexpr size_t kMaxWifiNetworks = 4;
void wifiBegin(const WifiNetwork* networks, size_t count);
void wifiTick();
bool wifiUp();
const char* wifiSsid();  // network currently joined or being tried ("" if none)

}  // namespace dcg
