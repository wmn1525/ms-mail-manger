from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..icloud_cache import reset_config_cache
from ..imap_client import GenericImapClient, ImapCredential
from ..models import IcloudMailbox, ImapConfig
from ..schemas import CheckOut, ImapConfigCreate, ImapConfigOut, ImapConfigUpdate
from ..security import decrypt_value, encrypt_value, get_current_admin


router = APIRouter(prefix="/imap-configs", tags=["imap-configs"], dependencies=[Depends(get_current_admin)])


def imap_config_out(config: ImapConfig) -> ImapConfigOut:
    """隐藏密码密文，仅返回后台列表需要的状态字段。"""

    return ImapConfigOut(
        id=config.id,
        name=config.name,
        host=config.host,
        port=config.port,
        username=config.username,
        folder=config.folder,
        use_ssl=config.use_ssl,
        remark=config.remark,
        status=config.status,
        last_error=config.last_error,
        last_checked_at=config.last_checked_at,
        created_at=config.created_at,
        updated_at=config.updated_at,
        has_password=bool(config.password_enc),
    )


def credential_from_config(config: ImapConfig) -> ImapCredential:
    """把数据库配置转换成可连接 IMAP 的凭据对象。"""

    password = decrypt_value(config.password_enc)
    if not password:
        raise RuntimeError("缺少 IMAP 密码")
    return ImapCredential(
        host=config.host,
        port=config.port,
        username=config.username,
        password=password,
        folder=config.folder,
        use_ssl=config.use_ssl,
    )


def check_config_model(config: ImapConfig) -> CheckOut:
    """测活并把结果写回 IMAP 配置状态。"""

    checked_at = datetime.now(UTC)
    try:
        GenericImapClient(credential_from_config(config)).check_alive()
        config.status = "live"
        config.last_error = None
    except Exception as exc:
        config.status = "dead"
        config.last_error = str(exc)
    config.last_checked_at = checked_at
    return CheckOut(id=config.id, status=config.status, error=config.last_error, checked_at=checked_at)


@router.get("", response_model=list[ImapConfigOut])
def list_imap_configs(db: Session = Depends(get_db)) -> list[ImapConfigOut]:
    configs = db.scalars(select(ImapConfig).order_by(ImapConfig.id.desc())).all()
    return [imap_config_out(config) for config in configs]


@router.post("", response_model=ImapConfigOut)
def create_imap_config(payload: ImapConfigCreate, db: Session = Depends(get_db)) -> ImapConfigOut:
    config = ImapConfig(
        name=payload.name.strip(),
        host=payload.host.strip(),
        port=payload.port,
        username=payload.username.strip(),
        password_enc=encrypt_value(payload.password),
        folder="INBOX",
        use_ssl=payload.use_ssl,
        remark=payload.remark,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return imap_config_out(config)


@router.patch("/{config_id}", response_model=ImapConfigOut)
def update_imap_config(
    config_id: int,
    payload: ImapConfigUpdate,
    db: Session = Depends(get_db),
) -> ImapConfigOut:
    """更新 IMAP 连接参数，账号身份变化时重建本地缓存。"""

    config = db.get(ImapConfig, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="IMAP 配置不存在")
    previous_identity = (config.host, config.port, config.username, config.use_ssl)
    config.name = payload.name.strip()
    config.host = payload.host.strip()
    config.port = payload.port
    config.username = payload.username.strip()
    if payload.password:
        config.password_enc = encrypt_value(payload.password)
    config.use_ssl = payload.use_ssl
    config.remark = payload.remark
    config.status = "unknown"
    config.last_error = None
    config.last_checked_at = None
    config.folder = "INBOX"
    current_identity = (config.host, config.port, config.username, config.use_ssl)
    if current_identity != previous_identity:
        reset_config_cache(db, config.id)
    db.commit()
    db.refresh(config)
    return imap_config_out(config)


@router.post("/{config_id}/check", response_model=CheckOut)
def check_imap_config(config_id: int, db: Session = Depends(get_db)) -> CheckOut:
    config = db.get(ImapConfig, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="IMAP 配置不存在")
    result = check_config_model(config)
    db.commit()
    return result


@router.delete("/{config_id}")
def delete_imap_config(config_id: int, db: Session = Depends(get_db)) -> dict:
    """删除未绑定邮箱的 IMAP 配置及其同步状态。"""

    config = db.get(ImapConfig, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="IMAP 配置不存在")
    used = db.scalar(select(IcloudMailbox.id).where(IcloudMailbox.imap_config_id == config_id).limit(1))
    if used:
        raise HTTPException(status_code=400, detail="该 IMAP 配置已绑定 iCloud 邮箱，不能删除")
    reset_config_cache(db, config.id)
    db.delete(config)
    db.commit()
    return {"ok": True}
