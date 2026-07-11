from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


settings = get_settings()
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 30} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def configure_sqlite_connection(dbapi_connection, connection_record) -> None:
        """为后台同步写入启用 WAL、外键和锁等待，避免阻塞 API 查询。"""

        del connection_record
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_sqlite()


def _migrate_sqlite() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if "mailboxes" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("mailboxes")}
    if "public_token" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE mailboxes ADD COLUMN public_token VARCHAR(80)"))
            rows = connection.execute(text("SELECT id FROM mailboxes WHERE public_token IS NULL OR public_token = ''"))
            for row in rows:
                connection.execute(
                    text("UPDATE mailboxes SET public_token = :token WHERE id = :id"),
                    {"token": f"tk_{row.id:06d}", "id": row.id},
                )
            connection.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS ix_mailboxes_public_token ON mailboxes (public_token)")
            )
