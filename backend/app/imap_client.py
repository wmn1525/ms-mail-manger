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
    "X-Original-To",
    "Envelope-To",
    "Apparently-To",
    "Resent-To",
]


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
        folders = [item.strip() for item in re.split(r"[\n,，]+", self.credential.folder or "INBOX")]
        return [folder for folder in folders if folder] or ["INBOX"]

    def _normalize_email(self, value: str) -> str:
        return value.strip().lower()

    def _remove_split_alias(self, value: str) -> str:
        local, separator, domain = self._normalize_email(value).rpartition("@")
        if not separator:
            return self._normalize_email(value)
        return f"{local.split('+', 1)[0]}@{domain}"

    def _has_split_alias(self, value: str) -> bool:
        local, separator, _ = self._normalize_email(value).rpartition("@")
        return bool(separator and "+" in local)

    def _message_recipients(self, message: Message) -> set[str]:
        values: list[str] = []
        for header in RECIPIENT_HEADERS:
            values.extend(message.get_all(header, []))
        addresses = {self._normalize_email(address) for _, address in getaddresses(values) if address}
        # 有些转发头会把地址放在裸文本里，补一层轻量兜底解析。
        for value in values:
            addresses.update(self._normalize_email(item) for item in re.findall(r"[\w.+-]+@[\w.-]+", value))
        return addresses

    def _matches_recipient(self, message: Message, recipient_email: str | None, include_aliases: bool) -> bool:
        if not recipient_email:
            return True
        target = self._normalize_email(recipient_email)
        recipients = self._message_recipients(message)
        if target in recipients:
            return True
        if not include_aliases or self._has_split_alias(target):
            return False
        target_base = self._remove_split_alias(target)
        return any(self._remove_split_alias(address) == target_base for address in recipients)

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
        uid_value = uid.decode("ascii", errors="ignore") if isinstance(uid, bytes) else uid
        folder_value = base64.urlsafe_b64encode(folder.encode("utf-8")).decode("ascii")
        return f"imap:{folder_value}:{uid_value}"

    def _parse_uid(self, uid: str) -> tuple[str | None, str]:
        parts = uid.split(":", 2)
        if len(parts) != 3 or parts[0] != "imap":
            return None, uid
        folder = base64.urlsafe_b64decode(parts[1].encode("ascii")).decode("utf-8")
        return folder, parts[2]

    def _parse_folder_line(self, value: bytes) -> str | None:
        # IMAP LIST 返回的最后一个带引号字段通常就是服务器真实目录名。
        text = value.decode("utf-8", errors="replace")
        quoted = re.findall(r'"((?:[^"\\]|\\.)*)"', text)
        if quoted:
            return quoted[-1].replace(r"\"", '"').strip()
        parts = text.rsplit(" ", 1)
        return parts[-1].strip() if parts else None

    def _open(self) -> imaplib.IMAP4:
        if self.credential.use_ssl:
            context = ssl.create_default_context()
            imap = imaplib.IMAP4_SSL(self.credential.host, self.credential.port, ssl_context=context)
        else:
            imap = imaplib.IMAP4(self.credential.host, self.credential.port)
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

    def list_folders(self) -> list[str]:
        imap = self._open()
        try:
            status, data = imap.list()
            if status != "OK" or not data:
                raise RuntimeError("无法获取 IMAP 目录列表")
            folders: list[str] = []
            for item in data:
                if not item:
                    continue
                folder = self._parse_folder_line(item)
                if folder and folder not in folders:
                    folders.append(folder)
            return folders or ["INBOX"]
        finally:
            imap.logout()

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
                uids = data[0].split()[-limit:]
                uids.reverse()
                for uid in uids:
                    status, fetched = imap.uid(
                        "fetch",
                        uid,
                        "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE TO CC BCC DELIVERED-TO X-ORIGINAL-TO ENVELOPE-TO APPARENTLY-TO RESENT-TO)])",
                    )
                    if status != "OK" or not fetched:
                        continue
                    raw = next((item[1] for item in fetched if isinstance(item, tuple) and item[1]), None)
                    if not raw:
                        continue
                    parsed_message = message_from_bytes(raw)
                    if not self._matches_recipient(parsed_message, recipient_email, include_aliases):
                        continue
                    message = format_message(uid, parsed_message, include_body=False)
                    message["uid"] = self._scoped_uid(folder, uid)
                    messages.append(message)
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
                    raw = next((item[1] for item in fetched if isinstance(item, tuple) and item[1]), None)
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
                uids = data[0].split()[-limit:]
                uids.reverse()
                for uid in uids:
                    status, fetched = imap.uid("fetch", uid, "(RFC822)")
                    if status != "OK" or not fetched:
                        continue
                    raw = next((item[1] for item in fetched if isinstance(item, tuple) and item[1]), None)
                    if not raw:
                        continue
                    parsed_message = message_from_bytes(raw)
                    if not self._matches_recipient(parsed_message, recipient_email, include_aliases):
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
