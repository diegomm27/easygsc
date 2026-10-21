"""Guided setup: walk the Google Cloud steps, install the OAuth client, run auth, then
connect the user's AI apps (``connect``).

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
from collections.abc import Sequence
from pathlib import Path

from . import auth, connect
from .cli import _doctor
from .prompts import Cancelled, ask, confirm

DOWNLOADS_DIR = Path.home() / "Downloads"

PROJECT_URL = "https://console.cloud.google.com/projectcreate"
API_URL = "https://console.cloud.google.com/apis/library/searchconsole.googleapis.com"
CONSENT_URL = "https://console.cloud.google.com/auth/overview"
PUBLISH_URL = "https://console.cloud.google.com/auth/audience"
CLIENT_URL = "https://console.cloud.google.com/auth/clients"
BRANDING_URL = "https://console.cloud.google.com/auth/branding"

# Google requires a home page and privacy policy link before an external app can be
# published. They point at the user's own site; easygsc's privacy statement (the
# README's security section) is the fallback for sites without a privacy page.
PRIVACY_URL = "https://github.com/diegomm27/easygsc#security-and-transparency"

CLIENT_STEP = (
    CLIENT_URL,
    "Create the OAuth client",
    (
        "Click 'Create client'.",
        "Application type: Desktop app (not Web application).",
        "Name: easygsc.",
        "Click 'Create', then 'Download JSON' right away: Google won't show the secret again.",
        "Leave the file in Downloads; setup picks it up from there.",
    ),
)

STEPS = (
    (
        PROJECT_URL,
        "Create a Google Cloud project",
        (
            "Project name: easygsc (any name works).",
            "Click 'Create', then select it in the project picker at the top.",
        ),
    ),
    (
        API_URL,
        "Enable the Search Console API",
        (
            "Check that the project picker shows your new project.",
            "Click 'Enable'.",
        ),
    ),
    (
        CONSENT_URL,
        "Set up the consent screen",
        (
            "Click 'Get started'.",
            "App name: easygsc.",
            "User support email: your email.",
            "Audience: External.",
            "Contact information: your email.",
            "Accept the policy, then click 'Create'.",
        ),
    ),
    CLIENT_STEP,
    (
        BRANDING_URL,
        "Fill in Branding (Google won't let you publish without these links)",
        (
            "App logo: leave it empty; uploading one forces Google verification.",
            "Application home page: your website, e.g. https://example.com",
            f"Privacy policy link: your site's privacy page, or {PRIVACY_URL}",
            "Terms of service link: leave it empty.",
            "Authorized domains: your domain, e.g. example.com (the one you verified).",
            "Add github.com too if you used the privacy link above.",
            "Click 'Save'.",
        ),
    ),
    (
        PUBLISH_URL,
        "Publish the app",
        (
            "Click 'Publish app' and confirm.",
            "Check that the status reads 'In production'.",
            "In 'Testing' Google expires your login every 7 days, so publish it.",
            "Publishing does not expose your data: each login sees only its own site.",
            "At login Google warns the app isn't verified; that is expected for a",
            "personal app. Click 'Advanced', then 'Go to easygsc'.",
        ),
    ),
)


class SetupError(RuntimeError):
    """A setup problem the user can fix; the message is user-facing."""


AUTH_FIX = (
    "Rerun 'easygsc setup' once that is fixed. If the client file looks incomplete or "
    "was edited, download it again from the Clients page."
)


class WebClientError(SetupError):
    pass


def _step(url: str, title: str, actions: Sequence[str], no_browser: bool) -> None:
    """Print one Cloud step as a numbered list; opening the URL is always step 1."""
    print(f"\n{title}")
    opened = not no_browser and webbrowser.open(url)
    print(f"  1. Open this URL: {url}" + ("  (it just opened in your browser)" if opened else ""))
    for number, action in enumerate(actions, start=2):
        print(f"  {number}. {action}")
    ask("Press Enter when done... ")


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
            "That is a Web application client; easygsc needs a Desktop app client."
        )
    raise SetupError(f"{path} is not a Google OAuth client file (no 'installed' key).")


def _configured_where() -> str | None:
    if os.environ.get("EASYGSC_CLIENT_ID") and os.environ.get("EASYGSC_CLIENT_SECRET"):
        return "the EASYGSC_CLIENT_ID/EASYGSC_CLIENT_SECRET env vars"
    try:
        load_client(auth.CLIENT_SECRET_PATH)
    except SetupError:
        return None
    return str(auth.CLIENT_SECRET_PATH)


def _download_dirs() -> list[Path]:
    """Downloads folders to search: OneDrive often redirects the real one."""
    home = Path.home()
    candidates = [DOWNLOADS_DIR, home / "OneDrive" / "Downloads"]
    try:
        candidates += sorted(home.glob("OneDrive - */Downloads"))
    except OSError:
        pass
    return [folder for folder in candidates if folder.is_dir()]


def _searched_dirs() -> str:
    folders = _download_dirs()
    return " or ".join(str(folder) for folder in folders) if folders else str(DOWNLOADS_DIR)


def find_downloaded(downloads: Path | None = None) -> Path | None:
    """Newest client_secret*.json in Downloads; the pattern also covers .json.json."""
    folders = [downloads] if downloads is not None else _download_dirs()
    candidates = []
    for folder in folders:
        try:
            candidates += [(p.stat().st_mtime, p) for p in folder.glob("client_secret*.json")]
        except OSError:
            continue
    candidates = [pair for pair in candidates if pair[1].is_file()]
    if not candidates:
        return None
    candidates.sort(reverse=True)
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return None  # a tie is ambiguous: ask instead of guessing
    return candidates[0][1]


def _announce(path: Path | None) -> Path | None:
    if path is not None:
        print(f"\nUsing the client file you downloaded: {path}")
    return path


def _obtain_client(no_browser: bool) -> Path:
    source = _announce(find_downloaded())
    while True:
        if source is None:
            raw = ask(f"Path to the downloaded JSON (I looked in {_searched_dirs()}): ")
            source = Path(raw.strip().strip("\"'").strip()).expanduser()  # Copy-as-path quotes
        try:
            load_client(source)
            return source
        except WebClientError as exc:
            print(_redact(str(exc)))
            _step(*CLIENT_STEP, no_browser)
            found = find_downloaded()
            source = _announce(found) if found != source else None
        except SetupError as exc:
            print(_redact(str(exc)))
            source = None


def install_client(source: Path, dest: Path | None = None) -> Path:
    """Copy (never move) the client JSON to the config dir with 0600 permissions."""
    dest = dest if dest is not None else auth.CLIENT_SECRET_PATH
    try:
        same = dest.read_bytes() == source.read_bytes()
    except OSError:
        same = False
    if dest.is_file() and same:
        print(f"{dest} already holds this client.")
        return dest
    if dest.is_file():
        if not confirm(f"{dest} already exists. Overwrite it? [y/N] "):
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
    print(f"Installed the client as {dest}.")
    return dest


def _connect_apps() -> int:
    # The login is saved by now, so a cancel here must not read like a failed setup.
    try:
        return connect.choose_and_connect()
    except Cancelled:
        print(
            "Connecting apps cancelled. Your Google login is saved; "
            "run 'easygsc connect' when ready.",
            file=sys.stderr,
        )
        return 2


def _known_secrets() -> tuple[str, ...]:
    secrets = set()
    for var in ("EASYGSC_CLIENT_SECRET", "EASYGSC_REFRESH_TOKEN"):
        if value := os.environ.get(var):
            secrets.add(value)
    try:
        client = next(iter(auth.client_config().values()))
        if value := client.get("client_secret"):
            secrets.add(value)
    except (auth.AuthError, StopIteration):
        pass
    try:
        token = json.loads(auth.TOKEN_PATH.read_text(encoding="utf-8"))
        for key in ("client_secret", "refresh_token"):
            if value := token.get(key):
                secrets.add(value)
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return tuple(sorted(secrets, key=len, reverse=True))


def _redact(text: str) -> str:
    """Remove known client secrets and refresh tokens from user-facing text."""
    for secret in _known_secrets():
        text = text.replace(secret, "***")
    return text


def _doctor_ok() -> bool:
    """Run the doctor check; a failing check is reported, never raised.

    ``google-auth`` raises ``RefreshError`` from inside ``doctor`` when the stored
    token was revoked, which would otherwise end the wizard in a traceback.
    """
    try:
        return _doctor() == 0
    except Exception as exc:  # noqa: BLE001 - the wizard reports instead of crashing
        print(f"check failed: {_redact(f'{type(exc).__name__}: {exc}')}", file=sys.stderr)
        return False


def _authenticate(no_browser: bool) -> int:
    print("\nNow logging in to Google...")
    try:
        auth.run_oauth_flow(no_browser=no_browser, print_refresh_token=False)
    except (auth.AuthError, ValueError, OSError) as exc:
        # A malformed or edited client file and a network problem both read as a
        # fixable message; the wizard never ends in a Python traceback.
        print(f"auth failed: {_redact(str(exc))}\n{AUTH_FIX}", file=sys.stderr)
        return 1
    if not _doctor_ok():
        print("auth check failed; see the report above.", file=sys.stderr)
        return 1
    print(f"Authenticated; token saved to {auth.TOKEN_PATH}.")
    return _connect_apps()


def _run(no_browser: bool) -> int:
    if where := _configured_where():
        print(f"easygsc already has an OAuth client configured ({where}).")
        if auth.TOKEN_PATH.is_file() and _doctor_ok():
            print("Everything is ready: the client is installed and auth works.")
            return _connect_apps()
        if confirm("Skip the Google Cloud walkthrough and run auth now? [Y/n] ", default=True):
            return _authenticate(no_browser)

    for url, title, actions in STEPS:
        _step(url, title, actions, no_browser)
    source = _obtain_client(no_browser)
    install_client(source)
    if confirm(f"Delete the downloaded copy at {source}? [y/N] "):
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
        print("setup cancelled; run 'easygsc setup' again when ready.", file=sys.stderr)
        return 2
    except SetupError as exc:
        print(f"setup failed: {_redact(str(exc))}", file=sys.stderr)
        return 1
