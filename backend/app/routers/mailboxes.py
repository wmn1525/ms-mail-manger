from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..email_address import remove_split_alias
from ..email_client import MailCredential, OutlookImapClient
from ..models import Mailbox
from ..schemas import (
    BulkCheckIn,
    BulkCheckOut,
    CheckOut,
    ImportIn,
    ImportOut,
    MailboxCreate,
    MailboxListOut,
    MailboxOut,
    MessageDetailOut,
    MessageListOut,
    RemoveAbnormalOut,
)
from ..security import decrypt_value, encrypt_value, generate_public_token, get_current_admin


router = APIRouter(prefix="/mailboxes", tags=["mailboxes"], dependencies=[Depends(get_current_admin)])


def mailbox_out(mailbox: Mailbox) -> MailboxOut:
    return MailboxOut(
        id=mailbox.id,
        email=mailbox.email,
        public_token=mailbox.public_token,
        remark=mailbox.remark,
        status=mailbox.status,
        last_error=mailbox.last_error,
        last_checked_at=mailbox.last_checked_at,
        created_at=mailbox.created_at,
        updated_at=mailbox.updated_at,
        has_password=bool(mailbox.password_enc),
        has_client_id=bool(mailbox.client_id_enc),
        has_token=bool(mailbox.token_enc),
    )


def credential_from_mailbox(mailbox: Mailbox) -> MailCredential:
    return MailCredential(
        email=mailbox.email,
        password=decrypt_value(mailbox.password_enc),
        client_id=decrypt_value(mailbox.client_id_enc),
        token=decrypt_value(mailbox.token_enc),
    )


def parse_import_line(line: str) -> tuple[str, str | None, str | None, str | None] | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "----" in line:
        parts = [part.strip() for part in line.split("----")]
    else:
        parts = [part.strip() for part in line.replace("\t", ",").split(",")]
    if not parts or "@" not in parts[0]:
        raise ValueError("邮箱格式不正确")
    while len(parts) < 4:
        parts.append("")
    return parts[0], parts[1] or None, parts[2] or None, parts[3] or None


def upsert_mailbox(db: Session, payload: MailboxCreate) -> tuple[Mailbox, bool]:
    mailbox = db.scalar(select(Mailbox).where(Mailbox.email == str(payload.email)))
    created = mailbox is None
    if mailbox is None:
        mailbox = Mailbox(email=str(payload.email), public_token=generate_public_token())
        db.add(mailbox)
    elif not mailbox.public_token:
        mailbox.public_token = generate_public_token()
    if payload.password is not None:
        mailbox.password_enc = encrypt_value(payload.password)
    if payload.client_id is not None:
        mailbox.client_id_enc = encrypt_value(payload.client_id)
    if payload.token is not None:
        mailbox.token_enc = encrypt_value(payload.token)
    if payload.remark is not None:
        mailbox.remark = payload.remark
    return mailbox, created


def check_credential(credential: MailCredential) -> tuple[str, str | None]:
    try:
        OutlookImapClient(credential).check_alive()
        return "live", None
    except Exception as exc:
        return "dead", str(exc)


def check_mailbox_model(mailbox: Mailbox) -> CheckOut:
    checked_at = datetime.now(UTC)
    status_value, error = check_credential(credential_from_mailbox(mailbox))
    mailbox.status = status_value
    mailbox.last_error = error
    mailbox.last_checked_at = checked_at
    return CheckOut(id=mailbox.id, status=status_value, error=error, checked_at=checked_at)


@router.get("", response_model=MailboxListOut)
def list_mailboxes(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    email: str | None = Query(default=None, max_length=320),
    db: Session = Depends(get_db),
) -> MailboxListOut:
    """分页查询微软邮箱，分裂地址会先回源到原始邮箱。"""

    offset = (page - 1) * page_size
    email_filter = (
        func.lower(Mailbox.email) == remove_split_alias(email)
        if email and email.strip()
        else None
    )
    mailbox_query = select(Mailbox)
    count_query = select(func.count()).select_from(Mailbox)
    if email_filter is not None:
        mailbox_query = mailbox_query.where(email_filter)
        count_query = count_query.where(email_filter)
    mailboxes = db.scalars(mailbox_query.order_by(Mailbox.id.desc()).offset(offset).limit(page_size)).all()
    total = db.scalar(count_query) or 0
    live_query = select(func.count()).select_from(Mailbox).where(Mailbox.status == "live")
    dead_query = select(func.count()).select_from(Mailbox).where(Mailbox.status == "dead")
    token_query = select(func.count()).select_from(Mailbox).where(Mailbox.token_enc.is_not(None))
    if email_filter is not None:
        live_query = live_query.where(email_filter)
        dead_query = dead_query.where(email_filter)
        token_query = token_query.where(email_filter)
    live = db.scalar(live_query) or 0
    dead = db.scalar(dead_query) or 0
    with_token = db.scalar(token_query) or 0
    return MailboxListOut(
        items=[mailbox_out(mailbox) for mailbox in mailboxes],
        total=total,
        page=page,
        page_size=page_size,
        live=live,
        dead=dead,
        with_token=with_token,
    )


