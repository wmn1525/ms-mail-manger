"""iCloud 缓存查询、验证码范围和过期清理测试。"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.db import Base
from backend.app.icloud_cache import (
    cleanup_expired_cache,
    find_latest_cached_code,
    get_cached_message,
    list_cached_messages,
)
from backend.app.imap_client import scoped_uid
from backend.app.models import IcloudCachedMessage, IcloudMailbox, ImapConfig
from backend.app.schemas import CodeOut, MessageDetailOut, MessageListOut


class IcloudCacheTestCase(unittest.TestCase):
    """验证公开接口依赖的本地查询不需要 IMAP 连接。"""

    def setUp(self) -> None:
        """创建包含三封缓存邮件的隔离数据库。"""

        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "cache.db"
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
            db.flush()
            mailbox = IcloudMailbox(
                email="user@icloud.com",
                public_token="tk_cache",
                imap_config_id=config.id,
            )
            db.add(mailbox)
            db.flush()
            self.mailbox_id = mailbox.id
            self.config_id = config.id
            for uid, code in ((1, "111111"), (2, None), (3, None)):
                db.add(
                    IcloudCachedMessage(
                        icloud_mailbox_id=mailbox.id,
                        imap_config_id=config.id,
                        folder="INBOX",
                        uid=uid,
                        subject=f"邮件 {uid}",
                        sender="sender@example.com",
                        message_date="2026-07-10T10:00:00+08:00",
                        snippet=f"摘要 {uid}",
                        body=f"正文 {uid}",
                        html=None,
                        code=code,
                        cached_at=datetime.now(UTC),
                    )
                )
            db.commit()

    def tearDown(self) -> None:
        """关闭数据库并删除临时文件。"""

        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_list_and_detail_preserve_public_uid(self) -> None:
        """列表按数字 UID 倒序，详情继续使用现有 scoped UID。"""

        with self.session_factory() as db:
            messages = list_cached_messages(db, self.mailbox_id, 2)
            detail = get_cached_message(db, self.mailbox_id, scoped_uid("INBOX", 3))
            invalid_detail = get_cached_message(db, self.mailbox_id, "imap:not-base64:3")

        self.assertEqual([message["subject"] for message in messages], ["邮件 3", "邮件 2"])
        self.assertEqual(detail["body"], "正文 3")
        self.assertEqual(detail["uid"], scoped_uid("INBOX", 3))
        self.assertIsNone(invalid_detail)
        self.assertEqual(MessageListOut(mailbox_id=self.mailbox_id, messages=messages).mailbox_id, self.mailbox_id)
        self.assertEqual(MessageDetailOut(**detail).uid, scoped_uid("INBOX", 3))

    def test_code_limit_only_scans_latest_messages(self) -> None:
        """limit 不包含旧验证码时返回空，扩大范围后才返回该验证码。"""

        with self.session_factory() as db:
            limited = find_latest_cached_code(db, self.mailbox_id, 2)
            expanded = find_latest_cached_code(db, self.mailbox_id, 3)

        self.assertIsNone(limited)
        self.assertEqual(expanded["code"], "111111")
        response = CodeOut(
            mailbox_token="tk_cache",
            email="user@icloud.com",
            code=expanded["code"],
            message=expanded,
        )
        self.assertEqual(response.message.uid, scoped_uid("INBOX", 1))

    def test_cleanup_removes_only_expired_messages(self) -> None:
        """七天清理按缓存写入时间执行，不受邮件 Date 头影响。"""

        with self.session_factory() as db:
            expired = db.get(IcloudCachedMessage, 1)
            expired.cached_at = datetime.now(UTC) - timedelta(days=8)
            db.commit()
            removed = cleanup_expired_cache(db)
            db.commit()
            remaining = list_cached_messages(db, self.mailbox_id, 10)

        self.assertEqual(removed, 1)
        self.assertEqual(len(remaining), 2)


if __name__ == "__main__":
    unittest.main()
