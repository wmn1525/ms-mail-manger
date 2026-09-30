"""通过网络请求次数验证取码优化，并覆盖排序、范围与授权行为。"""

import unittest
from unittest.mock import patch

from backend.app.email_client import MailCredential, OutlookImapClient
from backend.app.email_graph import GraphMailClient
from backend.app.mail_oauth import GRAPH_MODES
from backend.tests.test_alias_code_isolation import FakeOutlookImap, build_message, graph_message


class ImapCodePerformanceTestCase(unittest.TestCase):
    """验证共享邮箱仅下载匹配的正文，且不会返回超出 limit 的旧验证码。"""

    def test_unmatched_200_messages_use_four_header_requests(self) -> None:
        """找不到收件人时，200 次全文下载缩减为 4 次邮件头读取。"""

        imap = FakeOutlookImap({uid: build_message("other@outlook.com", "123456") for uid in range(1, 201)})
        client = OutlookImapClient(MailCredential(email="user@outlook.com"))
        with patch.object(client, "_open", return_value=imap):
            result = client._find_latest_code_imap(10, "user+shop@outlook.com")
        self.assertIsNone(result)
        self.assertEqual(len(imap.fetches), 4)
        self.assertTrue(all("HEADER.FIELDS" in fields for _, fields in imap.fetches))
        self.assertTrue(imap.closed)

    def test_alias_downloads_only_matching_body(self) -> None:
        """最旧的目标别名仍可命中，无关邮件的验证码和正文都不能混入。"""

        messages = {uid: build_message("other@outlook.com", "123456") for uid in range(1, 201)}
        messages[1] = build_message("user+shop@outlook.com", "654321")
        imap = FakeOutlookImap(messages)
        client = OutlookImapClient(MailCredential(email="user@outlook.com"))
        with patch.object(client, "_open", return_value=imap):
            result = client._find_latest_code_imap(10, "USER+SHOP@outlook.com")
        self.assertEqual(result["code"], "654321")
        self.assertEqual(len(imap.fetches), 5)
        self.assertEqual([uids for uids, fields in imap.fetches if "HEADER.FIELDS" not in fields], [[1]])

    def test_token_lookup_uses_batch_and_latest_uid(self) -> None:
        """批次响应为升序时仍返回最新验证码，最近 10 封只需两次 FETCH。"""

        messages = {uid: build_message("user@outlook.com", "无验证码") for uid in range(1, 11)}
        messages[2] = build_message("user@outlook.com", "222222")
        messages[9] = build_message("user@outlook.com", "999999")
        imap = FakeOutlookImap(messages)
        client = OutlookImapClient(MailCredential(email="user@outlook.com"))
        with patch.object(client, "_open", return_value=imap):
            result = client._find_latest_code_imap(10)
        self.assertEqual(result["uid"], "9")
        self.assertEqual(result["code"], "999999")
        self.assertEqual(len(imap.fetches), 2)
        self.assertTrue(all("BODY.PEEK[]" in fields for _, fields in imap.fetches))

    def test_latest_message_requires_only_one_fetch(self) -> None:
        """常见的最新邮件命中场景不应因批量扫描增加往返。"""

        imap = FakeOutlookImap({1: build_message("user@outlook.com", "111111")})
        client = OutlookImapClient(MailCredential(email="user@outlook.com"))
        with patch.object(client, "_open", return_value=imap):
            self.assertEqual(client._find_latest_code_imap(10)["code"], "111111")
        self.assertEqual(len(imap.fetches), 1)

    def test_limit_excludes_old_code_for_alias_and_token(self) -> None:
        """批量预取不能扩大业务扫描范围，目标最新一封无验证码时必须返回空。"""

        for recipient in (None, "user+shop@outlook.com"):
            with self.subTest(recipient=recipient):
                imap = FakeOutlookImap({
                    1: build_message("user+shop@outlook.com", "111111"),
                    2: build_message("user+shop@outlook.com", "无验证码"),
                })
                client = OutlookImapClient(MailCredential(email="user@outlook.com"))
                with patch.object(client, "_open", return_value=imap):
                    self.assertIsNone(client._find_latest_code_imap(1, recipient))

    def test_fetch_error_is_reported_and_connection_closed(self) -> None:
        """读取失败不能伪装成无验证码，并应释放连接。"""

        imap = FakeOutlookImap({1: build_message("user@outlook.com", "111111")})
        client = OutlookImapClient(MailCredential(email="user@outlook.com"))
        with (
            patch.object(client, "_open", return_value=imap),
            patch.object(imap, "uid", side_effect=[("OK", [b"1"]), ("NO", [b"failed"])]),
        ):
            with self.assertRaisesRegex(RuntimeError, "批量读取"):
                client._find_latest_code_imap(10)
        self.assertTrue(imap.closed)


