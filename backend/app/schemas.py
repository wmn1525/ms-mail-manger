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


class ImapConfigCreate(BaseModel):
    """创建接码 IMAP 配置所需字段。"""

    name: str
    host: str
    port: int = Field(default=993, ge=1, le=65535)
    username: str
    password: str
    use_ssl: bool = True
    remark: str | None = None


class ImapConfigUpdate(BaseModel):
    """修改 IMAP 配置，密码留空时保持原密码。"""

    name: str
    host: str
    port: int = Field(ge=1, le=65535)
    username: str
    password: str | None = None
    use_ssl: bool
    remark: str | None = None


class ImapConfigOut(BaseModel):
    """返回给后台列表的 IMAP 配置信息，不暴露密码明文。"""

    id: int
    name: str
    host: str
    port: int
    username: str
    folder: str
    use_ssl: bool
    remark: str | None
    status: str
    last_error: str | None
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime
    has_password: bool = False

    model_config = ConfigDict(from_attributes=True)


class IcloudMailboxCreate(BaseModel):
    """新增单个 iCloud 转发邮箱时绑定目标 IMAP 配置。"""

    email: EmailStr
    imap_config_id: int
    remark: str | None = None


class IcloudMailboxOut(BaseModel):
    """后台展示 iCloud 邮箱及其绑定的 IMAP 配置。"""

    id: int
    email: EmailStr
    public_token: str
    imap_config_id: int
    imap_config_name: str
    remark: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IcloudMailboxListOut(BaseModel):
    items: list[IcloudMailboxOut]
    total: int
    page: int
    page_size: int


class IcloudImportIn(BaseModel):
    """批量导入 iCloud 邮箱，每行一个邮箱，可追加备注。"""

    imap_config_id: int
    content: str = Field(..., description="每行：邮箱 或 邮箱----备注")


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
