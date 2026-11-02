"""A tiny local HTTP server for lecture videos with byte-range support.

Python's built-in ``http.server`` ignores ``Range`` headers, so browsers can't
seek in large videos served by it. This adds just enough of RFC 7233 (a single
``bytes=a-b`` range) for <video> seeking, plus CORS so the app on another
localhost port can play the files. It binds to 127.0.0.1 by default and only
serves files under the given root.
"""
from __future__ import annotations

import mimetypes
import os
import re
import urllib.parse
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_RANGE = re.compile(r"bytes=(\d*)-(\d*)$")
mimetypes.add_type("video/mp4", ".m4v")
mimetypes.add_type("text/vtt", ".vtt")
mimetypes.add_type("video/x-matroska", ".mkv")


def make_handler(root: Path):
    root = Path(root).resolve()

    class RangeHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Accept-Ranges", "bytes")
            super().end_headers()

        def list_directory(self, path):  # no directory listings
            self.send_error(HTTPStatus.NOT_FOUND)
            return None

        def _resolve(self) -> Path | None:
            rel = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path).lstrip("/")
            target = (root / rel).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                return None
            return target if target.is_file() else None

        def do_GET(self):
            self._serve(send_body=True)

        def do_HEAD(self):
            self._serve(send_body=False)

        def _serve(self, send_body: bool):
            target = self._resolve()
            if not target:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            size = target.stat().st_size
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            start, end = 0, size - 1
            status = HTTPStatus.OK
            header = self.headers.get("Range")
            if header:
                m = _RANGE.match(header.strip())
                if not m or (not m.group(1) and not m.group(2)):
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                if m.group(1):
                    start = int(m.group(1))
                    if m.group(2):
                        end = min(int(m.group(2)), size - 1)
                else:  # suffix range: last N bytes
                    start = max(0, size - int(m.group(2)))
                if start >= size or start > end:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                status = HTTPStatus.PARTIAL_CONTENT
            length = end - start + 1
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            if status == HTTPStatus.PARTIAL_CONTENT:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if not send_body:
                return
            with open(target, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    block = f.read(min(1 << 20, remaining))
                    if not block:
                        break
                    try:
                        self.wfile.write(block)
                    except (BrokenPipeError, ConnectionResetError):
                        return  # the player moved on; normal while seeking
                    remaining -= len(block)

        def log_message(self, fmt, *args):
            if os.environ.get("LECTURES_VERBOSE"):
                super().log_message(fmt, *args)

    return RangeHandler


def serve(root: Path, port: int = 4322, host: str = "127.0.0.1"):
    httpd = ThreadingHTTPServer((host, port), make_handler(root))
    print(f"Serving lecture media from {root} at http://{host}:{port}/ (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
