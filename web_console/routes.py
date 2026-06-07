from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates


router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


def _primary_sections(active_label: str) -> list[dict[str, object]]:
    items = [
        ("Overview", "Over", "/dashboard"),
        ("Monitor", "Mon", "/monitor"),
        ("Insights", "Info", "/insights"),
        ("Interfaces", "I/O", "/interfaces"),
        ("Data Forwarding", "Fwd", "/forwarding"),
        ("Connectivity", "Conn", "/connectivity"),
        ("System", "Sys", "/system"),
    ]
    return [
        {
            "label": label,
            "compact": compact,
            "href": href,
            "active": label == active_label,
            "disabled": False,
        }
        for label, compact, href in items
    ]


def _is_authenticated(request: Request) -> bool:
    return bool(request.session.get("authenticated"))


@router.get("/", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "login.html",
        {"product_name": "MetaCrust Edge Gateway", "page_title": "Login"},
    )


@router.post("/api/login")
async def login_action(request: Request) -> JSONResponse:
    payload = await request.json()
    username = str(payload.get("username", ""))
    password = str(payload.get("password", ""))
    if username == "gateway" and password == "gateway":
        request.session["authenticated"] = True
        request.session["username"] = username
        return JSONResponse({"ok": True, "redirect": "/dashboard"})
    return JSONResponse({"ok": False, "message": "Invalid credentials."}, status_code=status.HTTP_401_UNAUTHORIZED)


@router.post("/logout")
async def logout_action(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request) -> HTMLResponse:
    if not _is_authenticated(request):
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "product_name": "MetaCrust Edge Gateway",
            "page_title": "Dashboard",
            "primary_sections": _primary_sections("Overview"),
            "status_chips": [],
            "connectivity_items": [],
            "runtime_snapshot": {"runtime_state": "external_engine", "workers": []},
            "uptime": "-",
            "disk": {"pct": 0, "used_gb": 0, "total_gb": 0},
        },
    )


@router.get("/api/engine/health")
async def engine_health(request: Request) -> JSONResponse:
    client = request.app.state.engine_client
    return JSONResponse(await client.health())

