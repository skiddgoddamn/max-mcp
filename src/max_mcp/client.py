import asyncio
import pathlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp import FastMCP
from pymax import Client, WebClient

from . import secure

SESSION_DIR = pathlib.Path.home() / ".max-mcp"
SESSION_FILE = "session.db"
KIND_FILE = "session.kind"
PHONE_FILE = "session.phone"

LOGIN_QR = "python -m max_mcp.auth login-qr"
LOGIN_SMS = "python -m max_mcp.auth login-sms --phone +7..."


@dataclass
class AppCtx:
    client: Any  # WebClient | Client — both share the same public method surface


def _read_kind() -> tuple[str, str | None]:
    kind = secure.read_secret(SESSION_DIR / KIND_FILE) or "web"
    phone = secure.read_secret(SESSION_DIR / PHONE_FILE)
    return kind, phone


def _build_client():
    kind, phone = _read_kind()
    if kind == "sms":
        if not phone:
            raise RuntimeError(
                f"SMS session marker found but phone is missing. Re-login with: {LOGIN_SMS}"
            )
        return Client(
            phone=phone,
            work_dir=str(SESSION_DIR),
            session_name=SESSION_FILE,
        )
    return WebClient(work_dir=str(SESSION_DIR), session_name=SESSION_FILE)


@asynccontextmanager
async def lifespan(_server: FastMCP) -> AsyncIterator[AppCtx]:
    session_path = SESSION_DIR / SESSION_FILE
    if not session_path.exists():
        raise RuntimeError(
            "MAX session missing. Run one of:\n"
            f"  {LOGIN_QR}\n"
            f"  {LOGIN_SMS}"
        )
    secure.check_dir(SESSION_DIR)

    client = _build_client()
    ready = asyncio.Event()

    @client.on_start()
    async def _ready(_c) -> None:
        ready.set()

    task = asyncio.create_task(client.start())
    try:
        await asyncio.wait_for(ready.wait(), timeout=30)
        yield AppCtx(client=client)
    finally:
        try:
            await client.stop()
        except Exception:
            pass
        task.cancel()
