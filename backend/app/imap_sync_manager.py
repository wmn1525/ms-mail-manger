"""管理每个普通 IMAP 配置的持久增量同步线程。"""

from dataclasses import dataclass
import imaplib
import logging
import threading
import time

from sqlalchemy import select

from .db import SessionLocal
from .icloud_cache import cleanup_expired_cache
from .imap_client import GenericImapClient, ImapCredential
from .imap_sync import (
    ImapCacheSynchronizer,
    ImapConfigChangedError,
    ImapConfigMissingError,
    imap_config_fingerprint,
    mark_sync_error,
)
from .models import ImapConfig
from .security import decrypt_value


POLL_INTERVAL_SECONDS = 2
RECONNECT_INTERVAL_SECONDS = 5
SUPERVISOR_INTERVAL_SECONDS = 2
CACHE_CLEANUP_INTERVAL_SECONDS = 3600
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImapWorkerConfig:
    """同步线程使用的不可变配置，配置变化时由管理器重启线程。"""

    # 数据库配置主键。
    config_id: int
    # 用于判断账号、密码或连接参数是否发生变化。
    fingerprint: tuple[str, int, str, str, bool]
    # 解密后的连接凭据，仅保留在线程内存中。
    credential: ImapCredential


class ImapSyncWorker(threading.Thread):
    """为单个 IMAP 配置维持连接并定时同步新 UID。"""

    def __init__(self, config: ImapWorkerConfig):
        """固定连接配置并创建线程私有的停止事件与同步器。"""

        super().__init__(name=f"imap-sync-{config.config_id}", daemon=True)
        # 工作线程固定使用创建时的配置快照。
        self.config = config
        # 停止事件同时用于可中断的轮询等待。
        self.stop_event = threading.Event()
        # 同步器不持有数据库会话，线程之间不会共享 Session。
        self.synchronizer = ImapCacheSynchronizer()

    def stop(self) -> None:
        """请求线程结束，网络调用会在超时后退出。"""

        self.stop_event.set()

    def _logout(self, imap: imaplib.IMAP4 | None) -> None:
        """关闭当前连接，忽略服务器已断开的退出错误。"""

        if not imap:
            return
        try:
            imap.logout()
        except Exception:
            pass

    def run(self) -> None:
        """连接成功后每两秒增量检查，失败则五秒后重新连接。"""

        while not self.stop_event.is_set():
            imap: imaplib.IMAP4 | None = None
            try:
                imap = GenericImapClient(self.config.credential).open_selected()
                while not self.stop_event.is_set():
                    self.synchronizer.sync_once(
                        self.config.config_id,
                        imap,
                        expected_fingerprint=self.config.fingerprint,
                    )
                    if self.stop_event.wait(POLL_INTERVAL_SECONDS):
                        break
            except (ImapConfigMissingError, ImapConfigChangedError):
                return
            except Exception as exc:
                mark_sync_error(self.config.config_id, str(exc))
                if self.stop_event.wait(RECONNECT_INTERVAL_SECONDS):
                    return
            finally:
                self._logout(imap)


class ImapSyncManager:
    """监督 IMAP 工作线程，并响应后台配置的新增、修改和删除。"""

    def __init__(self):
        """初始化监督线程状态，实际线程只在应用 startup 后创建。"""

        # 管理器停止事件控制监督循环和全部工作线程。
        self.stop_event = threading.Event()
        # 监督线程只在应用启动后创建。
        self.supervisor: threading.Thread | None = None
        # 当前配置主键对应的指纹和工作线程。
        self.workers: dict[int, tuple[tuple[str, int, str, str, bool], ImapSyncWorker]] = {}

    def _load_configs(self) -> dict[int, ImapWorkerConfig]:
        """从数据库加载连接快照，密码密文参与变更检测但不写入日志。"""

        missing_password_ids: list[int] = []
        with SessionLocal() as db:
            configs = db.scalars(select(ImapConfig).order_by(ImapConfig.id)).all()
            snapshots: dict[int, ImapWorkerConfig] = {}
            for config in configs:
                password = decrypt_value(config.password_enc)
                if not password:
                    missing_password_ids.append(config.id)
                    continue
                fingerprint = imap_config_fingerprint(config)
                snapshots[config.id] = ImapWorkerConfig(
                    config_id=config.id,
                    fingerprint=fingerprint,
                    credential=ImapCredential(
                        host=config.host,
                        port=config.port,
                        username=config.username,
                        password=password,
                        folder="INBOX",
                        use_ssl=config.use_ssl,
                    ),
                )
        for config_id in missing_password_ids:
            mark_sync_error(config_id, "缺少 IMAP 密码")
        return snapshots

    def _stop_worker(self, config_id: int) -> None:
        """停止并移除指定配置的工作线程。"""

        current = self.workers.pop(config_id, None)
        if not current:
            return
        worker = current[1]
        worker.stop()
        worker.join(timeout=20)

    def _reconcile_workers(self) -> None:
        """根据数据库快照启动新线程，并重启参数发生变化的线程。"""

        snapshots = self._load_configs()
        for config_id, (fingerprint, _) in list(self.workers.items()):
            snapshot = snapshots.get(config_id)
            if not snapshot or snapshot.fingerprint != fingerprint:
                self._stop_worker(config_id)
        for config_id, snapshot in snapshots.items():
            if config_id in self.workers:
                continue
            worker = ImapSyncWorker(snapshot)
            self.workers[config_id] = (snapshot.fingerprint, worker)
            worker.start()

    def _cleanup_cache(self) -> None:
        """在独立事务中清理过期临时邮件。"""

        with SessionLocal() as db:
            cleanup_expired_cache(db)
            db.commit()

    def _run(self) -> None:
        """运行监督循环，并保证退出时回收全部工作线程。"""

        next_cleanup_at = time.monotonic()
        try:
            while not self.stop_event.is_set():
                try:
                    self._reconcile_workers()
                    if time.monotonic() >= next_cleanup_at:
                        self._cleanup_cache()
                        next_cleanup_at = time.monotonic() + CACHE_CLEANUP_INTERVAL_SECONDS
                except Exception:
                    # 单次监督失败不应终止已有同步线程，下一轮会重新加载配置。
                    logger.exception("IMAP 同步监督循环执行失败")
                self.stop_event.wait(SUPERVISOR_INTERVAL_SECONDS)
        finally:
            for config_id in list(self.workers):
                self._stop_worker(config_id)

    def start(self) -> None:
        """启动唯一监督线程；重复调用不会创建多份同步任务。"""

        if self.supervisor and self.supervisor.is_alive():
            return
        self.stop_event.clear()
        self.supervisor = threading.Thread(target=self._run, name="imap-sync-manager", daemon=True)
        self.supervisor.start()

    def stop(self) -> None:
        """停止监督线程并等待工作线程在网络超时范围内结束。"""

        self.stop_event.set()
        if self.supervisor:
            self.supervisor.join(timeout=30)


imap_sync_manager = ImapSyncManager()
