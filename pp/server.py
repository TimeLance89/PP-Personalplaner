from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .admin_maintenance_api import build_admin_maintenance_router
from .admin_settings_api import build_admin_settings_router
from .api import build_router
from .config import load_settings
from .db import Database
from .hardening import PersonnelGuardMiddleware

settings = load_settings()
db = Database(settings.data_dir / "personalplaner.sqlite3")
db.initialize()

app = FastAPI(title="PP – Personalplaner", version="0.2.0", docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.add_middleware(PersonnelGuardMiddleware, db=db, settings=settings)
app.include_router(build_router(db, settings))
app.include_router(build_admin_settings_router(db, settings))
app.include_router(build_admin_maintenance_router(db, settings))

STATIC = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


if __name__ == "__main__":
    uvicorn.run("pp.server:app", host=settings.host, port=settings.port, reload=False)
