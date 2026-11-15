// DC Guardian — ESP32 door firmware.
//
// The device NEVER decides access: it reports card UID + distance to the backend, waits for
// a signed GRANTED decision and only then moves the servo. See docs/protocolo-esp32.md.
#if !DCG_DIAG  // the diagnostics build (src/diag_main.cpp) has its own setup/loop

#include <Arduino.h>
#include <esp_task_wdt.h>

// Unique name on purpose: the ESP32 SDK ships other headers called "config.h".
#if __has_include("dcg_config.h")
#include "dcg_config.h"
#else
#error "Falta include/dcg_config.h: copia include/dcg_config.example.h a include/dcg_config.h y rellénalo."
#endif

#include "access_controller.h"
#include "backend_client.h"
#include "hal_esp32.h"
#include "lcd_esp32.h"
#include "net.h"
#include "pins.h"

#ifndef DCG_BENCH_MODE
#define DCG_BENCH_MODE 0
#endif
#ifndef DCG_BACKEND_CA_PEM
#define DCG_BACKEND_CA_PEM nullptr
#endif
// Older dcg_config.h files without the LCD section keep compiling (LCD on, autodetect).
// Optional second WiFi network (failover). "" password = open network.
#ifndef DCG_WIFI_SSID_2
#define DCG_WIFI_SSID_2 ""
#endif
#ifndef DCG_WIFI_PASSWORD_2
#define DCG_WIFI_PASSWORD_2 ""
#endif
#ifndef DCG_LCD_ENABLED
#define DCG_LCD_ENABLED 1
#endif
#ifndef DCG_LCD_I2C_ADDR
#define DCG_LCD_I2C_ADDR 0x00
#endif

static const char* kFirmwareVersion = "1.0.0";
static constexpr uint32_t kWatchdogS = 15;  // > worst case loop (3 HTTP calls × 3 s)

using namespace dcg;

static NtpClock ntpClock;
static HardwareRandom rng;
static Esp32HttpTransport transport;
static Esp32Hal* hal = nullptr;
static Lcd2004* lcd = nullptr;
static BackendClient* backend = nullptr;
static AccessController* controller = nullptr;
static bool configOk = false;

static bool isHex64(const char* s) {
  if (strlen(s) != 64) return false;
  for (const char* p = s; *p; ++p)
    if (!isxdigit((unsigned char)*p)) return false;
  // Refuse the placeholder from dcg_config.example.h.
  return strcmp(s, "0000000000000000000000000000000000000000000000000000000000000000") != 0;
}

// ------------------------------------------------------------------ serial console
static void printStatus() {
  SensorSnapshot s = hal->sensor();
  Serial.printf(
      "fw=%s state=%s online=%d door=%s angle=%d present=%d dist=%.1f raw=%.1f thr=%.0f "
      "fault=%d rfid=%d wifi=%d ssid=%s rssi=%d ntp=%d session=%s heap=%u lcd=%s\n",
      kFirmwareVersion, systemStateName(controller->state()), controller->online(),
      doorStateName(hal->doorState()), hal->doorAngle(), s.present, s.distanceCm,
      hal->rawDistance(), controller->config().presenceThresholdCm, s.fault, hal->rfidOk(),
      wifiUp(), wifiSsid(), hal->rssi(), ntpClock.synced(),
      controller->sessionId().empty() ? "-" : controller->sessionId().c_str(), hal->freeHeap(),
      (lcd && lcd->present()) ? lcd->screenName() : "none");
}

