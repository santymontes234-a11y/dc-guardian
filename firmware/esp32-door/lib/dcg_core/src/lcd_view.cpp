#include "lcd_view.h"

#include <cstdio>
#include <cstring>

#include "protocol.h"

namespace dcg {

namespace {
inline bool before(uint32_t now, uint32_t until) { return int32_t(until - now) > 0; }

struct Reason {
  const char* code;
  const char* text;  // ≤ 20 ASCII chars
};

// Backend reason codes (app/services/access_engine.py REASON_TEXT) and firmware abort reasons.
constexpr Reason kReasons[] = {
    {"UNKNOWN_CARD", "Tarjeta desconocida"},
    {"CARD_NOT_ACTIVE", "Tarjeta no activa"},
    {"CARD_LOCKED", "Tarjeta bloqueada"},
    {"CARD_NOT_LINKED", "Tarjeta sin titular"},
    {"ENGINEER_INACTIVE", "Ingeniero inactivo"},
    {"NO_VALID_AUTH", "Sin autorizacion"},
    {"REQUEST_PENDING", "Solicitud pendiente"},
    {"AUTH_EXPIRED", "Autorizacion vencida"},
    {"AUTH_REVOKED", "Autoriz. revocada"},
    {"AUTH_NOT_STARTED", "Fuera de horario"},
    {"AUTH_REJECTED", "Solicitud rechazada"},
    {"NO_FACE_ENROLLED", "Rostro no registrado"},
    {"FACE_MISMATCH", "Rostro no coincide"},
    {"LIVENESS_FAILED", "Prueba de vida fallo"},
    {"FACE_NOT_DETECTED", "Rostro no detectado"},
    {"MULTIPLE_FACES", "Varios rostros"},
    {"MODEL_MISMATCH", "Otro modelo facial"},
    {"BIOMETRIC_ERROR", "Error biometrico"},
    {"PRESENCE_LOST", "Presencia perdida"},
    {"NO_PRESENCE", "Sin presencia"},
    {"SENSOR_ERROR", "Error de sensor"},
    {"DEVICE_DISABLED", "Puerta deshabilitada"},
    {"TIMEOUT", "Tiempo agotado"},
    {"SESSION_SUPERSEDED", "Intento reemplazado"},
    {"LOCAL_EMERGENCY", "Cierre emergencia"},
    {"EMERGENCY_CLOSE", "Cierre emergencia"},
    {"NETWORK_ERROR", "Sin respuesta red"},
    {"HTTP_ERROR", "Error del servidor"},
    {"BAD_SIGNATURE", "Firma invalida"},
    {"BAD_PAYLOAD", "Respuesta invalida"},
    {"CLOCK_NOT_SYNCED", "Reloj sin sincron."},
    {"SESSION_MISMATCH", "Sesion incorrecta"},
    {"DOOR_BUSY", "Puerta ocupada"},
    {"OPEN_REJECTED", "Apertura rechazada"},
    {"INTERRUPTED", "Intento interrumpido"},
    {"OFFLINE", "Sin conexion"},
};

std::string fit(const std::string& s) { return s.size() > 20 ? s.substr(0, 20) : s; }
}  // namespace

const char* lcdScreenName(LcdScreen s) {
  switch (s) {
    case LcdScreen::BOOT: return "BOOT";
    case LcdScreen::CONFIG_ERROR: return "CONFIG_ERROR";
    case LcdScreen::DISCONNECTED: return "DISCONNECTED";
    case LcdScreen::CONN_ERROR: return "CONN_ERROR";
    case LcdScreen::SENSOR_ERROR: return "SENSOR_ERROR";
    case LcdScreen::WAIT_CARD: return "WAIT_CARD";
    case LcdScreen::PRESENCE: return "PRESENCE";
    case LcdScreen::RFID_READ: return "RFID_READ";
    case LcdScreen::VERIFYING: return "VERIFYING";
    case LcdScreen::FACE: return "FACE";
    case LcdScreen::GRANTED: return "GRANTED";
    case LcdScreen::DENIED: return "DENIED";
    case LcdScreen::ACCESS_ERROR: return "ACCESS_ERROR";
    case LcdScreen::DOOR_OPEN: return "DOOR_OPEN";
    case LcdScreen::DOOR_CLOSING: return "DOOR_CLOSING";
    case LcdScreen::DOOR_CLOSED: return "DOOR_CLOSED";
    case LcdScreen::ALARM: return "ALARM";
    case LcdScreen::ENTRANCE_GRANTED: return "ENTRANCE_GRANTED";
    case LcdScreen::ENTRANCE_DENIED: return "ENTRANCE_DENIED";
    case LcdScreen::ENV_ALARM: return "ENV_ALARM";
  }
  return "?";
}

const char* LcdView::reasonShort(const std::string& code) {
  for (const Reason& r : kReasons)
    if (code == r.code) return r.text;
  return nullptr;
}

void LcdView::onFeedback(Feedback f, const std::string& reason, uint32_t nowMs) {
  // Persistent modes (READY, PRESENCE, WAITING, OFFLINE, ERROR without reason) are already
  // reflected by LcdInput.state; only outcomes of an attempt become transient screens.
  switch (f) {
    case Feedback::GRANTED:
      flash_ = LcdScreen::GRANTED;
      flashUntil_ = nowMs + t_.grantedMs;
      break;
    case Feedback::DENIED:
      flash_ = LcdScreen::DENIED;
      flashUntil_ = nowMs + t_.deniedMs;
      break;
    case Feedback::ERROR:
      if (reason.empty()) return;
      flash_ = LcdScreen::ACCESS_ERROR;
      flashUntil_ = nowMs + t_.errorMs;
      break;
    default:
      return;
  }
  flashReason_ = reason;
  flashActive_ = true;
}

void LcdView::onEntrance(bool granted, const std::string& name, uint32_t nowMs) {
  entranceActive_ = true;
  entranceGranted_ = granted;
  entranceName_ = sanitizeLcdText(name, 40);
  entranceUntil_ = nowMs + t_.entranceMs;
}

LcdScreen LcdView::pick(const LcdInput& in, uint32_t now) {
  if (flashActive_ && !before(now, flashUntil_)) flashActive_ = false;

  // Door cycle: remember that it just closed to show "Puerta cerrada" for a moment.
  if (lastDoor_ != DoorState::CLOSED && in.door == DoorState::CLOSED) {
    closedActive_ = true;
    closedUntil_ = now + t_.closedMs;
  }
  lastDoor_ = in.door;
  if (closedActive_ && !before(now, closedUntil_)) closedActive_ = false;
  if (entranceActive_ && !before(now, entranceUntil_)) entranceActive_ = false;

  if (configError_) return LcdScreen::CONFIG_ERROR;
  if (in.alarm) return LcdScreen::ALARM;
  if (!in.wifiUp && in.state != SystemState::BOOT) return LcdScreen::DISCONNECTED;
  if (in.door != DoorState::CLOSED) {
    if (flashActive_ && flash_ == LcdScreen::GRANTED) return LcdScreen::GRANTED;
    return in.door == DoorState::CLOSING ? LcdScreen::DOOR_CLOSING : LcdScreen::DOOR_OPEN;
  }
  // A new attempt (card read) wins over the leftovers of the previous one.
  if (in.state == SystemState::CARD_READ) return LcdScreen::RFID_READ;
  if (in.state == SystemState::WAITING_DECISION)
    return phase_ == "AWAITING_FACE" ? LcdScreen::FACE : LcdScreen::VERIFYING;
  // The main entrance is another door: its outcome shows only while the room is not mid-cycle.
  if (entranceActive_) return entranceGranted_ ? LcdScreen::ENTRANCE_GRANTED : LcdScreen::ENTRANCE_DENIED;
  if (closedActive_) return LcdScreen::DOOR_CLOSED;
  if (flashActive_) return flash_;
  if (in.env.alarm && (in.state == SystemState::IDLE || in.state == SystemState::PRESENCE))
    return LcdScreen::ENV_ALARM;

  switch (in.state) {
    case SystemState::BOOT: return LcdScreen::BOOT;
    case SystemState::OFFLINE: return LcdScreen::CONN_ERROR;
    case SystemState::ERROR: return LcdScreen::SENSOR_ERROR;
    case SystemState::PRESENCE: return LcdScreen::PRESENCE;
    case SystemState::DOOR_OPEN: return LcdScreen::DOOR_OPEN;
    case SystemState::DOOR_CLOSING: return LcdScreen::DOOR_CLOSING;
    default: return LcdScreen::WAIT_CARD;
  }
}

void LcdView::update(const LcdInput& in, uint32_t nowMs) {
  LcdScreen next = pick(in, nowMs);
  if (next == LcdScreen::RFID_READ && screen_ != LcdScreen::RFID_READ) {
    flashActive_ = false;  // a new attempt clears the previous outcome
    closedActive_ = false;
  }
  screen_ = next;
  render(in, nowMs);
}

std::string LcdView::distanceText(const SensorSnapshot& s) {
  if (s.fault) return "Dist: FALLO SENSOR";
  if (s.distanceCm < 0) return "Dist: --- cm";
  char buf[24];
  std::snprintf(buf, sizeof buf, "Dist: %.1f cm", double(s.distanceCm));
  return buf;
}

std::string LcdView::envText(const EnvStatus& e) {
  if (e.sensor == DhtStatus::ERROR) return "TEMP/HUM: ERROR DHT";
  if (e.sensor != DhtStatus::OK) return "TEMP --.-C HUM --%";
  char buf[32];
  std::snprintf(buf, sizeof buf, "TEMP %.1fC HUM %d%%", double(e.temperatureC),
                int(e.humidityPct + 0.5f));
  return buf;
}

void LcdView::setName(int row, const std::string& name, const char* fallback) {
  // Up to 40 chars over two lines, wrapped at the last space when possible.
  if (name.empty()) { set(row, fallback); return; }
  std::string a = name, b;
  if (a.size() > size_t(kCols)) {
    size_t cut = a.rfind(' ', size_t(kCols));
    if (cut == std::string::npos || cut == 0) cut = size_t(kCols);
    b = a.substr(cut);
    a = a.substr(0, cut);
    while (!b.empty() && b[0] == ' ') b.erase(0, 1);
  }
  set(row, a);
  if (row + 1 < kRows) set(row + 1, b.empty() ? fallback : b);
}

void LcdView::clearLines() {
  for (auto& l : lines_) {
    std::memset(l, ' ', kCols);
    l[kCols] = '\0';
  }
}

void LcdView::set(int row, const std::string& text) {
  std::memset(lines_[row], ' ', kCols);
  std::memcpy(lines_[row], text.data(), text.size() < size_t(kCols) ? text.size() : size_t(kCols));
}

void LcdView::render(const LcdInput& in, uint32_t now) {
  static const char kSpin[] = {'|', '/', '-', '\\'};
  const char spin = kSpin[(now / 250) % 4];
  const std::string dist = distanceText(in.sensor);
  const char* why = reasonShort(flashReason_);
  const std::string reason = why ? why : fit(flashReason_);
  char thr[24];
  std::snprintf(thr, sizeof thr, "Alarma si < %d cm", int(in.thresholdCm + 0.5f));

  clearLines();
  switch (screen_) {
    case LcdScreen::BOOT:
      set(0, "    DC GUARDIAN");
      set(1, "Iniciando sistema");
      set(2, std::string("Conectando WiFi ") + spin);
      break;
    case LcdScreen::CONFIG_ERROR:
      set(0, "ERROR CONFIGURACION");
      set(1, "Revise dcg_config.h");
      set(2, "Puerta bloqueada");
      break;
    case LcdScreen::DISCONNECTED:
      set(0, "SISTEMA DESCONECTADO");
      set(1, "WiFi sin conexion");
      set(2, "Puerta bloqueada");
      set(3, std::string("Reintentando ") + spin);
      break;
    case LcdScreen::CONN_ERROR:
      set(0, "ERROR DE CONEXION");
      set(1, "Servidor no responde");
      set(2, "Puerta bloqueada");
      set(3, std::string("Reintentando ") + spin);
      break;
    case LcdScreen::SENSOR_ERROR:
      set(0, "ERROR DE SENSOR");
      set(1, std::string("RFID:    ") + (in.rfidOk ? "OK" : "FALLO"));
      set(2, std::string("HC-SR04: ") + (in.sensor.fault ? "FALLO" : "OK"));
      set(3, "Puerta bloqueada");
      break;
    case LcdScreen::WAIT_CARD:
      set(0, "DC GUARDIAN  ONLINE");
      set(1, "Esperando tarjeta");
      // Resting screen: room temperature/humidity once the DHT11 has reported.
      set(2, in.env.sensor == DhtStatus::UNKNOWN ? std::string(thr) : envText(in.env));
      set(3, dist);
      break;
    case LcdScreen::PRESENCE:
      set(0, "DC GUARDIAN  ONLINE");
      set(1, "Esperando tarjeta");
      set(2, "Sala: persona dentro");
      set(3, dist);
      break;
    case LcdScreen::ALARM:
      set(0, "!!!!  ALARMA  !!!!");
      set(1, "Intruso detectado");
      set(2, "dentro de la sala");
      set(3, dist);
      break;
    case LcdScreen::ENTRANCE_GRANTED:
      set(0, "ENTRADA PRINCIPAL");
      set(1, "ACCESO QR OK");
      setName(2, entranceName_, "");
      break;
    case LcdScreen::ENTRANCE_DENIED:
      set(0, "ENTRADA PRINCIPAL");
      set(1, "QR DENEGADO");
      break;
    case LcdScreen::ENV_ALARM: {
      const EnvThresholds& th = in.env.thresholds;
      set(0, "ALARMA AMBIENTAL");
      set(1, envText(in.env));
      if (in.env.temperatureC >= th.tempCriticalC) set(2, "Temperatura critica");
      else if (in.env.humidityPct < th.humidityLowPct || in.env.humidityPct > th.humidityHighPct)
        set(2, "Humedad fuera rango");
      else set(2, "Revise la sala");
      set(3, std::string("Ventilador: ") + (in.env.fan ? "ON" : "OFF"));
      break;
    }
    case LcdScreen::RFID_READ:
      set(0, "RFID DETECTADO");
      set(1, "UID " + uid_);
      set(2, std::string("Enviando ") + spin);
      set(3, dist);
      break;
    case LcdScreen::VERIFYING:
      set(0, "VERIFICANDO");
      set(1, "AUTORIZACION");
      set(2, std::string("Espere ") + spin);
      set(3, dist);
      break;
    case LcdScreen::FACE:
      set(0, "RECONOCIMIENTO");
      set(1, "FACIAL");
      set(2, "Mire a la camara");
      set(3, std::string("Analizando ") + spin);
      break;
    case LcdScreen::GRANTED:
      set(0, "ACCESO AUTORIZADO");
      set(1, greeting_.empty() ? "Bienvenido" : greeting_);
      if (name_.empty()) {
        set(2, "Abriendo puerta...");
      } else {  // up to 40 chars over two lines, wrapped at the last space when possible
        std::string a = name_, b;
        if (a.size() > size_t(kCols)) {
          size_t cut = a.rfind(' ', size_t(kCols));
          if (cut == std::string::npos || cut == 0) cut = size_t(kCols);
          b = a.substr(cut);
          a = a.substr(0, cut);
          while (!b.empty() && b[0] == ' ') b.erase(0, 1);
        }
        set(2, a);
        set(3, b.empty() ? "Abriendo puerta..." : b);
      }
      break;
    case LcdScreen::DENIED:
      set(0, "ACCESO DENEGADO");
      set(1, reason);
      set(3, "Puerta cerrada");
      break;
    case LcdScreen::ACCESS_ERROR:
      set(0, "ERROR DE CONEXION");
      set(1, "Intento cancelado");
      set(2, reason);
      set(3, "Puerta cerrada");
      break;
    case LcdScreen::DOOR_OPEN:
      set(0, "PUERTA ABIERTA");
      set(1, "Pase, por favor");
      set(3, dist);
      break;
    case LcdScreen::DOOR_CLOSING:
      set(0, "CERRANDO PUERTA");
      set(1, "Mantengase alejado");
      break;
    case LcdScreen::DOOR_CLOSED:
      set(0, "PUERTA CERRADA");
      set(1, "Acceso registrado");
      break;
  }
}

}  // namespace dcg
