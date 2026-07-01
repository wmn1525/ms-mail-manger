from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request

from .email_client import clean_text, extract_code


GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_UID_PREFIX = "graph:"


class GraphMailClient:
    # Microsoft Graph 读信客户端，用于支持不能走 IMAP 但可走 Mail.Read 的账号。
    def __init__(self, access_token: str):
        self.access_token = access_token

    def check_alive(self) -> None:
        self.list_messages(limit=1)

    def list_messages(self, limit: int = 30) -> list[dict]:
        params = {
            "$top": str(limit),
            "$select": "id,subject,from,receivedDateTime,bodyPreview",
            "$orderby": "receivedDateTime desc",
        }
        payload = self._request("/me/mailFolders/inbox/messages", params)
        messages = payload.get("value")
        if not isinstance(messages, list):
            return []
        return [format_graph_message(message, include_body=False) for message in messages if isinstance(message, dict)]

    def get_message(self, uid: str) -> dict:
        message_id = decode_graph_uid(uid)
        params = {
            "$select": "id,subject,from,receivedDateTime,bodyPreview,body",
        }
        payload = self._request(f"/me/messages/{urllib.parse.quote(message_id, safe='')}", params)
        return format_graph_message(payload, include_body=True)

    def find_latest_code(self, limit: int = 10) -> dict | None:
        for message in self.list_messages(limit=limit):
            if message.get("code"):
                return message
            detail = self.get_message(str(message["uid"]))
            if detail.get("code"):
                return detail
        return None

    def _request(self, path: str, params: dict[str, str]) -> dict:
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"{GRAPH_API_BASE}{path}?{query}",
            headers={"Authorization": f"Bearer {self.access_token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(read_graph_error(exc)) from exc
        payload = json.loads(data)
        if not isinstance(payload, dict):
            raise RuntimeError("Graph 返回格式不正确")
        return payload


def encode_graph_uid(message_id: str) -> str:
    # Graph 原始 ID 可能包含路径敏感字符，返回给前端前改成 URL 安全形式。
    encoded = base64.urlsafe_b64encode(message_id.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{GRAPH_UID_PREFIX}{encoded}"


def decode_graph_uid(uid: str) -> str:
    if not uid.startswith(GRAPH_UID_PREFIX):
        return uid
    encoded = uid[len(GRAPH_UID_PREFIX) :]
    padded = encoded + "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")


def format_graph_message(message: dict, include_body: bool) -> dict:
    subject = get_text(message, "subject")
    body_preview = get_text(message, "bodyPreview")
    body = get_graph_body(message) if include_body else body_preview
    html_body = body if include_body and get_graph_body_type(message).lower() == "html" else ""
    text_body = clean_text(body)
    return {
        "uid": encode_graph_uid(get_text(message, "id")),
        "subject": subject,
        "from": get_sender(message),
        "date": get_text(message, "receivedDateTime") or None,
        "snippet": body_preview[:240] if body_preview else "点击查看邮件详情",
        "body": text_body,
        "html": html_body,
        "code": extract_code(subject, text_body or body_preview),
    }


def get_text(source: dict, key: str) -> str:
    value = source.get(key)
    return value if isinstance(value, str) else ""


def get_sender(message: dict) -> str:
    sender = message.get("from")
    if not isinstance(sender, dict):
        return ""
    address = sender.get("emailAddress")
    if not isinstance(address, dict):
        return ""
    name = get_text(address, "name")
    email = get_text(address, "address")
    if name and email:
        return f"{name} <{email}>"
    return email or name


def get_graph_body(message: dict) -> str:
    body = message.get("body")
    if not isinstance(body, dict):
        return ""
    return get_text(body, "content")


def get_graph_body_type(message: dict) -> str:
    body = message.get("body")
    if not isinstance(body, dict):
        return ""
    return get_text(body, "contentType")


def read_graph_error(exc: urllib.error.HTTPError) -> str:
    body = exc.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return f"Graph HTTP {exc.code}: {body[:240]}"
    error = payload.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        message = error.get("message")
        if isinstance(code, str) and isinstance(message, str):
            return f"Graph HTTP {exc.code} {code}: {message}"
    return f"Graph HTTP {exc.code}: {body[:240]}"
