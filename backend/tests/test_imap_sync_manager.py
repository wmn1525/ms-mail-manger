"""IMAP 工作线程的断线重连与关闭测试。"""

import threading
import unittest
from unittest.mock import patch

from backend.app.imap_client import ImapCredential
from backend.app.imap_sync_manager import ImapSyncWorker, ImapWorkerConfig


class FakeConnection:
    """记录工作线程是否正常退出持久连接。"""

    def __init__(self):
        # logout_called 用于验证 finally 清理路径。
        self.logout_called = False

    def logout(self) -> None:
        """标记连接已关闭。"""

        self.logout_called = True


class RetryClient:
    """第一次连接失败、第二次成功，用于验证五秒重连路径。"""

    # 创建连接的累计次数。
    attempts = 0
    # 第二次返回的连接实例。
    connection = FakeConnection()

    def __init__(self, credential: ImapCredential):
        # 测试只验证线程行为，不使用凭据内容。
        self.credential = credential

    def open_selected(self) -> FakeConnection:
        """首次抛错，后续返回可关闭连接。"""

        RetryClient.attempts += 1
        if RetryClient.attempts == 1:
            raise RuntimeError("temporary failure")
        return RetryClient.connection


class StopAfterSync:
    """成功同步一次后请求工作线程停止。"""

    def __init__(self, stop_event: threading.Event):
        # 使用工作线程自身事件结束内层轮询。
        self.stop_event = stop_event
        # 同步次数用于断言重连后真正执行了任务。
        self.calls = 0

    def sync_once(
        self,
        config_id: int,
        imap: FakeConnection,
        expected_fingerprint: tuple[str, int, str, str, bool],
    ) -> None:
        """记录成功调用并触发线程停止。"""

        del config_id, imap, expected_fingerprint
        self.calls += 1
        self.stop_event.set()


class ImapSyncWorkerTestCase(unittest.TestCase):
    """验证连接错误不会终止工作线程。"""

    def test_worker_reconnects_and_logs_out(self) -> None:
        """首次连接失败后应记录错误、重新连接并在停止时 logout。"""

        RetryClient.attempts = 0
        RetryClient.connection = FakeConnection()
        config = ImapWorkerConfig(
            config_id=1,
            fingerprint=("imap.126.com", 993, "receiver", "encrypted", True),
            credential=ImapCredential("imap.126.com", 993, "receiver", "password"),
        )
        worker = ImapSyncWorker(config)
        synchronizer = StopAfterSync(worker.stop_event)
        worker.synchronizer = synchronizer

        with (
            patch("backend.app.imap_sync_manager.GenericImapClient", RetryClient),
            patch("backend.app.imap_sync_manager.mark_sync_error") as mark_error,
            patch("backend.app.imap_sync_manager.RECONNECT_INTERVAL_SECONDS", 0),
        ):
            worker.run()

        self.assertEqual(RetryClient.attempts, 2)
        self.assertEqual(synchronizer.calls, 1)
        self.assertTrue(RetryClient.connection.logout_called)
        mark_error.assert_called_once_with(1, "temporary failure")


if __name__ == "__main__":
    unittest.main()
