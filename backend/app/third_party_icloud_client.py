"""校验第三方 iCloud 取码链接并提取页面中的验证码。"""

from html.parser import HTMLParser
import re
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen


ALLOWED_HOST = "icloudapi.xyz"
MAX_RESPONSE_BYTES = 2_000_000
CODE_CONTEXT_RE = re.compile(
    r"(?:验证码|verification code|security code|one-time code|passcode|otp)[^\d]{0,80}(\d{4,8})(?!\d)",
    re.IGNORECASE,
)


class ThirdPartyIcloudError(RuntimeError):
    """表示第三方服务不可用或返回内容无法取码。"""


class VisibleTextParser(HTMLParser):
    """只收集页面可见文本，避免把 CSS 色值误识别成验证码。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """进入脚本或样式区域后暂停收集文本。"""

        del attrs
        if tag in {"script", "style"}:
            self.ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        """离开脚本或样式区域后恢复收集文本。"""

        if tag in {"script", "style"} and self.ignored_depth > 0:
            self.ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        """保留正文文本，供带语义上下文的验证码正则查询。"""

        if self.ignored_depth == 0:
            self.parts.append(data)

    def text(self) -> str:
        """合并并压缩页面文本中的空白。"""

        return " ".join(" ".join(self.parts).split())


def validate_fetch_url(email: str, fetch_url: str) -> str:
    """限制链接到指定服务和邮箱，避免后台取码接口成为任意 URL 代理。"""

    value = fetch_url.strip()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("取码链接格式不正确") from exc
    if parsed.scheme not in {"http", "https"} or parsed.hostname != ALLOWED_HOST:
        raise ValueError(f"取码链接必须使用 {ALLOWED_HOST}")
    if parsed.username or parsed.password or port not in {None, 80, 443}:
        raise ValueError("取码链接格式不正确")
    if not parsed.path.startswith("/show/") or parsed.query or parsed.fragment:
        raise ValueError("取码链接路径格式不正确")
    linked_email = unquote(parsed.path.rsplit("/", 1)[-1])
    if linked_email.lower() != email.strip().lower():
        raise ValueError("取码链接中的邮箱与导入邮箱不一致")
    return value


def extract_page_code(content: str) -> str | None:
    """从可见正文的验证码语义附近提取 4 至 8 位数字。"""

    parser = VisibleTextParser()
    parser.feed(content)
    match = CODE_CONTEXT_RE.search(parser.text())
    return match.group(1) if match else None


def fetch_latest_code(email: str, fetch_url: str) -> str:
    """请求第三方页面并返回当前验证码，不暴露完整链接到错误信息。"""

    validated_url = validate_fetch_url(email, fetch_url)
    request = Request(
        validated_url,
        headers={"Accept": "text/html", "User-Agent": "MailManager/1.0"},
    )
    try:
        with urlopen(request, timeout=15) as response:
            validate_fetch_url(email, response.geturl())
            if response.headers.get_content_type() != "text/html":
                raise ThirdPartyIcloudError("第三方服务未返回取码页面")
            content_bytes = response.read(MAX_RESPONSE_BYTES + 1)
            if len(content_bytes) > MAX_RESPONSE_BYTES:
                raise ThirdPartyIcloudError("第三方取码页面过大")
            charset = response.headers.get_content_charset() or "utf-8"
    except HTTPError as exc:
        raise ThirdPartyIcloudError(f"第三方服务返回 HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise ThirdPartyIcloudError("第三方服务连接失败") from exc
    except ValueError as exc:
        raise ThirdPartyIcloudError(str(exc)) from exc

    code = extract_page_code(content_bytes.decode(charset, errors="replace"))
    if not code:
        raise ThirdPartyIcloudError("第三方页面未识别到验证码")
    return code
