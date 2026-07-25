import argparse
import asyncio
import pathlib
import sys

from pymax import (
    Client,
    ConsolePasswordProvider,
    ConsoleSmsCodeProvider,
    ExtraConfig,
    WebClient,
)

from . import secure
from .net import configure_proxy
from .qr_server import LocalPasswordProvider, LocalQrServer, RefreshingQrAuthFlow

SESSION_DIR = pathlib.Path.home() / ".max-mcp"
SESSION_FILE = "session.db"
KIND_FILE = "session.kind"
PHONE_FILE = "session.phone"


def _mark_session(kind: str, phone: str | None = None) -> None:
    secure.write_secret(SESSION_DIR / KIND_FILE, kind)
    if phone:
        secure.write_secret(SESSION_DIR / PHONE_FILE, phone)


def _print_me(c) -> None:
    me = c.me
    print(
        f"Logged in as: {getattr(me, 'first_name', '?')} (id={getattr(me, 'id', '?')})",
        file=sys.stderr,
    )


async def _start_until_logged_in(client, logged_in: asyncio.Event) -> None:
    """Run the login flow, tolerating the cancellation that shutdown leaks.

    ``on_start`` calls ``client.stop()`` the moment the login succeeds, which
    cancels the WebSocket reader that ``client.start()`` is still awaiting; the
    cancellation then surfaces here even though the session is already on disk
    (upstream issue #1), leaving ``session.kind`` unwritten. It is swallowed
    only once the login has been confirmed and only when this task was not
    cancelled from the outside.
    """
    try:
        await client.start()
    except asyncio.CancelledError:
        task = asyncio.current_task()
        cancelled_externally = task is not None and task.cancelling() > 0
        if cancelled_externally or not logged_in.is_set():
            raise


async def _login_qr() -> None:
    secure.ensure_dir(SESSION_DIR)
    server = LocalQrServer()
    client = WebClient(
        work_dir=str(SESSION_DIR),
        session_name=SESSION_FILE,
        auth_flow=RefreshingQrAuthFlow(server, LocalPasswordProvider(server)),
        extra_config=ExtraConfig(proxy=configure_proxy()),
    )
    logged_in = asyncio.Event()

    @client.on_start()
    async def _ready(c: WebClient) -> None:
        _print_me(c)
        server.connected()
        logged_in.set()
        await c.stop()

    try:
        await _start_until_logged_in(client, logged_in)
        secure.harden_file(SESSION_DIR / SESSION_FILE)
        _mark_session("web")
        await asyncio.sleep(2)  # let the browser show the "connected" state
    finally:
        server.stop()


async def _login_sms(phone: str) -> None:
    secure.ensure_dir(SESSION_DIR)
    client = Client(
        phone=phone,
        work_dir=str(SESSION_DIR),
        session_name=SESSION_FILE,
        sms_code_provider=ConsoleSmsCodeProvider(),
        password_provider=ConsolePasswordProvider(),
        extra_config=ExtraConfig(proxy=configure_proxy()),
    )
    logged_in = asyncio.Event()

    @client.on_start()
    async def _ready(c: Client) -> None:
        _print_me(c)
        logged_in.set()
        await c.stop()

    await _start_until_logged_in(client, logged_in)
    secure.harden_file(SESSION_DIR / SESSION_FILE)
    _mark_session("sms", phone=phone)


def main() -> None:
    p = argparse.ArgumentParser(prog="max-mcp.auth")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login-qr", help="Scan QR with MAX mobile app")
    sms = sub.add_parser("login-sms", help="Phone + SMS code (works without phone app)")
    sms.add_argument("--phone", required=True, help="E.164 phone, e.g. +79991234567")
    sub.add_parser("login", help="Alias of login-qr (deprecated)")
    args = p.parse_args()

    if args.cmd in ("login-qr", "login"):
        asyncio.run(_login_qr())
    elif args.cmd == "login-sms":
        asyncio.run(_login_sms(args.phone))


if __name__ == "__main__":
    main()
