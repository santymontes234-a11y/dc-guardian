"""Persisted status values (Spanish, uppercase) — see design doc section 3."""

from enum import StrEnum


class AdminRole(StrEnum):
    ADMIN = "admin"
    AUDITOR = "auditor"


class EngineerStatus(StrEnum):
    ACTIVE = "ACTIVO"
    INACTIVE = "INACTIVO"
    SUSPENDED = "SUSPENDIDO"
    ERASED = "ELIMINADO"  # personal + biometric data erased; terminal (row kept for history)


ENGINEER_SETTABLE_STATUSES = frozenset({EngineerStatus.ACTIVE, EngineerStatus.INACTIVE, EngineerStatus.SUSPENDED})


class CardStatus(StrEnum):
    ACTIVE = "ACTIVA"
    BLOCKED = "BLOQUEADA"
    LOST = "PERDIDA"
    RETIRED = "BAJA"


class RequestStatus(StrEnum):
    PENDING = "PENDIENTE"
    APPROVED = "APROBADA"
    REJECTED = "RECHAZADA"
    EXPIRED = "EXPIRADA"
    REVOKED = "REVOCADA"
    FINISHED = "FINALIZADA"


TERMINAL_REQUEST_STATUSES = frozenset(
    {RequestStatus.REJECTED, RequestStatus.EXPIRED, RequestStatus.REVOKED, RequestStatus.FINISHED}
)


class DeviceStatus(StrEnum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    DISABLED = "DESHABILITADO"


class AccessDirection(StrEnum):
    ENTRY = "ENTRADA"
    EXIT = "SALIDA"


class AccessState(StrEnum):
    CARD_READ = "CARD_READ"
    AWAITING_FACE = "AWAITING_FACE"
    FACE_OK = "FACE_OK"
    GRANTED = "GRANTED"
    OPENED = "OPENED"
    CLOSED = "CLOSED"
    DENIED = "DENIED"
    TIMEOUT = "TIMEOUT"


class AlertSeverity(StrEnum):
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


class ActorType(StrEnum):
    ADMIN = "admin"
    DEVICE = "device"
    SYSTEM = "system"
    ENGINEER = "engineer"
