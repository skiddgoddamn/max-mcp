"""Platform-aware hardening of the session directory and the secrets inside it.

POSIX keeps the original model: a 0700 directory, 0600 files, ``O_NOFOLLOW``
opens and an owner check. Windows has neither uid nor mode bits — ``os.getuid``
does not exist there and ``st_mode`` always looks world-readable — so the same
intent is expressed with ACLs: inheritance is stripped and only the current
account is granted access (``icacls``), and the check refuses a directory whose
DACL still hands access to a broad principal such as Everyone or Users.

The Windows ACL check is read through ``icacls /save``, which emits SDDL with
raw SIDs, so it does not depend on the locale of the account names.
"""

from __future__ import annotations

import os
import pathlib
import re
import stat
import subprocess
import sys
import tempfile

IS_WINDOWS = os.name == "nt"

_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_BINARY = getattr(os, "O_BINARY", 0)
_O_NOINHERIT = getattr(os, "O_NOINHERIT", 0)

# Well-known SIDs (and their SDDL aliases) that must never hold an ACE on the
# session directory — each of them would let another account read the session.
_BROAD_SIDS = {
    "WD", "S-1-1-0",        # Everyone
    "AU", "S-1-5-11",       # Authenticated Users
    "BU", "S-1-5-32-545",   # BUILTIN\Users
    "IU", "S-1-5-4",        # Interactive
    "NU", "S-1-5-2",        # Network
    "AN", "S-1-5-7",        # Anonymous
    "DU",                   # Domain Users
    "GU",                   # Domain Guests
}

_ACE_RE = re.compile(r"\(([^)]*)\)")


def _warn(msg: str) -> None:
    print(f"max-mcp: {msg}", file=sys.stderr)


def is_link(path: pathlib.Path) -> bool:
    """True for a POSIX symlink or a Windows symlink/junction (reparse point)."""
    try:
        st = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _current_principal() -> str | None:
    """``DOMAIN\\user`` for the current account, as icacls expects it."""
    p = _run(["whoami"])
    if p is not None and p.returncode == 0 and p.stdout.strip():
        return p.stdout.strip()
    user = os.environ.get("USERNAME")
    if not user:
        return None
    domain = os.environ.get("USERDOMAIN")
    return f"{domain}\\{user}" if domain else user


def _windows_harden(path: pathlib.Path) -> None:
    """Drop inherited ACEs and grant only the current account. Best effort."""
    principal = _current_principal()
    if not principal:
        _warn(f"cannot determine the current account; ACLs on {path} left as they are")
        return
    grant = f"{principal}:(OI)(CI)F" if path.is_dir() else f"{principal}:F"
    p = _run(["icacls", str(path), "/inheritance:r", "/grant:r", grant])
    if p is None:
        _warn(f"icacls is unavailable; ACLs on {path} left as they are")
    elif p.returncode != 0:
        _warn(f"icacls failed on {path}: {(p.stderr or p.stdout).strip()}")


def _decode_sddl(data: bytes) -> str:
    """icacls writes UTF-16LE, usually without a BOM — plain 'utf-16' would choke."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-16-le", errors="replace")
    except UnicodeError:
        return data.decode("utf-8", errors="replace")


def _windows_dacl_sids(path: pathlib.Path) -> list[str] | None:
    """SIDs referenced by the object's DACL, or None if the ACL cannot be read."""
    with tempfile.TemporaryDirectory(prefix="max-mcp-acl-") as tmpdir:
        out = pathlib.Path(tmpdir) / "acl.sddl"
        p = _run(["icacls", str(path), "/save", str(out)])
        if p is None or p.returncode != 0 or not out.exists():
            return None
        raw = _decode_sddl(out.read_bytes())

    sids: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("D:"):
            continue
        for ace in _ACE_RE.findall(line):
            parts = ace.split(";")
            if len(parts) >= 6 and parts[5].strip():
                sids.append(parts[5].strip().upper())
    return sids


def ensure_dir(path: pathlib.Path) -> None:
    """Create the session directory if needed and restrict it to this account."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if is_link(path):
        raise RuntimeError(f"{path} is a symlink; refusing to use")

    if IS_WINDOWS:
        _windows_harden(path)
        return

    st = path.lstat()
    if st.st_uid != os.getuid():
        raise RuntimeError(f"{path} is not owned by current user")
    if st.st_mode & 0o077:
        path.chmod(0o700)


def check_dir(path: pathlib.Path) -> None:
    """Refuse to start if the session directory is reachable by anyone else."""
    if is_link(path):
        raise RuntimeError(f"{path} is a symlink; refusing to use")

    if IS_WINDOWS:
        sids = _windows_dacl_sids(path)
        if sids is None:
            _warn(f"could not read the ACL of {path}; skipping the permission check")
            return
        broad = sorted({s for s in sids if s in _BROAD_SIDS})
        if broad:
            raise RuntimeError(
                f"{path} grants access to {', '.join(broad)}; re-run the login "
                "command to restrict it to your account"
            )
        return

    st = path.lstat()
    if st.st_uid != os.getuid():
        raise RuntimeError(f"{path} is not owned by current user")
    if st.st_mode & 0o077:
        raise RuntimeError(
            f"{path} permissions too open ({oct(st.st_mode & 0o777)}); tighten to 0700"
        )


def harden_file(path: pathlib.Path) -> None:
    """Restrict a single secret file to this account."""
    if is_link(path):
        raise RuntimeError(f"{path} is a symlink; refusing to harden the target")
    if IS_WINDOWS:
        _windows_harden(path)
        return
    path.chmod(0o600)


def write_secret(path: pathlib.Path, data: str) -> None:
    """Write a secret without following a symlink planted in its place."""
    if is_link(path):
        path.unlink()
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _O_NOFOLLOW | _O_BINARY | _O_NOINHERIT
    fd = os.open(str(path), flags, 0o600)
    try:
        os.write(fd, data.encode("utf-8"))
    finally:
        os.close(fd)
    harden_file(path)


def read_secret(path: pathlib.Path) -> str | None:
    """Read a secret written by :func:`write_secret`, or None if it is absent."""
    if not path.exists():
        return None
    if is_link(path):
        raise RuntimeError(f"{path} is a symlink; refusing to read")
    fd = os.open(str(path), os.O_RDONLY | _O_NOFOLLOW | _O_BINARY)
    try:
        data = os.read(fd, 4096)
    finally:
        os.close(fd)
    return data.decode("utf-8").strip()