@router.post("", response_model=MailboxOut)
def create_mailbox(payload: MailboxCreate, db: Session = Depends(get_db)) -> MailboxOut:
    mailbox, _ = upsert_mailbox(db, payload)
    db.commit()
    db.refresh(mailbox)
    return mailbox_out(mailbox)


@router.post("/import", response_model=ImportOut)
def import_mailboxes(payload: ImportIn, db: Session = Depends(get_db)) -> ImportOut:
    created = 0
    updated = 0
    skipped = 0
    errors: list[str] = []
    checked = 0
    failed = 0

    for index, raw_line in enumerate(payload.content.splitlines(), start=1):
        try:
            parsed = parse_import_line(raw_line)
            if parsed is None:
                skipped += 1
                continue
            email, password, client_id, token = parsed
            checked += 1
            status_value, error = check_credential(
                MailCredential(email=email, password=password, client_id=client_id, token=token)
            )
            if status_value != "live":
                failed += 1
                skipped += 1
                errors.append(f"第 {index} 行：测活失败，未导入：{error}")
                continue
            mailbox, is_created = upsert_mailbox(
                db,
                MailboxCreate(email=email, password=password, client_id=client_id, token=token),
            )
            mailbox.status = "live"
            mailbox.last_error = None
            mailbox.last_checked_at = datetime.now(UTC)
            if is_created:
                created += 1
            else:
                updated += 1
        except Exception as exc:
            errors.append(f"第 {index} 行：{exc}")

    db.commit()
    return ImportOut(created=created, updated=updated, skipped=skipped, checked=checked, failed=failed, errors=errors)


@router.post("/bulk-check", response_model=BulkCheckOut)
def bulk_check_mailboxes(payload: BulkCheckIn, db: Session = Depends(get_db)) -> BulkCheckOut:
    results: list[CheckOut] = []
    live = 0
    dead = 0
    for mailbox_id in payload.ids:
        mailbox = db.get(Mailbox, mailbox_id)
        if not mailbox:
            continue
        result = check_mailbox_model(mailbox)
        results.append(result)
        if result.status == "live":
            live += 1
        else:
            dead += 1
    db.commit()
    return BulkCheckOut(checked=len(results), live=live, dead=dead, results=results)


@router.delete("/abnormal", response_model=RemoveAbnormalOut)
def remove_abnormal_mailboxes(db: Session = Depends(get_db)) -> RemoveAbnormalOut:
    mailboxes = db.scalars(select(Mailbox).where(Mailbox.status == "dead")).all()
    removed = len(mailboxes)
    for mailbox in mailboxes:
        db.delete(mailbox)
    db.commit()
    return RemoveAbnormalOut(removed=removed)


@router.delete("/{mailbox_id}")
def delete_mailbox(mailbox_id: int, db: Session = Depends(get_db)) -> dict:
    mailbox = db.get(Mailbox, mailbox_id)
    if not mailbox:
        raise HTTPException(status_code=404, detail="邮箱不存在")
    db.delete(mailbox)
    db.commit()
    return {"ok": True}


@router.post("/{mailbox_id}/check", response_model=CheckOut)
def check_mailbox(mailbox_id: int, db: Session = Depends(get_db)) -> CheckOut:
    mailbox = db.get(Mailbox, mailbox_id)
    if not mailbox:
        raise HTTPException(status_code=404, detail="邮箱不存在")

    result = check_mailbox_model(mailbox)
    db.commit()
    db.refresh(mailbox)
    return result


@router.get("/{mailbox_id}/messages", response_model=MessageListOut)
def get_messages(
    mailbox_id: int,
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
) -> MessageListOut:
    mailbox = db.get(Mailbox, mailbox_id)
    if not mailbox:
        raise HTTPException(status_code=404, detail="邮箱不存在")
    try:
        messages = OutlookImapClient(credential_from_mailbox(mailbox)).list_messages(limit=limit)
    except Exception as exc:
        mailbox.status = "dead"
        mailbox.last_error = str(exc)
        mailbox.last_checked_at = datetime.now(UTC)
        db.commit()
        raise HTTPException(status_code=400, detail=f"获取邮件失败：{exc}") from exc
    return MessageListOut(mailbox_id=mailbox.id, messages=messages)


@router.get("/{mailbox_id}/messages/{uid}", response_model=MessageDetailOut)
def get_message_detail(mailbox_id: int, uid: str, db: Session = Depends(get_db)) -> MessageDetailOut:
    mailbox = db.get(Mailbox, mailbox_id)
    if not mailbox:
        raise HTTPException(status_code=404, detail="邮箱不存在")
    try:
        message = OutlookImapClient(credential_from_mailbox(mailbox)).get_message(uid=uid)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"获取邮件详情失败：{exc}") from exc
    return MessageDetailOut(**message)
