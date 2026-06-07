from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"


def _reexec_in_venv() -> None:
    if not VENV_PYTHON.exists():
        return
    if Path(sys.prefix).resolve() == (ROOT / ".venv").resolve():
        return
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])


_reexec_in_venv()

try:
    import uvicorn
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing Python dependency. Run once:\n"
        "  python3 -m venv .venv\n"
        "  . .venv/bin/activate\n"
        "  pip install -e .\n"
        "Then run:\n"
        "  python3 main.py"
    ) from exc


if __name__ == "__main__":
    host = os.environ.get("GATEWAY_HUB_HOST", "0.0.0.0")
    port = int(os.environ.get("GATEWAY_HUB_PORT", "8000"))
    uvicorn.run("web_console.main:app", host=host, port=port, reload=False)
