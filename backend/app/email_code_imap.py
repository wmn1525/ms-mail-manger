"""Microsoft 取码按批读取邮件头，仅下载目标收件人的正文。"""

from collections.abc import Iterator
from email import message_from_bytes
from email.message import Message
import imaplib
import re

from .imap_client import HEADER_FETCH_FIELDS, message_recipients


# 收件人扫描只传输小体积邮件头，避免逐封下载无关正文和附件。
HEADER_BATCH_SIZE = 50
UID_PATTERN = re.compile(rb"\bUID\s+(\d+)\b")


def fetch_batch(imap: imaplib.IMAP4, uids: list[bytes], fields: str) -> dict[bytes, Message]:
    """按真实 UID 关联响应，服务端返回顺序不代表邮件的新旧顺序。"""

    status, fetched = imap.uid("fetch", b",".join(uids), fields)
    if status != "OK" or not fetched:
        raise RuntimeError("批量读取取码邮件失败")
    messages: dict[bytes, Message] = {}
    for item in fetched:
        if not isinstance(item, tuple) or not item[1]:
            continue
        match = UID_PATTERN.search(item[0])
        if match:
            messages[match.group(1)] = message_from_bytes(item[1])
    return messages


def code_messages(
    imap: imaplib.IMAP4, uids: list[bytes], recipient_email: str | None
) -> Iterator[tuple[bytes, Message]]:
    """按调用方给定的倒序 UID 产出正文，完整地址匹配保留别名隔离。"""

    if not recipient_email:
        # 最新一封可直接命中，避免常见路径多传输其他邮件；其余邮件批量读取。
        pages = [uids[:1]] + [uids[index:index + 10] for index in range(1, len(uids), 10)]
        for page in pages:
            if not page:
                continue
            messages = fetch_batch(imap, page, "(UID BODY.PEEK[])")
            for uid in page:
                if uid in messages:
                    yield uid, messages[uid]
        return

    fields = HEADER_FETCH_FIELDS.replace("(BODY", "(UID BODY", 1)
    for index in range(0, len(uids), HEADER_BATCH_SIZE):
        page = uids[index:index + HEADER_BATCH_SIZE]
        headers = fetch_batch(imap, page, fields)
        for uid in page:
            header = headers.get(uid)
            if header is None or recipient_email not in message_recipients(header):
                continue
            # 匹配邮件通常很少，按需取正文可在命中验证码后立即停止。
            messages = fetch_batch(imap, [uid], "(UID BODY.PEEK[])")
            message = messages.get(uid)
            if message is not None and recipient_email in message_recipients(message):
                yield uid, message
