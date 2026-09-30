"""Microsoft IMAP 与 Graph 别名取码隔离测试。"""

from email.message import EmailMessage
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.db import Base
from backend.app.email_client import MailCredential, OutlookImapClient
from backend.app.email_graph import GraphMailClient
from backend.app.models import Mailbox
from backend.app.routers.public import get_public_latest_code_by_email


def build_message(recipient: str, code: str) -> bytes:
    """构造带完整收件别名的验证码邮件。"""

    message = EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = recipient
    message["Subject"] = "验证码"
    message.set_content(f"你的验证码是 {code}")
    return message.as_bytes()


class FakeOutlookImap:
    """提供 Outlook IMAP 取码所需的最小协议。"""

    def __init__(self, messages: dict[int, bytes]) -> None:
        """保存 UID 到邮件正文的映射。"""

        self.messages = messages
        # 记录请求种类和 UID，断言批量读取没有下载无关正文。
        self.fetches: list[tuple[list[int], str]] = []
        # 无论成功还是异常，都应释放此次连接。
        self.closed = False

    def select(self, folder: str, readonly: bool) -> tuple[str, list[bytes]]:
        """模拟成功打开收件箱。"""

        del folder, readonly
        return "OK", []

    def uid(
        self,
        command: str,
        uid: bytes | None,
        fields: str,
    ) -> tuple[str, list[bytes | tuple[bytes, bytes]]]:
        """模拟批量 FETCH，刻意按升序返回以验证客户端使用真实 UID。"""

        if command == "search":
            return "OK", [b" ".join(str(value).encode("ascii") for value in sorted(self.messages))]
        if uid is None:
            raise AssertionError("FETCH 必须指定 UID")
        values = [int(value) for value in uid.split(b",")]
        self.fetches.append((values, fields))
        fetched: list[bytes | tuple[bytes, bytes]] = []
        for value in sorted(values):
            raw = self.messages[value]
            if "HEADER.FIELDS" in fields:
                raw = raw.split(b"\n\n", 1)[0] + b"\n\n"
            metadata = f"1 (UID {value} BODY[] {{{len(raw)}}}".encode("ascii")
            fetched.extend([(metadata, raw), b")"])
        return "OK", fetched

    def logout(self) -> None:
        """测试连接无需释放真实网络资源。"""

        self.closed = True


class FakeGraphClient(GraphMailClient):
    """使用内存邮件验证 Graph 的完整别名过滤。"""

    def __init__(self, messages: list[dict]) -> None:
        """跳过 access token，仅保存测试邮件。"""

        self.messages = messages

    def _list_message_payloads(self, limit: int) -> list[dict]:
        """按 Graph 接口的数量上限返回原始邮件。"""

        return self.messages[:limit]

    def get_message(self, uid: str) -> dict:
        """正文验证码已在摘要中，测试不应读取详情。"""

        raise AssertionError(f"不应读取邮件详情：{uid}")


def graph_message(uid: str, recipient: str, code: str) -> dict:
    """构造包含 Graph 收件人结构的邮件。"""

    return {
        "id": uid,
        "subject": f"验证码 {code}",
        "bodyPreview": "",
        "toRecipients": [{"emailAddress": {"address": recipient}}],
    }


class AliasCodeIsolationTestCase(unittest.TestCase):
    """验证同一 Microsoft 邮箱下的不同别名不会串码。"""

    def test_outlook_imap_filters_exact_alias(self) -> None:
        """IMAP 最新邮件属于其他别名时必须继续查找目标别名。"""

        imap = FakeOutlookImap(
            {
                1: build_message("user+shop@outlook.com", "111111"),
                2: build_message("user+work@outlook.com", "222222"),
            }
        )
        client = OutlookImapClient(MailCredential(email="user@outlook.com"))
        with patch.object(client, "_open", return_value=imap):
            message = client._find_latest_code_imap(10, "user+shop@outlook.com")

        self.assertEqual(message["code"], "111111")

    def test_graph_filters_exact_alias(self) -> None:
        """Graph 取码只返回目标完整别名收到的验证码。"""

        client = FakeGraphClient(
            [
                graph_message("work", "user+work@outlook.com", "222222"),
                graph_message("shop", "user+shop@outlook.com", "111111"),
            ]
        )

        message = client.find_latest_code(10, "user+shop@outlook.com")

        self.assertEqual(message["code"], "111111")

    def test_public_lookup_passes_full_alias_to_microsoft_client(self) -> None:
        """按邮箱取码入口必须向 Microsoft 客户端传递请求中的完整别名。"""

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        with session_factory() as db:
            db.add(Mailbox(email="user@outlook.com", public_token="tk_alias_test"))
            db.commit()
            with patch.object(
                OutlookImapClient,
                "find_latest_code",
                return_value={
                    "uid": "1",
                    "subject": "验证码",
                    "from": "sender@example.com",
                    "date": None,
                    "snippet": "111111",
                    "code": "111111",
                },
            ) as find_code:
                response = get_public_latest_code_by_email("user+shop@outlook.com", 10, db)

        find_code.assert_called_once_with(limit=10, recipient_email="user+shop@outlook.com")
        self.assertEqual(str(response.email), "user+shop@outlook.com")
        self.assertEqual(response.code, "111111")


if __name__ == "__main__":
    unittest.main()
