from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    app_name: str = "Microsoft Mail Admin"
    api_prefix: str = "/api"
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'app.db'}"
    app_secret: str = "change-me-before-production"
    jwt_expire_minutes: int = 720
    admin_username: str = "admin"
    admin_password: str = "admin123"
    public_api_key: str = "change-me-public-api-key"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    frontend_dist_dir: str = str(BASE_DIR.parent / "frontend" / "dist")

    imap_host: str = "outlook.office365.com"
    imap_port: int = 993
    imap_folder: str = "INBOX"
    microsoft_scope: str = "https://outlook.office.com/IMAP.AccessAsUser.All offline_access openid email"

    model_config = SettingsConfigDict(env_file=str(BASE_DIR.parent / ".env"), env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    Path(settings.database_url.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)
    return settings
