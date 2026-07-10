from __future__ import annotations

import base64
from dataclasses import dataclass
from email.message import Message
from email.utils import getaddresses
import imaplib
import re
import ssl

from .email_client import format_message, message_from_bytes


RECIPIENT_HEADERS = [
    "To",
    "Cc",
    "Bcc",
    "Delivered-To",
    "X-Delivered-To",
    "X-Original-To",
    "Original-Recipient",
    "X-Original-Recipient",
    "Envelope-To",
    "X-Envelope-To",
    "Apparently-To",
    "Resent-To",
    "X-Forwarded-To",
    "X-Rcpt-To",
    "X-Real-To",
]
HEADER_FETCH_FIELDS = (
    "(BODY.PEEK[HEADER.FIELDS "
    "(FROM SUBJECT DATE TO CC BCC DELIVERED-TO X-DELIVERED-TO X-ORIGINAL-TO ORIGINAL-RECIPIENT "
    "X-ORIGINAL-RECIPIENT ENVELOPE-TO X-ENVELOPE-TO APPARENTLY-TO RESENT-TO X-FORWARDED-TO X-RCPT-TO X-REAL-TO)])"
)
HEADER_SCAN_PAGE_SIZE = 20
HEADER_SCAN_MAX_UIDS = 200
IMAP_TIMEOUT_SECONDS = 15


def normalize_email(value: str) -> str:
    """统一邮件地址大小写和首尾空白，保证缓存映射稳定。"""

    return value.strip().lower()


def remove_split_alias(value: str) -> str:
    """去除本地部分的加号别名，把分裂地址归一到基础邮箱。"""

    local, separator, domain = normalize_email(value).rpartition("@")
    if not separator:
        return normalize_email(value)
    return f"{local.split('+', 1)[0]}@{domain}"


def message_recipients(message: Message) -> set[str]:
    """从常见投递头中提取全部收件人，兼容网易转发邮件头。"""

    values: list[str] = []
    for header in RECIPIENT_HEADERS:
        values.extend(message.get_all(header, []))
    addresses = {normalize_email(address) for _, address in getaddresses(values) if address}
    for value in values:
        addresses.update(normalize_email(item) for item in re.findall(r"[\w.+-]+@[\w.-]+", value))
    return addresses


def scoped_uid(folder: str, uid: bytes | str | int) -> str:
    """把远端 UID 与目录编码为现有公开接口使用的稳定 UID。"""

    uid_value = uid.decode("ascii", errors="ignore") if isinstance(uid, bytes) else str(uid)
    folder_value = base64.urlsafe_b64encode(folder.encode("utf-8")).decode("ascii")
    return f"imap:{folder_value}:{uid_value}"


def parse_scoped_uid(uid: str) -> tuple[str | None, str]:
    """解析公开 UID；旧的裸 UID 仍由普通 IMAP 详情读取逻辑处理。"""

    parts = uid.split(":", 2)
    if len(parts) != 3 or parts[0] != "imap":
        return None, uid
    folder = base64.urlsafe_b64decode(parts[1].encode("ascii")).decode("utf-8")
    return folder, parts[2]


@dataclass
class ImapCredential:
    """描述一个普通 IMAP 收件箱，供 iCloud 转发接码使用。"""

    host: str
    port: int
    username: str
    password: str
    folder: str = "INBOX"
    use_ssl: bool = True


