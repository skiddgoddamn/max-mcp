import os
import pathlib
import subprocess
import sys
import tempfile


class FileQrHandler:
    """QR handler for MAX device-link login.

    Renders the login link as an SVG file and opens it in the default viewer,
    instead of printing block-character ASCII to the terminal — the latter
    raises UnicodeEncodeError on a Windows cp1251 console (\\u2588 is
    unencodable). The raw link is always printed to stderr as a fallback.
    """

    def __init__(self, out_dir: str | None = None) -> None:
        self._dir = pathlib.Path(out_dir or tempfile.gettempdir())

    async def show_qr(self, qr_url: str) -> None:
        print(f"MAX login link: {qr_url}", file=sys.stderr, flush=True)
        try:
            import qrcode
            import qrcode.image.svg

            img = qrcode.make(qr_url, image_factory=qrcode.image.svg.SvgImage)
            path = self._dir / "max-login-qr.svg"
            img.save(str(path))
            print(f"QR image: {path}", file=sys.stderr, flush=True)
            _open(path)
        except Exception as e:  # rendering is best-effort; the link still works
            print(
                f"(couldn't render QR image: {e}; scan the link above)",
                file=sys.stderr,
                flush=True,
            )


def _open(path: pathlib.Path) -> None:
    try:
        if hasattr(os, "startfile"):
            os.startfile(str(path))  # type: ignore[attr-defined]  # Windows
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass
