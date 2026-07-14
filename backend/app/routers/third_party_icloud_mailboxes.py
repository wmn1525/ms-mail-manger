"""第三方 iCloud 邮箱导入、列表、取码和删除接口。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import EmailStr, TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..email_address import remove_split_alias
from ..models import IcloudMailbox, Mailbox, ThirdPartyIcloudMailbox
from ..schemas import (
    ImportOut,
    ThirdPartyIcloudCodeOut,
    ThirdPartyIcloudImportIn,
    ThirdPartyIcloudMailboxListOut,
    ThirdPartyIcloudMailboxOut,
)
from ..security import decrypt_value, encrypt_value, generate_public_token, get_current_admin
from ..third_party_icloud_client import ThirdPartyIcloudError, fetch_latest_code, validate_fetch_url


router = APIRouter(
    prefix="/third-party-icloud-mailboxes",
    tags=["third-party-icloud-mailboxes"],
    dependencies=[Depends(get_current_admin)],
)
EMAIL_ADAPTER = TypeAdapter(EmailStr)


def generate_unique_token(db: Session) -> str:
    """生成同时避开三类邮箱记录的公开标识。"""

    while True:
        token = generate_public_token()
        exists_mailbox = db.scalar(select(Mailbox.id).where(Mailbox.public_token == token).limit(1))
        exists_icloud = db.scalar(
            select(IcloudMailbox.id).where(IcloudMailbox.public_token == token).limit(1)
        )
        exists_third_party = db.scalar(
            select(ThirdPartyIcloudMailbox.id).where(
                ThirdPartyIcloudMailbox.public_token == token
            ).limit(1)
        )
        if not exists_mailbox and not exists_icloud and not exists_third_party:
            return token


def parse_import_line(line: str) -> tuple[str, str] | None:
    """解析严格的“邮箱----取码链接”导入格式。"""

    value = line.strip()
    if not value or value.startswith("#"):
        return None
    parts = [part.strip() for part in value.split("----")]
    if len(parts) != 2 or not parts[1]:
        raise ValueError("格式必须为：邮箱----取码链接")
    email = str(EMAIL_ADAPTER.validate_python(parts[0]))
    return email, validate_fetch_url(email, parts[1])


def upsert_mailbox(db: Session, email: str, fetch_url: str) -> bool:
    """按邮箱更新加密取码链接，并返回是否为新增记录。"""

    mailbox = db.scalar(
        select(ThirdPartyIcloudMailbox).where(func.lower(ThirdPartyIcloudMailbox.email) == email.lower())
    )
    created = mailbox is None
    encrypted_url = encrypt_value(fetch_url)
    if encrypted_url is None:
        raise ValueError("取码链接不能为空")
    if mailbox is None:
        mailbox = ThirdPartyIcloudMailbox(
            email=email,
            public_token=generate_unique_token(db),
            fetch_url_enc=encrypted_url,
        )
        db.add(mailbox)
    else:
        if not mailbox.public_token:
            mailbox.public_token = generate_unique_token(db)
        mailbox.fetch_url_enc = encrypted_url
    return created


@router.get("", response_model=ThirdPartyIcloudMailboxListOut)
def list_mailboxes(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    email: str | None = Query(default=None, max_length=320),
    db: Session = Depends(get_db),
) -> ThirdPartyIcloudMailboxListOut:
    """分页查询第三方 iCloud 邮箱，分裂地址会回源到基础邮箱。"""

    email_filter = (
        func.lower(ThirdPartyIcloudMailbox.email) == remove_split_alias(email)
        if email and email.strip()
        else None
    )
    query = select(ThirdPartyIcloudMailbox)
    count_query = select(func.count()).select_from(ThirdPartyIcloudMailbox)
    if email_filter is not None:
        query = query.where(email_filter)
        count_query = count_query.where(email_filter)
    mailboxes = db.scalars(
        query.order_by(ThirdPartyIcloudMailbox.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return ThirdPartyIcloudMailboxListOut(
        items=[ThirdPartyIcloudMailboxOut.model_validate(mailbox) for mailbox in mailboxes],
        total=db.scalar(count_query) or 0,
        page=page,
        page_size=page_size,
    )


@router.post("/import", response_model=ImportOut)
def import_mailboxes(
    payload: ThirdPartyIcloudImportIn,
    db: Session = Depends(get_db),
) -> ImportOut:
    """批量导入第三方 iCloud 邮箱，重复邮箱会更新取码链接。"""

    created = 0
    updated = 0
    skipped = 0
    errors: list[str] = []
    for index, raw_line in enumerate(payload.content.splitlines(), start=1):
        try:
            parsed = parse_import_line(raw_line)
            if parsed is None:
                skipped += 1
                continue
            email, fetch_url = parsed
            if upsert_mailbox(db, email, fetch_url):
                created += 1
            else:
                updated += 1
        except Exception as exc:
            errors.append(f"第 {index} 行：{exc}")
    db.commit()
    return ImportOut(created=created, updated=updated, skipped=skipped, errors=errors)


@router.get("/{mailbox_id}/code", response_model=ThirdPartyIcloudCodeOut)
def get_latest_code(mailbox_id: int, db: Session = Depends(get_db)) -> ThirdPartyIcloudCodeOut:
    """通过加密保存的第三方链接实时读取验证码。"""

    mailbox = db.get(ThirdPartyIcloudMailbox, mailbox_id)
    if not mailbox:
        raise HTTPException(status_code=404, detail="第三方 iCloud 邮箱不存在")
    fetch_url = decrypt_value(mailbox.fetch_url_enc)
    if not fetch_url:
        raise HTTPException(status_code=400, detail="第三方 iCloud 取码链接为空")
    try:
        return ThirdPartyIcloudCodeOut(email=mailbox.email, code=fetch_latest_code(mailbox.email, fetch_url))
    except ThirdPartyIcloudError as exc:
        raise HTTPException(status_code=400, detail=f"获取验证码失败：{exc}") from exc


@router.delete("/{mailbox_id}")
def delete_mailbox(mailbox_id: int, db: Session = Depends(get_db)) -> dict:
    """删除第三方 iCloud 邮箱及其加密取码链接。"""

    mailbox = db.get(ThirdPartyIcloudMailbox, mailbox_id)
    if not mailbox:
        raise HTTPException(status_code=404, detail="第三方 iCloud 邮箱不存在")
    db.delete(mailbox)
    db.commit()
    return {"ok": True}
