import os
import pathlib

import pytest

from max_mcp import secure
from max_mcp.tools import send


def test_env_roots_split_on_the_platform_separator(tmp_path, monkeypatch):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    monkeypatch.setenv("MAX_MCP_SEND_ROOTS", os.pathsep.join([str(a), str(b)]))

    roots = send._allowed_roots()

    # on Windows a bare ':' split "C:\..." into "C" and "\..." and lost both roots
    assert set(roots) == {a.resolve(), b.resolve()}


def test_file_inside_an_allowed_root_is_accepted(tmp_path, monkeypatch):
    root = tmp_path / "outbox"
    root.mkdir()
    f = root / "report.pdf"
    f.write_bytes(b"%PDF-1.4")
    monkeypatch.setenv("MAX_MCP_SEND_ROOTS", str(root))

    assert send._validate_path(str(f)) == f.resolve()


def test_file_outside_the_allowed_roots_is_refused(tmp_path, monkeypatch):
    root = tmp_path / "outbox"
    root.mkdir()
    monkeypatch.setenv("MAX_MCP_SEND_ROOTS", str(root))
    outsider = tmp_path / "secret.txt"
    outsider.write_text("nope")

    with pytest.raises(PermissionError, match="outside allowed roots"):
        send._validate_path(str(outsider))


def test_case_differing_root_still_matches_on_windows(tmp_path, monkeypatch):
    if not secure.IS_WINDOWS:
        pytest.skip("case-insensitive matching is a Windows concern")
    root = tmp_path / "Outbox"
    root.mkdir()
    f = root / "a.txt"
    f.write_text("x")
    monkeypatch.setenv("MAX_MCP_SEND_ROOTS", str(root).lower())

    assert send._validate_path(str(f)) == f.resolve()


def test_directory_is_not_a_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_MCP_SEND_ROOTS", str(tmp_path))
    d = tmp_path / "dir"
    d.mkdir()

    with pytest.raises(ValueError, match="regular file"):
        send._validate_path(str(d))


def test_denied_root_wins_over_an_allowed_root(tmp_path, monkeypatch):
    denied = pathlib.Path.home() / ".max-mcp"
    if not denied.exists():
        pytest.skip("no ~/.max-mcp on this machine")
    f = denied / "session.db"
    if not f.exists():
        pytest.skip("no session file to test against")
    monkeypatch.setenv("MAX_MCP_SEND_ROOTS", str(denied))

    with pytest.raises(PermissionError, match="denied root"):
        send._validate_path(str(f))
