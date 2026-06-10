from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from gateway_ipc import GatewayCoreIpcTask

from .engine_client import EngineClient
from .routes import load_saved_sensor_configs, router, send_saved_sensor_configs_to_core


PACKAGE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ipc_task = GatewayCoreIpcTask()
    app.state.core_ipc = ipc_task
    loaded_configs = load_saved_sensor_configs()
    ipc_task.start()
    startup_send_task = asyncio.create_task(
        _send_loaded_configs_when_connected(ipc_task, loaded_configs),
        name="gateway-core-ipc-startup-config-send",
    )
    try:
        yield
    finally:
        startup_send_task.cancel()
        try:
            await startup_send_task
        except asyncio.CancelledError:
            pass
        await ipc_task.stop()


app = FastAPI(title="MetaCrust Gateway", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key="change-this-for-production")
app.state.engine_client = EngineClient()
app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
app.include_router(router)


async def _send_loaded_configs_when_connected(ipc_task: GatewayCoreIpcTask, loaded_configs: list[str]) -> None:
    if not loaded_configs:
        return

    for _ in range(200):
        if ipc_task.status.connected:
            break
        await asyncio.sleep(0.1)

    if not ipc_task.status.connected:
        print(f"[gateway-ipc] startup config send skipped, core not connected: {loaded_configs}", flush=True)
        return

    results = await send_saved_sensor_configs_to_core(ipc_task, loaded_configs)
    print(f"[gateway-ipc] startup config send results: {results}", flush=True)
