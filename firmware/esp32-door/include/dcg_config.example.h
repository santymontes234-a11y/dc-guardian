// DC Guardian — device configuration.
// Copy to include/dcg_config.h (gitignored) and fill in. NEVER commit dcg_config.h.
#pragma once

// ---------------------------------------------------------------- WiFi
#define DCG_WIFI_SSID "MiRedWiFi"
#define DCG_WIFI_PASSWORD "cambia-esto"

// ---------------------------------------------------------------- backend
// Base URL without trailing slash. The PC running FastAPI must listen on 0.0.0.0:
//   uvicorn app.main:app --host 0.0.0.0 --port 8000
#define DCG_BACKEND_URL "http://192.168.1.10:8000"
#define DCG_API_PREFIX "/api/v1"

// Identity: device_code and the secret shown ONCE by POST /api/v1/devices
// (or after rotating it). 64 hex characters.
#define DCG_DEVICE_ID "DC-DOOR-01"
#define DCG_DEVICE_SECRET "0000000000000000000000000000000000000000000000000000000000000000"

// Optional HTTPS: if DCG_BACKEND_URL starts with https:// you MUST define the CA (PEM).
// #define DCG_BACKEND_CA_PEM R"PEM(
// -----BEGIN CERTIFICATE-----
// ...
// -----END CERTIFICATE-----
// )PEM"

// ---------------------------------------------------------------- time
#define DCG_NTP_SERVER_1 "pool.ntp.org"
#define DCG_NTP_SERVER_2 "time.google.com"
#define DCG_CLOCK_SKEW_S 30  // must match DCG_DEVICE_CLOCK_SKEW_S on the backend

// ---------------------------------------------------------------- servo calibration
#define DCG_SERVO_CLOSED_DEG 0
#define DCG_SERVO_OPEN_DEG 90       // limit the travel: never force the mechanical stop
#define DCG_SERVO_MIN_US 500        // SG90: 500–2400 µs. MG996R: 1000–2000 µs typical
#define DCG_SERVO_MAX_US 2400
#define DCG_SERVO_TRAVEL_MS 600     // sweep time 0°→90° (gentler current peak)

// ---------------------------------------------------------------- LCD 2004 I2C (optional)
#define DCG_LCD_ENABLED 1
#define DCG_LCD_I2C_ADDR 0x00       // 0x00 = autodetect (0x27 PCF8574T / 0x3F PCF8574AT)
