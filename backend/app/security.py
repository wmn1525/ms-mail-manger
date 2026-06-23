from datetime import UTC, datetime, timedelta
import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet
from fastapi import Depends, Header, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def _fernet() -> Fernet:
    secret = get_settings().app_secret.encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def encrypt_value(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_value(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")


def verify_admin(username: str, password: str) -> bool:
    settings = get_settings()
    return hmac.compare_digest(username, settings.admin_username) and hmac.compare_digest(
        password, settings.admin_password
    )


def create_access_token(subject: str) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode({"sub": subject, "exp": expire}, settings.app_secret, algorithm="HS256")


def get_current_admin(token: str = Depends(oauth2_scheme)) -> str:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录已失效",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, get_settings().app_secret, algorithms=["HS256"])
        username = payload.get("sub")
        if username != get_settings().admin_username:
            raise credentials_error
        return username
    except JWTError as exc:
        raise credentials_error from exc


def generate_public_token() -> str:
    return f"tk_{secrets.token_urlsafe(18).replace('-', '').replace('_', '')[:24]}"


def generate_api_key() -> str:
    return f"ak_{secrets.token_urlsafe(32).replace('-', '').replace('_', '')[:40]}"


def hash_api_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def verify_public_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    api_key: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> None:
    expected = get_settings().public_api_key
    provided = x_api_key or api_key
    if not provided:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key 无效")
    if expected and hmac.compare_digest(provided, expected):
        return

    from .models import ApiKey

    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(provided), ApiKey.enabled.is_(True)))
    if not key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key 无效")
    key.last_used_at = datetime.now(UTC)
    db.commit()
