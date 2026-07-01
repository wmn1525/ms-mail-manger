from __future__ import annotations

from dataclasses import dataclass
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
import html
import imaplib
import re
import ssl

from .config import get_settings
from .mail_oauth import GRAPH_MODES, IMAP_MODE, refresh_access_token_for_scope


CODE_RE = re.compile(r"(?<!\d)(\d{4,8})(?!\d)")
HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class MailCredential:
    email: str
    password: str | None = None
    client_id: str | None = None
    token: str | None = None


def decode_mime(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def clean_text(value: str) -> str:
    value = HTML_TAG_RE.sub(" ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def decode_part(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if not payload:
        return ""
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def extract_text(message: Message) -> str:
    parts: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            disposition = part.get_content_disposition()
            if disposition == "attachment":
                continue
            if content_type not in {"text/plain", "text/html"}:
                continue
            text = decode_part(part)
            if not text:
                continue
            parts.append(clean_text(text) if content_type == "text/html" else clean_text(text))
    else:
        text = decode_part(message)
        if text:
            parts.append(clean_text(text))
    return " ".join(part for part in parts if part)


def extract_html(message: Message) -> str:
    html_parts: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_disposition() == "attachment":
                continue
            if part.get_content_type() != "text/html":
                continue
            text = decode_part(part)
            if text:
                html_parts.append(text)
    elif message.get_content_type() == "text/html":
        text = decode_part(message)
        if text:
            html_parts.append(text)
    return "\n".join(html_parts)


def extract_code(subject: str, body: str) -> str | None:
    for source in (subject, body):
        match = CODE_RE.search(source)
        if match:
            return match.group(1)
    return None


def format_message(uid: bytes | str, message: Message, include_body: bool = False) -> dict:
    subject = decode_mime(message.get("Subject"))
    sender = decode_mime(message.get("From"))
    body = extract_text(message) if include_body else ""
    html_body = extract_html(message) if include_body else ""
    date_value = message.get("Date")
    try:
        date_value = parsedate_to_datetime(date_value).isoformat() if date_value else None
    except Exception:
        pass
    uid_value = uid.decode("ascii", errors="ignore") if isinstance(uid, bytes) else uid
    return {
        "uid": uid_value,
        "subject": subject,
        "from": sender,
        "date": date_value,
        "snippet": body[:240] if body else "点击查看邮件详情",
        "body": body,
        "html": html_body,
        "code": extract_code(subject, body),
    }


def refresh_access_token(client_id: str, refresh_token: str) -> str:
    settings = get_settings()
    return refresh_access_token_for_scope(client_id, refresh_token, settings.microsoft_scope)


class OutlookImapClient:
    def __init__(self, credential: MailCredential):
        self.credential = credential
        self.settings = get_settings()

    def _has_refresh_token(self) -> bool:
        return bool(self.credential.client_id and self.credential.token and not self.credential.token.startswith("eyJ"))

    def _graph_client(self):
        # Graph 模式需要先用最小读信请求确认 token 不只是能换取，还能真正读邮箱。
        from .email_graph import GraphMailClient

        errors: list[str] = []
        if not self.credential.client_id or not self.credential.token:
            raise RuntimeError("缺少 Microsoft OAuth 凭据")
        for mode in GRAPH_MODES:
            try:
                token = refresh_access_token_for_scope(self.credential.client_id, self.credential.token, mode.scope)
                client = GraphMailClient(token)
                client.check_alive()
                return client
            except Exception as exc:
                errors.append(f"{mode.name}: {exc}")
        raise RuntimeError("Graph 模式不可用：" + "；".join(errors))

    def _run_auto(self, graph_call, imap_call):
        # OAuth refresh token 按新GR、老GR、IMAP 的顺序判断；密码账号仍直接走 IMAP。
        if not self._has_refresh_token():
            return imap_call()
        try:
            return graph_call(self._graph_client())
        except Exception as graph_exc:
            try:
                return imap_call()
            except Exception as imap_exc:
                raise RuntimeError(f"三种模式均不可用：{graph_exc}；imap: {imap_exc}") from imap_exc

    def _open(self) -> imaplib.IMAP4_SSL:
        context = ssl.create_default_context()
        imap = imaplib.IMAP4_SSL(self.settings.imap_host, self.settings.imap_port, ssl_context=context)
        try:
            if self.credential.token:
                token = self.credential.token
                if self.credential.client_id and not token.startswith("eyJ"):
                    token = refresh_access_token_for_scope(self.credential.client_id, token, IMAP_MODE.scope)
                auth = f"user={self.credential.email}\x01auth=Bearer {token}\x01\x01"
                imap.authenticate("XOAUTH2", lambda _: auth.encode("utf-8"))
            elif self.credential.password:
                imap.login(self.credential.email, self.credential.password)
            else:
                raise RuntimeError("缺少密码或 OAuth 令牌")
            return imap
        except Exception:
            try:
                imap.logout()
            except Exception:
                pass
            raise

    def check_alive(self) -> None:
        def check_graph(client):
            client.check_alive()

        def check_imap():
            self._check_alive_imap()

        self._run_auto(check_graph, check_imap)

    def _check_alive_imap(self) -> None:
        imap = self._open()
        try:
            status, _ = imap.select(self.settings.imap_folder, readonly=True)
            if status != "OK":
                raise RuntimeError("无法打开收件箱")
        finally:
            imap.logout()

    def list_messages(self, limit: int = 30) -> list[dict]:
        return self._run_auto(lambda client: client.list_messages(limit), lambda: self._list_messages_imap(limit))

    def _list_messages_imap(self, limit: int = 30) -> list[dict]:
        imap = self._open()
        try:
            status, _ = imap.select(self.settings.imap_folder, readonly=True)
            if status != "OK":
                raise RuntimeError("无法打开收件箱")

            status, data = imap.uid("search", None, "ALL")
            if status != "OK" or not data or not data[0]:
                return []

            uids = data[0].split()[-limit:]
            uids.reverse()
            messages: list[dict] = []
            for uid in uids:
                status, fetched = imap.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                if status != "OK" or not fetched:
                    continue
                raw = next((item[1] for item in fetched if isinstance(item, tuple) and item[1]), None)
                if not raw:
                    continue
                msg = message_from_bytes(raw)
                messages.append(format_message(uid, msg, include_body=False))
            return messages
        finally:
            imap.logout()

    def get_message(self, uid: str) -> dict:
        if self._has_refresh_token() and uid.startswith("graph:"):
            return self._graph_client().get_message(uid)
        return self._run_auto(lambda client: client.get_message(uid), lambda: self._get_message_imap(uid))

    def _get_message_imap(self, uid: str) -> dict:
        imap = self._open()
        try:
            status, _ = imap.select(self.settings.imap_folder, readonly=True)
            if status != "OK":
                raise RuntimeError("无法打开收件箱")

            status, fetched = imap.uid("fetch", uid, "(RFC822)")
            if status != "OK" or not fetched:
                raise RuntimeError("邮件不存在或无法读取")

            raw = next((item[1] for item in fetched if isinstance(item, tuple) and item[1]), None)
            if not raw:
                raise RuntimeError("邮件内容为空")
            return format_message(uid, message_from_bytes(raw), include_body=True)
        finally:
            imap.logout()

    def find_latest_code(self, limit: int = 10) -> dict | None:
        return self._run_auto(lambda client: client.find_latest_code(limit), lambda: self._find_latest_code_imap(limit))

    def _find_latest_code_imap(self, limit: int = 10) -> dict | None:
        imap = self._open()
        try:
            status, _ = imap.select(self.settings.imap_folder, readonly=True)
            if status != "OK":
                raise RuntimeError("无法打开收件箱")

            status, data = imap.uid("search", None, "ALL")
            if status != "OK" or not data or not data[0]:
                return None

            uids = data[0].split()[-limit:]
            uids.reverse()
            for uid in uids:
                status, fetched = imap.uid("fetch", uid, "(RFC822)")
                if status != "OK" or not fetched:
                    continue
                raw = next((item[1] for item in fetched if isinstance(item, tuple) and item[1]), None)
                if not raw:
                    continue
                message = format_message(uid, message_from_bytes(raw), include_body=True)
                if message.get("code"):
                    return message
            return None
        finally:
            imap.logout()
