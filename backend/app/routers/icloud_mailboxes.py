from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..imap_client import GenericImapClient, ImapCredential
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
from ..security import decrypt_value, generate_public_token, get_current_admin


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


def upsert_icloud_mailbox(db: Session, payload: IcloudMailboxCreate) -> tuple[IcloudMailbox, bool]:
    """按邮箱去重导入，重复邮箱更新绑定的 IMAP 配置。"""

    mailbox = db.scalar(select(IcloudMailbox).where(func.lower(IcloudMailbox.email) == str(payload.email).lower()))
    created = mailbox is None
    if mailbox is None:
        mailbox = IcloudMailbox(email=str(payload.email), public_token=generate_unique_icloud_token(db))
        db.add(mailbox)
    mailbox.imap_config_id = payload.imap_config_id
    if payload.remark is not None:
        mailbox.remark = payload.remark
    return mailbox, created


def icloud_client_from_mailbox(mailbox: IcloudMailbox, db: Session) -> GenericImapClient:
    """根据 iCloud 邮箱绑定关系打开对应的 IMAP 接收箱。"""

    config = db.get(ImapConfig, mailbox.imap_config_id)
    if not config:
        raise HTTPException(status_code=404, detail="绑定的 IMAP 配置不存在")
    password = decrypt_value(config.password_enc)
    if not password:
        raise HTTPException(status_code=400, detail="IMAP 配置缺少密码")
    return GenericImapClient(
        ImapCredential(
            host=config.host,
            port=config.port,
            username=config.username,
            password=password,
            folder=config.folder,
            use_ssl=config.use_ssl,
        )
    )


@router.get("", response_model=IcloudMailboxListOut)
def list_icloud_mailboxes(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> IcloudMailboxListOut:
    offset = (page - 1) * page_size
    rows = db.execute(
        select(IcloudMailbox, ImapConfig.name)
        .join(ImapConfig, IcloudMailbox.imap_config_id == ImapConfig.id)
        .order_by(IcloudMailbox.id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()
    total = db.scalar(select(func.count()).select_from(IcloudMailbox)) or 0
    return IcloudMailboxListOut(
        items=[icloud_mailbox_out(mailbox, config_name) for mailbox, config_name in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=IcloudMailboxOut)
def create_icloud_mailbox(payload: IcloudMailboxCreate, db: Session = Depends(get_db)) -> IcloudMailboxOut:
    config = db.get(ImapConfig, payload.imap_config_id)
    if not config:
        raise HTTPException(status_code=404, detail="IMAP 配置不存在")
    mailbox, _ = upsert_icloud_mailbox(db, payload)
    db.commit()
    db.refresh(mailbox)
    return icloud_mailbox_out(mailbox, config.name)


@router.post("/import", response_model=ImportOut)
def import_icloud_mailboxes(payload: IcloudImportIn, db: Session = Depends(get_db)) -> ImportOut:
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
            _, is_created = upsert_icloud_mailbox(
                db, IcloudMailboxCreate(email=email, imap_config_id=payload.imap_config_id, remark=remark)
            )
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
    mailbox = db.get(IcloudMailbox, mailbox_id)
    if not mailbox:
        raise HTTPException(status_code=404, detail="iCloud 邮箱不存在")
    try:
        messages = icloud_client_from_mailbox(mailbox, db).list_messages(
            limit=limit,
            recipient_email=mailbox.email,
            include_aliases=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"获取邮件失败：{exc}") from exc
    return MessageListOut(mailbox_id=mailbox.id, messages=messages)


@router.get("/{mailbox_id}/messages/{uid}", response_model=MessageDetailOut)
def get_icloud_message_detail(mailbox_id: int, uid: str, db: Session = Depends(get_db)) -> MessageDetailOut:
    mailbox = db.get(IcloudMailbox, mailbox_id)
    if not mailbox:
        raise HTTPException(status_code=404, detail="iCloud 邮箱不存在")
    try:
        message = icloud_client_from_mailbox(mailbox, db).get_message(uid=uid)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"获取邮件详情失败：{exc}") from exc
    return MessageDetailOut(**message)


@router.delete("/{mailbox_id}")
def delete_icloud_mailbox(mailbox_id: int, db: Session = Depends(get_db)) -> dict:
    mailbox = db.get(IcloudMailbox, mailbox_id)
    if not mailbox:
        raise HTTPException(status_code=404, detail="iCloud 邮箱不存在")
    db.delete(mailbox)
    db.commit()
    return {"ok": True}