class GraphCodePerformanceTestCase(unittest.TestCase):
    """业务读信请求同时验证 Graph 权限，避免探活带来的额外往返。"""

    def setUp(self) -> None:
        """使用虚拟刷新凭据，所有远端请求在测试中替换。"""

        # 仅用于测试，不会发送到 Microsoft。
        self.client = OutlookImapClient(MailCredential(email="user@outlook.com", client_id="test", token="refresh"))

    def test_graph_code_uses_one_read_request(self) -> None:
        """摘要包含验证码时只读取一次邮件列表，省去独立探活。"""

        payload = {"value": [graph_message("latest", "user@outlook.com", "123456")]}
        with (
            patch("backend.app.email_client.refresh_access_token_for_scope", return_value="access"),
            patch.object(GraphMailClient, "_request", return_value=payload) as request,
        ):
            result = self.client.find_latest_code()
        self.assertEqual(result["code"], "123456")
        self.assertEqual(request.call_count, 1)

    def test_permission_failure_tries_next_existing_graph_mode(self) -> None:
        """令牌刷新成功但无读信权限时，仍需尝试已有的另一 Graph scope。"""

        with (
            patch("backend.app.email_client.refresh_access_token_for_scope", return_value="access") as refresh,
            patch.object(GraphMailClient, "find_latest_code", side_effect=[RuntimeError("denied"), None]),
            patch.object(self.client, "_find_latest_code_imap") as imap,
        ):
            self.assertIsNone(self.client.find_latest_code())
        self.assertEqual([call.args[2] for call in refresh.call_args_list], [mode.scope for mode in GRAPH_MODES])
        imap.assert_not_called()

    def test_existing_imap_mode_still_runs_after_graph_denied(self) -> None:
        """两个 Graph 模式均拒绝读信时仍执行已有 IMAP 路径。"""

        with (
            patch("backend.app.email_client.refresh_access_token_for_scope", return_value="access"),
            patch.object(GraphMailClient, "find_latest_code", side_effect=RuntimeError("denied")),
            patch.object(self.client, "_find_latest_code_imap", return_value=None) as imap,
        ):
            self.assertIsNone(self.client.find_latest_code(3, "user@outlook.com"))
        imap.assert_called_once_with(3, "user@outlook.com")

    def test_graph_detail_does_not_try_imap_uid(self) -> None:
        """Graph 专属 UID 读取失败不能发送给 IMAP，也不需要额外探活。"""

        with (
            patch("backend.app.email_client.refresh_access_token_for_scope", return_value="access"),
            patch.object(GraphMailClient, "get_message", side_effect=RuntimeError("denied")),
            patch.object(GraphMailClient, "check_alive") as alive,
            patch.object(self.client, "_get_message_imap") as imap,
        ):
            with self.assertRaisesRegex(RuntimeError, "Graph 模式不可用"):
                self.client.get_message("graph:dGVzdA")
        alive.assert_not_called()
        imap.assert_not_called()


if __name__ == "__main__":
    unittest.main()
