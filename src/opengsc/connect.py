"""Connect opengsc to AI apps: build the launch command and register it in each app.

Editing an app's config never loses data: only plain JSON is edited, a timestamped
backup is written first, the file is replaced atomically and every other entry is
kept. Nothing here makes network calls.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from . import __version__

SERVER_NAME = "opengsc"


class ConnectError(Exception):
    """An app config opengsc could not edit; the message is user-facing."""


def _direct_url() -> dict | None:
    """Where this opengsc was installed from (PEP 610), or None for an index release."""
    try:
        text = metadata.distribution(SERVER_NAME).read_text("direct_url.json")
        return json.loads(text) if text else None
    except (metadata.PackageNotFoundError, json.JSONDecodeError):
        return None


def _tool(name: str) -> str:
    # GUI apps (Claude Desktop on macOS, for one) do not inherit the shell PATH, so an
    # absolute path is what lets them start uv/uvx.
    return shutil.which(name) or name


def _file_url_path(url: str) -> str:
    return url2pathname(urlparse(url).path)


def launch_command() -> tuple[str, list[str]]:
    """How an AI app should start this exact opengsc, even before it is on PyPI."""
    origin = _direct_url() or {}
    url = origin.get("url", "")
    vcs = origin.get("vcs_info") or {}
    if url and vcs.get("vcs") == "git" and vcs.get("commit_id"):
        return _tool("uvx"), ["--from", f"git+{url}@{vcs['commit_id']}", SERVER_NAME]
    if url.startswith("file:") and "dir_info" in origin:
        folder = _file_url_path(url)
        if origin["dir_info"].get("editable"):
            return _tool("uv"), ["run", "--directory", folder, SERVER_NAME]
        return _tool("uvx"), ["--from", folder, SERVER_NAME]
    if url and "archive_info" in origin:
        source = _file_url_path(url) if url.startswith("file:") else url
        return _tool("uvx"), ["--from", source, SERVER_NAME]
    return _tool("uvx"), [f"{SERVER_NAME}@{__version__}"]


def _backup(path: Path) -> Path:
    backup = path.with_name(f"{path.name}.{time.strftime('%Y%m%d-%H%M%S')}.bak")
    shutil.copy2(path, backup)
    return backup


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        if path.is_file():
            shutil.copymode(path, tmp_name)  # keep the app's own permissions
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def add_server(
    path: Path, section: str, entry: dict, replace: Callable[[], bool]
) -> tuple[str, Path | None]:
    """Register ``entry`` as ``<section>.opengsc`` in the JSON config at ``path``.

    Returns ``(status, backup)``. Status is ``added``, ``updated``, ``unchanged``, or
    ``kept`` when ``replace()`` declined overwriting a different opengsc entry. Raises
    ConnectError, leaving the file untouched, for anything but a plain JSON object.
    """
    exists = path.is_file()
    try:
        raw = path.read_text(encoding="utf-8-sig") if exists else ""
    except OSError as exc:
        raise ConnectError(f"Cannot read {path}: {exc}") from exc
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        raise ConnectError(
            f"{path} is not plain JSON (comments or a typo?), so opengsc left it untouched."
        ) from None
    if not isinstance(data, dict):
        raise ConnectError(f"{path} does not hold a JSON object, so opengsc left it untouched.")
    servers = data.setdefault(section, {})
    if not isinstance(servers, dict):
        raise ConnectError(
            f"'{section}' in {path} is not a JSON object, so opengsc left it untouched."
        )

    current = servers.get(SERVER_NAME)
    if current == entry:
        return "unchanged", None
    if current is not None and not replace():
        return "kept", None
    servers[SERVER_NAME] = entry
    try:
        backup = _backup(path) if exists else None
        _write_atomic(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise ConnectError(f"Cannot write {path}: {exc}") from exc
    return ("updated" if current is not None else "added"), backup
