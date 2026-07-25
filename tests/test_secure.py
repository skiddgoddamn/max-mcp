import os
import pathlib

import pytest

from max_mcp import secure


def test_session_dir_roundtrip(tmp_path: pathlib.Path):
    d = tmp_path / ".max-mcp"
    secure.ensure_dir(d)
    secure.check_dir(d)  # must not raise on a freshly hardened directory

    secret = d / "session.kind"
    secure.write_secret(secret, "web")
    assert secure.read_secret(secret) == "web"


def test_write_secret_does_not_add_crlf(tmp_path: pathlib.Path):
    # os.open without O_BINARY translates \n on Windows and corrupts the value
    p = tmp_path / "session.phone"
    secure.write_secret(p, "+79991234567\n")
    assert p.read_bytes() == b"+79991234567\n"
    assert secure.read_secret(p) == "+79991234567"


def test_read_secret_missing_returns_none(tmp_path: pathlib.Path):
    assert secure.read_secret(tmp_path / "nope") is None


@pytest.mark.skipif(secure.IS_WINDOWS, reason="POSIX permission model")
def test_posix_dir_is_0700(tmp_path: pathlib.Path):
    d = tmp_path / ".max-mcp"
    secure.ensure_dir(d)
    assert (d.stat().st_mode & 0o777) == 0o700

    d.chmod(0o755)
    with pytest.raises(RuntimeError, match="too open"):
        secure.check_dir(d)


@pytest.mark.skipif(not secure.IS_WINDOWS, reason="Windows ACL model")
def test_windows_dacl_is_readable_and_narrow(tmp_path: pathlib.Path):
    d = tmp_path / ".max-mcp"
    secure.ensure_dir(d)

    sids = secure._windows_dacl_sids(d)
    if sids is None:
        pytest.skip("icacls unavailable")
    assert sids, "the hardened directory must still carry a DACL"
    assert not [s for s in sids if s in secure._BROAD_SIDS]


@pytest.mark.skipif(not secure.IS_WINDOWS, reason="Windows ACL model")
def test_windows_check_rejects_everyone(tmp_path: pathlib.Path):
    d = tmp_path / ".max-mcp"
    secure.ensure_dir(d)
    # S-1-1-0 is Everyone; granting it must make the check refuse to start
    os.system(f'icacls "{d}" /grant *S-1-1-0:(OI)(CI)R >nul 2>&1')

    if not [s for s in (secure._windows_dacl_sids(d) or []) if s in secure._BROAD_SIDS]:
        pytest.skip("could not widen the ACL in this environment")
    with pytest.raises(RuntimeError, match="grants access"):
        secure.check_dir(d)
