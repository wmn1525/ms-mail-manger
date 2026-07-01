from dataclasses import dataclass
import json
import urllib.error
import urllib.parse
import urllib.request


MICROSOFT_TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
NEW_GRAPH_SCOPE = "User.Read Mail.Read offline_access"
OLD_GRAPH_SCOPE = "https://graph.microsoft.com/.default"
IMAP_SCOPE = "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"


@dataclass(frozen=True)
class OAuthMode:
    # 标识当前 refresh token 成功换取的是哪一种读信令牌。
    name: str
    scope: str


GRAPH_MODES = (
    OAuthMode("new_graph", NEW_GRAPH_SCOPE),
    OAuthMode("old_graph", OLD_GRAPH_SCOPE),
)
IMAP_MODE = OAuthMode("imap", IMAP_SCOPE)


class TokenRefreshError(RuntimeError):
    # 保留 Microsoft 返回的关键错误，方便导入失败时定位授权问题。
    pass


def refresh_access_token_for_scope(client_id: str, refresh_token: str, scope: str) -> str:
    # refresh token 的可用 scope 与签发方式强相关，因此由调用方显式指定。
    form = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": scope,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        MICROSOFT_TOKEN_URL,
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise TokenRefreshError(read_microsoft_error(exc)) from exc

    payload = json.loads(data)
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise TokenRefreshError("Microsoft 未返回 access_token")
    return access_token


def read_microsoft_error(exc: urllib.error.HTTPError) -> str:
    # HTTPError 的 body 只能读取一次，这里统一压缩成安全的短错误文本。
    body = exc.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return f"HTTP {exc.code}: {body[:240]}"

    error = payload.get("error")
    description = payload.get("error_description")
    if isinstance(error, str) and isinstance(description, str):
        return f"HTTP {exc.code} {error}: {description}"
    return f"HTTP {exc.code}: {body[:240]}"
