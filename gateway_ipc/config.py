from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class IpcClientConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    connect_timeout_s: float = 2.0
    reconnect_delay_s: float = 1.0
    read_limit_bytes: int = 65536
    framing: str = "newline"
    enabled: bool = True
    ack_timeout_s: float = 2.0
    ack_retries: int = 3

    @classmethod
    def from_env(cls) -> "IpcClientConfig":
        return cls(
            host=os.environ.get("GATEWAY_CORE_IPC_HOST", cls.host),
            port=int(os.environ.get("GATEWAY_CORE_IPC_PORT", str(cls.port))),
            connect_timeout_s=float(os.environ.get("GATEWAY_CORE_IPC_CONNECT_TIMEOUT", str(cls.connect_timeout_s))),
            reconnect_delay_s=float(os.environ.get("GATEWAY_CORE_IPC_RECONNECT_DELAY", str(cls.reconnect_delay_s))),
            read_limit_bytes=int(os.environ.get("GATEWAY_CORE_IPC_READ_LIMIT", str(cls.read_limit_bytes))),
            framing=os.environ.get("GATEWAY_CORE_IPC_FRAMING", cls.framing),
            enabled=os.environ.get("GATEWAY_CORE_IPC_ENABLED", "true").lower() not in {"0", "false", "no", "off"},
            ack_timeout_s=float(os.environ.get("GATEWAY_CORE_IPC_ACK_TIMEOUT", str(cls.ack_timeout_s))),
            ack_retries=int(os.environ.get("GATEWAY_CORE_IPC_ACK_RETRIES", str(cls.ack_retries))),
        )
