"""
Central config loader for NexVi.Meets.
All secrets/keys are read from environment variables only — never hardcoded,
never committed. Copy .env.example to .env and fill in real values.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- App ---
    app_name: str = "NexVi.Meets"
    environment: str = "development"

    # --- MongoDB ---
    mongo_uri: str
    mongo_db_name: str = "nexvi_meets"

    # --- ChromaDB ---
    chroma_persist_dir: str = "./chroma_data"

    # --- Groq ---
    groq_api_key: str
    groq_model: str = "llama-3.3-70b-versatile"

    # --- Sarvam ---
    sarvam_api_key: str
    sarvam_model: str = "sarvam-translate"  # normalization step

    # --- Google Calendar OAuth ---
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    # --- Live capture ---
    rolling_window_seconds: int = 40

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
