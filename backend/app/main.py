from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import init_db
from .imap_sync_manager import imap_sync_manager
from .routers import (
    api_keys,
    auth,
    icloud_mailboxes,
    imap_configs,
    mailboxes,
    public,
    third_party_icloud_mailboxes,
)


settings = get_settings()
app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    """初始化数据库后启动普通 IMAP 增量同步任务。"""

    init_db()
    imap_sync_manager.start()


@app.on_event("shutdown")
def shutdown() -> None:
    """应用退出时停止后台连接，避免容器重启遗留线程。"""

    imap_sync_manager.stop()


@app.get("/health")
def health() -> dict:
    return {"ok": True}


app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(api_keys.router, prefix=settings.api_prefix)
app.include_router(mailboxes.router, prefix=settings.api_prefix)
app.include_router(imap_configs.router, prefix=settings.api_prefix)
app.include_router(icloud_mailboxes.router, prefix=settings.api_prefix)
app.include_router(third_party_icloud_mailboxes.router, prefix=settings.api_prefix)
app.include_router(public.router, prefix=settings.api_prefix)
app.include_router(public.token_router, prefix=settings.api_prefix)


frontend_dist = Path(settings.frontend_dist_dir)
if frontend_dist.exists():
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str) -> FileResponse:
        requested = frontend_dist / full_path
        if full_path and requested.is_file():
            return FileResponse(requested)
        return FileResponse(frontend_dist / "index.html")
