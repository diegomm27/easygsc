"""CLI entry points.

- ``opengsc`` (no args) or ``opengsc serve``: run the MCP server over stdio.
- ``opengsc auth [--no-browser]``: run the OAuth flow, store the token.
- ``opengsc doctor``: report auth mode, token expiry, readable property
  count, config paths and version; exit 1 when auth does not work.

Rules: logs go to stderr (default level WARNING); secrets are never printed;
user-facing command output (doctor, auth) goes to stdout.
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import __version__, api, auth, server


def _setup_logging() -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.WARNING,
        format="%(name)s %(levelname)s: %(message)s",
        force=True,  # a fresh CLI process has no handlers; also rebinds in tests
    )


def _auth_mode() -> str:
    import os

    if os.environ.get("OPENGSC_SERVICE_ACCOUNT_FILE"):
        return "service-account"
    if auth.TOKEN_PATH.is_file():
        return "oauth-token"
    return "none"


def _doctor() -> int:
    lines = [
        f"opengsc version: {__version__}",
        f"auth mode: {_auth_mode()}",
        f"config dir: {auth.CONFIG_DIR}",
        f"token file: {auth.TOKEN_PATH}",
        f"client secret file: {auth.CLIENT_SECRET_PATH}",
    ]
    mode = _auth_mode()
    if mode == "oauth-token":
        info = auth.token_info()
        lines.append(f"token expiry: {info.get('expiry', 'unknown')}")
        lines.append(f"token has refresh_token: {info.get('has_refresh_token', False)}")
    elif mode == "service-account":
        lines.append("token expiry: n/a (service account keys do not expire)")
    else:
        lines.append("token expiry: n/a (not authenticated)")

    if mode == "none":
        lines.append("readable properties: unknown (not authenticated)")
        lines.append("auth check: FAILED - run 'opengsc auth' or set OPENGSC_SERVICE_ACCOUNT_FILE")
        print("\n".join(lines))
        return 1

    try:
        data = api.list_sites()
        count = len(data.get("siteEntry", []))
        lines.append(f"readable properties: {count}")
        lines.append("auth check: OK")
        print("\n".join(lines))
        return 0
    except api.ApiError as err:
        lines.append(f"readable properties: unknown (API error)")
        lines.append(f"auth check: FAILED - {err}")
        print("\n".join(lines))
        return 1


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(
        prog="opengsc",
        description=(
            "Minimal, transparent, read-only MCP server for Google Search "
            "Console. With no arguments, serves MCP over stdio."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    auth_parser = sub.add_parser("auth", help="run the OAuth flow and store the token")
    auth_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open a browser window; print the URL to open instead",
    )

    sub.add_parser("doctor", help="show auth mode, token expiry, config paths, version")
    sub.add_parser("serve", help="run the MCP server over stdio (default)")

    args = parser.parse_args(argv)

    if args.command == "auth":
        try:
            auth.run_oauth_flow(no_browser=args.no_browser)
            return 0
        except auth.AuthError as exc:
            print(f"auth failed: {exc}", file=sys.stderr)
            return 1
    if args.command == "doctor":
        return _doctor()
    # No args or explicit serve: MCP over stdio.
    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
