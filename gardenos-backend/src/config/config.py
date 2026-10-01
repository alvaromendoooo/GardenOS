import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import PostgresDsn
from sqlalchemy import create_engine
from flask_httpauth import HTTPBasicAuth

env_path = Path(__file__).resolve().parent.parent.parent / ".env"

class Settings(BaseSettings):
    # APP settings
    APP_NAME: str = "GardenOS"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = '0.0.0.0'

    # Auth
    REFRESH_TOKEN: int
    # Signs access tokens. No default on purpose: a known key lets anyone forge tokens.
    SECRET_KEY: str
    ACCESS_TOKEN_MINUTES: int = 15
    REFRESH_TOKEN_DAYS: int = 30

    # Secrets and External Services
    DATABASE_URL: PostgresDsn

    # Production
    TRUSTED_PROXIES: int = 0

    # Configuration to load from .env automatically
    model_config = SettingsConfigDict(
        env_file = env_path,
        env_file_encoding = "utf-8",
        extra = "ignore"
    )

# Singletons
settings = Settings()
engine = create_engine(str(settings.DATABASE_URL))
auth = HTTPBasicAuth()