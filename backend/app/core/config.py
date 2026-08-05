"""Single source of configuration for CommitGuard.

Design decision (recorded in docs/architecture.md): every field has a
safe default so that importing the app never explodes, but the adapters
that need real credentials call the ``require_*`` helpers below and fail
loudly with an actionable message at the point of use. This gives us:

- runtime requires real Mongo / Groq / GitHub credentials (there is no
  silent degraded mode that could make a demo look like it worked when it
  did not),
- the test suite still imports and runs with no ``.env`` present, using
  the in-memory adapters it injects explicitly.

Never hardcode a secret here. Copy ``.env.example`` to ``backend/.env``.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class MissingCredentialError(RuntimeError):
    """Raised when a real integration is used without its credentials."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- App ---
    app_name: str = "CommitGuard"
    environment: str = "development"
    cors_origins: str = "http://localhost:5173"

    # --- MongoDB (required at runtime) ---
    mongo_uri: str = ""
    mongo_db_name: str = "commitguard"

    # --- Groq (primary extractor; falls back to the deterministic one) ---
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_timeout_seconds: float = 60.0

    # --- GitHub Issues (the one deep integration; required at runtime) ---
    github_token: str = ""
    github_repo: str = ""  # "owner/repo", must be a sandbox/test repo
    github_api_base: str = "https://api.github.com"

    # --- Safety gate ---
    confidence_threshold: float = 0.75

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def require_mongo_uri(self) -> str:
        if not self.mongo_uri:
            raise MissingCredentialError(
                "MONGO_URI is not set. CommitGuard needs a real MongoDB to persist "
                "candidates and the audit log. Copy backend/.env.example to "
                "backend/.env and set MONGO_URI, or run `docker compose up -d mongo` "
                "and use mongodb://localhost:27017."
            )
        return self.mongo_uri

    def require_github(self) -> tuple[str, str]:
        if not self.github_token or not self.github_repo:
            raise MissingCredentialError(
                "GITHUB_TOKEN and GITHUB_REPO must both be set to create issues. "
                "Use a sandbox repository (never a live production tracker) and a "
                "token with 'issues: write'. Set them in backend/.env."
            )
        return self.github_token, self.github_repo

    @property
    def groq_enabled(self) -> bool:
        return bool(self.groq_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
