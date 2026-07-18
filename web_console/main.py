from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from gateway_edge_server import EdgeServerTask
from gateway_forwarding import ForwardingService
from gateway_ipc import GatewayCoreIpcTask

from .engine_client import EngineClient
from .routes import load_saved_edge_server_config, load_saved_sensor_configs, router, send_saved_sensor_configs_to_core


PACKAGE_DIR = Path(__file__).resolve().parent
LOGGER = logging.getLogger("edge_server")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ipc_task = GatewayCoreIpcTask()
    edge_server_task = EdgeServerTask()
    forwarding_service = ForwardingService(core_ipc=ipc_task)
    app.state.core_ipc = ipc_task
    app.state.edge_server = edge_server_task
    app.state.forwarding = forwarding_service
    loaded_configs = load_saved_sensor_configs()
    edge_config = load_saved_edge_server_config()
    ipc_task.start()
    LOGGER.info("hub_lifespan edge_server_starting")
    edge_server_task.start(edge_config)
    forwarding_service.start()
    LOGGER.info("hub_lifespan forwarding_started gateway_id=%s", forwarding_service.gateway_id)
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
        await forwarding_service.stop()
        LOGGER.info("hub_lifespan forwarding_stopped")
        await edge_server_task.stop()
        LOGGER.info("hub_lifespan edge_server_stopped")
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