static void handleSerial() {
  static String line;
  while (Serial.available()) {
    char c = char(Serial.read());
    if (c != '\n' && c != '\r') {
      if (line.length() < 64) line += c;
      continue;
    }
    line.trim();
    if (line.isEmpty()) continue;
    if (line == "status") {
      printStatus();
    } else if (line == "close") {
      // Same effect as the physical emergency button: can only close, never open.
      controller->localEmergencyClose();
#if DCG_BENCH_MODE
    } else if (line.startsWith("uid ")) {
      String uid = line.substring(4);
      uid.toUpperCase();
      hal->benchInjectCard(uid.c_str());
      Serial.printf("[bench] card %s injected\n", uid.c_str());
    } else if (line.startsWith("dist ")) {
      String v = line.substring(5);
      hal->benchSetDistance(v == "off" ? -1.0f : v.toFloat());
      Serial.printf("[bench] distance override %s\n", v.c_str());
#endif
    } else {
      Serial.println("comandos: status | close"
#if DCG_BENCH_MODE
                     " | uid <HEX> | dist <cm>|off"
#endif
      );
    }
    line = "";
  }
}

// ------------------------------------------------------------------ setup / loop
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf("\nDC Guardian door firmware %s%s\n", kFirmwareVersion,
                DCG_BENCH_MODE ? "  ** BENCH MODE: no usar en producción **" : "");

  Esp32HalConfig hc;
  hc.door.closedAngle = DCG_SERVO_CLOSED_DEG;
  hc.door.openAngle = DCG_SERVO_OPEN_DEG;
  hc.door.travelMs = DCG_SERVO_TRAVEL_MS;
  hc.servoMinUs = DCG_SERVO_MIN_US;
  hc.servoMaxUs = DCG_SERVO_MAX_US;
  hal = new Esp32Hal(hc);
  hal->begin();  // servo is commanded CLOSED here, before any networking

#if DCG_LCD_ENABLED
  // Non-critical: without a display the door works exactly the same.
  lcd = new Lcd2004(PIN_LCD_SDA, PIN_LCD_SCL, DCG_LCD_I2C_ADDR);
  lcd->begin();
  hal->attachLcd(lcd);
  lcd->startTask(hal);
#endif

  configOk = isHex64(DCG_DEVICE_SECRET) && strlen(DCG_DEVICE_ID) > 0 &&
             transport.begin(DCG_BACKEND_URL, DCG_BACKEND_CA_PEM);
  if (!configOk) {
    Serial.println("[FATAL] Configuración inválida (secreto de 64 hex, URL http(s)://, CA si es "
                   "https). El dispositivo no operará; puerta cerrada.");
    hal->feedback(Feedback::ERROR, "CONFIG");
    if (lcd) lcd->setConfigError();
    return;
  }

  static const WifiNetwork networks[] = {{DCG_WIFI_SSID, DCG_WIFI_PASSWORD},
                                         {DCG_WIFI_SSID_2, DCG_WIFI_PASSWORD_2}};
  wifiBegin(networks, DCG_WIFI_SSID_2[0] ? 2 : 1);
  ntpClock.begin(DCG_NTP_SERVER_1, DCG_NTP_SERVER_2);

  BackendSettings bs;
  bs.deviceId = DCG_DEVICE_ID;
  bs.secret = DCG_DEVICE_SECRET;
  bs.apiPrefix = DCG_API_PREFIX;
  bs.clockSkewS = DCG_CLOCK_SKEW_S;
  backend = new BackendClient(bs, transport, ntpClock, rng);
  controller = new AccessController(*hal, *backend, kFirmwareVersion);

  // A hung loop resets the chip; after reset the servo is commanded CLOSED again.
  esp_task_wdt_init(kWatchdogS, true);
  esp_task_wdt_add(nullptr);
}

void loop() {
  if (!configOk) {  // misconfigured: stay closed forever, keep the console alive
    delay(1000);
    return;
  }
  esp_task_wdt_reset();

  static uint32_t lastRfidCheck = 0;
  if (millis() - lastRfidCheck > 5000) {
    lastRfidCheck = millis();
    hal->checkRfidHealth();
  }
  if (hal->takeButtonPress()) controller->localEmergencyClose();
  handleSerial();
  wifiTick();
  controller->tick();
  delay(10);
}

#endif  // !DCG_DIAG
