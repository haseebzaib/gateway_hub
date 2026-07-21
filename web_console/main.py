from __future__ import annotations

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
from .network_runtime import RUNTIME as network_runtime
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
    load_saved_sensor_configs()
    edge_config = load_saved_edge_server_config()
    # Resync the saved rs232/rs485/modbus_tcp config to gateway_core every time the
    # IPC connection is (re)established — not just once at hub startup. gateway_core
    # keeps no local copy of sensor config (see sensorprocess.cpp: it starts with
    # empty runtimes and waits for this over IPC), so without this hook it would
    # silently never get configured whenever it connects after a short startup
    # window, or reconnects after a restart/crash.
    ipc_task.on_connected = lambda: send_saved_sensor_configs_to_core(ipc_task)
    ipc_task.start()
    LOGGER.info("hub_lifespan edge_server_starting")
    edge_server_task.start(edge_config)
    forwarding_service.start()
    LOGGER.info("hub_lifespan forwarding_started gateway_id=%s", forwarding_service.gateway_id)
    await network_runtime.start()
    app.state.network_runtime = network_runtime
    try:
        yield
    finally:
        await network_runtime.stop()
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
