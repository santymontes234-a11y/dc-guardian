# Cableado del ESP32 (DC Guardian)

Placa: **ESP32 DevKit v1** (ESP32-WROOM-32, 30 o 38 pines). Los pines están definidos en
`firmware/esp32-door/include/pins.h`.

## 1. Tabla de pines

| Componente | Pin del módulo | Pin ESP32 | Alimentación | Notas |
|---|---|---|---|---|
| RC522 | SDA (SS) | GPIO 5 | **3.3 V** | VSPI. GPIO 5 es pin de arranque, pero el SS queda en reposo en alto y no da problemas |
| RC522 | SCK | GPIO 18 | | |
| RC522 | MOSI | GPIO 23 | | |
| RC522 | MISO | GPIO 19 | | |
| RC522 | RST | GPIO 22 | | |
| RC522 | IRQ | — | | Sin conectar (se usa sondeo) |
| RC522 | 3.3V / GND | 3V3 / GND | | **No conectar a 5 V**: el RC522 no los tolera |
| HC-SR04 | TRIG | GPIO 26 | **5 V** | 3.3 V basta para disparar el TRIG |
| HC-SR04 | ECHO | GPIO 27 **vía divisor** | | ECHO sale a 5 V: 1 kΩ en serie + 2 kΩ a GND ⇒ unos 3.3 V |
| HC-SR04 | VCC / GND | 5V (VIN) / GND | | |
| Servo | Señal (naranja) | GPIO 13 | | PWM 50 Hz, 500–2400 µs |
| Servo | V+ (rojo) | **5 V** (ver §3) | **5 V** | Nunca desde el pin 3V3 |
| Servo | GND (marrón) | GND común | | |
| Botón de emergencia | un terminal | GPIO 4 | | El otro terminal a GND (pull-up interno, activo en bajo) |
| LED verde | ánodo | GPIO 25 → 220 Ω | | Cátodo a GND |
| LED rojo | ánodo | GPIO 33 → 220 Ω | | Cátodo a GND |
| Zumbador activo | | GPIO 32 → 1 kΩ → base NPN | 5 V | 2N2222: emisor a GND, colector al zumbador (−) y zumbador (+) a 5 V |
| LCD 2004 + PCF8574 (opcional) | SDA | GPIO 21 | **5 V** | I2C a 100 kHz; dirección 0x27 o 0x3F (autodetección). Ver §5 sobre las pull-ups |
| LCD 2004 + PCF8574 | SCL | **GPIO 17** | | No es el GPIO 22 por defecto: el GPIO 22 es el RST del RC522. Válido en placas **WROOM-32**; en una **WROVER** (con PSRAM) el GPIO 16/17 está ocupado: usa GPIO 14 y cambia `PIN_LCD_SCL` |
| LCD 2004 + PCF8574 | VCC / GND | 5V (VIN) / GND | | El contraste se ajusta con el potenciómetro del módulo |

Pines que se evitan a propósito: GPIO 0, 2, 12 y 15 (de arranque), GPIO 6–11 (flash interna) y GPIO 34–39 (solo entrada).

## 2. Diagrama de conexiones

```
                         ┌─────────────────────────────┐
     USB 5 V ───────────►│ VIN(5V)       ESP32 DevKit  │
                         │ 3V3 ──────────────┐         │
                         │ GND ─────┐        │         │
                         └──────────┼────────┼─────────┘
                                    │        │
   ┌──────────── RC522 ──────────┐  │        │
   │ 3.3V ◄──────────────────────┼──┼────────┘
   │ GND  ◄──────────────────────┼──┤
   │ SDA  ◄── GPIO 5             │  │
   │ SCK  ◄── GPIO 18            │  │
   │ MOSI ◄── GPIO 23            │  │
   │ MISO ──► GPIO 19            │  │
   │ RST  ◄── GPIO 22            │  │
   └─────────────────────────────┘  │
                                    │
   ┌──────────── HC-SR04 ────────┐  │
   │ VCC  ◄── 5V (VIN)           │  │
   │ TRIG ◄── GPIO 26            │  │
   │ ECHO ──┬── 1 kΩ ──► GPIO 27 │  │        ECHO 5 V ──[1k]──┬──► GPIO 27 (≈3.3 V)
   │        │                    │  │                         [2k]
   │ GND  ◄─┼────────────────────┼──┤                          GND
   └────────┼────────────────────┘  │
            └── 2 kΩ ── GND ────────┤
                                    │
   ┌──────────── Servo ──────────┐  │      ┌──────── Fuente 5 V (≥1 A SG90, ≥2.5 A MG996R) ──┐
   │ Señal ◄── GPIO 13           │  │      │ +5 V ───┬──────────► Servo V+                     │
   │ V+    ◄── 5 V (ver §3) ─────┼──┼──────┤         ═╪═ 470 µF / 10 V (junto al servo)      │
   │ GND   ────────────────────────┴──────┤ GND ────┴──────────► Servo GND y GND del ESP32    │
   └─────────────────────────────┘         └──────────────────────────────────────────────────┘

   Botón:   GPIO 4 ──[pulsador]── GND
   LEDs:    GPIO 25 ──[220 Ω]──►|── GND (verde)     GPIO 33 ──[220 Ω]──►|── GND (rojo)
   Zumbador: GPIO 32 ──[1 kΩ]── base 2N2222; colector ── (−)zumbador(+) ── 5 V; emisor ── GND
```

