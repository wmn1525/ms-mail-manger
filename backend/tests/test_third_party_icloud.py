"""第三方 iCloud 链接校验和验证码解析测试。"""

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.db import Base
from backend.app.models import ThirdPartyIcloudMailbox
from backend.app.routers.public import get_public_latest_code_by_email
from backend.app.routers.third_party_icloud_mailboxes import parse_import_line, upsert_mailbox
from backend.app.security import encrypt_value
from backend.app.third_party_icloud_client import (
    ThirdPartyIcloudError,
    extract_page_code,
    fetch_latest_code,
    validate_fetch_url,
)


EMAIL = "user@icloud.com"
FETCH_URL = "http://icloudapi.xyz/show/access-token/user@icloud.com"


class FakeHeaders:
    """提供取码客户端使用的最小响应头接口。"""

    def get_content_type(self) -> str:
        """模拟第三方服务返回 HTML。"""

        return "text/html"

    def get_content_charset(self) -> str:
        """声明测试正文使用 UTF-8。"""

        return "utf-8"


class FakeResponse:
    """模拟 urllib 可作为上下文管理器使用的响应。"""

    def __init__(self, content: str, final_url: str = FETCH_URL) -> None:
        """保存响应正文和最终链接，供取码流程读取。"""

        self.content = content.encode("utf-8")
        self.final_url = final_url
        self.headers = FakeHeaders()

    def __enter__(self) -> "FakeResponse":
        """进入响应读取上下文。"""

        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """测试响应没有需要释放的网络资源。"""

        del exc_type, exc_value, traceback

    def geturl(self) -> str:
        """返回重定向后的最终链接。"""

        return self.final_url

    def read(self, size: int) -> bytes:
        """按客户端给定上限返回测试正文。"""

        return self.content[:size]


class ThirdPartyIcloudClientTestCase(unittest.TestCase):
    """验证取码只访问指定服务并忽略页面样式数字。"""

    def test_validate_fetch_url_accepts_expected_format(self) -> None:
        """合法链接应原样保留，便于后续加密保存。"""

        self.assertEqual(validate_fetch_url(EMAIL, FETCH_URL), FETCH_URL)

    def test_validate_fetch_url_rejects_wrong_host_or_email(self) -> None:
        """拒绝任意主机代理和链接邮箱不一致的导入数据。"""

        with self.assertRaisesRegex(ValueError, "icloudapi.xyz"):
            validate_fetch_url(EMAIL, "https://example.com/show/token/user@icloud.com")
        with self.assertRaisesRegex(ValueError, "邮箱与导入邮箱不一致"):
            validate_fetch_url(EMAIL, "https://icloudapi.xyz/show/token/other@icloud.com")

    def test_extract_page_code_ignores_css_numbers(self) -> None:
        """CSS 色值不能抢在正文验证码之前被误识别。"""

        content = """
        <html><head><style>.code { color: #202123; width: 5600px; }</style></head>
        <body><p>输入此临时验证码以继续：</p><p>007951</p></body></html>
        """
        self.assertEqual(extract_page_code(content), "007951")

    def test_fetch_latest_code_reads_html_response(self) -> None:
        """客户端应从第三方 HTML 正文返回验证码。"""

        response = FakeResponse("<html><body>验证码：123456</body></html>")
        with patch("backend.app.third_party_icloud_client.urlopen", return_value=response):
            self.assertEqual(fetch_latest_code(EMAIL, FETCH_URL), "123456")

    def test_fetch_latest_code_rejects_telemetry_json(self) -> None:
        """性能上报 JSON 中的内存数字不能被当成验证码。"""

        response = FakeResponse('{"memory":{"totalJSHeapSize":16861562}}')
        with patch("backend.app.third_party_icloud_client.urlopen", return_value=response):
            with self.assertRaisesRegex(ThirdPartyIcloudError, "未识别到验证码"):
                fetch_latest_code(EMAIL, FETCH_URL)

    def test_parse_import_line_requires_email_and_url(self) -> None:
        """批量导入严格使用用户指定的双字段格式。"""

        self.assertEqual(parse_import_line(f"{EMAIL}----{FETCH_URL}"), (EMAIL, FETCH_URL))
        with self.assertRaisesRegex(ValueError, "格式必须为"):
            parse_import_line(EMAIL)

    def test_api_key_code_lookup_normalizes_split_alias(self) -> None:
        """API Key 按分裂邮箱取码时应回源到第三方基础邮箱。"""

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        encrypted_url = encrypt_value(FETCH_URL)
        self.assertIsNotNone(encrypted_url)
        with session_factory() as db:
            mailbox = ThirdPartyIcloudMailbox(
                email=EMAIL,
                public_token="tk_third_party_test",
                fetch_url_enc=str(encrypted_url),
            )
            db.add(mailbox)
            db.commit()
            with patch("backend.app.routers.public.fetch_latest_code", return_value="654321"):
                result = get_public_latest_code_by_email(
                    email="user+split@icloud.com",
                    limit=10,
                    db=db,
                )
        self.assertEqual(result.email, EMAIL)
        self.assertEqual(result.mailbox_token, "tk_third_party_test")
        self.assertEqual(result.code, "654321")

    def test_new_import_generates_public_token(self) -> None:
        """新导入记录必须生成 API Key 标准响应所需的公开标识。"""

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        with session_factory() as db:
            self.assertTrue(upsert_mailbox(db, EMAIL, FETCH_URL))
            db.commit()
            mailbox = db.scalar(select(ThirdPartyIcloudMailbox))
            self.assertIsNotNone(mailbox)
            if mailbox is None:
                self.fail("第三方 iCloud 邮箱未写入数据库")
        self.assertTrue(mailbox.public_token.startswith("tk_"))


if __name__ == "__main__":
    unittest.main()
