"""IMAP 增量同步与临时邮件写入测试。"""

from email.message import EmailMessage
from pathlib import Path
import tempfile
import unittest

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db import Base
from backend.app.icloud_cache import request_config_backfill
from backend.app.imap_sync import ImapCacheSynchronizer
from backend.app.models import IcloudCachedMessage, IcloudMailbox, ImapConfig, ImapSyncState


def build_message(recipient: str, code: str, subject: str = "验证码") -> bytes:
    """构造只含文本正文的验证邮件，便于验证收件人和验证码解析。"""

    message = EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = recipient
    message["Subject"] = subject
    message["Date"] = "Fri, 10 Jul 2026 10:00:00 +0800"
    message.set_content(f"你的验证码是 {code}")
    return message.as_bytes()


class FakeImap:
    """实现同步器使用的最小 IMAP 协议，并记录批量 FETCH 调用。"""

    def __init__(self, messages: dict[int, bytes], uid_validity: int = 1):
        # 远端 UID 到原始邮件的映射。
        self.messages = messages
        # 当前目录 UIDVALIDITY。
        self.uid_validity = uid_validity
        # 每次 FETCH 请求的 UID 集合，用于断言没有逐封读取。
        self.fetch_uid_sets: list[tuple[int, ...]] = []
        # 指定 UID 在 FETCH 响应中缺失，用于模拟不完整批次。
        self.omitted_uids: set[int] = set()

    def response(self, name: str) -> tuple[str, list[bytes]]:
        """返回同步器要求的 UIDVALIDITY 响应。"""

        if name != "UIDVALIDITY":
            return name, []
        return name, [str(self.uid_validity).encode("ascii")]

    def uid(self, command: str, *args: str | None) -> tuple[str, list[bytes | tuple[bytes, bytes]]]:
        """支持 SEARCH 和批量 FETCH，并模拟网易的 UID 边界返回。"""

        if command == "search":
            if args[-1] == "ALL":
                values = sorted(self.messages)
            else:
                start_uid = int(str(args[-1]).split(":", 1)[0])
                boundary = max((uid for uid in self.messages if uid < start_uid), default=None)
                values = ([boundary] if boundary is not None else []) + [
                    uid for uid in sorted(self.messages) if uid >= start_uid
                ]
            return "OK", [" ".join(str(uid) for uid in values).encode("ascii")]
        if command != "fetch":
            raise AssertionError(f"不支持的命令：{command}")
        uid_values = tuple(int(value) for value in str(args[0]).split(","))
        self.fetch_uid_sets.append(uid_values)
        fetched: list[bytes | tuple[bytes, bytes]] = []
        for sequence, uid in enumerate(uid_values, start=1):
            if uid in self.omitted_uids or uid not in self.messages:
                continue
            raw = self.messages[uid]
            metadata = f"{sequence} (UID {uid} BODY[] {{{len(raw)}}}".encode("ascii")
            fetched.extend([(metadata, raw), b")"])
        return "OK", fetched


