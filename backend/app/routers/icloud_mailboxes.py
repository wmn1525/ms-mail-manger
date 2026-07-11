from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
<<<<<<< HEAD
from ..email_address import remove_split_alias
from ..imap_client import GenericImapClient, ImapCredential
=======
from ..icloud_cache import (
    delete_mailbox_cache,
    get_cached_message,
    list_cached_messages,
    request_config_backfill,
)
>>>>>>> 1e104d0dfe6406c6cbc7689a4636cd90d70e15eb
from ..models import IcloudMailbox, ImapConfig, Mailbox
from ..schemas import (
    IcloudImportIn,
    IcloudMailboxCreate,
    IcloudMailboxListOut,
    IcloudMailboxOut,
    ImportOut,
    MessageDetailOut,
    MessageListOut,
)
from ..security import generate_public_token, get_current_admin


router = APIRouter(prefix="/icloud-mailboxes", tags=["icloud-mailboxes"], dependencies=[Depends(get_current_admin)])


def parse_icloud_line(line: str) -> tuple[str, str | None] | None:
    """解析 iCloud 导入行，支持邮箱或邮箱加备注。"""

    line = line.strip()
    if not line or line.startswith("#"):
        return None
    parts = [part.strip() for part in line.split("----")]
    if not parts or "@" not in parts[0]:
        raise ValueError("邮箱格式不正确")
    return parts[0], parts[1] if len(parts) > 1 and parts[1] else None


def icloud_mailbox_out(mailbox: IcloudMailbox, config_name: str) -> IcloudMailboxOut:
    """组合 iCloud 邮箱和绑定的 IMAP 配置名称。"""

    return IcloudMailboxOut(
        id=mailbox.id,
        email=mailbox.email,
        public_token=mailbox.public_token,
        imap_config_id=mailbox.imap_config_id,
        imap_config_name=config_name,
        remark=mailbox.remark,
        created_at=mailbox.created_at,
        updated_at=mailbox.updated_at,
    )


def generate_unique_icloud_token(db: Session) -> str:
    """生成同时避开 Microsoft 邮箱和 iCloud 邮箱的公开 token。"""

    while True:
        token = generate_public_token()
        exists_mailbox = db.scalar(select(Mailbox.id).where(Mailbox.public_token == token).limit(1))
        exists_icloud = db.scalar(select(IcloudMailbox.id).where(IcloudMailbox.public_token == token).limit(1))
        if not exists_mailbox and not exists_icloud:
            return token


def upsert_icloud_mailbox(db: Session, payload: IcloudMailboxCreate) -> tuple[IcloudMailbox, bool, int | None]:
    """按邮箱去重导入，并返回修改前的 IMAP 配置用于缓存失效。"""

    mailbox = db.scalar(select(IcloudMailbox).where(func.lower(IcloudMailbox.email) == str(payload.email).lower()))
    created = mailbox is None
    previous_config_id = mailbox.imap_config_id if mailbox else None
    if mailbox is None:
        mailbox = IcloudMailbox(email=str(payload.email), public_token=generate_unique_icloud_token(db))
        db.add(mailbox)
    mailbox.imap_config_id = payload.imap_config_id
    if payload.remark is not None:
        mailbox.remark = payload.remark
    return mailbox, created, previous_config_id


def update_cache_binding(db: Session, mailbox: IcloudMailbox, previous_config_id: int | None) -> None:
    """新建或重新绑定邮箱时清理旧缓存，并请求目标配置回填。"""

    if previous_config_id == mailbox.imap_config_id:
        return
    if mailbox.id is not None:
        delete_mailbox_cache(db, mailbox.id)
    request_config_backfill(db, mailbox.imap_config_id)


