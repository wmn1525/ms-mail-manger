from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ApiKey
from ..schemas import ApiKeyCreateIn, ApiKeyCreateOut, ApiKeyOut, ApiKeyUpdateIn
from ..security import generate_api_key, get_current_admin, hash_api_key


router = APIRouter(prefix="/api-keys", tags=["api-keys"], dependencies=[Depends(get_current_admin)])


@router.get("", response_model=list[ApiKeyOut])
def list_api_keys(db: Session = Depends(get_db)) -> list[ApiKeyOut]:
    return list(db.scalars(select(ApiKey).order_by(ApiKey.id.desc())).all())


@router.post("", response_model=ApiKeyCreateOut)
def create_api_key(payload: ApiKeyCreateIn, db: Session = Depends(get_db)) -> ApiKeyCreateOut:
    raw_key = generate_api_key()
    api_key = ApiKey(
        name=payload.name.strip() or "default",
        key_prefix=raw_key[:10],
        key_hash=hash_api_key(raw_key),
        enabled=True,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return ApiKeyCreateOut(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        enabled=api_key.enabled,
        last_used_at=api_key.last_used_at,
        created_at=api_key.created_at,
        api_key=raw_key,
    )


@router.patch("/{api_key_id}", response_model=ApiKeyOut)
def update_api_key(api_key_id: int, payload: ApiKeyUpdateIn, db: Session = Depends(get_db)) -> ApiKeyOut:
    api_key = db.get(ApiKey, api_key_id)
    if not api_key:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    api_key.enabled = payload.enabled
    db.commit()
    db.refresh(api_key)
    return api_key


@router.delete("/{api_key_id}")
def delete_api_key(api_key_id: int, db: Session = Depends(get_db)) -> dict:
    api_key = db.get(ApiKey, api_key_id)
    if not api_key:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    db.delete(api_key)
    db.commit()
    return {"ok": True}
