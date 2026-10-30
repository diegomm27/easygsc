"""Local setup page: the Google Cloud steps and the client upload, in the browser.

The page only collects the OAuth client JSON; installing it, the Google login and
connecting apps stay in the terminal wizard (``setup``). The server listens on
127.0.0.1 on a random port, answers only requests that carry its one-time token and
its own Host header, and stops as soon as a valid client arrives. It makes no
outbound calls and logs nothing, since request lines carry the token.
"""

from __future__ import annotations

import hmac
import html
import json
import secrets
import socketserver
import threading
import webbrowser
from collections.abc import Callable, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, urlsplit

MAX_UPLOAD = 64 * 1024  # a client file is well under 1 KB
_DRAIN_LIMIT = 16 * MAX_UPLOAD  # read a refused body up to this size so the reply arrives
REQUEST_TIMEOUT = 10.0  # seconds a connection may stall before it is dropped

Step = tuple[str, str, Sequence[str]]
Check = Callable[[bytes], "str | None"]


def _render_steps(steps: Sequence[Step]) -> str:
    items = []
    for url, title, actions in steps:
        link = html.escape(url)
        rows = "".join(f"<li>{html.escape(action)}</li>" for action in actions)
        items.append(
            '<li class="step"><label><input type="checkbox"> '
            f'<span class="title">{html.escape(title)}</span></label>'
            f'<ol><li>Open <a href="{link}" target="_blank" rel="noopener noreferrer">'
            f"{link}</a></li>{rows}</ol></li>"
        )
    return "\n".join(items)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self) -> None:
        # HTTPServer.server_bind resolves the host's FQDN, which can stall for seconds
        # on Windows; the name is never used.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def handle_error(self, request: object, client_address: object) -> None:
        pass  # a tab closed mid-request must not print a traceback into the wizard


class SetupServer:
    """Serve the setup page until a client file passes ``check``; use as a context."""

    def __init__(self, steps: Sequence[Step], check: Check) -> None:
        self._check = check
        self._token = secrets.token_urlsafe(32)
        self._client: bytes | None = None
        self._lock = threading.Lock()
        self._done = threading.Event()
        template = resources.files("easygsc").joinpath("setup_page.html").read_text("utf-8")
        self._page = (
            template.replace("{{steps}}", _render_steps(steps))
            .replace("{{token}}", self._token)
            .replace("{{max}}", str(MAX_UPLOAD))
        )
        self._httpd = _Server(("127.0.0.1", 0), self._handler())
        self.port = self._httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/?token={self._token}"
        self._hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        self._origins = {f"http://{host}" for host in self._hosts}
        # A short poll keeps close() quick once the client has arrived.
        serve = lambda: self._httpd.serve_forever(poll_interval=0.05)  # noqa: E731
        self._thread = threading.Thread(target=serve, daemon=True)
        self._thread.start()

    def __enter__(self) -> SetupServer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def wait(self) -> bytes:
        """Block until a valid client arrives; short waits keep Ctrl+C working on Windows."""
        while not self._done.wait(0.2):
            pass
        assert self._client is not None
        return self._client

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join()

    def _valid(self, token: str) -> bool:
        return hmac.compare_digest(token.encode(), self._token.encode())

    def _accept(self, data: bytes) -> tuple[int, dict]:
        with self._lock:
            if self._done.is_set():
                return 409, {"error": "Setup already has a client; go back to the terminal."}
            try:
                problem = self._check(data)
            except Exception:  # noqa: BLE001 - the page reports instead of crashing
                problem = "That file could not be read as an OAuth client."
            if problem:
                return 400, {"error": problem}
            self._client = data
            self._done.set()
        return 200, {"ok": True}

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class Handler(BaseHTTPRequestHandler):
            timeout = REQUEST_TIMEOUT  # a stalled connection is dropped, not kept forever
            server_version = "easygsc"
            sys_version = ""

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                pass  # request lines carry the token

            def _send(self, status: int, body: bytes, kind: str, extra: dict | None = None):
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                for name, value in (extra or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status: int, payload: dict) -> None:
                self._send(status, json.dumps(payload).encode(), "application/json")

            def _not_found(self) -> None:
                self._send(404, b"Not found", "text/plain; charset=utf-8")

            def _own_host(self) -> bool:
                # A DNS-rebinding page reaches 127.0.0.1 under its own Host name.
                return self.headers.get("Host") in server._hosts

            def do_GET(self) -> None:  # noqa: N802 - http.server naming
                if not self._own_host():
                    return self._json(403, {"error": "Wrong host."})
                parts = urlsplit(self.path)
                token = parse_qs(parts.query).get("token", [""])[0]
                if parts.path != "/" or not server._valid(token):
                    return self._not_found()
                nonce = secrets.token_urlsafe(16)
                policy = (
                    f"default-src 'none'; style-src 'nonce-{nonce}'; "
                    f"script-src 'nonce-{nonce}'; connect-src 'self'; form-action 'none'; "
                    "base-uri 'none'; frame-ancestors 'none'"
                )
                body = server._page.replace("{{nonce}}", nonce).encode()
                self._send(
                    200,
                    body,
                    "text/html; charset=utf-8",
                    {"Content-Security-Policy": policy, "X-Frame-Options": "DENY"},
                )

            def do_POST(self) -> None:  # noqa: N802 - http.server naming
                if not self._own_host():
                    return self._json(403, {"error": "Wrong host."})
                origin = self.headers.get("Origin")
                if origin is not None and origin not in server._origins:
                    return self._json(403, {"error": "Wrong origin."})
                if urlsplit(self.path).path != "/client":
                    return self._not_found()
                if not server._valid(self.headers.get("X-Easygsc-Token", "")):
                    return self._json(403, {"error": "Wrong token."})
                try:
                    length = int(self.headers.get("Content-Length", ""))
                except ValueError:
                    return self._json(411, {"error": "Missing length."})
                if length < 0 or length > MAX_UPLOAD:
                    if 0 < length <= _DRAIN_LIMIT:
                        self.rfile.read(length)
                    self.close_connection = True
                    return self._json(413, {"error": "That file is too large for an OAuth client."})
                status, payload = server._accept(self.rfile.read(length))
                self._json(status, payload)

        return Handler


def collect_client(
    steps: Sequence[Step], check: Check, opener: Callable[[str], bool] | None = None
) -> bytes | None:
    """Open the setup page and return the uploaded client, or None if no browser opened.

    ``check`` returns an error message for the page, or None for a usable client.
    """
    opener = opener or webbrowser.open
    with SetupServer(steps, check) as server:
        if not opener(server.url):
            return None
        print("\nThe setup steps are open in your browser:")
        print(f"  {server.url}")
        print("Follow them there; this window waits for the client file. Press Ctrl+C to stop.")
        return server.wait()
