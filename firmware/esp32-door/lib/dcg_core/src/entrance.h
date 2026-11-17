// Main entrance (QR) signal (contrato-qr-dht11.md §3, protocolo §10).
//
// The kiosk browser scans the QR; the backend decides and queues ONE signal for this device.
// The firmware polls POST /device/entrance/poll every second and only shows the outcome:
//   GRANTED ⇒ entrance green LED (GPIO 14) for led_ms + LCD 3 s
//   DENIED  ⇒ red LED blinks 3 times + short beep + LCD
// then acknowledges with POST /device/entrance/{id}/ack.
//
// Security invariants (tested in test/test_entrance):
//  * This module never moves the servo of the server room: the entrance actuator is a LED.
//  * Unsigned / badly signed / malformed replies are ignored entirely (the LED stays off).
//  * id must be 32 lowercase hex before it goes into the ack URL; led_ms 1000–10000.
//  * display_name is untrusted text: printable ASCII ≤ 40 chars, used only for the LCD.
//  * The same signal id is never shown twice.
#pragma once

#include <cstdint>
#include <string>

#include "access_controller.h"
#include "backend_client.h"
#include "protocol.h"

namespace dcg {

struct EntranceTiming {
  uint32_t pollMs = 1000;          // contract: poll every 1000 ms
  uint32_t errorBackoffMs = 5000;  // after a failed poll, so a dead backend cannot stall the loop
  uint8_t ackMaxAttempts = 3;
};

class EntrancePoller {
 public:
  EntrancePoller(DeviceHal& hal, Backend& backend, EntranceTiming t = {})
      : hal_(hal), backend_(backend), t_(t) {}

  // At most one HTTP call per tick (poll or a pending ack). Returns true if it made one.
  // Does nothing while `online` is false (fail-closed: no signal, LED stays off).
  bool tick(uint32_t now, bool online);

  uint32_t shown() const { return shown_; }        // signals shown so far
  const std::string& lastId() const { return lastId_; }

 private:
  void handle(const EntranceSignal& s);

  DeviceHal& hal_;
  Backend& backend_;
  EntranceTiming t_;
  bool started_ = false;
  uint32_t nextMs_ = 0;
  std::string lastId_;   // last signal acted upon (dedup)
  std::string ackId_;    // pending ack ("" = none)
  uint8_t ackAttempts_ = 0;
  uint32_t shown_ = 0;
};

}  // namespace dcg
