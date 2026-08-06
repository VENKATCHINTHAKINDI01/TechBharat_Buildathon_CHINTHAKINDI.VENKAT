"""Single source of configuration for Nexvi.Meets.

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

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MissingCredentialError(RuntimeError):
    """Raised when a real integration is used without its credentials."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- App ---
    app_name: str = "Nexvi.Meets"
    environment: str = "development"
    cors_origins: str = "http://localhost:5173"

    # --- MongoDB (required at runtime) ---
    mongo_uri: str = ""
    mongo_db_name: str = "nexvi_meets"

    # --- Groq (primary extractor; falls back to the deterministic one) ---
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_timeout_seconds: float = 60.0

    # --- GitHub Issues (the one deep integration; required at runtime) ---
    github_token: str = ""
    github_repo: str = ""  # "owner/repo", must be a sandbox/test repo
    github_api_base: str = "https://api.github.com"

    # --- Sarvam (optional code-switch normalization) ---
    sarvam_api_key: str = ""
    sarvam_model: str = "sarvam-translate:v1"

    # --- Google Calendar (second gated side effect) ---
    google_credentials_path: str = "credentials.json"
    google_token_path: str = "token.json"
    google_calendar_id: str = "primary"

    # --- Cross-meeting memory (ChromaDB) ---
    # Local fallback: used when CHROMA_API_KEY is not set.
    chroma_persist_dir: str = "./chroma_data"
    # Chroma Cloud: set all three to use the hosted service instead of local.
    chroma_api_key: str = ""
    chroma_tenant: str = ""
    chroma_database: str = ""
    memory_similarity_threshold: float = 0.35

    # --- Agent orchestration: "inhouse" | "langgraph" ---
    agent_runtime: str = "inhouse"

    # --- Live meeting mode: speech to text ---
    # Groq hosts Whisper Large v3 Turbo at ~216x realtime, which is what
    # lets a file endpoint drive a live experience.
    groq_transcription_model: str = "whisper-large-v3-turbo"
    # ISO-639-1 hint. Leave empty to let Whisper auto-detect, which is
    # required for code-mixed speech.
    live_asr_language: str = ""
    sarvam_api_base: str = "https://api.sarvam.ai"
    sarvam_stt_model: str = "saarika:v2.5"

    @field_validator("sarvam_language_code")
    @classmethod
    def _valid_sarvam_language(cls, value: str) -> str:
        """Coerce at load time.

        A typo here previously reached Sarvam and came back as a 400
        during the end-of-meeting diarization pass -- after the call was
        over and the audio already captured. Catching it at startup means
        the worst case is a log line, not a lost speaker refinement.
        """
        from app.adapters.transcription.languages import normalize_language_code

        return normalize_language_code(value)
    sarvam_language_code: str = "unknown"   # "unknown" = auto-detect
    # Seconds of audio per chunk. Lower = snappier, more requests.
    live_chunk_seconds: int = 6
    # Keep buffered audio for the end-of-meeting diarization pass.
    live_keep_audio: bool = True
    live_max_buffered_mb: int = 200

    # --- Live meeting mode ---
    live_diarization_enabled: bool = True
    live_window_seconds: int = 40
    live_min_new_segments: int = 2

    # --- Safety gate ---
    confidence_threshold: float = 0.75

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def require_mongo_uri(self) -> str:
        if not self.mongo_uri:
            raise MissingCredentialError(
                "MONGO_URI is not set. Nexvi.Meets needs a real MongoDB to persist "
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
    def chroma_cloud_enabled(self) -> bool:
        """True when all three Chroma Cloud credentials are present.
        If False, the adapter falls back to the local PersistentClient."""
        return bool(self.chroma_api_key and self.chroma_tenant and self.chroma_database)

    @property
    def groq_enabled(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def live_audio_enabled(self) -> bool:
        """Live audio capture needs at least one speech-to-text engine."""
        return bool(self.groq_api_key or self.sarvam_api_key)

    @property
    def sarvam_enabled(self) -> bool:
        return bool(self.sarvam_api_key)

    @property
    def enabled_side_effects(self) -> list[str]:
        """Which gated side effects are actually configured.

        Reported by /readiness so a demo never discovers mid-approval that
        a credential is missing.
        """
        effects = ["github_issue"] if (self.github_token and self.github_repo) else []
        import os

        if os.path.exists(self.google_credentials_path) or os.path.exists(self.google_token_path):
            effects.append("calendar_invite")
        effects.extend(["memory_index", "notification"])
        return effects


@lru_cache
def get_settings() -> Settings:
    return Settings()
