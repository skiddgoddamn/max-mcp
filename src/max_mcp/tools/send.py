import os
import pathlib
import stat
import tempfile
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from .. import secure
from ..client import AppCtx
from ..normalize import message_to_dict

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".webm"}

MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB hard cap

_HOME = pathlib.Path.home().resolve()
_TMP = pathlib.Path(tempfile.gettempdir())
_DEFAULT_ROOTS = (_HOME / "Downloads", _HOME / "Documents", _TMP)
_DENY_ROOTS = (
    _HOME / ".max-mcp",
    _HOME / ".ssh",
    _HOME / ".aws",
    _HOME / ".gnupg",
    _HOME / ".config",
    _HOME / ".kube",
    _HOME / ".docker",
    _HOME / "Library" / "Keychains",
    _HOME / "AppData" / "Roaming" / "Microsoft" / "Crypto",
    pathlib.Path(os.environ.get("SystemRoot", r"C:\Windows")) if secure.IS_WINDOWS else pathlib.Path("/etc"),
    pathlib.Path("/private/etc"),
    pathlib.Path("/var"),
    pathlib.Path("/private/var"),
)


def _allowed_roots() -> tuple[pathlib.Path, ...]:
    """Roots a file may be sent from — ``MAX_MCP_SEND_ROOTS`` overrides the defaults.

    The separator is the platform's own (``:`` on POSIX, ``;`` on Windows,
    where a bare ``:`` would split every drive letter off its path).
    """
    env = os.environ.get("MAX_MCP_SEND_ROOTS")
    if not env:
        return tuple(p.resolve() for p in _DEFAULT_ROOTS if p.exists())
    roots: list[pathlib.Path] = []
    for raw in env.split(os.pathsep):
        raw = raw.strip()
        if not raw:
            continue
        roots.append(pathlib.Path(raw).expanduser().resolve())
    return tuple(roots)


def _is_within(child: pathlib.Path, parent: pathlib.Path) -> bool:
    # normcase so that C:\Users and c:\users are the same root on Windows
    c = pathlib.PurePath(os.path.normcase(str(child)))
    p = pathlib.PurePath(os.path.normcase(str(parent)))
    try:
        c.relative_to(p)
    except ValueError:
        return False
    return True


def _validate_path(file_path: str) -> pathlib.Path:
    if not isinstance(file_path, str) or not file_path:
        raise ValueError("file_path must be a non-empty string")
    if "\x00" in file_path:
        raise ValueError("file_path contains NUL byte")

    path = pathlib.Path(file_path).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as e:
        raise ValueError(f"file_path does not resolve: {e}") from e

    # Reject links at the leaf to prevent confused-deputy redirection
    if secure.is_link(path):
        raise ValueError("symlinks are not allowed as file_path")

    st = resolved.lstat()
    if not stat.S_ISREG(st.st_mode):
        raise ValueError("file_path must point to a regular file")

    if st.st_size > MAX_FILE_BYTES:
        raise ValueError(f"file exceeds {MAX_FILE_BYTES} bytes")

    for deny in _DENY_ROOTS:
        try:
            deny_r = deny.resolve()
        except OSError:
            continue
        if _is_within(resolved, deny_r):
            raise PermissionError(f"path is under denied root: {deny}")

    roots = _allowed_roots()
    if not roots:
        raise PermissionError(
            "no allowed roots configured; set MAX_MCP_SEND_ROOTS=/path1:/path2"
        )
    if not any(_is_within(resolved, r) for r in roots):
        raise PermissionError(
            f"path is outside allowed roots: {[str(r) for r in roots]}"
        )
    return resolved


def _attachment(path: pathlib.Path):
    from pymax import File, Photo, Video

    ext = path.suffix.lower()
    if ext in PHOTO_EXT:
        return Photo(path=str(path))
    if ext in VIDEO_EXT:
        return Video(path=str(path))
    return File(path=str(path))


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def send_message(
        ctx: Context[ServerSession, AppCtx],
        chat_id: int,
        text: str,
        reply_to_id: int | None = None,
    ) -> dict[str, Any]:
        """Send a text message to a MAX chat. Optionally reply to a message."""
        client = ctx.request_context.lifespan_context.client
        sent = await client.send_message(
            chat_id=chat_id, text=text, reply_to=reply_to_id
        )
        return message_to_dict(sent)

    @mcp.tool()
    async def send_file(
        ctx: Context[ServerSession, AppCtx],
        chat_id: int,
        file_path: str,
        caption: str | None = None,
    ) -> dict[str, Any]:
        """Send a file/photo/video to a MAX chat. Attachment type picked by extension.

        file_path must be a real file inside one of the allowed roots
        (default: ~/Downloads, ~/Documents, the system temp dir; override via
        MAX_MCP_SEND_ROOTS env var, separated by os.pathsep — ':' on POSIX,
        ';' on Windows). Symlinks are rejected; paths under ~/.ssh, ~/.aws,
        ~/.max-mcp, /etc, /var (C:\\Windows on Windows) are denied.
        """
        path = _validate_path(file_path)
        client = ctx.request_context.lifespan_context.client
        att = _attachment(path)
        sent = await client.send_message(
            chat_id=chat_id, text=caption or "", attachments=[att]
        )
        return message_to_dict(sent)
