from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import EmailStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..email_address import remove_split_alias
from ..email_client import MailCredential, OutlookImapClient
from ..imap_client import GenericImapClient, ImapCredential
from ..models import IcloudMailbox, ImapConfig, Mailbox
from ..schemas import CodeOut, MessageDetailOut, MessageListOut, PublicMailboxOut
from ..security import decrypt_value, verify_public_api_key


router = APIRouter(prefix="/public", tags=["public"], dependencies=[Depends(verify_public_api_key)])
token_router = APIRouter(prefix="/token", tags=["token"])


def public_mailbox_out(mailbox: Mailbox) -> PublicMailboxOut:
    return PublicMailboxOut(
        email=mailbox.email,
        public_token=mailbox.public_token,
        remark=mailbox.remark,
        status=mailbox.status,
        last_checked_at=mailbox.last_checked_at,
    )


def public_icloud_out(mailbox: IcloudMailbox) -> PublicMailboxOut:
    """iCloud 转发邮箱复用公开邮箱响应结构，状态由绑定 IMAP 决定。"""

    return PublicMailboxOut(
        email=mailbox.email,
        public_token=mailbox.public_token,
        remark=mailbox.remark,
        status="forwarded",
        last_checked_at=None,
    )


def credential_from_mailbox(mailbox: Mailbox) -> MailCredential:
    return MailCredential(
        email=mailbox.email,
        password=decrypt_value(mailbox.password_enc),
        client_id=decrypt_value(mailbox.client_id_enc),
        token=decrypt_value(mailbox.token_enc),
    )


def imap_credential_from_config(config: ImapConfig) -> ImapCredential:
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


def get_mailbox_by_token(token: str, db: Session) -> Mailbox:
    mailbox = db.scalar(select(Mailbox).where(Mailbox.public_token == token))
    if not mailbox:
        raise HTTPException(status_code=404, detail="邮箱 token 不存在")
    return mailbox


def get_icloud_by_token(token: str, db: Session) -> IcloudMailbox | None:
    return db.scalar(select(IcloudMailbox).where(IcloudMailbox.public_token == token))


def get_mailbox_by_email_or_none(email: str, db: Session) -> Mailbox | None:
    value = email.strip().lower()
    mailbox = db.scalar(select(Mailbox).where(func.lower(Mailbox.email) == value))
    if mailbox:
        return mailbox

    normalized_email = remove_split_alias(value)
    if normalized_email != value:
        return db.scalar(select(Mailbox).where(func.lower(Mailbox.email) == normalized_email))
    return None


def get_icloud_by_email_or_none(email: str, db: Session) -> IcloudMailbox | None:
    value = str(email).strip().lower()
    mailbox = db.scalar(select(IcloudMailbox).where(func.lower(IcloudMailbox.email) == value))
    if mailbox:
        return mailbox

    normalized_email = remove_split_alias(value)
    if normalized_email != value:
        return db.scalar(select(IcloudMailbox).where(func.lower(IcloudMailbox.email) == normalized_email))
    return None


def get_mailbox_by_email(email: EmailStr, db: Session) -> Mailbox:
    mailbox = get_mailbox_by_email_or_none(str(email), db)
    if mailbox:
        return mailbox

    raise HTTPException(status_code=404, detail="邮箱不存在")


def get_icloud_client(mailbox: IcloudMailbox, db: Session) -> GenericImapClient:
    config = db.get(ImapConfig, mailbox.imap_config_id)
    if not config:
        raise HTTPException(status_code=404, detail="绑定的 IMAP 配置不存在")
    return GenericImapClient(imap_credential_from_config(config))


@router.get("/mailboxes", response_model=list[PublicMailboxOut])
def list_public_mailboxes(db: Session = Depends(get_db)) -> list[PublicMailboxOut]:
    mailboxes = db.scalars(select(Mailbox).order_by(Mailbox.id.desc())).all()
    icloud_mailboxes = db.scalars(select(IcloudMailbox).order_by(IcloudMailbox.id.desc())).all()
    return [public_mailbox_out(mailbox) for mailbox in mailboxes] + [
        public_icloud_out(mailbox) for mailbox in icloud_mailboxes
    ]


