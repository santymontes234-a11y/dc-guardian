// Host runner: the REAL firmware core (AccessController + BackendClient + DoorController +
// PresenceDetector) running on the PC against a gateway over real HTTP (POSIX sockets).
// Only the hardware is simulated: a person stands at 30 cm and presents a card at t = 1 s.
//
//   host_runner <host> <port> <secret> <seconds> [uid]
//
// Prints one JSON line on stdout with what happened; logs go to stderr.
#include <arpa/inet.h>
#include <netdb.h>
#include <sys/socket.h>
#include <unistd.h>

#include <chrono>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <random>
#include <thread>

#include "access_controller.h"
#include "backend_client.h"
#include "presence.h"

using namespace dcg;

struct PosixHttp : HttpTransport {
  std::string host;
  int port;

  HttpResponse send(const std::string& method, const std::string& pq,
                    const std::vector<HttpHeader>& headers, const std::string& body) override {
    HttpResponse r;
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    timeval tv{3, 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof tv);
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(uint16_t(port));
    inet_pton(AF_INET, host.c_str(), &addr.sin_addr);
    if (connect(fd, (sockaddr*)&addr, sizeof addr) != 0) { close(fd); r.status = -1; return r; }
    std::string req = method + " " + pq + " HTTP/1.1\r\nHost: " + host + "\r\nConnection: close\r\n";
    for (auto& h : headers) req += h.name + ": " + h.value + "\r\n";
    req += "Content-Length: " + std::to_string(body.size()) + "\r\n\r\n" + body;
    ::send(fd, req.data(), req.size(), 0);
    std::string resp;
    char buf[2048];
    ssize_t n;
    while ((n = recv(fd, buf, sizeof buf, 0)) > 0) resp.append(buf, size_t(n));
    close(fd);
    size_t sep = resp.find("\r\n\r\n");
    if (resp.rfind("HTTP/1.", 0) != 0 || sep == std::string::npos) { r.status = -2; return r; }
    r.status = atoi(resp.c_str() + 9);
    r.body = resp.substr(sep + 4);
    size_t pos = resp.find("\r\n");
    while (pos < sep) {
      size_t end = resp.find("\r\n", pos + 2);
      std::string line = resp.substr(pos + 2, end - pos - 2);
      size_t colon = line.find(':');
      if (colon != std::string::npos) {
        std::string k = line.substr(0, colon), v = line.substr(colon + 1);
        while (!v.empty() && v[0] == ' ') v.erase(0, 1);
        for (auto& c : k) c = char(tolower(c));
        if (k == "x-timestamp") r.timestamp = v;
        if (k == "x-signature") r.signature = v;
      }
      pos = end;
    }
    return r;
  }
};

struct RealClock : Clock {
  bool synced() const override { return true; }
  int64_t epochSeconds() const override { return int64_t(time(nullptr)); }
};

struct DevRandom : RandomSource {
  std::random_device rd;
  void fill(uint8_t* b, size_t len) override { for (size_t i = 0; i < len; ++i) b[i] = uint8_t(rd()); }
};

static uint32_t nowMs() {
  using namespace std::chrono;
  static auto t0 = steady_clock::now();
  return uint32_t(duration_cast<milliseconds>(steady_clock::now() - t0).count());
}

struct SimHal : DeviceHal {
  DoorController door;
  PresenceDetector presence;
  std::string pendingCard;
  int opens = 0;
  int maxAngle = 0;
  std::vector<std::string> doorLog;

  uint32_t millis() override { return nowMs(); }
  bool networkUp() override { return true; }
  int rssi() override { return -50; }
  uint32_t freeHeap() override { return 200000; }
  SensorSnapshot sensor() override {
    return {presence.present(), presence.distanceCm(), presence.sensorFault()};
  }
  void setPresenceThreshold(float cm) override { presence.setThreshold(cm); }
  bool readCard(std::string& uid) override {
    if (pendingCard.empty()) return false;
    uid = pendingCard;
    pendingCard.clear();
    return true;
  }
  bool rfidOk() override { return true; }
  bool openDoor(const OpenGrant& g) override {
    bool ok = door.open(g, nowMs());
    opens += ok;
    return ok;
  }
  void closeDoor(CloseReason r) override { door.emergencyClose(nowMs(), r); }
  DoorState doorState() override { return door.state(); }
  DoorEvent takeDoorEvent() override {
    DoorEvent e = door.takeEvent();
    if (e.type == DoorEvent::Type::OPENED) doorLog.push_back("OPENED");
    if (e.type == DoorEvent::Type::CLOSED) doorLog.push_back(std::string("CLOSED:") + closeReasonName(e.reason));
    return e;
  }
  void feedback(Feedback, const std::string&) override {}
  void log(const std::string& line) override { fprintf(stderr, "[%6u] %s\n", nowMs(), line.c_str()); }
};

int main(int argc, char** argv) {
  if (argc < 5) {
    fprintf(stderr, "usage: %s <host> <port> <secret> <seconds> [uid]\n", argv[0]);
    return 2;
  }
  PosixHttp http;
  http.host = argv[1];
  http.port = atoi(argv[2]);
  RealClock clock;
  DevRandom rng;
  BackendSettings bs;
  bs.deviceId = "DC-DOOR-01";
  bs.secret = argv[3];
  BackendClient client(bs, http, clock, rng);
  SimHal hal;
  ControllerTiming timing;
  timing.sessionGraceMs = 1000;
  AccessController ctl(hal, client, "1.0.0-host", timing);

  const uint32_t runMs = uint32_t(atoi(argv[4])) * 1000;
  const std::string uid = argc > 5 ? argv[5] : "04A1B2C3";
  bool cardSent = false;
  uint32_t lastPing = 0;
  while (nowMs() < runMs) {
    uint32_t t = nowMs();
    if (t - lastPing >= 60) { lastPing = t; hal.presence.update(true, 30.0f, t); }
    hal.door.tick(t);
    if (hal.door.angle() > hal.maxAngle) hal.maxAngle = hal.door.angle();
    if (!cardSent && t >= 1000) { hal.pendingCard = uid; cardSent = true; }
    ctl.tick();
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  std::string events;
  for (size_t i = 0; i < hal.doorLog.size(); ++i) events += (i ? ",\"" : "\"") + hal.doorLog[i] + "\"";
  printf("{\"opens\":%d,\"max_angle\":%d,\"door\":\"%s\",\"state\":\"%s\",\"online\":%s,\"door_events\":[%s]}\n",
         hal.opens, hal.maxAngle, doorStateName(hal.door.state()), systemStateName(ctl.state()),
         ctl.online() ? "true" : "false", events.c_str());
  return 0;
}
