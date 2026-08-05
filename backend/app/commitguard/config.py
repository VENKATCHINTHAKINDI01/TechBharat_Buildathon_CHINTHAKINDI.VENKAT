"""CommitGuard-local settings.

Kept separate from ``app.config.Settings`` (Nexvi.Meets') per
docs/architecture.md: CommitGuard must not silently share or mutate the
existing product's config surface. Currently holds only the safety gate's
confidence threshold, per data-contracts.md's requirement that the
threshold live in Settings, not be hardcoded inside the gate function.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class CommitGuardSettings(BaseSettings):
    confidence_threshold: float = 0.75

    class Config:
        env_prefix = "COMMITGUARD_"
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_commitguard_settings() -> CommitGuardSettings:
    return CommitGuardSettings()
