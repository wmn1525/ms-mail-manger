from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Mailbox(Base):
    __tablename__ = "mailboxes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    public_token: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_id_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ImapConfig(Base):
    """保存接码 IMAP 收件箱配置，供 iCloud 转发邮箱复用。"""

    __tablename__ = "imap_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=993)
    username: Mapped[str] = mapped_column(String(320), nullable=False)
    password_enc: Mapped[str] = mapped_column(Text, nullable=False)
    folder: Mapped[str] = mapped_column(String(120), nullable=False, default="INBOX")
    use_ssl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class IcloudMailbox(Base):
    """记录会转发到指定 IMAP 收件箱的 iCloud 邮箱。"""

    __tablename__ = "icloud_mailboxes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    public_token: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    imap_config_id: Mapped[int] = mapped_column(ForeignKey("imap_configs.id"), nullable=False, index=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ImapSyncState(Base):
    """保存每个 IMAP 收件箱的增量同步游标和回填进度。"""

    __tablename__ = "imap_sync_states"
    __table_args__ = (UniqueConstraint("imap_config_id", "folder", name="uq_imap_sync_state_folder"),)

    # 主键仅供数据库关联，业务定位使用 IMAP 配置与目录组合。
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # 同步状态归属的 IMAP 配置。
    imap_config_id: Mapped[int] = mapped_column(ForeignKey("imap_configs.id"), nullable=False, index=True)
    # 当前只同步 INBOX，但保留目录字段用于校验 UID 的作用域。
    folder: Mapped[str] = mapped_column(String(120), nullable=False, default="INBOX")
    # UIDVALIDITY 改变时原 UID 全部失效，必须重建缓存。
    uid_validity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 最后一次完整提交到缓存的远端 UID。
    last_uid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 最近一次请求回填的时间，用于避免并发新增邮箱时丢失回填请求。
    backfill_requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # 最近一次成功完成回填的请求时间，落后于请求时间时仍需继续回填。
    last_backfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 最近一次成功完成增量检查的时间。
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IcloudCachedMessage(Base):
    """保存已匹配到 iCloud 邮箱的临时邮件内容，公开接口只读取该表。"""

    __tablename__ = "icloud_cached_messages"
    __table_args__ = (
        UniqueConstraint(
            "icloud_mailbox_id",
            "imap_config_id",
            "folder",
            "uid",
            name="uq_icloud_cached_message_uid",
        ),
    )

    # 本地缓存主键，不对外暴露。
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # 邮件匹配到的 iCloud 邮箱，分裂别名会归一到基础邮箱。
    icloud_mailbox_id: Mapped[int] = mapped_column(ForeignKey("icloud_mailboxes.id"), nullable=False, index=True)
    # 邮件来源的 IMAP 配置，用于配置切换和 UIDVALIDITY 重置时清理。
    imap_config_id: Mapped[int] = mapped_column(ForeignKey("imap_configs.id"), nullable=False, index=True)
    # 远端目录，与 UID 一起构成稳定作用域。
    folder: Mapped[str] = mapped_column(String(120), nullable=False, default="INBOX")
    # 远端数字 UID，用整数排序确保最新邮件顺序正确。
    uid: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # 已解码的邮件主题。
    subject: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 已解码的发件人展示值。
    sender: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 原邮件日期使用字符串保存，保持现有公开接口格式。
    message_date: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # 邮件正文摘要，供列表接口直接返回。
    snippet: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 清洗后的文本正文，供详情与验证码解析使用。
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 原始 HTML 正文，没有 HTML 时保存空值。
    html: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 从主题或正文中识别出的 4 至 8 位验证码。
    code: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    # 写入本地缓存的时间，按该字段执行七天保留清理。
    cached_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
