# Gateway Core IPC

Python TCP client for communication with the C++ `gateway_core` process.

The C++ side owns the server socket. `gateway_hub` connects as a client and
keeps reconnecting until the core is available.

Current implementation is intentionally schema-neutral. Message pattern can be
decided later. The default framing is newline-delimited UTF-8 text because it is
easy to test manually.

Environment variables:

```text
GATEWAY_CORE_IPC_ENABLED=true
GATEWAY_CORE_IPC_HOST=127.0.0.1
GATEWAY_CORE_IPC_PORT=8765
GATEWAY_CORE_IPC_FRAMING=newline
GATEWAY_CORE_IPC_CONNECT_TIMEOUT=2.0
GATEWAY_CORE_IPC_RECONNECT_DELAY=1.0
GATEWAY_CORE_IPC_READ_LIMIT=65536
```

Test endpoints in the web app:

```text
GET  /api/core-ipc/status
POST /api/core-ipc/send {"message":"ping"}
```