@router.get("/mailboxes/by-email", response_model=PublicMailboxOut)
def get_public_mailbox_by_email(email: EmailStr = Query(...), db: Session = Depends(get_db)) -> PublicMailboxOut:
    mailbox = get_mailbox_by_email_or_none(str(email), db)
    if mailbox:
        return public_mailbox_out(mailbox)
    icloud_mailbox = get_icloud_by_email_or_none(str(email), db)
    if icloud_mailbox:
        return public_icloud_out(icloud_mailbox)
    raise HTTPException(status_code=404, detail="邮箱不存在")


@router.get("/mailboxes/by-email/messages", response_model=MessageListOut)
def list_public_messages_by_email(
    email: EmailStr = Query(...),
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
) -> MessageListOut:
    mailbox = get_mailbox_by_email_or_none(str(email), db)
    if not mailbox:
        icloud_mailbox = get_icloud_by_email_or_none(str(email), db)
        if not icloud_mailbox:
            raise HTTPException(status_code=404, detail="邮箱不存在")
        try:
            messages = get_icloud_client(icloud_mailbox, db).list_messages(
                limit=limit,
                recipient_email=str(email),
                include_aliases=True,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"获取邮件失败：{exc}") from exc
        return MessageListOut(mailbox_id=icloud_mailbox.id, messages=messages)
    try:
        messages = OutlookImapClient(credential_from_mailbox(mailbox)).list_messages(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"获取邮件失败：{exc}") from exc
    return MessageListOut(mailbox_id=mailbox.id, messages=messages)


@router.get("/mailboxes/by-email/messages/{uid}", response_model=MessageDetailOut)
def get_public_message_detail_by_email(
    uid: str,
    email: EmailStr = Query(...),
    db: Session = Depends(get_db),
) -> MessageDetailOut:
    mailbox = get_mailbox_by_email_or_none(str(email), db)
    if not mailbox:
        icloud_mailbox = get_icloud_by_email_or_none(str(email), db)
        if not icloud_mailbox:
            raise HTTPException(status_code=404, detail="邮箱不存在")
        try:
            message = get_icloud_client(icloud_mailbox, db).get_message(uid=uid)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"获取邮件详情失败：{exc}") from exc
        return MessageDetailOut(**message)
    try:
        message = OutlookImapClient(credential_from_mailbox(mailbox)).get_message(uid=uid)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"获取邮件详情失败：{exc}") from exc
    return MessageDetailOut(**message)


@router.get("/mailboxes/by-email/code", response_model=CodeOut)
def get_public_latest_code_by_email(
    email: EmailStr = Query(...),
    limit: int = Query(default=10, ge=1, le=30),
    db: Session = Depends(get_db),
) -> CodeOut:
    mailbox = get_mailbox_by_email_or_none(str(email), db)
    if not mailbox:
        icloud_mailbox = get_icloud_by_email_or_none(str(email), db)
        if not icloud_mailbox:
            raise HTTPException(status_code=404, detail="邮箱不存在")
        try:
            message = get_icloud_client(icloud_mailbox, db).find_latest_code(
                limit=limit,
                recipient_email=str(email),
                include_aliases=True,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"获取验证码失败：{exc}") from exc
        return CodeOut(
            mailbox_token=icloud_mailbox.public_token,
            email=icloud_mailbox.email,
            code=message.get("code") if message else None,
            message=message if message else None,
        )
    try:
        message = OutlookImapClient(credential_from_mailbox(mailbox)).find_latest_code(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"获取验证码失败：{exc}") from exc
    return CodeOut(
        mailbox_token=mailbox.public_token,
        email=mailbox.email,
        code=message.get("code") if message else None,
        message=message if message else None,
    )


