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

    # Secrets and External Services
    DATABASE_URL: PostgresDsn


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