class ImapSyncTestCase(unittest.TestCase):
    """使用独立 SQLite 文件验证同步事务和 UID 状态。"""

    def setUp(self) -> None:
        """为每个测试创建隔离数据库和基础 IMAP 配置。"""

        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_engine(f"sqlite:///{database_path}")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.session_factory() as db:
            config = ImapConfig(
                name="网易",
                host="imap.126.com",
                port=993,
                username="receiver@126.com",
                password_enc="encrypted-password",
                folder="INBOX",
                use_ssl=True,
            )
            db.add(config)
            db.commit()
            self.config_id = config.id
        self.synchronizer = ImapCacheSynchronizer(self.session_factory)

    def tearDown(self) -> None:
        """释放数据库连接后删除临时目录。"""

        self.engine.dispose()
        self.temp_dir.cleanup()

    def add_mailbox(self, email: str) -> int:
        """新增绑定到测试配置的 iCloud 邮箱并返回主键。"""

        with self.session_factory() as db:
            mailbox = IcloudMailbox(
                email=email,
                public_token=f"tk_{email.split('@', 1)[0]}",
                imap_config_id=self.config_id,
            )
            db.add(mailbox)
            db.commit()
            return mailbox.id

    def cached_count(self, mailbox_id: int | None = None) -> int:
        """统计全部或指定邮箱的缓存邮件数量。"""

        with self.session_factory() as db:
            query = select(func.count()).select_from(IcloudCachedMessage)
            if mailbox_id is not None:
                query = query.where(IcloudCachedMessage.icloud_mailbox_id == mailbox_id)
            return db.scalar(query) or 0

    def test_initial_backfill_batches_headers_and_matches_aliases(self) -> None:
        """首次回填应批量读取邮件，并把加号别名归一到基础邮箱。"""

        mailbox_id = self.add_mailbox("user@icloud.com")
        imap = FakeImap(
            {
                1: build_message("other@icloud.com", "111111"),
                2: build_message("user+shop@icloud.com", "222222"),
                3: build_message("user@icloud.com", "333333"),
            }
        )

        self.synchronizer.sync_once(self.config_id, imap)

        self.assertEqual(self.cached_count(mailbox_id), 2)
        self.assertEqual(imap.fetch_uid_sets, [(1, 2, 3), (2, 3)])
        with self.session_factory() as db:
            state = db.scalar(select(ImapSyncState).where(ImapSyncState.imap_config_id == self.config_id))
            codes = db.scalars(
                select(IcloudCachedMessage.code)
                .where(IcloudCachedMessage.icloud_mailbox_id == mailbox_id)
                .order_by(IcloudCachedMessage.uid)
            ).all()
            self.assertEqual(state.last_uid, 3)
            self.assertEqual(state.uid_validity, 1)
            self.assertEqual(codes, ["222222", "333333"])

    def test_incremental_sync_filters_boundary_and_is_idempotent(self) -> None:
        """增量搜索必须过滤边界 UID，重复轮询不能重复写入。"""

        mailbox_id = self.add_mailbox("user@icloud.com")
        imap = FakeImap({1: build_message("user@icloud.com", "111111")})
        self.synchronizer.sync_once(self.config_id, imap)
        imap.messages[2] = build_message("user+next@icloud.com", "222222")
        imap.fetch_uid_sets.clear()

        self.synchronizer.sync_once(self.config_id, imap)
        self.synchronizer.sync_once(self.config_id, imap)

        self.assertEqual(self.cached_count(mailbox_id), 2)
        self.assertEqual(imap.fetch_uid_sets, [(2,), (2,)])
        with self.session_factory() as db:
            state = db.scalar(select(ImapSyncState).where(ImapSyncState.imap_config_id == self.config_id))
            self.assertEqual(state.last_uid, 2)

    def test_uid_validity_change_rebuilds_cache(self) -> None:
        """UIDVALIDITY 改变后必须删除旧 UID 内容并重新回填。"""

        mailbox_id = self.add_mailbox("user@icloud.com")
        imap = FakeImap({10: build_message("user@icloud.com", "101010")}, uid_validity=1)
        self.synchronizer.sync_once(self.config_id, imap)
        imap.uid_validity = 2
        imap.messages = {1: build_message("user@icloud.com", "202020")}

        self.synchronizer.sync_once(self.config_id, imap)

        self.assertEqual(self.cached_count(mailbox_id), 1)
        with self.session_factory() as db:
            message = db.scalar(select(IcloudCachedMessage))
            state = db.scalar(select(ImapSyncState).where(ImapSyncState.imap_config_id == self.config_id))
            self.assertEqual((message.uid, message.code), (1, "202020"))
            self.assertEqual((state.uid_validity, state.last_uid), (2, 1))

    def test_incomplete_batch_does_not_advance_cursor(self) -> None:
        """邮件头批次不完整时整轮失败，游标保持最后成功位置。"""

        self.add_mailbox("user@icloud.com")
        imap = FakeImap({1: build_message("user@icloud.com", "111111")})
        self.synchronizer.sync_once(self.config_id, imap)
        imap.messages[2] = build_message("user@icloud.com", "222222")
        imap.omitted_uids.add(2)

        with self.assertRaisesRegex(RuntimeError, "邮件头不完整"):
            self.synchronizer.sync_once(self.config_id, imap)

        with self.session_factory() as db:
            state = db.scalar(select(ImapSyncState).where(ImapSyncState.imap_config_id == self.config_id))
            self.assertEqual(state.last_uid, 1)

    def test_new_mailbox_backfill_and_multiple_recipients(self) -> None:
        """新增邮箱触发回填，多收件人邮件应分别写入对应邮箱缓存。"""

        first_id = self.add_mailbox("first@icloud.com")
        imap = FakeImap({1: build_message("first@icloud.com, second+tag@icloud.com", "654321")})
        self.synchronizer.sync_once(self.config_id, imap)
        second_id = self.add_mailbox("second@icloud.com")
        with self.session_factory() as db:
            request_config_backfill(db, self.config_id)
            db.commit()

        self.synchronizer.sync_once(self.config_id, imap)

        self.assertEqual(self.cached_count(first_id), 1)
        self.assertEqual(self.cached_count(second_id), 1)


if __name__ == "__main__":
    unittest.main()
