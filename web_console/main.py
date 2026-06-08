from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from gateway_ipc import GatewayCoreIpcTask

from .engine_client import EngineClient
from .routes import router


PACKAGE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ipc_task = GatewayCoreIpcTask()
    app.state.core_ipc = ipc_task
    ipc_task.start()
    try:
        yield
    finally:
        await ipc_task.stop()


app = FastAPI(title="MetaCrust Gateway", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key="change-this-for-production")
app.state.engine_client = EngineClient()
app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
app.include_router(router)
