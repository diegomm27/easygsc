"""Guided setup: walk the Google Cloud steps, install the OAuth client, run auth.

Only ``run_oauth_flow`` and the doctor check make network calls, through the existing
allowlist guard. Nothing here prints the client secret.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import webbrowser
from pathlib import Path

from . import __version__, auth
from .cli import _doctor

DOWNLOADS_DIR = Path.home() / "Downloads"

PROJECT_URL = "https://console.cloud.google.com/projectcreate"
API_URL = "https://console.cloud.google.com/apis/library/searchconsole.googleapis.com"
CONSENT_URL = "https://console.cloud.google.com/auth/overview"
PUBLISH_URL = "https://console.cloud.google.com/auth/audience"
CLIENT_URL = "https://console.cloud.google.com/auth/clients"

STEPS = (
    (PROJECT_URL, "Create a project (for example 'opengsc') and select it in the picker."),
    (API_URL, "Enable the Search Console API for that project: click 'Enable'."),
    (CONSENT_URL, "Consent screen: External, app name 'opengsc', your emails."),
    (PUBLISH_URL, "Publishing does not expose your data and avoids the 7-day login expiry."),
    (CLIENT_URL, "Create a 'Desktop app' OAuth client, then click 'Download JSON'."),
)


class SetupError(RuntimeError):
    """A setup problem the user can fix; the message is user-facing."""


class WebClientError(SetupError):
    pass


class Cancelled(Exception):
    """The user cancelled setup with EOF, Ctrl+D or q/quit."""


def _input(prompt: str) -> str:
    try:
        answer = input(prompt)
    except EOFError:
        raise Cancelled("no input") from None
    if answer.strip().lower() in ("q", "quit"):
        raise Cancelled("quit")
    return answer


def _confirm(prompt: str, default: bool = False) -> bool:
    answer = _input(prompt).strip().lower()
    return default if not answer else answer in ("y", "yes")


def _step(url: str, explanation: str, no_browser: bool) -> None:
    print(f"\n{explanation}")
    if no_browser or not webbrowser.open(url):
        print(f"Open this URL: {url}")
    _input("Press Enter when done... ")


def load_client(path: Path) -> dict:
    """Return a validated Desktop-app client config, or raise SetupError."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SetupError(f"Cannot read {path}: {exc}") from exc
    except json.JSONDecodeError:
        raise SetupError(f"{path} is not valid JSON.") from None
    installed = data.get("installed") if isinstance(data, dict) else None
    if installed:
        if not installed.get("client_id") or not installed.get("client_secret"):
            raise SetupError(f"{path} has no client_id/client_secret under 'installed'.")
        return data
    if isinstance(data, dict) and "web" in data:
        raise WebClientError(
            "That is a Web application client; opengsc needs a Desktop app client."
        )
    raise SetupError(f"{path} is not a Google OAuth client file (no 'installed' key).")


def _configured_where() -> str | None:
    if os.environ.get("OPENGSC_CLIENT_ID") and os.environ.get("OPENGSC_CLIENT_SECRET"):
        return "the OPENGSC_CLIENT_ID/OPENGSC_CLIENT_SECRET env vars"
    try:
        load_client(auth.CLIENT_SECRET_PATH)
    except SetupError:
        return None
    return str(auth.CLIENT_SECRET_PATH)


def find_downloaded(downloads: Path | None = None) -> Path | None:
    """Newest client_secret*.json in Downloads; the pattern also covers .json.json."""
    downloads = downloads if downloads is not None else DOWNLOADS_DIR
    try:
        files = [p for p in downloads.glob("client_secret*.json") if p.is_file()]
        candidates = sorted(((p.stat().st_mtime, p) for p in files), reverse=True)
    except OSError:
        return None
    if not candidates:
        return None
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return None  # a tie is ambiguous: ask instead of guessing
    return candidates[0][1]


def _obtain_client(no_browser: bool) -> Path:
    source = find_downloaded()
    while True:
        if source is None:
            raw = _input(f"Path to the downloaded JSON (look in {DOWNLOADS_DIR}): ")
            source = Path(raw.strip().strip("\"'").strip()).expanduser()  # Copy-as-path quotes
        try:
            load_client(source)
            return source
        except WebClientError as exc:
            print(exc)
            _step(*STEPS[-1], no_browser)
            found = find_downloaded()
            source = found if found != source else None
        except SetupError as exc:
            print(exc)
            source = None


def install_client(source: Path, dest: Path | None = None) -> Path:
    """Copy (never move) the client JSON to the config dir with 0600 permissions."""
    dest = dest if dest is not None else auth.CLIENT_SECRET_PATH
    try:
        same = dest.read_bytes() == source.read_bytes()
    except OSError:
        same = False
    if dest.is_file() and not same:
        if not _confirm(f"{dest} already exists. Overwrite it? [y/N] "):
            print(f"Keeping the existing file at {dest}.")
            return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=".client_secret-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as out, open(source, "rb") as src:
            shutil.copyfileobj(src, out)
            out.flush()
            os.fsync(out.fileno())
        try:
            os.chmod(tmp_name, 0o600)  # mkstemp already creates it 0600 on POSIX
        except OSError:
            pass  # best effort on platforms without POSIX permissions
        os.replace(tmp_name, dest)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return dest


def _next_steps() -> None:
    package = f"opengsc@{__version__}"
    snippet = {"mcpServers": {"opengsc": {"command": "uvx", "args": [package]}}}
    print("\nNext: add opengsc to your MCP client.\nClaude Desktop (claude_desktop_config.json):")
    print(json.dumps(snippet, indent=2))
    print(f"Claude Code:\n  claude mcp add opengsc -- uvx {package}")


def _authenticate(no_browser: bool) -> int:
    print("\nNow logging in to Google...")
    try:
        auth.run_oauth_flow(no_browser=no_browser)
    except auth.AuthError as exc:
        print(
            f"auth failed: {exc}\nRerun 'opengsc setup' once the client is fixed.", file=sys.stderr
        )
        return 1
    if _doctor() != 0:
        print("auth check failed; see the report above.", file=sys.stderr)
        return 1
    _next_steps()
    return 0


def _run(no_browser: bool) -> int:
    if where := _configured_where():
        print(f"opengsc already has an OAuth client configured ({where}).")
        if auth.TOKEN_PATH.is_file() and _doctor() == 0:
            print("Everything is ready: the client is installed and auth works.")
            _next_steps()
            return 0
        if _confirm("Skip the Google Cloud walkthrough and run auth now? [Y/n] ", default=True):
            return _authenticate(no_browser)

    for url, explanation in STEPS:
        _step(url, explanation, no_browser)
    source = _obtain_client(no_browser)
    install_client(source)
    if _confirm(f"Delete the downloaded copy at {source}? [y/N] "):
        try:
            source.unlink()
        except OSError:
            pass
    return _authenticate(no_browser)


def run(no_browser: bool = False) -> int:
    """Interactive setup: 0 success, 1 failure, 2 cancelled; Ctrl+C reaches the CLI."""
    try:
        return _run(no_browser)
    except Cancelled:
        print("setup cancelled; run 'opengsc setup' again when ready.", file=sys.stderr)
        return 2
    except SetupError as exc:
        print(f"setup failed: {exc}", file=sys.stderr)
        return 1
