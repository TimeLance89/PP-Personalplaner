from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .admin_maintenance_api import build_admin_maintenance_router
from .admin_settings_api import build_admin_settings_router
from .api import build_router
from .automation_api import build_automation_router
from .automation_engine import automation_loop, ensure_automation_schema
from .config import load_settings
from .db import Database
from .hardening import PersonnelGuardMiddleware
from .workflow_api import build_workflow_router
from .workflow_center import ensure_workflow_schema
from .workflow_runner import workflow_loop

settings = load_settings()
db = Database(settings.data_dir / "personalplaner.sqlite3")
db.initialize()
ensure_automation_schema(db)
ensure_workflow_schema(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    automation_task = asyncio.create_task(automation_loop(db, settings, stop), name="pp-automation-engine")
    workflow_task = asyncio.create_task(workflow_loop(db, settings, stop), name="pp-workflow-center")
    app.state.automation_stop = stop
    app.state.automation_task = automation_task
    app.state.workflow_task = workflow_task
    try:
        yield
    finally:
        stop.set()
        for task in (automation_task, workflow_task):
            try:
                await asyncio.wait_for(task, timeout=5)
            except (TimeoutError, asyncio.CancelledError):
                task.cancel()


app = FastAPI(title="PP – Personalplaner", version="0.4.0", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.add_middleware(PersonnelGuardMiddleware, db=db, settings=settings)
app.include_router(build_router(db, settings))
app.include_router(build_admin_settings_router(db, settings))
app.include_router(build_admin_maintenance_router(db, settings))
app.include_router(build_automation_router(db, settings))
app.include_router(build_workflow_router(db, settings))

STATIC = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


if __name__ == "__main__":
    uvicorn.run("pp.server:app", host=settings.host, port=settings.port, reload=False)
