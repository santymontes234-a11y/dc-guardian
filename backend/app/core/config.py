"""Application settings loaded from environment variables (prefix ``DCG_``) or ``.env``."""

from __future__ import annotations

import json
import logging
import os
import secrets
from urllib.parse import urlsplit
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent

log = logging.getLogger(__name__)

# ≈ 32 random bytes in URL-safe base64 (secrets.token_urlsafe(32) gives 43 chars).
MIN_SECRET_LEN = 43


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DCG_",
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["dev", "test", "prod"] = "dev"
    simulation: bool = False

    data_dir: Path = PROJECT_ROOT / "data"
    database_url: str | None = None

    # --- Admin authentication ---
    jwt_secret: str | None = None
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_expire_minutes: int = Field(default=60, ge=5, le=24 * 60)
    cookie_name: str = "dcg_session"
    cookie_secure: bool = False
    login_max_failures: int = Field(default=5, ge=1)
    login_lockout_minutes: int = Field(default=15, ge=1)
    login_rate_per_minute: int = Field(default=10, ge=1)  # per client IP

    # --- Secrets at rest (device HMAC secrets are encrypted with this key) ---
    master_key: str | None = None

    # --- Domain rules ---
    institutional_email_domain: str | None = None  # e.g. "dcguardian.edu"; None = any domain
    request_max_days_ahead: int = 90
    request_start_grace_minutes: int = 5  # a request may start this far in the past
    scheduler_enabled: bool = True
    scheduler_interval_s: int = Field(default=60, ge=5)

    # --- Access policy defaults ---
    access_session_timeout_s: int = 30
    device_clock_skew_s: int = 30
    face_threshold: float = Field(default=0.45, gt=0, lt=1)  # 1:1 cosine to count a frame as a match
    face_frames: int = Field(default=5, ge=1, le=15)  # verify() requires exactly this many frames
    face_min_matches: int = Field(default=3, ge=1)  # ≤ face_frames (validated below)
    access_poll_ms: int = Field(default=500, ge=300, le=2000)
    granted_valid_s: int = 10  # a GRANTED decision must be acted on (opened) within this time
    device_offline_s: int = 45  # no heartbeat for longer → OFFLINE + alert
    device_heartbeat_s: int = Field(default=15, ge=5, le=60)
    device_sweep_interval_s: int = Field(default=10, ge=2)
    failure_window_minutes: int = 5  # REPEATED_FAILURES: N denials of one card in this window...
    failure_max: int = 3
    card_lock_minutes: int = 10  # ...lock the card this long
    exit_window_hours: int = 24  # an entry older than this no longer counts as "inside"
    # Kiosk (face camera next to the door). None in dev/test → derived from DCG_MASTER_KEY.
    kiosk_token: str | None = None
    # Simulation: where the virtual ESP32 sends its signed requests (this same backend).
    sim_base_url: str = "http://127.0.0.1:8000"

    # --- Face registration (Registro 1) ---
    face_provider: Literal["auto", "insightface", "mock"] = "auto"  # auto: mock if simulation, else insightface
    face_model: str = "buffalo_l"  # fallback buffalo_s if it cannot be loaded
    face_enroll_min_samples: int = Field(default=3, ge=1, le=10)
    face_enroll_max_samples: int = Field(default=5, ge=1, le=10)
    face_consistency_threshold: float = Field(default=0.40, gt=0, lt=1)  # min cosine between any two samples
    # New face vs. another engineer's samples. Must be ≤ face_threshold: a face that would verify
    # as engineer A must never be registrable as engineer B.
    face_duplicate_threshold: float = Field(default=0.45, gt=0, lt=1)
    face_min_det_score: float = 0.60
    face_min_size_px: int = 80
    face_min_sharpness: float = 40.0  # variance of the Laplacian on the 112 px face crop
    face_max_yaw_ratio: float = 0.35  # |nose offset| / eye distance (0 = frontal)
    image_max_bytes: int = 6 * 1024 * 1024

    @model_validator(mode="after")
    def _fill_defaults(self) -> "Settings":
        # Any explicitly provided key must be strong (HS256 with a short secret is brute-forceable).
        for name in ("jwt_secret", "master_key", "kiosk_token"):
            value = getattr(self, name)
            if value is not None and len(value) < MIN_SECRET_LEN:
                raise ValueError(f"DCG_{name.upper()} must be at least {MIN_SECRET_LEN} characters")
        if self.database_url is None:
            self.database_url = f"sqlite:///{self.data_dir / 'dcguardian.db'}"
        # Biometric policy must be coherent: a misconfiguration must never fail open.
        if self.face_min_matches > self.face_frames:
            raise ValueError("DCG_FACE_MIN_MATCHES must be <= DCG_FACE_FRAMES")
        if self.face_duplicate_threshold > self.face_threshold:
            raise ValueError("DCG_FACE_DUPLICATE_THRESHOLD must be <= DCG_FACE_THRESHOLD")
        # The virtual ESP32 signs real device requests: they must never leave this machine.
        sim_host = urlsplit(self.sim_base_url).hostname
        if sim_host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("DCG_SIM_BASE_URL must point to this machine (127.0.0.1 / localhost)")
        if self.env == "prod":
            missing = [n for n in ("jwt_secret", "master_key") if not getattr(self, n)]
            if missing:
                raise ValueError(f"Missing required settings in prod: {', '.join(missing)}")
            if not self.cookie_secure:
                raise ValueError("DCG_COOKIE_SECURE must be true in prod")
            # The mock face provider accepts any textured image: never in production.
            if self.face_provider == "mock" or (self.face_provider == "auto" and self.simulation):
                raise ValueError("The mock face provider is not allowed in prod "
                                 "(set DCG_FACE_PROVIDER=insightface and DCG_SIMULATION=false)")
            # /sim decrypts the real device secrets and can sign as the door: never in production.
            if self.simulation:
                raise ValueError("DCG_SIMULATION is not allowed in prod")
        elif self.env == "test":
            self.jwt_secret = self.jwt_secret or secrets.token_urlsafe(48)
            self.master_key = self.master_key or secrets.token_urlsafe(32)
            self.scheduler_enabled = False  # tests call the sweep explicitly
        elif not (self.jwt_secret and self.master_key):
            keys = _load_or_create_dev_keys(self.data_dir)
            self.jwt_secret = self.jwt_secret or keys["jwt_secret"]
            self.master_key = self.master_key or keys["master_key"]
        return self


def _load_or_create_dev_keys(data_dir: Path) -> dict[str, str]:
    """In dev, persist random keys in ``data/.dev_keys.json`` (gitignored, mode 600)."""
    path = data_dir / ".dev_keys.json"
    if path.exists():
        return json.loads(path.read_text())
    data_dir.mkdir(parents=True, exist_ok=True)
    keys = {"jwt_secret": secrets.token_urlsafe(48), "master_key": secrets.token_urlsafe(32)}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(keys, fh)
    log.warning("Generated development keys in %s (set DCG_JWT_SECRET / DCG_MASTER_KEY to override)", path)
    return keys


@lru_cache
def get_settings() -> Settings:
    return Settings()
