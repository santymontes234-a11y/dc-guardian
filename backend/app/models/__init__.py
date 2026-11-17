"""Import every model so ``Base.metadata`` is complete (used by Alembic and tests)."""

from app.models.access import AccessSession
from app.models.admin import Admin
from app.models.authorization import AuthorizationRequest
from app.models.card import RfidCard, normalize_uid
from app.models.engineer import EMBEDDING_DIM, Engineer, FaceEmbedding
from app.models.entrance import EntranceEvent, QrCredential
from app.models.environment import EnvironmentReading
from app.models.facility import Area, Device, DeviceNonce
from app.models.monitoring import Alert, AuditLog

__all__ = [
    "EMBEDDING_DIM",
    "AccessSession",
    "Admin",
    "Alert",
    "Area",
    "AuditLog",
    "AuthorizationRequest",
    "Device",
    "DeviceNonce",
    "Engineer",
    "EntranceEvent",
    "EnvironmentReading",
    "FaceEmbedding",
    "QrCredential",
    "RfidCard",
    "normalize_uid",
]
