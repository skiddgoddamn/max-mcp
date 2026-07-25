"""Localhost login page for MAX device-link auth.

MAX QR links expire (~2 min) and pymax neither regenerates them nor has a way to
collect a 2FA cloud password without a TTY. This serves the whole flow on
http://127.0.0.1:<port>:

* an auto-refreshing QR (RefreshingQrAuthFlow requests a fresh link on expiry),
* and, if the account has a 2FA password, an input field on the same page.

The password is POSTed to localhost only — it never leaves the machine.
"""
from __future__ import annotations

import http.server
import io
import os
import sys
import threading
import time
import urllib.parse
from typing import TYPE_CHECKING

from pymax.auth.models import AuthResult
from pymax.auth.qr import QrAuthFlow
from pymax.logging import get_logger

if TYPE_CHECKING:
    from pymax.app import App

logger = get_logger(__name__)

HOST = "127.0.0.1"
PORT = int(os.environ.get("MAX_MCP_QR_PORT", "5199"))
LOGIN_DEADLINE_S = int(os.environ.get("MAX_MCP_QR_TIMEOUT", "600"))

# status: waiting | pending | password | verifying | open
_state = {"qr": None, "status": "waiting", "hint": None}
_password = {"value": None}
_lock = threading.Lock()

_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MAX — привязка устройства</title>
<style>
 :root{color-scheme:dark}
 body{font-family:system-ui,Segoe UI,Roboto,sans-serif;background:#0f0f14;color:#eaeaf0;
   margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center}
 .card{background:#17171f;padding:32px 36px;border-radius:18px;text-align:center;
   box-shadow:0 12px 48px #000a;max-width:420px}
 h1{font-size:17px;font-weight:600;margin:0 0 20px;line-height:1.4}
 .frame{width:320px;min-height:320px;margin:0 auto;background:#fff;border-radius:14px;
   display:flex;align-items:center;justify-content:center;overflow:hidden}
 .frame img{width:300px;height:300px}
 .ok{font-size:72px;line-height:320px}
 .st{color:#9a9aae;font-size:14px;margin:18px 0 0}
 .hint{color:#7a7a8e;font-size:12px;margin:8px 0 0}
 form{display:flex;flex-direction:column;gap:12px;padding:22px;width:82%}
 form .lbl{color:#333;font-size:14px}
 form input{padding:11px;font-size:16px;border:1px solid #bbb;border-radius:8px}
 form button{padding:11px;font-size:15px;border:0;border-radius:8px;background:#3b7;color:#fff;cursor:pointer}
</style></head>
<body><div class="card">
 <h1 id="h">MAX &rarr; Настройки &rarr; Устройства &rarr; Привязать устройство &rarr; сканировать</h1>
 <div class="frame" id="frame"><span class="st">Ожидание QR…</span></div>
 <p class="st" id="st">Ожидание QR…</p>
 <p class="hint">QR обновляется автоматически. Пароль (если запросит) уходит только на localhost.</p>
</div>
<script>
let mode=null;
function esc(s){return (s||'').replace(/[<>&"]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]));}
async function tick(){
 try{
  const s=await (await fetch('/state',{cache:'no-store'})).json();
  const frame=document.getElementById('frame'), st=document.getElementById('st');
  if(s.status==='open'){ if(mode!=='open'){mode='open';frame.innerHTML='<div class="ok">✅</div>';} st.textContent='Подключено — можно закрыть вкладку.'; return; }
  if(s.status==='password'){
   if(mode!=='password'){ mode='password';
    frame.innerHTML='<form id="pf"><div class="lbl">Облачный пароль (2FA)'+(s.hint?': '+esc(s.hint):'')+'</div><input id="pw" type="password" autocomplete="off" autofocus><button>Отправить</button></form>';
    document.getElementById('pf').onsubmit=async e=>{e.preventDefault();const v=document.getElementById('pw').value;
     await fetch('/password',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'password='+encodeURIComponent(v)});
     mode='verifying';document.getElementById('frame').innerHTML='<span class="st">Проверка пароля…</span>';};
   }
   st.textContent='Требуется пароль двухфакторной защиты.';
  }
  else if(s.status==='verifying'){ if(mode!=='verifying'){mode='verifying';frame.innerHTML='<span class="st">Проверка…</span>';} st.textContent='Проверка…'; }
  else if(s.hasQr){ mode='qr'; frame.innerHTML='<img alt="QR" src="/qr.svg?t='+Date.now()+'">'; st.textContent='QR активен, обновляется автоматически.'; }
  else{ st.textContent='Ожидание QR…'; }
 }catch(e){}
 setTimeout(tick,2000);
}
tick();
</script></body></html>""".encode("utf-8")


def _render_svg(link: str) -> bytes:
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(link, image_factory=qrcode.image.svg.SvgImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue()


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):  # silence access log
        pass

    def do_GET(self):
        route = self.path.split("?", 1)[0]
        if route == "/":
            self._send(200, "text/html; charset=utf-8", _PAGE)
        elif route == "/state":
            with _lock:
                has = "true" if _state["qr"] else "false"
                hint = _state["hint"]
                status = _state["status"]
            hint_json = "null" if hint is None else '"' + hint.replace('"', "'") + '"'
            body = f'{{"status":"{status}","hasQr":{has},"hint":{hint_json}}}'.encode()
            self._send(200, "application/json", body)
        elif route == "/qr.svg":
            with _lock:
                link = _state["qr"]
            if not link:
                self._send(204, "text/plain", b"")
                return
            try:
                self._send(200, "image/svg+xml", _render_svg(link))
            except Exception:
                self._send(500, "text/plain", b"")
        else:
            self._send(404, "text/plain", b"")

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/password":
            self._send(404, "text/plain", b"")
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        pw = urllib.parse.parse_qs(raw).get("password", [""])[0]
        with _lock:
            _password["value"] = pw
            _state["status"] = "verifying"
        self._send(200, "application/json", b'{"ok":true}')

    def _send(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)


class LocalQrServer:
    """Serves the login QR (and 2FA password prompt) on a localhost page."""

    def __init__(self) -> None:
        self._httpd: http.server.ThreadingHTTPServer | None = None
        self._opened = False

    def _ensure(self) -> None:
        if self._httpd is not None:
            return
        try:
            http.server.ThreadingHTTPServer.allow_reuse_address = True
            self._httpd = http.server.ThreadingHTTPServer((HOST, PORT), _Handler)
        except OSError as e:
            logger.warning("QR server not started (%s)", e)
            self._httpd = None
            return
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        logger.info("Login page live at http://%s:%s", HOST, PORT)

    async def show_qr(self, qr_link: str) -> None:
        with _lock:
            _state["qr"] = qr_link
            _state["status"] = "pending"
            _state["hint"] = None
        self._ensure()
        print(f"MAX login link: {qr_link}", file=sys.stderr, flush=True)
        if not self._opened:
            self._opened = True
            try:
                import webbrowser

                webbrowser.open(f"http://{HOST}:{PORT}")
            except Exception:
                pass

    def request_password(self, hint: str | None) -> None:
        with _lock:
            _state["status"] = "password"
            _state["hint"] = hint
            _state["qr"] = None
            _password["value"] = None

    def take_password(self) -> str | None:
        with _lock:
            v = _password["value"]
            _password["value"] = None
            return v

    def connected(self) -> None:
        with _lock:
            _state["status"] = "open"
            _state["qr"] = None
            _password["value"] = None

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd = None


class LocalPasswordProvider:
    """PasswordProvider that collects the 2FA password from the localhost page."""

    def __init__(self, server: LocalQrServer) -> None:
        self._server = server

    async def get_password(self, hint: str | None = None) -> str:
        import asyncio

        self._server.request_password(hint)
        deadline = time.time() + LOGIN_DEADLINE_S
        while time.time() < deadline:
            pw = self._server.take_password()
            if pw:
                return pw
            await asyncio.sleep(0.5)
        raise RuntimeError("2FA password not entered in time")


class RefreshingQrAuthFlow(QrAuthFlow):
    """QR auth that regenerates the link when it expires instead of giving up."""

    async def authenticate(self, app: App) -> AuthResult:
        logger.info("starting qr authentication (auto-refresh)")
        deadline = time.time() + LOGIN_DEADLINE_S
        qr_info = None
        while time.time() < deadline:
            qr_info = await app.api.auth.request_qr()
            await self.qr_provider.show_qr(qr_info.qr_link)
            if await self._poll_qr(app, qr_info):
                break
            logger.info("QR expired; regenerating")
        else:
            raise RuntimeError("QR login timed out — nobody scanned in time")

        result = await app.api.auth.confirm_qr(qr_info.track_id)
        token = result.login_token
        if not token and result.password_challenge:
            token = await self._authenticate_with_password(
                app,
                track_id=result.password_challenge.track_id,
                hint=result.password_challenge.hint,
            )
        return AuthResult(token=token)
