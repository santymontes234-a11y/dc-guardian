# Hardware de DC Guardian

Resumen del hardware de la puerta. El cableado detallado (diagrama ASCII, alimentación del
servo, comprobaciones antes de encender y niveles lógicos del LCD) está en
[cableado.md](cableado.md). Los pines salen de `firmware/esp32-door/include/pins.h`, y esta
tabla se ha copiado de ese archivo.

> Estado: el firmware **compila** (`esp32dev`, `esp32dev-diag`, `esp32dev-bench`) y pasa sus
> pruebas en el PC (`pio test -e native`) y contra el backend real (`test/integration`).
> **No se ha probado en una placa física** durante el desarrollo.

## 1. Lista de materiales

| Componente | Uso en el sistema | Notas |
|---|---|---|
| ESP32 DevKit v1 (ESP32-WROOM-32) | Controlador de la puerta: lee sensores, habla con el backend por HTTP firmado con HMAC y mueve el servo | Con una WROVER, los GPIO 16/17 no están libres (ver LCD) |
| RFID RC522 + tarjetas/llaveros MIFARE (13.56 MHz) | Primer factor: el UID se envía al backend, que es quien decide | **Solo 3.3 V** |
| Sensor ultrasónico HC-SR04 | Presencia frente a la puerta: sin presencia se ignora la tarjeta, y si la persona se aleja se deniega el acceso | Divisor 1 kΩ / 2 kΩ en ECHO |
| Servo SG90 (o MG996R) | Representa la cerradura: 0° cerrado, 90° abierto | MG996R exige fuente externa ≥ 2.5 A |
| LCD 2004 con módulo I2C PCF8574 (opcional) | Muestra el estado: esperando tarjeta, distancia, verificando, rostro, concedido o denegado, puerta y errores | Ver §3 |
| Pulsador | Cierre de emergencia local, que solo cierra y nunca abre | A GND, con pull-up interno |
| LED verde y LED rojo + 2 × 220 Ω (opcional) | Indicación visual | |
| Zumbador activo + 2N2222 + 1 kΩ (opcional) | Indicación sonora | |
| Webcam USB o integrada | Segundo factor: la usa el **navegador** del kiosco (`/pages/kiosk.html`), no el ESP32 | El kiosco debe abrirse en `http://localhost` o con HTTPS |
| PC con Linux | Ejecuta el backend (nativo o Docker) y el navegador del kiosco | Misma red WiFi que el ESP32 |
| Protoboard, cables dupont, resistencias 1 kΩ y 2 kΩ, condensador 470–1000 µF / ≥ 10 V | Montaje y filtrado del servo | |
| Fuente de 5 V ≥ 1 A (SG90) o ≥ 2.5 A (MG996R) | Alimentación del servo | GND común con el ESP32 |
| Conversor de nivel I2C BSS138 (recomendado si hay LCD) | Protege los GPIO del ESP32 de las pull-ups de 5 V del PCF8574 | Ver [cableado.md §5](cableado.md#5-pantalla-lcd-2004-i2c-opcional) |

## 2. Conexiones (verificadas en `pins.h`)

| Componente | Pin del componente | Pin ESP32 | Observaciones |
|---|---|---|---|
| RC522 | SDA/SS | GPIO 5 | Bus VSPI |
| RC522 | SCK | GPIO 18 | |
| RC522 | MOSI | GPIO 23 | |
| RC522 | MISO | GPIO 19 | |
| RC522 | RST | GPIO 22 | Por eso el LCD no usa el SCL por defecto |
| RC522 | 3.3V · GND | 3V3 · GND | **Nunca a 5 V** |
| HC-SR04 | TRIG | GPIO 26 | |
| HC-SR04 | ECHO | GPIO 27 | **A través de un divisor** 1 kΩ (serie) / 2 kΩ (a GND) |
| HC-SR04 | VCC · GND | 5V (VIN) · GND | |
| Servo | Señal | GPIO 13 | PWM 50 Hz, 500–2400 µs |
| Servo | V+ · GND | 5 V · GND común | No alimentar desde 3V3 |
| LCD 2004 (PCF8574) | SDA | GPIO 21 | I2C 100 kHz |
| LCD 2004 (PCF8574) | SCL | GPIO 17 | Configurable en `PIN_LCD_SCL` |
| LCD 2004 (PCF8574) | VCC · GND | 5V (VIN) · GND | Contraste con el potenciómetro del módulo |
| Pulsador de emergencia | un terminal | GPIO 4 | El otro a GND |
| LED verde | ánodo (con 220 Ω) | GPIO 25 | |
| LED rojo | ánodo (con 220 Ω) | GPIO 33 | |
| Zumbador | base del 2N2222 (con 1 kΩ) | GPIO 32 | |

Pines evitados a propósito: GPIO 0, 2, 12 y 15 (de arranque), 6–11 (flash) y 34–39 (solo entrada).

## 3. LCD 2004 I2C

### Configuración

| Parámetro | Valor | Dónde |
|---|---|---|
| Activación | `DCG_LCD_ENABLED 1` | `include/dcg_config.h` |
| Dirección I2C | `DCG_LCD_I2C_ADDR 0x00` = autodetección de **0x27** (PCF8574T) y **0x3F** (PCF8574AT) | `include/dcg_config.h` |
| Pines | `PIN_LCD_SDA = 21`, `PIN_LCD_SCL = 17` | `include/pins.h` |
| Bus | 100 kHz y timeout de 10 ms por transacción | `src/lcd_esp32.cpp` |
| Alimentación | 5 V (VIN) con conversor de nivel o pull-ups a 3.3 V | [cableado.md §5](cableado.md#5-pantalla-lcd-2004-i2c-opcional) |
| Librerías | Solo `Wire` (incluida en el core de Arduino-ESP32) | Driver propio HD44780/PCF8574 |

No se usa `LiquidCrystal_I2C` porque esas librerías llaman a `Wire.begin()` con los pines por
defecto (21/22), y el GPIO 22 ya es el RST del RC522.

Para encontrar la dirección y probar la pantalla, usa el firmware de diagnóstico:
`pio run -e esp32dev-diag -t upload` y, en la consola serie, `lcd`. Escanea el bus I2C y escribe
un patrón de prueba con la dirección detectada.

### Máquina de estados de la pantalla

La lógica es pura y tiene pruebas (`lib/dcg_core/src/lcd_view.*`, `test/test_lcd`, 14 casos).
Las pantallas usan solo ASCII, porque la ROM A00 del HD44780 no tiene tildes.

| # | Pantalla (`LcdScreen`) | Cuándo | Línea 1 |
|---|---|---|---|
| 1 | `WAIT_CARD` | Reposo, en línea, sin presencia | `DC GUARDIAN  ONLINE` · `Esperando tarjeta` |
| 2 | `PRESENCE` | HC-SR04 por debajo del umbral | `PRESENCIA DETECTADA` |
| 3 | (distancia) | Línea 4 de `WAIT_CARD`, `PRESENCE`, `RFID_READ`, `VERIFYING` y `DOOR_OPEN` | `Dist: 34.5 cm` / `Dist: --- cm` / `Dist: FALLO SENSOR` |
| 4 | `RFID_READ` | Tarjeta leída, enviándose al backend | `RFID DETECTADO` + UID |
| 5 | `VERIFYING` | Esperando la decisión del backend | `VERIFICANDO` `AUTORIZACION` |
| 6 | `FACE` | El backend responde `AWAITING_FACE` | `RECONOCIMIENTO` `FACIAL` `Mire a la camara` |
| 7 | `GRANTED` | Decisión `GRANTED` firmada (1.5 s) | `ACCESO AUTORIZADO` |
| 8 | `DENIED` | Denegación (3 s), con el motivo abreviado | `ACCESO DENEGADO` + motivo |
| 9 | `DOOR_OPEN` / `DOOR_CLOSING` | Servo abriendo o abierto / cerrando | `PUERTA ABIERTA` / `CERRANDO PUERTA` |
| 10 | `DOOR_CLOSED` | Fin del ciclo de puerta (2 s) | `PUERTA CERRADA` |
| 11 | `CONN_ERROR` / `ACCESS_ERROR` | Hay WiFi pero el backend o NTP no responden / un intento abortado por la red | `ERROR DE CONEXION` |
| 12 | `DISCONNECTED` | Sin WiFi | `SISTEMA DESCONECTADO` |
| – | `SENSOR_ERROR`, `CONFIG_ERROR`, `BOOT` | Fallo del RC522 o del HC-SR04 · `dcg_config.h` inválido · arranque | |

### Por qué no bloquea

- La pantalla tiene su **propia tarea FreeRTOS** (`lcd`, núcleo 0, prioridad 1, cada 100 ms). La
  lectura RFID y el HTTP corren en el `loop()` (núcleo 1). El servo y el HC-SR04 corren en la tarea `io`
  (núcleo 1, prioridad 3). Ninguna de ellas toca el bus I2C.
- El controlador solo notifica eventos (`onStateChange`, `onCardDetected`, `onSessionPhase` y
  `feedback`). Cada evento copia unos pocos bytes bajo un mutex.
- Solo se envían los caracteres que cambiaron (unos 0.5 ms por carácter).
- Si el LCD deja de responder, la tarea lo vuelve a buscar cada 5 s. La puerta no depende de la pantalla.

## 4. Firmware

Compilación, configuración (`dcg_config.h`), carga y consola serie:
[firmware/esp32-door/README.md](../firmware/esp32-door/README.md) y
[installation.md §4](installation.md#4-firmware-esp32).