class GenericImapClient:
    """读取普通 IMAP 收件箱中的最近邮件和验证码。"""

    def __init__(self, credential: ImapCredential):
        self.credential = credential

    def _folders(self) -> list[str]:
        # 163 等共享接码箱目录多且响应慢，取码只扫描收件箱避免逐目录全量搜索。
        return ["INBOX"]

    def _normalize_email(self, value: str) -> str:
        return normalize_email(value)

    def _remove_split_alias(self, value: str) -> str:
        return remove_split_alias(value)

    def _message_recipients(self, message: Message) -> set[str]:
        return message_recipients(message)

    def _matches_recipient(self, message: Message, recipient_email: str | None, include_aliases: bool) -> bool:
        if not recipient_email:
            return True
        target = self._normalize_email(recipient_email)
        recipients = self._message_recipients(message)
        if target in recipients:
            return True
        if not include_aliases:
            return False
        target_base = self._remove_split_alias(target)
        return any(self._remove_split_alias(address) == target_base for address in recipients)

    def _first_payload(self, fetched: list[bytes | tuple[bytes, bytes]]) -> bytes | None:
        """IMAP FETCH 会混入结束标记，这里只取真正的邮件字节。"""

        return next((item[1] for item in fetched if isinstance(item, tuple) and item[1]), None)

    def _fetch_message(self, imap: imaplib.IMAP4, uid: bytes | str, body: str) -> Message | None:
        """按需读取邮件头或完整邮件，避免验证码接口无谓下载正文。"""

        status, fetched = imap.uid("fetch", uid, body)
        if status != "OK" or not fetched:
            return None
        raw = self._first_payload(fetched)
        return message_from_bytes(raw) if raw else None

    def _recent_uid_pages(self, value: bytes, max_count: int) -> list[list[bytes]]:
        """从最新 UID 开始分页，限制共享接码箱的单次扫描范围。"""

        uids = value.split()[-max_count:]
        uids.reverse()
        return [uids[index : index + HEADER_SCAN_PAGE_SIZE] for index in range(0, len(uids), HEADER_SCAN_PAGE_SIZE)]

    def _select_folder(self, imap: imaplib.IMAP4, folder: str) -> None:
        errors: list[str] = []
        for readonly in (True, False):
            status, data = imap.select(folder, readonly=readonly)
            if status == "OK":
                return
            error = "; ".join(item.decode("utf-8", errors="replace") for item in data if item)
            errors.append(error or status)
        raise RuntimeError(f"{folder}: {'；'.join(errors)}")

    def _scoped_uid(self, folder: str, uid: bytes | str) -> str:
        return scoped_uid(folder, uid)

    def _parse_uid(self, uid: str) -> tuple[str | None, str]:
        return parse_scoped_uid(uid)

    def _open(self) -> imaplib.IMAP4:
        if self.credential.use_ssl:
            context = ssl.create_default_context()
            imap = imaplib.IMAP4_SSL(
                self.credential.host,
                self.credential.port,
                ssl_context=context,
                timeout=IMAP_TIMEOUT_SECONDS,
            )
        else:
            imap = imaplib.IMAP4(self.credential.host, self.credential.port, timeout=IMAP_TIMEOUT_SECONDS)
        try:
            imap.login(self.credential.username, self.credential.password)
            # 部分 Coremail 服务要求客户端声明 ID，否则 SELECT 会被判定为 unsafe login。
            imaplib.Commands.setdefault("ID", ("AUTH", "SELECTED"))
            imap._simple_command(
                "ID",
                '("name" "ms-mail-manager" "version" "1.0" "vendor" "ms-mail-manager")',
            )
            return imap
        except Exception:
            try:
                imap.logout()
            except Exception:
                pass
            raise

    def check_alive(self) -> None:
        imap = self._open()
        try:
            errors: list[str] = []
            for folder in self._folders():
                try:
                    self._select_folder(imap, folder)
                    return
                except Exception as exc:
                    errors.append(str(exc))
            raise RuntimeError("无法打开收件箱：" + "；".join(errors))
        finally:
            imap.logout()

    def open_selected(self) -> imaplib.IMAP4:
        """打开持久连接并以只读方式选择 INBOX，供后台增量同步复用。"""

        imap = self._open()
        try:
            status, data = imap.select("INBOX", readonly=True)
            if status != "OK":
                error = "; ".join(item.decode("utf-8", errors="replace") for item in data if item)
                raise RuntimeError(f"INBOX: {error or status}")
            return imap
        except Exception:
            try:
                imap.logout()
            except Exception:
                pass
            raise

    def list_messages(
        self,
        limit: int = 30,
        recipient_email: str | None = None,
        include_aliases: bool = True,
    ) -> list[dict]:
        imap = self._open()
        try:
            messages: list[dict] = []
            errors: list[str] = []
            for folder in self._folders():
                try:
                    self._select_folder(imap, folder)
                except Exception as exc:
                    errors.append(str(exc))
                    continue
                status, data = imap.uid("search", None, "ALL")
                if status != "OK" or not data or not data[0]:
                    continue
                for uid_page in self._recent_uid_pages(data[0], max(limit, HEADER_SCAN_MAX_UIDS)):
                    for uid in uid_page:
                        parsed_message = self._fetch_message(imap, uid, HEADER_FETCH_FIELDS)
                        if not parsed_message:
                            continue
                        if not self._matches_recipient(parsed_message, recipient_email, include_aliases):
                            continue
                        message = format_message(uid, parsed_message, include_body=False)
                        message["uid"] = self._scoped_uid(folder, uid)
                        messages.append(message)
                        if len(messages) >= limit:
                            break
                    if len(messages) >= limit:
                        break
                if len(messages) >= limit:
                    break
            if not messages and errors:
                raise RuntimeError("无法打开收件箱：" + "；".join(errors))
            return messages
        finally:
            imap.logout()

    def get_message(self, uid: str) -> dict:
        imap = self._open()
        try:
            scoped_folder, raw_uid = self._parse_uid(uid)
            folders = [scoped_folder] if scoped_folder else self._folders()
            errors: list[str] = []
            for folder in folders:
                if not folder:
                    continue
                try:
                    self._select_folder(imap, folder)
                    status, fetched = imap.uid("fetch", raw_uid, "(RFC822)")
                    if status != "OK" or not fetched:
                        raise RuntimeError("邮件不存在或无法读取")
                    raw = self._first_payload(fetched)
                    if not raw:
                        raise RuntimeError("邮件内容为空")
                    message = format_message(raw_uid, message_from_bytes(raw), include_body=True)
                    message["uid"] = self._scoped_uid(folder, raw_uid)
                    return message
                except Exception as exc:
                    errors.append(str(exc))
            raise RuntimeError("邮件不存在或无法读取：" + "；".join(errors))
        finally:
            imap.logout()

    def find_latest_code(
        self,
        limit: int = 10,
        recipient_email: str | None = None,
        include_aliases: bool = True,
    ) -> dict | None:
        imap = self._open()
        try:
            errors: list[str] = []
            for folder in self._folders():
                try:
                    self._select_folder(imap, folder)
                except Exception as exc:
                    errors.append(str(exc))
                    continue
                status, data = imap.uid("search", None, "ALL")
                if status != "OK" or not data or not data[0]:
                    continue
                for uid_page in self._recent_uid_pages(data[0], max(limit, HEADER_SCAN_MAX_UIDS)):
                    for uid in uid_page:
                        header_message = self._fetch_message(imap, uid, HEADER_FETCH_FIELDS)
                        if not header_message:
                            continue
                        if not self._matches_recipient(header_message, recipient_email, include_aliases):
                            continue
                        parsed_message = self._fetch_message(imap, uid, "(RFC822)")
                        if not parsed_message:
                            continue
                        message = format_message(uid, parsed_message, include_body=True)
                        message["uid"] = self._scoped_uid(folder, uid)
                        if message.get("code"):
                            return message
            if errors:
                raise RuntimeError("无法打开收件箱：" + "；".join(errors))
            return None
        finally:
            imap.logout()