## 3. Alimentación del servo (importante)

| Servo | Consumo típico | Pico/bloqueo | Cómo alimentarlo |
|---|---|---|---|
| **SG90** (9 g) | 100–250 mA | unos 650 mA | Pin VIN/5V del DevKit **solo** con un buen cable USB y un puerto de ≥1 A. Si el ESP32 se reinicia al mover el servo (brown-out), pasa a fuente externa |
| **MG996R** | 500–900 mA | **2.5 A** | **Siempre con fuente externa de 5–6 V y ≥2.5 A**. Nunca desde el ESP32 ni desde USB |

Reglas:

1. **GND común**: la masa de la fuente externa debe unirse a la del ESP32. Sin ella, la señal PWM no tiene referencia.
2. **Condensador de 470 µF–1000 µF** (≥10 V) entre +5 V y GND, pegado al conector del servo. Absorbe los picos de arranque.
3. **Nunca alimentar el servo desde 3V3.** El regulador del DevKit (AMS1117, unos 800 mA) se satura y resetea el chip.
4. El firmware limita el recorrido a 0°–90° y lo barre en 600 ms. Así no fuerza los topes mecánicos y reduce el pico de corriente. Con un MG996R ajusta `DCG_SERVO_MIN_US/MAX_US` (1000–2000 µs típicos) en `dcg_config.h`.
5. El ESP32 y los demás módulos pueden seguir con USB aunque el servo use su propia fuente.

## 4. Comprobaciones antes de encender

- [ ] RC522 conectado a **3.3 V** y no a 5 V.
- [ ] Divisor en el ECHO del HC-SR04: medir unos 3.3 V con el pulso en alto, o comprobar las resistencias de 1 kΩ y 2 kΩ.
- [ ] GND común entre el ESP32, la fuente del servo y el HC-SR04.
- [ ] Condensador del servo con la polaridad correcta (la franja va a GND).
- [ ] Servo sin acoplar al mecanismo en la primera prueba. Al arrancar debe ir a 0° (cerrado).

## 5. Pantalla LCD 2004 I2C (opcional)

Se activa con `DCG_LCD_ENABLED` en `dcg_config.h`. Es solo informativa: si no está conectada
o falla, el control de acceso funciona igual, porque la puerta no depende de ella.

```
   ┌──── LCD 2004 + PCF8574 ────┐
   │ VCC ◄── 5V (VIN)           │
   │ GND ◄── GND común          │
   │ SDA ◄─► GPIO 21            │
   │ SCL ◄── GPIO 17            │
   └────────────────────────────┘
```

**Niveles lógicos.** El módulo PCF8574 lleva pull-ups (normalmente de 4.7 kΩ) a su VCC. Si se
alimenta a 5 V, el SDA y el SCL quedan a 5 V en reposo, y los GPIO del ESP32 **no toleran 5 V**
según su hoja de datos. Hay tres opciones, de más a menos recomendable:

1. **Conversor de nivel I2C bidireccional** (BSS138, 4 canales) entre el módulo y el ESP32: el lado HV a 5 V y el LV a 3.3 V.
2. **Retirar las pull-ups del módulo** (R5/R6, o el puente correspondiente) y poner 4.7 kΩ de SDA y SCL a **3.3 V**. El PCF8574 reconoce 3.3 V como nivel alto con VCC = 5 V.
3. Alimentar el módulo a 3.3 V. Funciona en algunos LCD, pero normalmente el contraste queda muy bajo.

Comprobación: con el multímetro, el SDA y el SCL en reposo deben medir **≤ 3.3 V** respecto a GND.
Prueba individual: el comando `lcd` del firmware de diagnóstico (`esp32dev-diag`).
