from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .engine_client import EngineClient
from .routes import router


app = FastAPI(title="MetaCrust Gateway")
app.add_middleware(SessionMiddleware, secret_key="change-this-for-production")
app.state.engine_client = EngineClient()
app.mount("/static", StaticFiles(directory="web_console/static"), name="static")
app.include_router(router)