@router.get("/mailboxes/{token}", response_model=PublicMailboxOut)
def get_public_mailbox(token: str, db: Session = Depends(get_db)) -> PublicMailboxOut:
    mailbox = db.scalar(select(Mailbox).where(Mailbox.public_token == token))
    if mailbox:
        return public_mailbox_out(mailbox)
    icloud_mailbox = get_icloud_by_token(token, db)
    if icloud_mailbox:
        return public_icloud_out(icloud_mailbox)
    raise HTTPException(status_code=404, detail="邮箱 token 不存在")


@router.get("/mailboxes/{token}/messages", response_model=MessageListOut)
def list_public_messages(
    token: str,
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
) -> MessageListOut:
    icloud_mailbox = get_icloud_by_token(token, db)
    if icloud_mailbox:
        try:
            messages = get_icloud_client(icloud_mailbox, db).list_messages(
                limit=limit,
                recipient_email=icloud_mailbox.email,
                include_aliases=True,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"获取邮件失败：{exc}") from exc
        return MessageListOut(mailbox_id=icloud_mailbox.id, messages=messages)
    mailbox = get_mailbox_by_token(token, db)
    try:
        messages = OutlookImapClient(credential_from_mailbox(mailbox)).list_messages(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"获取邮件失败：{exc}") from exc
    return MessageListOut(mailbox_id=mailbox.id, messages=messages)


@router.get("/mailboxes/{token}/messages/{uid}", response_model=MessageDetailOut)
def get_public_message_detail(token: str, uid: str, db: Session = Depends(get_db)) -> MessageDetailOut:
    icloud_mailbox = get_icloud_by_token(token, db)
    if icloud_mailbox:
        try:
            message = get_icloud_client(icloud_mailbox, db).get_message(uid=uid)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"获取邮件详情失败：{exc}") from exc
        return MessageDetailOut(**message)
    mailbox = get_mailbox_by_token(token, db)
    try:
        message = OutlookImapClient(credential_from_mailbox(mailbox)).get_message(uid=uid)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"获取邮件详情失败：{exc}") from exc
    return MessageDetailOut(**message)


@router.get("/mailboxes/{token}/code", response_model=CodeOut)
def get_public_latest_code(
    token: str,
    limit: int = Query(default=10, ge=1, le=30),
    db: Session = Depends(get_db),
) -> CodeOut:
    icloud_mailbox = get_icloud_by_token(token, db)
    if icloud_mailbox:
        try:
            message = get_icloud_client(icloud_mailbox, db).find_latest_code(
                limit=limit,
                recipient_email=icloud_mailbox.email,
                include_aliases=True,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"获取验证码失败：{exc}") from exc
        return CodeOut(
            mailbox_token=icloud_mailbox.public_token,
            email=icloud_mailbox.email,
            code=message.get("code") if message else None,
            message=message if message else None,
        )
    mailbox = get_mailbox_by_token(token, db)
    try:
        message = OutlookImapClient(credential_from_mailbox(mailbox)).find_latest_code(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"获取验证码失败：{exc}") from exc
    return CodeOut(
        mailbox_token=mailbox.public_token,
        email=mailbox.email,
        code=message.get("code") if message else None,
        message=message if message else None,
    )


@token_router.get("/{token}/code", response_model=CodeOut)
def get_token_latest_code(
    token: str,
    limit: int = Query(default=10, ge=1, le=30),
    db: Session = Depends(get_db),
) -> CodeOut:
    icloud_mailbox = get_icloud_by_token(token, db)
    if icloud_mailbox:
        try:
            message = get_icloud_client(icloud_mailbox, db).find_latest_code(
                limit=limit,
                recipient_email=icloud_mailbox.email,
                include_aliases=True,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"获取验证码失败：{exc}") from exc
        return CodeOut(
            mailbox_token=icloud_mailbox.public_token,
            email=icloud_mailbox.email,
            code=message.get("code") if message else None,
            message=message if message else None,
        )
    mailbox = get_mailbox_by_token(token, db)
    try:
        message = OutlookImapClient(credential_from_mailbox(mailbox)).find_latest_code(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"获取验证码失败：{exc}") from exc
    return CodeOut(
        mailbox_token=mailbox.public_token,
        email=mailbox.email,
        code=message.get("code") if message else None,
        message=message if message else None,
    )
