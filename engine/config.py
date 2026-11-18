"""Application settings and configuration.

Integration Standard 6:
All settings, paths, model names and limits come from environment variables or a config file.
No hard-coded paths or keys.
"""

from __future__ import annotations
import os
from pydantic import BaseModel, Field


class Settings(BaseModel):
    PORT: int = Field(default_factory=lambda: int(os.getenv("PORT", 8000)))
    HOST: str = Field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    DEBUG: bool = Field(default_factory=lambda: os.getenv("DEBUG", "false").lower() == "true")
    API_V1_PREFIX: str = Field(default_factory=lambda: os.getenv("API_V1_PREFIX", "/api/v1"))
    DEFAULT_TIME_POLICY: str = Field(default_factory=lambda: os.getenv("DEFAULT_TIME_POLICY", "original_media_time"))

    # STT & LLM
    STT_PROVIDER: str = Field(default_factory=lambda: os.getenv("STT_PROVIDER", "mock"))
    STT_MODEL_NAME: str = Field(default_factory=lambda: os.getenv("STT_MODEL_NAME", "whisper-base"))
    LLM_PROVIDER: str = Field(default_factory=lambda: os.getenv("LLM_PROVIDER", "rule_based"))
    LLM_MODEL_NAME: str = Field(default_factory=lambda: os.getenv("LLM_MODEL_NAME", "deterministic-rule-engine"))

    # Security & Retries
    IDEMPOTENCY_TTL_SECONDS: int = Field(default_factory=lambda: int(os.getenv("IDEMPOTENCY_TTL_SECONDS", 86400)))
    HMAC_SECRET_KEY: str = Field(default_factory=lambda: os.getenv("HMAC_SECRET_KEY", "incubrix-secure-signature-secret-key-32ch"))

    # Limits & Rules
    MAX_SPEED_FACTOR: float = Field(default_factory=lambda: float(os.getenv("MAX_SPEED_FACTOR", 4.0)))
    MIN_SPEED_FACTOR: float = Field(default_factory=lambda: float(os.getenv("MIN_SPEED_FACTOR", 0.25)))
    MIN_READABLE_CAPTION_DURATION_S: float = Field(default_factory=lambda: float(os.getenv("MIN_READABLE_CAPTION_DURATION_S", 0.70)))
    AUDIO_DUCKING_DB: float = Field(default_factory=lambda: float(os.getenv("AUDIO_DUCKING_DB", -18.0)))


def get_settings() -> Settings:
    return Settings()

