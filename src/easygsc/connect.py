"""Connect easygsc to AI apps: build the launch command and register it in each app.

Editing an app's config never loses data: only plain JSON is edited, a timestamped
backup is written first, the file is replaced atomically and every other entry is
kept. Apps with their own CLI (Claude Code, Codex) are registered through it. Nothing
here makes network calls.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from . import __version__
from .prompts import Cancelled, ask, confirm

SERVER_NAME = "easygsc"
TRY_IT = 'Open your AI app and ask: "List my Search Console sites."'
BROWSER_ONLY = (
    "Chats that only run in a web browser (ChatGPT, claude.ai, Gemini on the web) cannot\n"
    "start programs on your computer, so they cannot use easygsc. Use a desktop app above."
)


class ConnectError(Exception):
    """An app config easygsc could not edit; the message is user-facing.

    ``path`` names the file that failed; ``notes`` report files already updated.
    """

    def __init__(self, message: str, path: Path | None = None, notes: Sequence[str] = ()):
        super().__init__(message)
        self.path = path
        self.notes = list(notes)


def _direct_url() -> dict | None:
    """Where this easygsc was installed from (PEP 610), or None for an index release."""
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
    """How an AI app should start this exact easygsc, even before it is on PyPI."""
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
    """Copy the current file to a new `.bak`; an older backup is never overwritten."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.{stamp}.bak")
    counter = 1
    while backup.exists():  # two writes in the same second, or a loop over configs
        counter += 1
        backup = path.with_name(f"{path.name}.{stamp}-{counter}.bak")
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
            mode = stat.S_IMODE(os.stat(path).st_mode)
            if not mode & stat.S_IWRITE:
                # Some apps protect their config: leave it readable and rewritable by its
                # owner, or the next connect cannot update it.
                mode |= stat.S_IREAD | stat.S_IWRITE
                if os.name == "nt":
                    # Windows refuses to replace a read-only destination; POSIX does not,
                    # so the old file is left alone until the replace succeeds.
                    os.chmod(path, mode)
            os.chmod(tmp_name, mode)  # keep the app's own permissions
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.chmod(tmp_name, stat.S_IREAD | stat.S_IWRITE)  # Windows won't delete read-only
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def add_server(
    path: Path, section: str, entry: dict, replace: Callable[[], bool]
) -> tuple[str, Path | None]:
    """Register ``entry`` as ``<section>.easygsc`` in the JSON config at ``path``.

    Returns ``(status, backup)``. Status is ``added``, ``updated``, ``unchanged``, or
    ``kept`` when ``replace()`` declined overwriting a different easygsc entry. Raises
    ConnectError, leaving the file untouched, for anything but a plain JSON object.
    """
    if path.is_symlink():
        path = path.resolve()  # dotfile managers link configs: update the real file
    exists = path.is_file()
    try:
        raw = path.read_text(encoding="utf-8-sig") if exists else ""
    except OSError as exc:
        raise ConnectError(f"Cannot read {path}: {exc}", path) from exc
    except UnicodeDecodeError:
        raise ConnectError(
            f"{path} is not UTF-8 text, so easygsc left it untouched.", path
        ) from None
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        raise ConnectError(
            f"{path} is not plain JSON (comments or a typo?), so easygsc left it untouched.", path
        ) from None
    if not isinstance(data, dict):
        raise ConnectError(
            f"{path} does not hold a JSON object, so easygsc left it untouched.", path
        )
    servers = data.setdefault(section, {})
    if not isinstance(servers, dict):
        raise ConnectError(
            f"'{section}' in {path} is not a JSON object, so easygsc left it untouched.", path
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
        raise ConnectError(f"Cannot write {path}: {exc}", path) from exc
    return ("updated" if current is not None else "added"), backup


def _has_entry(path: Path, section: str, entry: dict) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data.get(section, {}).get(SERVER_NAME) == entry
    except (OSError, ValueError, AttributeError):
        return False


@dataclass(frozen=True)
class App:
    """An AI app easygsc can register itself in.

    A JSON app lists its candidate config files, the default one first. A CLI app is
    registered through its own command (``<cli> mcp add``), which owns its config.
    """

    name: str
    then: str  # what the user does next so the app loads easygsc
    configs: Callable[[], list[Path]] | None = None
    section: str = "mcpServers"
    stdio_type: bool = False  # the entry needs "type": "stdio"
    close_first: bool = False  # the app may rewrite its config while it runs
    cli: str | None = None
    add: Callable[[str, list[str]], list[str]] | None = None  # argv after the cli
    remove: tuple[str, ...] = ()  # argv after the cli; used when add refuses a duplicate
    exists: tuple[str, ...] = ()  # argv that exits 0 when easygsc is registered
    detect: tuple[str, ...] = ()  # executables that show the app is installed
    found_by_folder: bool = True  # an existing config folder means it is installed

    def targets(self) -> list[Path]:
        """Every candidate whose folder exists (all get the entry), else the default."""
        candidates = self.configs() if self.configs else []
        existing = [path for path in candidates if path.parent.is_dir()]
        return existing or candidates[:1]

    def found(self) -> bool:
        names = (*self.detect, self.cli) if self.cli else self.detect
        if any(shutil.which(name) for name in names):
            return True
        candidates = self.configs() if self.configs else []
        if any(path.is_file() for path in candidates):
            return True
        return self.found_by_folder and any(path.parent.is_dir() for path in candidates)

    def entry(self, command: str, args: list[str]) -> dict:
        entry = {"command": command, "args": list(args)}
        return {"type": "stdio", **entry} if self.stdio_type else entry


def _env_dir(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value) if value else default


def _app_support() -> Path:
    """Where desktop apps keep per-user settings on this OS."""
    if sys.platform == "win32":
        return _env_dir("APPDATA", Path.home() / "AppData" / "Roaming")
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return _env_dir("XDG_CONFIG_HOME", Path.home() / ".config")


def _claude_desktop() -> list[Path]:
    paths = [_app_support() / "Claude" / "claude_desktop_config.json"]
    if sys.platform == "win32":
        # The Microsoft Store build reads a virtualized copy inside its package folder.
        packages = _env_dir("LOCALAPPDATA", Path.home() / "AppData" / "Local") / "Packages"
        try:
            store = sorted(packages.glob("Claude_*"))
        except OSError:
            store = []
        paths += [
            p / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json" for p in store
        ]
    return paths


def _devin() -> list[Path]:
    # Windsurf became Devin Desktop; the old Windsurf file is only used if it is there.
    root = (
        _app_support()
        if sys.platform == "win32"
        else _env_dir("XDG_CONFIG_HOME", Path.home() / ".config")
    )
    return [
        root / "devin" / "mcp_config.json",
        Path.home() / ".codeium" / "windsurf" / "mcp_config.json",
    ]


APPS: tuple[App, ...] = (
    App(
        "Claude Desktop",
        "Open Claude Desktop again.",
        configs=_claude_desktop,
        close_first=True,
    ),
    App(
        "Claude Code",
        "Start a new Claude Code session.",
        cli="claude",
        add=lambda command, args: [
            "mcp",
            "add",
            "--scope",
            "user",
            SERVER_NAME,
            "--",
            command,
            *args,
        ],
        remove=("mcp", "remove", SERVER_NAME, "--scope", "user"),
    ),
    App(
        "Codex (OpenAI)",
        "Start a new Codex session.",
        cli="codex",
        add=lambda command, args: ["mcp", "add", SERVER_NAME, "--", command, *args],
        # `codex mcp add` overwrites silently; `get` reads every TOML spelling for us.
        exists=("mcp", "get", SERVER_NAME),
    ),
    App(
        "Gemini CLI",
        "Start a new Gemini CLI session.",
        configs=lambda: [Path.home() / ".gemini" / "settings.json"],
        detect=("gemini",),
        found_by_folder=False,  # ~/.gemini is shared with Antigravity
    ),
    App(
        "Google Antigravity",
        "Restart Antigravity.",
        configs=lambda: [Path.home() / ".gemini" / "config" / "mcp_config.json"],
        detect=("antigravity",),
    ),
    App(
        "Cursor",
        "Restart Cursor.",
        configs=lambda: [Path.home() / ".cursor" / "mcp.json"],
        stdio_type=True,
        detect=("cursor",),
    ),
    App(
        "VS Code (GitHub Copilot)",
        "Restart VS Code and use Copilot Chat in Agent mode.",
        configs=lambda: [_app_support() / "Code" / "User" / "mcp.json"],
        section="servers",
        stdio_type=True,
        detect=("code",),
    ),
    App(
        "Windsurf / Devin Desktop",
        "Restart Windsurf / Devin Desktop.",
        configs=_devin,
        detect=("windsurf", "devin"),
    ),
    App(
        "LM Studio",
        "Restart LM Studio.",
        configs=lambda: [Path.home() / ".lmstudio" / "mcp.json"],
        detect=("lms",),
    ),
)

STATUS = {
    "added": "Connected.",
    "updated": "Connected (replaced the old easygsc entry).",
    "unchanged": "Already connected; nothing changed.",
    "kept": "Kept your existing easygsc entry; nothing changed.",
}


def _run(argv: list[str]) -> tuple[int, str]:
    """Run an app's own CLI; returns (exit code, combined output)."""
    try:
        done = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return done.returncode, f"{done.stdout or ''}{done.stderr or ''}"


def _shell_line(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def _last_line(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else "no output"


def _ask_replace(app: App, question: str) -> Callable[[], bool]:
    """One replace question per app, even when it has several config files."""
    answers: list[bool] = []

    def replace() -> bool:
        if not answers:
            answers.append(confirm(f"  {app.name} {question} [y/N] "))
        return answers[0]

    return replace


def _connect_cli(app: App, command: str, args: list[str]) -> tuple[str, list[str]]:
    exe = shutil.which(app.cli)
    if not exe:
        raise ConnectError(f"the '{app.cli}' command was not found. Is {app.name} installed?")
    replace = _ask_replace(app, "already has an easygsc entry. Replace it with this one?")
    status = "added"
    if app.exists and _run([exe, *app.exists])[0] == 0:
        if not replace():
            return "kept", []
        status = "updated"
    code, out = _run([exe, *app.add(command, args)])
    if code != 0 and app.remove and "already exists" in out.lower():
        if not replace():
            return "kept", []
        code, out = _run([exe, *app.remove])
        if code != 0:
            raise ConnectError(f"removing the old entry failed: {_last_line(out)}")
        status = "updated"
        code, out = _run([exe, *app.add(command, args)])
        if code != 0:
            raise ConnectError(
                f"the old entry was already removed, but adding the new one failed: "
                f"{_last_line(out)}"
            )
    if code != 0:
        raise ConnectError(f"'{app.cli} mcp add' failed: {_last_line(out)}")
    return status, []


def _connect_json(app: App, command: str, args: list[str]) -> tuple[str, list[str]]:
    entry, targets = app.entry(command, args), app.targets()
    connected = all(_has_entry(path, app.section, entry) for path in targets)
    if app.close_first and app.found() and not connected:
        print(f"  Quit {app.name} completely (also from the system tray or menu bar).")
        ask("  Press Enter once it is closed... ")
    replace = _ask_replace(app, "already starts easygsc differently. Replace that?")
    statuses, notes = [], []
    for path in targets:
        try:
            status, backup = add_server(path, app.section, entry, replace)
        except ConnectError as exc:
            raise ConnectError(str(exc), exc.path, notes) from None
        statuses.append(status)
        notes.append(f"Settings file: {path}")
        if backup:
            notes.append(f"Backup of the previous file: {backup}")
    for status in ("kept", "updated", "added"):
        if status in statuses:
            return status, notes
    return "unchanged", notes


def _print_manual(app: App, command: str, args: list[str], path: Path | None = None) -> None:
    targets = [path] if path else app.targets()
    if app.cli:
        print("  Do it by hand: run this in a terminal:")
        print(f"    {_shell_line([app.cli, *app.add(command, args)])}")
    elif targets:
        snippet = json.dumps({app.section: {SERVER_NAME: app.entry(command, args)}}, indent=2)
        print(f"  Do it by hand: open {targets[0]} and add this")
        print(f'  (if "{app.section}" is already there, add only the "{SERVER_NAME}" part):')
        print("\n".join(f"    {line}" for line in snippet.splitlines()))
    else:
        _print_generic(command, args)


def _print_generic(command: str, args: list[str]) -> None:
    snippet = json.dumps(
        {"mcpServers": {SERVER_NAME: {"command": command, "args": args}}}, indent=2
    )
    print("\nAnother app")
    print('  In its settings, look for "MCP servers" (sometimes "Tools", "Connectors" or')
    print('  "Integrations") and add a local server, also called "stdio":')
    print(f"    Name:     {SERVER_NAME}")
    print(f"    Command:  {command}")
    print("    Arguments, one per line, in this order:")
    for arg in args:
        print(f"      {arg}")
    print("  If it asks for JSON instead, use:")
    print("\n".join(f"    {line}" for line in snippet.splitlines()))
    print("\n".join(f"  {line}" for line in BROWSER_ONLY.splitlines()))


def _connect_one(app: App, command: str, args: list[str]) -> tuple[bool, str, list[str]]:
    """Connect one app; returns (ok, status, notes) so a cancel can report the writes."""
    print(f"\n{app.name}")
    try:
        connect_app = _connect_cli if app.cli else _connect_json
        status, notes = connect_app(app, command, args)
    except ConnectError as exc:
        for note in exc.notes:  # copies updated before the one that failed
            print(f"  {note}")
        print(f"  Could not connect it automatically: {exc}")
        _print_manual(app, command, args, exc.path)
        return False, "", []
    print(f"  {STATUS[status]}")
    for note in notes:
        print(f"  {note}")
    if status in ("added", "updated"):
        print(f"  Next: {app.then}")
    return True, status, notes


def _print_already_written(done: Sequence[tuple[App, str, list[str]]]) -> None:
    """Say what a cancel left behind, so the user knows which files already changed."""
    written = [item for item in done if item[1] in ("added", "updated")]
    if not written:
        return
    print("\nAlready written before the cancel:")
    for app, status, notes in written:
        print(f"  {app.name}: {STATUS[status]}")
        for note in notes:
            print(f"    {note}")


def _choose(apps: Sequence[App]) -> list[int]:
    found = [number for number, app in enumerate(apps, 1) if app.found()]
    other = len(apps) + 1
    print("\nConnect easygsc to your AI apps")
    for number, app in enumerate(apps, 1):
        print(f"  {number}. {app.name}{'  (found on this computer)' if number in found else ''}")
    print(f"  {other}. Another app: show the settings to copy")
    default = found or [other]
    shown = ",".join(map(str, default))
    while True:
        raw = ask(f"Type the numbers of the apps you use (e.g. 1,3). Enter = {shown}, 0 = skip: ")
        raw = raw.strip()
        if not raw:
            return default
        if raw == "0":
            return []
        try:
            picks = sorted({int(part) for part in raw.replace(",", " ").split()})
        except ValueError:
            picks = []
        if picks and all(1 <= pick <= other for pick in picks):
            return picks
        print(f"Please type numbers from 1 to {other}, like 1,3 (or q to quit).")


def choose_and_connect(apps: Sequence[App] | None = None) -> int:
    """Menu + connect: 0 when every chosen app is set, 1 when one needs a manual step.

    Raises Cancelled on q/quit/EOF, after naming the files already written, so each
    caller can word the cancellation.
    """
    apps = APPS if apps is None else apps
    command, args = launch_command()
    picks = _choose(apps)
    if not picks:
        print("No apps connected. Run 'easygsc connect' any time to add one.")
        return 0
    failed = False
    done: list[tuple[App, str, list[str]]] = []
    try:
        for pick in picks:
            if pick > len(apps):
                _print_generic(command, args)
                continue
            app = apps[pick - 1]
            ok, status, notes = _connect_one(app, command, args)
            if status:
                done.append((app, status, notes))
            if not ok:
                failed = True
    except Cancelled:
        _print_already_written(done)  # a cancel must not hide the files already changed
        raise
    print(f"\n{TRY_IT}")
    if failed:
        print("Some apps still need the manual step shown above.")
    return 1 if failed else 0


def run() -> int:
    """``easygsc connect``: 0 success, 1 an app needs a manual step, 2 cancelled."""
    try:
        return choose_and_connect()
    except Cancelled:
        print("connect cancelled; run 'easygsc connect' again when ready.", file=sys.stderr)
        return 2
