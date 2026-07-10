"""普通 IMAP 收件箱到 iCloud 临时邮件表的增量同步逻辑。"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import Message
import imaplib
import re

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .db import SessionLocal
from .email_client import format_message, message_from_bytes
from .icloud_cache import CACHE_FOLDER, ensure_sync_state
from .imap_client import HEADER_FETCH_FIELDS, message_recipients, remove_split_alias
from .models import IcloudCachedMessage, IcloudMailbox, ImapConfig, ImapSyncState


INITIAL_BACKFILL_COUNT = 200
HEADER_BATCH_SIZE = 50
BODY_BATCH_SIZE = 10
MAX_IMAP_UID = 4_294_967_295
SYNC_HEADER_FETCH_FIELDS = HEADER_FETCH_FIELDS.replace("(BODY", "(UID BODY", 1)
SYNC_BODY_FETCH_FIELDS = "(UID BODY.PEEK[])"
UID_PATTERN = re.compile(rb"\bUID\s+(\d+)\b")


class ImapConfigMissingError(RuntimeError):
    """表示同步期间 IMAP 配置已被删除，工作线程应直接退出。"""


class ImapConfigChangedError(RuntimeError):
    """表示持久连接对应的配置已变化，工作线程应由管理器重启。"""


def imap_config_fingerprint(config: ImapConfig) -> tuple[str, int, str, str, bool]:
    """生成不含明文密码的连接指纹，用于阻止旧连接写入新配置缓存。"""

    return (config.host, config.port, config.username, config.password_enc, config.use_ssl)


@dataclass(frozen=True)
class SyncSnapshot:
    """网络读取开始前固定的同步游标与邮箱映射。"""

    # 配置主键用于写回状态。
    config_id: int
    # 本轮连接对应的配置指纹，提交前必须保持不变。
    config_fingerprint: tuple[str, int, str, str, bool]
    # 当前增量游标。
    last_uid: int
    # 回填请求时间快照，成功后只确认本次请求。
    backfill_requested_at: datetime
    # 是否需要扫描最近 200 封邮件。
    needs_backfill: bool
    # 归一化基础邮箱到 iCloud 邮箱主键的映射。
    mailbox_ids_by_email: dict[str, tuple[int, ...]]


@dataclass(frozen=True)
class CachedContent:
    """从完整邮件解析出的缓存字段。"""

    # 已解码主题。
    subject: str
    # 已解码发件人。
    sender: str
    # 保持公开接口格式的邮件日期。
    message_date: str | None
    # 列表摘要。
    snippet: str
    # 清洗后的正文。
    body: str
    # 原始 HTML 正文。
    html: str | None
    # 提取到的验证码。
    code: str | None


def chunked(values: list[int], size: int) -> Iterable[list[int]]:
    """按固定大小切分 UID，控制单条 FETCH 命令的内存占用。"""

    for index in range(0, len(values), size):
        yield values[index : index + size]


def parse_uid_validity(imap: imaplib.IMAP4) -> int:
    """读取 SELECT 响应中的 UIDVALIDITY，缺失时拒绝推进缓存游标。"""

    _, values = imap.response("UIDVALIDITY")
    if not values or not values[0]:
        raise RuntimeError("IMAP 服务器未返回 UIDVALIDITY")
    match = re.search(rb"\d+", values[0])
    if not match:
        raise RuntimeError("IMAP UIDVALIDITY 格式不正确")
    return int(match.group())


def search_all_uids(imap: imaplib.IMAP4) -> list[int]:
    """读取当前目录全部 UID，仅在首次回填时截取末尾 200 封。"""

    status, data = imap.uid("search", None, "ALL")
    if status != "OK":
        raise RuntimeError("无法搜索 IMAP 邮件 UID")
    return [int(value) for value in data[0].split()] if data and data[0] else []


def search_new_uids(imap: imaplib.IMAP4, last_uid: int) -> list[int]:
    """搜索游标后的 UID，并过滤网易服务器可能返回的边界邮件。"""

    start_uid = last_uid + 1
    status, data = imap.uid("search", None, "UID", f"{start_uid}:{MAX_IMAP_UID}")
    if status != "OK":
        raise RuntimeError("无法搜索 IMAP 新邮件 UID")
    values = [int(value) for value in data[0].split()] if data and data[0] else []
    return sorted({value for value in values if value > last_uid})


def fetch_message_batch(imap: imaplib.IMAP4, uids: list[int], fields: str) -> dict[int, Message]:
    """使用一条 UID FETCH 获取一批邮件，并按响应中的真实 UID 建立映射。"""

    if not uids:
        return {}
    uid_set = ",".join(str(uid) for uid in uids)
    status, fetched = imap.uid("fetch", uid_set, fields)
    if status != "OK" or fetched is None:
        raise RuntimeError("批量获取 IMAP 邮件失败")
    messages: dict[int, Message] = {}
    for item in fetched:
        if not isinstance(item, tuple) or not item[1]:
            continue
        match = UID_PATTERN.search(item[0])
        if not match:
            continue
        messages[int(match.group(1))] = message_from_bytes(item[1])
    return messages


def fetch_messages(imap: imaplib.IMAP4, uids: list[int], fields: str, batch_size: int) -> dict[int, Message]:
    """分批执行 FETCH，避免逐封网络往返。"""

    messages: dict[int, Message] = {}
    for uid_batch in chunked(uids, batch_size):
        messages.update(fetch_message_batch(imap, uid_batch, fields))
    return messages


def parse_cached_content(uid: int, message: Message) -> CachedContent:
    """复用现有邮件解析器并收窄为缓存模型需要的确定字段。"""

    parsed = format_message(str(uid), message, include_body=True)
    date_value = parsed.get("date")
    html_value = parsed.get("html")
    code_value = parsed.get("code")
    return CachedContent(
        subject=str(parsed.get("subject") or ""),
        sender=str(parsed.get("from") or ""),
        message_date=str(date_value) if date_value is not None else None,
        snippet=str(parsed.get("snippet") or ""),
        body=str(parsed.get("body") or ""),
        html=str(html_value) if html_value else None,
        code=str(code_value) if code_value else None,
    )


class ImapCacheSynchronizer:
    """在持久 IMAP 连接上执行一次可事务提交的增量同步。"""

    def __init__(self, session_factory: Callable[[], Session] = SessionLocal):
        """注入会话工厂，生产环境和隔离测试复用同一同步逻辑。"""

        self.session_factory = session_factory

    def _load_snapshot(
        self,
        config_id: int,
        expected_fingerprint: tuple[str, int, str, str, bool] | None = None,
    ) -> SyncSnapshot:
        """创建缺失状态并固定本轮邮箱映射，防止网络阶段持有数据库连接。"""

        with self.session_factory() as db:
            config = db.get(ImapConfig, config_id)
            if not config:
                raise ImapConfigMissingError("IMAP 配置已删除")
            fingerprint = imap_config_fingerprint(config)
            if expected_fingerprint and fingerprint != expected_fingerprint:
                raise ImapConfigChangedError("IMAP 配置已更新")
            state = ensure_sync_state(db, config_id)
            db.commit()
            db.refresh(state)
            rows = db.execute(
                select(IcloudMailbox.id, IcloudMailbox.email).where(IcloudMailbox.imap_config_id == config_id)
            ).all()
            grouped: dict[str, list[int]] = {}
            for mailbox_id, email in rows:
                grouped.setdefault(remove_split_alias(email), []).append(mailbox_id)
            needs_backfill = (
                state.last_backfilled_at is None or state.last_backfilled_at < state.backfill_requested_at
            )
            return SyncSnapshot(
                config_id=config_id,
                config_fingerprint=fingerprint,
                last_uid=state.last_uid,
                backfill_requested_at=state.backfill_requested_at,
                needs_backfill=needs_backfill,
                mailbox_ids_by_email={key: tuple(value) for key, value in grouped.items()},
            )

    def _reset_for_uid_validity(self, config_id: int, uid_validity: int) -> SyncSnapshot:
        """UIDVALIDITY 改变时原子清空旧缓存并建立新的回填请求。"""

        requested_at = datetime.now(UTC)
        with self.session_factory() as db:
            state = db.scalar(
                select(ImapSyncState).where(
                    ImapSyncState.imap_config_id == config_id,
                    ImapSyncState.folder == CACHE_FOLDER,
                )
            )
            if not state:
                raise RuntimeError("IMAP 同步状态不存在")
            db.execute(delete(IcloudCachedMessage).where(IcloudCachedMessage.imap_config_id == config_id))
            state.uid_validity = uid_validity
            state.last_uid = 0
            state.backfill_requested_at = requested_at
            state.last_backfilled_at = None
            db.commit()
        return self._load_snapshot(config_id)

    def _match_mailboxes(self, headers: dict[int, Message], snapshot: SyncSnapshot) -> dict[int, tuple[int, ...]]:
        """把邮件头中的收件人归一到当前配置绑定的 iCloud 邮箱。"""

        matches: dict[int, tuple[int, ...]] = {}
        for uid, message in headers.items():
            mailbox_ids: set[int] = set()
            for recipient in message_recipients(message):
                mailbox_ids.update(snapshot.mailbox_ids_by_email.get(remove_split_alias(recipient), ()))
            if mailbox_ids:
                matches[uid] = tuple(sorted(mailbox_ids))
        return matches

    def _store_results(
        self,
        snapshot: SyncSnapshot,
        uid_validity: int,
        cursor_uid: int,
        mailbox_ids_by_uid: dict[int, tuple[int, ...]],
        bodies: dict[int, Message],
    ) -> None:
        """在单个事务中写入邮件并推进游标，失败时整批回滚。"""

        now = datetime.now(UTC)
        with self.session_factory() as db:
            config = db.get(ImapConfig, snapshot.config_id)
            if not config:
                raise ImapConfigMissingError("IMAP 配置已删除")
            if imap_config_fingerprint(config) != snapshot.config_fingerprint:
                raise ImapConfigChangedError("IMAP 配置在同步期间发生变化")
            state = db.scalar(
                select(ImapSyncState).where(
                    ImapSyncState.imap_config_id == snapshot.config_id,
                    ImapSyncState.folder == CACHE_FOLDER,
                )
            )
            if not state or state.uid_validity != uid_validity:
                raise RuntimeError("IMAP 同步状态在提交前发生变化")
            candidate_uids = list(mailbox_ids_by_uid)
            existing: set[tuple[int, int]] = set()
            if candidate_uids:
                existing = set(
                    db.execute(
                        select(IcloudCachedMessage.icloud_mailbox_id, IcloudCachedMessage.uid).where(
                            IcloudCachedMessage.imap_config_id == snapshot.config_id,
                            IcloudCachedMessage.folder == CACHE_FOLDER,
                            IcloudCachedMessage.uid.in_(candidate_uids),
                        )
                    ).all()
                )
            for uid, mailbox_ids in mailbox_ids_by_uid.items():
                message = bodies.get(uid)
                if not message:
                    continue
                content = parse_cached_content(uid, message)
                for mailbox_id in mailbox_ids:
                    if (mailbox_id, uid) in existing:
                        continue
                    db.add(
                        IcloudCachedMessage(
                            icloud_mailbox_id=mailbox_id,
                            imap_config_id=snapshot.config_id,
                            folder=CACHE_FOLDER,
                            uid=uid,
                            subject=content.subject,
                            sender=content.sender,
                            message_date=content.message_date,
                            snippet=content.snippet,
                            body=content.body,
                            html=content.html,
                            code=content.code,
                            cached_at=now,
                        )
                    )
            state.last_uid = max(state.last_uid, cursor_uid)
            state.last_synced_at = now
            if snapshot.needs_backfill:
                state.last_backfilled_at = snapshot.backfill_requested_at
            config.status = "live"
            config.last_error = None
            config.last_checked_at = now
            db.commit()

    def sync_once(
        self,
        config_id: int,
        imap: imaplib.IMAP4,
        expected_fingerprint: tuple[str, int, str, str, bool] | None = None,
    ) -> None:
        """完成一次回填或增量检查，所有邮件头和正文均按批次获取。"""

        snapshot = self._load_snapshot(config_id, expected_fingerprint)
        uid_validity = parse_uid_validity(imap)
        with self.session_factory() as db:
            state_uid_validity = db.scalar(
                select(ImapSyncState.uid_validity).where(
                    ImapSyncState.imap_config_id == config_id,
                    ImapSyncState.folder == CACHE_FOLDER,
                )
            )
        if state_uid_validity != uid_validity:
            snapshot = self._reset_for_uid_validity(config_id, uid_validity)
            if expected_fingerprint and snapshot.config_fingerprint != expected_fingerprint:
                raise ImapConfigChangedError("IMAP 配置已更新")

        if snapshot.needs_backfill:
            all_uids = search_all_uids(imap)
            target_uids = all_uids[-INITIAL_BACKFILL_COUNT:]
            cursor_uid = max(all_uids, default=0)
        else:
            target_uids = search_new_uids(imap, snapshot.last_uid)
            cursor_uid = max(target_uids, default=snapshot.last_uid)

        headers = (
            fetch_messages(imap, target_uids, SYNC_HEADER_FETCH_FIELDS, HEADER_BATCH_SIZE)
            if snapshot.mailbox_ids_by_email
            else {}
        )
        if snapshot.mailbox_ids_by_email and set(headers) != set(target_uids):
            raise RuntimeError("批量获取 IMAP 邮件头不完整")
        mailbox_ids_by_uid = self._match_mailboxes(headers, snapshot)
        body_uids = sorted(mailbox_ids_by_uid)
        bodies = fetch_messages(imap, body_uids, SYNC_BODY_FETCH_FIELDS, BODY_BATCH_SIZE)
        if set(bodies) != set(body_uids):
            raise RuntimeError("批量获取 IMAP 邮件正文不完整")
        self._store_results(snapshot, uid_validity, cursor_uid, mailbox_ids_by_uid, bodies)


def mark_sync_error(config_id: int, error: str, session_factory: Callable[[], Session] = SessionLocal) -> None:
    """记录后台连接或同步错误，不删除最后一次成功缓存。"""

    with session_factory() as db:
        config = db.get(ImapConfig, config_id)
        if not config:
            return
        config.status = "dead"
        config.last_error = error
        config.last_checked_at = datetime.now(UTC)
        db.commit()