@router.get("", response_model=IcloudMailboxListOut)
def list_icloud_mailboxes(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    email: str | None = Query(default=None, max_length=320),
    db: Session = Depends(get_db),
) -> IcloudMailboxListOut:
    """分页查询 iCloud 邮箱，分裂地址会先回源到原始邮箱。"""

    offset = (page - 1) * page_size
    email_filter = (
        func.lower(IcloudMailbox.email) == remove_split_alias(email)
        if email and email.strip()
        else None
    )
    mailbox_query = select(IcloudMailbox, ImapConfig.name).join(
        ImapConfig, IcloudMailbox.imap_config_id == ImapConfig.id
    )
    count_query = select(func.count()).select_from(IcloudMailbox)
    if email_filter is not None:
        mailbox_query = mailbox_query.where(email_filter)
        count_query = count_query.where(email_filter)
    rows = db.execute(mailbox_query.order_by(IcloudMailbox.id.desc()).offset(offset).limit(page_size)).all()
    total = db.scalar(count_query) or 0
    return IcloudMailboxListOut(
        items=[icloud_mailbox_out(mailbox, config_name) for mailbox, config_name in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=IcloudMailboxOut)
def create_icloud_mailbox(payload: IcloudMailboxCreate, db: Session = Depends(get_db)) -> IcloudMailboxOut:
    """新增或更新 iCloud 邮箱，并为绑定变化请求缓存回填。"""

    config = db.get(ImapConfig, payload.imap_config_id)
    if not config:
        raise HTTPException(status_code=404, detail="IMAP 配置不存在")
    mailbox, _, previous_config_id = upsert_icloud_mailbox(db, payload)
    db.flush()
    update_cache_binding(db, mailbox, previous_config_id)
    db.commit()
    db.refresh(mailbox)
    return icloud_mailbox_out(mailbox, config.name)


@router.post("/import", response_model=ImportOut)
def import_icloud_mailboxes(payload: IcloudImportIn, db: Session = Depends(get_db)) -> ImportOut:
    """批量导入 iCloud 邮箱，并合并触发对应 IMAP 配置回填。"""

    config = db.get(ImapConfig, payload.imap_config_id)
    if not config:
        raise HTTPException(status_code=404, detail="IMAP 配置不存在")

    created = 0
    updated = 0
    skipped = 0
    errors: list[str] = []
    for index, raw_line in enumerate(payload.content.splitlines(), start=1):
        try:
            parsed = parse_icloud_line(raw_line)
            if parsed is None:
                skipped += 1
                continue
            email, remark = parsed
            mailbox, is_created, previous_config_id = upsert_icloud_mailbox(
                db, IcloudMailboxCreate(email=email, imap_config_id=payload.imap_config_id, remark=remark)
            )
            db.flush()
            update_cache_binding(db, mailbox, previous_config_id)
            if is_created:
                created += 1
            else:
                updated += 1
        except Exception as exc:
            errors.append(f"第 {index} 行：{exc}")

    db.commit()
    return ImportOut(created=created, updated=updated, skipped=skipped, errors=errors)


@router.get("/{mailbox_id}/messages", response_model=MessageListOut)
def get_icloud_messages(
    mailbox_id: int,
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
) -> MessageListOut:
    """从 SQLite 临时存件返回 iCloud 邮件列表。"""

    mailbox = db.get(IcloudMailbox, mailbox_id)
    if not mailbox:
        raise HTTPException(status_code=404, detail="iCloud 邮箱不存在")
    messages = list_cached_messages(db, mailbox.id, limit)
    return MessageListOut(mailbox_id=mailbox.id, messages=messages)


@router.get("/{mailbox_id}/messages/{uid}", response_model=MessageDetailOut)
def get_icloud_message_detail(mailbox_id: int, uid: str, db: Session = Depends(get_db)) -> MessageDetailOut:
    """从 SQLite 临时存件读取指定 iCloud 邮件详情。"""

    mailbox = db.get(IcloudMailbox, mailbox_id)
    if not mailbox:
        raise HTTPException(status_code=404, detail="iCloud 邮箱不存在")
    message = get_cached_message(db, mailbox.id, uid)
    if not message:
        raise HTTPException(status_code=400, detail="获取邮件详情失败：邮件不存在或缓存已过期")
    return MessageDetailOut(**message)


@router.delete("/{mailbox_id}")
def delete_icloud_mailbox(mailbox_id: int, db: Session = Depends(get_db)) -> dict:
    """删除 iCloud 邮箱及其全部临时邮件。"""

    mailbox = db.get(IcloudMailbox, mailbox_id)
    if not mailbox:
        raise HTTPException(status_code=404, detail="iCloud 邮箱不存在")
    delete_mailbox_cache(db, mailbox.id)
    db.delete(mailbox)
    db.commit()
    return {"ok": True}
