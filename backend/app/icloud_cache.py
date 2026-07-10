"""iCloud 临时邮件缓存的查询与失效操作。"""

import binascii
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .imap_client import parse_scoped_uid, scoped_uid
from .models import IcloudCachedMessage, ImapSyncState


CACHE_FOLDER = "INBOX"
CACHE_RETENTION_DAYS = 7


def cached_message_dict(message: IcloudCachedMessage, include_body: bool) -> dict:
    """把缓存模型转换为现有邮件接口使用的字典结构。"""

    result = {
        "uid": scoped_uid(message.folder, message.uid),
        "subject": message.subject,
        "from": message.sender,
        "date": message.message_date,
        "snippet": message.snippet,
        "code": message.code,
    }
    if include_body:
        result["body"] = message.body
        result["html"] = message.html
    return result


def list_cached_messages(db: Session, mailbox_id: int, limit: int) -> list[dict]:
    """按远端数字 UID 倒序返回指定 iCloud 邮箱的缓存邮件。"""

    messages = db.scalars(
        select(IcloudCachedMessage)
        .where(IcloudCachedMessage.icloud_mailbox_id == mailbox_id)
        .order_by(IcloudCachedMessage.uid.desc())
        .limit(limit)
    ).all()
    return [cached_message_dict(message, include_body=False) for message in messages]


def get_cached_message(db: Session, mailbox_id: int, uid: str) -> dict | None:
    """按公开 UID 查询详情，并确保邮件确实属于当前 iCloud 邮箱。"""

    try:
        folder, raw_uid = parse_scoped_uid(uid)
        uid_value = int(raw_uid)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return None
    if not folder:
        return None
    message = db.scalar(
        select(IcloudCachedMessage).where(
            IcloudCachedMessage.icloud_mailbox_id == mailbox_id,
            IcloudCachedMessage.folder == folder,
            IcloudCachedMessage.uid == uid_value,
        )
    )
    return cached_message_dict(message, include_body=True) if message else None


def find_latest_cached_code(db: Session, mailbox_id: int, limit: int) -> dict | None:
    """只在最新 limit 封缓存邮件中查找第一个验证码。"""

    messages = db.scalars(
        select(IcloudCachedMessage)
        .where(IcloudCachedMessage.icloud_mailbox_id == mailbox_id)
        .order_by(IcloudCachedMessage.uid.desc())
        .limit(limit)
    ).all()
    message = next((item for item in messages if item.code), None)
    return cached_message_dict(message, include_body=False) if message else None


def request_config_backfill(db: Session, config_id: int) -> None:
    """标记指定配置需要重新扫描最近邮件，不直接执行网络操作。"""

    requested_at = datetime.now(UTC)
    statement = sqlite_insert(ImapSyncState).values(
        imap_config_id=config_id,
        folder=CACHE_FOLDER,
        backfill_requested_at=requested_at,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[ImapSyncState.imap_config_id, ImapSyncState.folder],
        set_={"backfill_requested_at": requested_at},
    )
    db.execute(statement)


def ensure_sync_state(db: Session, config_id: int) -> ImapSyncState:
    """并发安全地创建同步状态并返回当前目录记录。"""

    statement = sqlite_insert(ImapSyncState).values(imap_config_id=config_id, folder=CACHE_FOLDER)
    db.execute(
        statement.on_conflict_do_nothing(
            index_elements=[ImapSyncState.imap_config_id, ImapSyncState.folder]
        )
    )
    state = db.scalar(
        select(ImapSyncState).where(
            ImapSyncState.imap_config_id == config_id,
            ImapSyncState.folder == CACHE_FOLDER,
        )
    )
    if not state:
        raise RuntimeError("无法创建 IMAP 同步状态")
    return state


def delete_mailbox_cache(db: Session, mailbox_id: int) -> None:
    """删除 iCloud 邮箱的全部临时邮件，供删除或重新绑定时调用。"""

    db.execute(delete(IcloudCachedMessage).where(IcloudCachedMessage.icloud_mailbox_id == mailbox_id))


def reset_config_cache(db: Session, config_id: int) -> None:
    """清除配置的 UID 状态和缓存，下一次同步会重新回填。"""

    db.execute(delete(IcloudCachedMessage).where(IcloudCachedMessage.imap_config_id == config_id))
    db.execute(delete(ImapSyncState).where(ImapSyncState.imap_config_id == config_id))


def cleanup_expired_cache(db: Session) -> int:
    """删除超过七天的临时邮件，并返回清理数量。"""

    cutoff = datetime.now(UTC) - timedelta(days=CACHE_RETENTION_DAYS)
    result = db.execute(delete(IcloudCachedMessage).where(IcloudCachedMessage.cached_at < cutoff))
    return result.rowcount or 0
