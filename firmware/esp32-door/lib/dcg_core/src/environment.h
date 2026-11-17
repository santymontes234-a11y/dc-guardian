// DHT11 environment monitoring of the server room (contrato-qr-dht11.md §4, protocolo §11).
//
//  * The HAL reads the DHT11 every 2 s (takeDhtSample). 3 failed reads in a row, or no read
//    at all for staleMs, put the sensor in ERROR.
//  * Every 10 s the last valid reading (or sensor ERROR with null values) goes to
//    POST /device/environment. The signed reply {fan, alarm} is applied.
//  * Local fallback when the backend is unreachable, the reply is badly signed or malformed:
//    the fan follows temp_high_c with 1 °C hysteresis and the alarm follows temp_critical_c /
//    humidity range, both computed on the device. "When in doubt, cool": the local fan
//    decision is OR-ed with the backend's, so a reply can never switch off a fan the local
//    thresholds require.
//  * Sensor in ERROR ⇒ fan OFF (no data to justify it) and the LCD shows the error.
//
// The environment never touches the door or the access state machine.
#pragma once

#include <cstdint>

#include "access_controller.h"
#include "backend_client.h"
#include "protocol.h"

namespace dcg {

struct EnvTiming {
  uint32_t sendEveryMs = 10000;   // POST /device/environment period
  uint8_t failuresForError = 3;   // consecutive failed reads ⇒ sensor ERROR
  uint32_t staleMs = 10000;       // no read finished for this long ⇒ sensor ERROR
  uint32_t remoteValidMs = 25000; // a backend decision older than this falls back to local
  float fanHysteresisC = 1.0f;    // fan OFF below temp_high_c - this
};

class EnvController {
 public:
  EnvController(DeviceHal& hal, Backend& backend, EnvTiming t = {})
      : hal_(hal), backend_(backend), t_(t) {}

  // Thresholds already validated by the heartbeat parser (DeviceConfig.env).
  void setThresholds(const EnvThresholds& th);

  // Drains the HAL samples and, if due, `online` and `mayCall`, sends the reading.
  // Returns true when it made an HTTP call (the main loop allows one auxiliary call per pass;
  // with mayCall=false a due send simply waits for the next pass).
  bool tick(uint32_t now, bool online, bool mayCall = true);

  // Feeds one DHT read directly (tick() does it from the HAL; public for tests/diagnostics).
  void onSample(const DhtSample& s, uint32_t now);

  const EnvStatus& status() const { return st_; }
  bool sensorOk() const { return st_.sensor != DhtStatus::ERROR; }

 private:
  bool localFan() const;
  bool localAlarm() const;
  void updateLocalFan();
  void recompute(uint32_t now);
  void publish();

  DeviceHal& hal_;
  Backend& backend_;
  EnvTiming t_;
  EnvStatus st_;

  bool hasValid_ = false;
  uint8_t failures_ = 0;
  bool anySample_ = false;
  uint32_t lastSampleMs_ = 0;

  bool localFanOn_ = false;       // hysteresis memory
  bool remoteOk_ = false;         // last send got a valid signed reply
  uint32_t remoteAtMs_ = 0;
  EnvReply remote_;

  bool started_ = false;
  uint32_t nextSendMs_ = 0;

  EnvStatus published_;
  bool everPublished_ = false;
};

}  // namespace dcg
