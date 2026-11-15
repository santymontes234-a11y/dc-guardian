// Bring-up / individual hardware tests (env: esp32dev-diag). NO network, NO access logic.
//
// WARNING: this build can move the servo on a serial command. Use it only on the bench,
// with the servo NOT attached to a real door, and flash the normal firmware afterwards.
#if DCG_DIAG

#include <Arduino.h>
#include <ESP32Servo.h>
#include <MFRC522.h>
#include <SPI.h>

#include "lcd_esp32.h"
#include "pins.h"
#include "presence.h"
#include "protocol.h"

static MFRC522 rfid(PIN_RFID_SS, PIN_RFID_RST);
static Servo servo;
static dcg::PresenceDetector presence;
enum class Mode { IDLE, RFID, DIST, BUTTON };
static Mode mode = Mode::IDLE;

static float ping(bool& valid) {
  digitalWrite(PIN_US_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_US_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_US_TRIG, LOW);
  unsigned long us = pulseIn(PIN_US_ECHO, HIGH, 25000);
  valid = us > 0;
  return valid ? us * 0.0343f / 2 : -1;
}

static void help() {
  Serial.println(
      "DIAG: rfid | dist | servo <0-180> | sweep | led | buzz | button | lcd | stop | info");
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n*** DC Guardian DIAG firmware: solo banco de pruebas ***");
  ESP32PWM::allocateTimer(0);
  servo.setPeriodHertz(50);
  servo.attach(PIN_SERVO, 500, 2400);
  servo.write(0);
  pinMode(PIN_US_TRIG, OUTPUT);
  pinMode(PIN_US_ECHO, INPUT);
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_EMERGENCY_BTN, INPUT_PULLUP);
  SPI.begin(PIN_RFID_SCK, PIN_RFID_MISO, PIN_RFID_MOSI, PIN_RFID_SS);
  rfid.PCD_Init();
  help();
}

static void info() {
  byte v = rfid.PCD_ReadRegister(MFRC522::VersionReg);
  Serial.printf("RC522 VersionReg=0x%02X (%s)  heap=%u\n", v,
                (v == 0x91 || v == 0x92) ? "OK" : (v == 0 || v == 0xFF) ? "SIN RESPUESTA" : "clon/otro",
                ESP.getFreeHeap());
  rfid.PCD_DumpVersionToSerial();
}

// I2C scan on the LCD pins + test pattern (shows the detected address on the display).
static void lcdTest() {
  uint8_t found[16];
  int n = dcg::Lcd2004::scan(PIN_LCD_SDA, PIN_LCD_SCL, found, 16);
  Serial.printf("I2C SDA=%d SCL=%d: %d dispositivo(s)", PIN_LCD_SDA, PIN_LCD_SCL, n);
  for (int i = 0; i < n; ++i) Serial.printf(" 0x%02X", found[i]);
  Serial.println(n ? "" : "  -> revisa cableado, alimentación y pull-ups");
  static dcg::Lcd2004 lcd(PIN_LCD_SDA, PIN_LCD_SCL);
  if (!lcd.begin()) return;
  char addr[21];
  snprintf(addr, sizeof addr, "I2C addr: 0x%02X", lcd.address());
  const char* lines[4] = {"DC GUARDIAN  DIAG", "LCD 2004 OK", addr, "12345678901234567890"};
  Serial.println(lcd.writeLines(lines) ? "Patrón enviado: ajusta el contraste (potenciómetro azul)"
                                       : "Error de escritura I2C");
}

static void command(String c) {
  c.trim();
  if (c == "rfid") { mode = Mode::RFID; Serial.println("Acerca tarjetas (stop para salir)"); }
  else if (c == "dist") { mode = Mode::DIST; Serial.println("raw_cm  median_cm  present"); }
  else if (c == "button") { mode = Mode::BUTTON; Serial.println("Pulsa el botón de emergencia"); }
  else if (c == "stop") mode = Mode::IDLE;
  else if (c == "info") info();
  else if (c == "lcd") lcdTest();
  else if (c.startsWith("servo ")) {
    int a = constrain(c.substring(6).toInt(), 0, 180);
    servo.write(a);
    Serial.printf("servo -> %d°\n", a);
  } else if (c == "sweep") {
    for (int a = 0; a <= 90; a += 2) { servo.write(a); delay(14); }
    delay(1000);
    for (int a = 90; a >= 0; a -= 2) { servo.write(a); delay(14); }
    Serial.println("sweep 0→90→0 OK");
  } else if (c == "led") {
    digitalWrite(PIN_LED_GREEN, HIGH); delay(500); digitalWrite(PIN_LED_GREEN, LOW);
    digitalWrite(PIN_LED_RED, HIGH); delay(500); digitalWrite(PIN_LED_RED, LOW);
    Serial.println("verde, rojo");
  } else if (c == "buzz") {
    digitalWrite(PIN_BUZZER, HIGH); delay(200); digitalWrite(PIN_BUZZER, LOW);
  } else help();
}

void loop() {
  static String line;
  while (Serial.available()) {
    char ch = char(Serial.read());
    if (ch == '\n' || ch == '\r') { if (line.length()) command(line); line = ""; }
    else if (line.length() < 32) line += ch;
  }
  switch (mode) {
    case Mode::RFID:
      if (rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {
        Serial.printf("UID=%s  tipo=%s\n",
                      dcg::uidToHex(rfid.uid.uidByte, rfid.uid.size).c_str(),
                      String(MFRC522::PICC_GetTypeName(rfid.PICC_GetType(rfid.uid.sak))).c_str());
        rfid.PICC_HaltA();
        rfid.PCD_StopCrypto1();
      }
      break;
    case Mode::DIST: {
      bool valid;
      float cm = ping(valid);
      presence.update(valid, cm, millis());
      Serial.printf("%7.1f  %9.1f  %d%s\n", cm, presence.distanceCm(), presence.present(),
                    presence.sensorFault() ? "  FALLO SENSOR" : "");
      delay(60);
      break;
    }
    case Mode::BUTTON: {
      static int last = HIGH;
      int b = digitalRead(PIN_EMERGENCY_BTN);
      if (b != last) { Serial.println(b == LOW ? "PULSADO" : "suelto"); last = b; delay(30); }
      break;
    }
    case Mode::IDLE: break;
  }
}

#endif  // DCG_DIAG
