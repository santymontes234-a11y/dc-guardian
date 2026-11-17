// Pin map (ESP32 DevKit v1, 30/38 pins). See docs/cableado.md for the wiring diagram.
#pragma once

// RC522 (SPI VSPI) — power at 3.3 V ONLY
constexpr int PIN_RFID_SS = 5;     // SDA/SS
constexpr int PIN_RFID_SCK = 18;
constexpr int PIN_RFID_MOSI = 23;
constexpr int PIN_RFID_MISO = 19;
constexpr int PIN_RFID_RST = 22;

// HC-SR04 — 5 V module; ECHO goes through a 1 kΩ / 2 kΩ divider (5 V → 3.3 V)
constexpr int PIN_US_TRIG = 26;
constexpr int PIN_US_ECHO = 27;

// Servo SG90 / MG996R — signal only; power from 5 V (external supply for MG996R)
constexpr int PIN_SERVO = 13;

// Inside exit button (to GND, internal pull-up): opens only if the backend says someone is inside
constexpr int PIN_EMERGENCY_BTN = 4;

// LCD 2004 + PCF8574 I2C backpack. NOT the ESP32 default I2C pins (21/22): GPIO 22 is the
// RC522 RST, so SCL moves to GPIO 17. Backpack at 5 V: see docs/cableado.md §5 (pull-ups / level shifter).
constexpr int PIN_LCD_SDA = 21;
constexpr int PIN_LCD_SCL = 17;

// Feedback (optional): LEDs through 220 Ω, active buzzer through NPN transistor
constexpr int PIN_LED_GREEN = 25;
constexpr int PIN_LED_RED = 33;
constexpr int PIN_BUZZER = 32;

// DHT11 temperature/humidity of the server room. DATA with a 10 kΩ pull-up to 3.3 V
// (the 3-pin module already has it). VCC 3.3 V. GPIO 16 is free on the DevKit v1 (WROOM-32;
// on WROVER modules it belongs to the PSRAM).
constexpr int PIN_DHT = 16;

// Main entrance (QR) green LED through 220 Ω. Distinct from PIN_LED_GREEN (room door).
constexpr int PIN_LED_ENTRANCE = 14;

// Fan: yellow LED through 220 Ω, or a relay module ONLY through an NPN transistor (+ flyback
// diode on a bare coil). GPIO 2 is a strapping pin: the LED/NPN base pull it LOW at boot, which
// is the safe value. The DevKit on-board blue LED is on GPIO 2 too, so it lights with the fan.
constexpr int PIN_FAN = 2;
