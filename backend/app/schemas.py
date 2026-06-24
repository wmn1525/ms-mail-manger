from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class MailboxBase(BaseModel):
    email: EmailStr
    password: str | None = None
    client_id: str | None = None
    token: str | None = None
    remark: str | None = None


class MailboxCreate(MailboxBase):
    pass


class MailboxUpdate(BaseModel):
    email: EmailStr | None = None
    password: str | None = None
    client_id: str | None = None
    token: str | None = None
    remark: str | None = None


class MailboxOut(BaseModel):
    id: int
    email: EmailStr
    public_token: str
    remark: str | None
    status: str
    last_error: str | None
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime
    has_password: bool = False
    has_client_id: bool = False
    has_token: bool = False

    model_config = ConfigDict(from_attributes=True)


class MailboxListOut(BaseModel):
    items: list[MailboxOut]
    total: int
    page: int
    page_size: int
    live: int
    dead: int
    with_token: int


class ImportIn(BaseModel):
    content: str = Field(..., description="每行：邮箱----密码----client_id----令牌")


class ImportOut(BaseModel):
    created: int
    updated: int
    skipped: int
    checked: int = 0
    failed: int = 0
    errors: list[str]


class CheckOut(BaseModel):
    id: int
    status: str
    error: str | None = None
    checked_at: datetime


class BulkCheckIn(BaseModel):
    ids: list[int]


class BulkCheckOut(BaseModel):
    checked: int
    live: int
    dead: int
    results: list[CheckOut]


class RemoveAbnormalOut(BaseModel):
    removed: int


class MessageOut(BaseModel):
    uid: str
    subject: str
    from_: str = Field(alias="from")
    date: str | None = None
    snippet: str
    code: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class MessageListOut(BaseModel):
    mailbox_id: int
    messages: list[MessageOut]


class MessageDetailOut(MessageOut):
    body: str
    html: str | None = None


class PublicMailboxOut(BaseModel):
    email: EmailStr
    public_token: str
    remark: str | None
    status: str
    last_checked_at: datetime | None


class CodeOut(BaseModel):
    mailbox_token: str
    email: EmailStr
    code: str | None = None
    message: MessageOut | None = None


class ApiKeyCreateIn(BaseModel):
    name: str = "default"


class ApiKeyOut(BaseModel):
    id: int
    name: str
    key_prefix: str
    enabled: bool
    last_used_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApiKeyCreateOut(ApiKeyOut):
    api_key: str


class ApiKeyUpdateIn(BaseModel):
    enabled: bool
