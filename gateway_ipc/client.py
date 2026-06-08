from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from .config import IpcClientConfig


class GatewayCoreTcpClient:
    def __init__(self, config: IpcClientConfig) -> None:
        self._config = config
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._write_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self._config.host, self._config.port),
            timeout=self._config.connect_timeout_s,
        )
        self._reader = reader
        self._writer = writer

    async def close(self) -> None:
        writer = self._writer
        self._reader = None
        self._writer = None
        if writer is None:
            return
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass

    async def send_bytes(self, payload: bytes) -> None:
        if self._writer is None:
            raise ConnectionError("Gateway core IPC is not connected.")
        async with self._write_lock:
            self._writer.write(payload)
            await self._writer.drain()

    async def send_text(self, message: str) -> None:
        payload = message.encode("utf-8")
        if self._config.framing == "newline" and not payload.endswith(b"\n"):
            payload += b"\n"
        await self.send_bytes(payload)

    async def read_messages(self) -> AsyncIterator[bytes]:
        if self._reader is None:
            raise ConnectionError("Gateway core IPC is not connected.")

        while True:
            if self._config.framing == "newline":
                payload = await self._reader.readline()
            else:
                payload = await self._reader.read(self._config.read_limit_bytes)
            if not payload:
                raise ConnectionError("Gateway core IPC disconnected.")
            yield payload
