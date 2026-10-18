"""Credential resolution, the OAuth flow, and token storage.

Resolution order (documented in README, printed by ``opengsc doctor``):
1. service account file (``OPENGSC_SERVICE_ACCOUNT_FILE``)
2. refresh token from the environment (``OPENGSC_REFRESH_TOKEN`` plus the
   OAuth client from env vars or ``client_secret.json``), for stateless setups
3. saved OAuth token (``~/.config/opengsc/token.json``)
4. otherwise run ``opengsc auth``

Nothing here logs or returns secrets; the refresh token is printed exactly
once, by ``run_oauth_flow``, because the user asked for it.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import credentials as oauth2_credentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow

from .allowlist import GuardedSession, attach_guard

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]

# Same location on every OS, per the project spec.
CONFIG_DIR = Path.home() / ".config" / "opengsc"
TOKEN_PATH = CONFIG_DIR / "token.json"
CLIENT_SECRET_PATH = CONFIG_DIR / "client_secret.json"

GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


class AuthError(RuntimeError):
    """Raised when no usable credentials can be resolved."""


def client_config() -> dict:
    """Build the 'installed' client config from env vars or client_secret.json."""
    client_id = os.environ.get("OPENGSC_CLIENT_ID")
    client_secret = os.environ.get("OPENGSC_CLIENT_SECRET")
    if client_id and client_secret:
        return {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": GOOGLE_AUTH_URI,
                "token_uri": GOOGLE_TOKEN_URI,
                "redirect_uris": ["http://localhost"],
            }
        }
    if CLIENT_SECRET_PATH.is_file():
        with open(CLIENT_SECRET_PATH, encoding="utf-8") as f:
            return json.load(f)
    raise AuthError(
        "No OAuth client configured. Provide OPENGSC_CLIENT_ID and "
        "OPENGSC_CLIENT_SECRET, or place a Desktop-app client_secret.json at "
        f"{CLIENT_SECRET_PATH}, then run 'opengsc auth'."
    )


def resolve_credentials():
    """Resolve credentials in the documented order. Raises AuthError if none."""
    sa_file = os.environ.get("OPENGSC_SERVICE_ACCOUNT_FILE")
    if sa_file:
        creds = service_account.Credentials.from_service_account_file(sa_file, scopes=SCOPES)
        return creds
    refresh_token = os.environ.get("OPENGSC_REFRESH_TOKEN")
    if refresh_token:
        client = next(iter(client_config().values()))
        return oauth2_credentials.Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=client.get("token_uri", GOOGLE_TOKEN_URI),
            client_id=client["client_id"],
            client_secret=client["client_secret"],
            scopes=SCOPES,
        )
    if TOKEN_PATH.is_file():
        return oauth2_credentials.Credentials.from_authorized_user_file(
            str(TOKEN_PATH), scopes=SCOPES
        )
    raise AuthError(
        "No credentials found. Run 'opengsc auth' first, or set "
        "OPENGSC_SERVICE_ACCOUNT_FILE for service-account setups. "
        f"Expected token at {TOKEN_PATH}."
    )


def token_info() -> dict:
    """Safe description of the stored token for doctor: no secrets."""
    if not TOKEN_PATH.is_file():
        return {"present": False}
    try:
        data = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"present": True, "readable": False}
    return {
        "present": True,
        "readable": True,
        "expiry": data.get("expiry"),
        "has_refresh_token": bool(data.get("refresh_token")),
        "scopes": data.get("scopes"),
        "account": data.get("account"),
    }


def save_token(credentials) -> Path:
    """Write the credentials JSON atomically with 0600 (best effort on Windows)."""
    payload = credentials.to_json()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".token-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp_name, 0o600)
        except OSError:
            pass  # best effort on platforms without POSIX permissions
        os.replace(tmp_name, TOKEN_PATH)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return TOKEN_PATH


def run_oauth_flow(no_browser: bool = False, *, print_refresh_token: bool = True):
    """Run the installed-app OAuth flow and persist the token.

    ``--no-browser`` still uses the loopback redirect flow; it only skips
    opening the browser window automatically (the URL is printed instead).
    ``print_refresh_token=False`` keeps the token out of stdout for callers
    such as ``opengsc setup``; ``opengsc auth`` keeps the default.
    """
    flow = InstalledAppFlow.from_client_config(client_config(), scopes=SCOPES)
    # The code exchange goes through the flow's own OAuth2Session: guard it.
    attach_guard(flow.oauth2session)
    credentials = flow.run_local_server(port=0, open_browser=not no_browser)
    save_token(credentials)
    # The user explicitly asked for the refresh token (stateless setups);
    # this is the only place it is ever printed.
    if print_refresh_token:
        print(f"OPENGSC_REFRESH_TOKEN={credentials.refresh_token}")
    return credentials


def make_authorized_session():
    """AuthorizedSession with guarded own traffic and guarded refresh channel."""
    from .allowlist import GuardedAuthorizedSession

    return GuardedAuthorizedSession(resolve_credentials())


def refresh_credentials_if_expired(credentials) -> None:
    """Refresh credentials through the guarded session if needed."""

    if not credentials.valid:
        credentials.refresh(GoogleAuthRequest(session=GuardedSession()))
