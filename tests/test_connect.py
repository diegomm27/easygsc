"""Tests for connecting opengsc to AI apps: files, PATH and app CLIs all faked."""

import json
import stat
from unittest import mock

import pytest

from opengsc import __version__, connect

SHA = "bbbc2a472fd253cac4bb9c2eed3b2aae919b197c"
ENTRY = {"command": "/abs/uvx", "args": ["opengsc@0.2.0"]}


def on_path(monkeypatch, **tools):
    monkeypatch.setattr(connect.shutil, "which", lambda name: tools.get(name))


def installed_from(monkeypatch, origin):
    monkeypatch.setattr(connect, "_direct_url", lambda: origin)


class TestLaunchCommand:
    def test_index_release_runs_the_pinned_version(self, monkeypatch):
        installed_from(monkeypatch, None)
        on_path(monkeypatch, uvx="/abs/uvx")
        assert connect.launch_command() == ("/abs/uvx", [f"opengsc@{__version__}"])

    def test_git_install_pins_the_exact_commit(self, monkeypatch):
        url = "https://github.com/diegomm27/opengsc"
        installed_from(monkeypatch, {"url": url, "vcs_info": {"vcs": "git", "commit_id": SHA}})
        on_path(monkeypatch, uvx="/abs/uvx")
        assert connect.launch_command() == (
            "/abs/uvx",
            ["--from", f"git+{url}@{SHA}", "opengsc"],
        )

    def test_editable_clone_runs_from_the_clone(self, monkeypatch, tmp_path):
        installed_from(monkeypatch, {"url": tmp_path.as_uri(), "dir_info": {"editable": True}})
        on_path(monkeypatch, uv="/abs/uv")
        assert connect.launch_command() == (
            "/abs/uv",
            ["run", "--directory", str(tmp_path), "opengsc"],
        )

    def test_local_folder_install_runs_from_that_folder(self, monkeypatch, tmp_path):
        installed_from(monkeypatch, {"url": tmp_path.as_uri(), "dir_info": {}})
        on_path(monkeypatch, uvx="/abs/uvx")
        assert connect.launch_command() == ("/abs/uvx", ["--from", str(tmp_path), "opengsc"])

    def test_wheel_install_runs_from_that_wheel(self, monkeypatch, tmp_path):
        wheel = tmp_path / "opengsc-0.2.0-py3-none-any.whl"
        installed_from(monkeypatch, {"url": wheel.as_uri(), "archive_info": {}})
        on_path(monkeypatch, uvx="/abs/uvx")
        assert connect.launch_command() == ("/abs/uvx", ["--from", str(wheel), "opengsc"])

    def test_falls_back_to_the_bare_tool_name_when_not_on_path(self, monkeypatch):
        installed_from(monkeypatch, None)
        on_path(monkeypatch)
        assert connect.launch_command() == ("uvx", [f"opengsc@{__version__}"])


def never_asked():
    raise AssertionError("asked to replace")


def leftovers(folder, name):
    return sorted(p.name for p in folder.iterdir() if p.name != name)


class TestAddServer:
    def test_creates_a_missing_file_and_its_folder(self, tmp_path):
        path = tmp_path / "App" / "config.json"
        assert connect.add_server(path, "mcpServers", ENTRY, never_asked) == ("added", None)
        assert json.loads(path.read_text()) == {"mcpServers": {"opengsc": ENTRY}}
        assert leftovers(path.parent, path.name) == []

    def test_keeps_other_servers_and_settings_and_backs_up_first(self, tmp_path):
        path = tmp_path / "config.json"
        original = json.dumps(
            {"theme": "dark", "mcpServers": {"other": {"command": "x", "args": []}}}, indent=4
        )
        path.write_text(original)

        status, backup = connect.add_server(path, "mcpServers", ENTRY, never_asked)

        assert status == "added"
        assert json.loads(path.read_text()) == {
            "theme": "dark",
            "mcpServers": {"other": {"command": "x", "args": []}, "opengsc": ENTRY},
        }
        assert backup.parent == tmp_path
        assert backup.name.startswith("config.json.") and backup.name.endswith(".bak")
        assert backup.read_text() == original
        assert leftovers(tmp_path, path.name) == [backup.name]

    def test_adds_the_section_when_missing(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text('{"editor.fontSize": 14}')
        connect.add_server(path, "servers", ENTRY, never_asked)
        assert json.loads(path.read_text()) == {
            "editor.fontSize": 14,
            "servers": {"opengsc": ENTRY},
        }

    def test_an_identical_entry_writes_nothing(self, tmp_path):
        path = tmp_path / "config.json"
        original = json.dumps({"mcpServers": {"opengsc": ENTRY}})
        path.write_text(original)
        assert connect.add_server(path, "mcpServers", ENTRY, never_asked) == ("unchanged", None)
        assert path.read_text() == original
        assert leftovers(tmp_path, path.name) == []

    def test_a_different_entry_is_replaced_only_after_a_yes(self, tmp_path):
        path = tmp_path / "config.json"
        original = json.dumps({"mcpServers": {"opengsc": {"command": "old", "args": []}}})
        path.write_text(original)

        assert connect.add_server(path, "mcpServers", ENTRY, lambda: False) == ("kept", None)
        assert path.read_text() == original
        assert leftovers(tmp_path, path.name) == []

        status, backup = connect.add_server(path, "mcpServers", ENTRY, lambda: True)
        assert status == "updated"
        assert json.loads(path.read_text()) == {"mcpServers": {"opengsc": ENTRY}}
        assert backup.read_text() == original

    @pytest.mark.parametrize(
        "content",
        [
            '{\n  // my servers\n  "mcpServers": {}\n}',  # JSONC comment
            '{"mcpServers": {},}',  # trailing comma
            "[]",
            '{"mcpServers": []}',
        ],
    )
    def test_anything_but_plain_json_is_left_untouched(self, tmp_path, content):
        path = tmp_path / "config.json"
        path.write_text(content)
        with pytest.raises(connect.ConnectError, match="left it untouched"):
            connect.add_server(path, "mcpServers", ENTRY, never_asked)
        assert path.read_text() == content
        assert leftovers(tmp_path, path.name) == []

    def test_reads_a_file_with_a_byte_order_mark(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_bytes(b'\xef\xbb\xbf{"mcpServers": {}}')
        assert connect.add_server(path, "mcpServers", ENTRY, never_asked)[0] == "added"
        assert json.loads(path.read_text(encoding="utf-8")) == {"mcpServers": {"opengsc": ENTRY}}

    def test_an_empty_file_counts_as_empty_settings(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("  \n")
        assert connect.add_server(path, "mcpServers", ENTRY, never_asked)[0] == "added"
        assert json.loads(path.read_text()) == {"mcpServers": {"opengsc": ENTRY}}

    def test_a_failed_replace_keeps_the_original_and_no_temp_file(self, tmp_path, monkeypatch):
        path = tmp_path / "config.json"
        original = json.dumps({"mcpServers": {}})
        path.write_text(original)
        monkeypatch.setattr(connect.os, "replace", mock.Mock(side_effect=OSError("locked")))

        with pytest.raises(connect.ConnectError, match="Cannot write"):
            connect.add_server(path, "mcpServers", ENTRY, never_asked)

        assert path.read_text() == original
        assert not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]

    @pytest.mark.parametrize(
        "raw",
        [
            json.dumps({"mcpServers": {}}).encode("utf-16"),  # PowerShell 5.1 '>' output
            '{"mcpServers": {}, "user": "José"}'.encode("cp1252"),  # old Notepad "ANSI"
        ],
    )
    def test_a_file_that_is_not_utf8_is_left_untouched(self, tmp_path, raw):
        path = tmp_path / "config.json"
        path.write_bytes(raw)
        with pytest.raises(connect.ConnectError, match="left it untouched"):
            connect.add_server(path, "mcpServers", ENTRY, never_asked)
        assert path.read_bytes() == raw
        assert leftovers(tmp_path, path.name) == []

    def test_a_read_only_file_leaves_no_temp_file_when_the_write_fails(self, tmp_path, monkeypatch):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"mcpServers": {}}))
        path.chmod(stat.S_IREAD)
        monkeypatch.setattr(connect.os, "replace", mock.Mock(side_effect=PermissionError("ro")))
        try:
            with pytest.raises(connect.ConnectError, match="Cannot write"):
                connect.add_server(path, "mcpServers", ENTRY, never_asked)
            assert not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
        finally:
            for leftover in tmp_path.iterdir():
                leftover.chmod(stat.S_IREAD | stat.S_IWRITE)

    def test_a_symlinked_config_updates_the_file_it_points_to(self, tmp_path):
        real = tmp_path / "dotfiles" / "config.json"
        real.parent.mkdir()
        real.write_text(json.dumps({"mcpServers": {}}))
        link = tmp_path / "config.json"
        try:
            link.symlink_to(real)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks are not available here")

        connect.add_server(link, "mcpServers", ENTRY, never_asked)

        assert link.is_symlink()
        assert json.loads(real.read_text()) == {"mcpServers": {"opengsc": ENTRY}}


# Captured at import, before the autouse guard in conftest swaps APPS for ().
REAL = {app.name: app for app in connect.APPS}
COMMAND = ("/abs/uvx", ["opengsc@0.2.0"])


def feed(*answers):
    answers = iter(answers)
    return lambda prompt="": next(answers)


@pytest.fixture
def launch(monkeypatch):
    monkeypatch.setattr(connect, "launch_command", lambda: COMMAND)
    on_path(monkeypatch)  # nothing on PATH unless a test says so


def json_app(folder, name, *, installed=False, **kwargs):
    path = folder / name / "mcp.json"
    if installed:
        path.parent.mkdir(parents=True)
    return connect.App(name, f"Restart {name}.", configs=lambda: [path], **kwargs), path


class TestMenu:
    def test_enter_connects_the_apps_found_on_this_computer(
        self, tmp_path, launch, monkeypatch, capsys
    ):
        found, found_path = json_app(tmp_path, "Found", installed=True)
        other, other_path = json_app(tmp_path, "Missing")
        monkeypatch.setattr("builtins.input", feed(""))

        assert connect.choose_and_connect([found, other]) == 0

        out = capsys.readouterr().out
        assert "1. Found  (found on this computer)" in out
        assert "2. Missing\n" in out
        assert json.loads(found_path.read_text()) == {
            "mcpServers": {"opengsc": {"command": "/abs/uvx", "args": ["opengsc@0.2.0"]}}
        }
        assert not other_path.exists()
        assert "Connected." in out and "Next: Restart Found." in out
        assert out.rstrip().endswith(connect.TRY_IT)

    def test_typed_numbers_pick_the_apps(self, tmp_path, launch, monkeypatch):
        found, found_path = json_app(tmp_path, "Found", installed=True)
        other, other_path = json_app(tmp_path, "Missing")
        monkeypatch.setattr("builtins.input", feed(" 2 "))
        assert connect.choose_and_connect([found, other]) == 0
        assert not found_path.exists()
        assert other_path.is_file()

    def test_zero_skips_and_writes_nothing(self, tmp_path, launch, monkeypatch, capsys):
        found, found_path = json_app(tmp_path, "Found", installed=True)
        monkeypatch.setattr("builtins.input", feed("0"))
        assert connect.choose_and_connect([found]) == 0
        assert not found_path.exists()
        assert "opengsc connect" in capsys.readouterr().out

    def test_invalid_answers_ask_again(self, tmp_path, launch, monkeypatch, capsys):
        app, path = json_app(tmp_path, "App")
        monkeypatch.setattr("builtins.input", feed("cursor", "9", "1,1"))
        assert connect.choose_and_connect([app]) == 0
        assert capsys.readouterr().out.count("Please type numbers from 1 to 2") == 2
        assert path.is_file()

    def test_another_app_prints_the_settings_to_copy(self, launch, monkeypatch, capsys):
        monkeypatch.setattr(
            connect, "launch_command", lambda: ("/abs/uv", ["run", "--directory", "/my dir", "x"])
        )
        monkeypatch.setattr("builtins.input", feed(""))  # nothing found: Enter = another app

        assert connect.choose_and_connect([]) == 0

        out = capsys.readouterr().out
        assert "Command:  /abs/uv" in out
        assert "      run\n      --directory\n      /my dir\n      x\n" in out
        snippet = out[out.index("{") : out.rindex("}") + 1]
        assert json.loads(snippet) == {
            "mcpServers": {
                "opengsc": {"command": "/abs/uv", "args": ["run", "--directory", "/my dir", "x"]}
            }
        }
        assert "web browser" in out

    def test_quit_cancels_without_writing(self, tmp_path, launch, monkeypatch, capsys):
        app, path = json_app(tmp_path, "App", installed=True)
        monkeypatch.setattr(connect, "APPS", (app,))
        monkeypatch.setattr("builtins.input", feed("q"))
        assert connect.run() == 2
        assert "connect cancelled" in capsys.readouterr().err
        assert not path.exists()


class TestJsonApps:
    def test_a_file_it_cannot_edit_gets_manual_steps_and_the_rest_still_run(
        self, tmp_path, launch, monkeypatch, capsys
    ):
        broken, broken_path = json_app(tmp_path, "Broken", installed=True)
        broken_path.write_text('{\n  // mine\n  "mcpServers": {}\n}')
        fine, fine_path = json_app(tmp_path, "Fine", installed=True)
        monkeypatch.setattr("builtins.input", feed(""))

        assert connect.choose_and_connect([broken, fine]) == 1

        out = capsys.readouterr().out
        assert "Could not connect it automatically" in out
        assert f"Do it by hand: open {broken_path}" in out
        assert '"opengsc": {' in out
        assert broken_path.read_text() == '{\n  // mine\n  "mcpServers": {}\n}'
        assert fine_path.is_file()
        assert "manual step" in out

    def test_an_app_that_rewrites_its_config_is_closed_first(
        self, tmp_path, launch, monkeypatch, capsys
    ):
        app, path = json_app(tmp_path, "Desk", installed=True, close_first=True)
        prompts = []

        def answer(prompt=""):
            prompts.append((prompt, path.exists()))
            return ""

        monkeypatch.setattr("builtins.input", answer)
        assert connect.choose_and_connect([app]) == 0
        assert "Quit Desk completely" in capsys.readouterr().out
        closed = [p for p in prompts if "once it is closed" in p[0]]
        assert closed == [(closed[0][0], False)]  # asked once, before the file was written
        assert path.is_file()

    def test_every_existing_config_copy_is_updated_after_one_question(
        self, tmp_path, launch, monkeypatch, capsys
    ):
        copies = [tmp_path / "a" / "c.json", tmp_path / "b" / "c.json"]
        for copy in copies:
            copy.parent.mkdir()
            copy.write_text(json.dumps({"mcpServers": {"opengsc": {"command": "old"}}}))
        app = connect.App("Desk", "Reopen it.", configs=lambda: copies)
        monkeypatch.setattr("builtins.input", feed("", "y"))

        assert connect.choose_and_connect([app]) == 0

        for copy in copies:
            assert json.loads(copy.read_text())["mcpServers"]["opengsc"]["command"] == "/abs/uvx"
        out = capsys.readouterr().out
        assert "replaced the old opengsc entry" in out
        assert out.count("Backup of the previous file") == 2

    def test_a_failing_copy_is_named_and_the_updated_one_is_reported(
        self, tmp_path, launch, monkeypatch, capsys
    ):
        good, bad = tmp_path / "a" / "c.json", tmp_path / "b" / "c.json"
        good.parent.mkdir()
        bad.parent.mkdir()
        bad.write_text('{ // mine\n  "mcpServers": {}\n}')
        app = connect.App("Desk", "Reopen it.", configs=lambda: [good, bad])
        monkeypatch.setattr("builtins.input", feed(""))

        assert connect.choose_and_connect([app]) == 1

        out = capsys.readouterr().out
        assert f"Settings file: {good}" in out
        assert f"Do it by hand: open {bad}" in out
        assert f"Do it by hand: open {good}" not in out

    def test_an_already_connected_app_is_not_asked_to_close(
        self, tmp_path, launch, monkeypatch, capsys
    ):
        app, path = json_app(tmp_path, "Desk", installed=True, close_first=True)
        path.write_text(json.dumps({"mcpServers": {"opengsc": app.entry(*COMMAND)}}))
        monkeypatch.setattr("builtins.input", feed(""))  # the menu is the only prompt

        assert connect.choose_and_connect([app]) == 0

        out = capsys.readouterr().out
        assert "Quit Desk" not in out
        assert "Already connected" in out

    def test_entry_shapes(self):
        assert REAL["VS Code (GitHub Copilot)"].section == "servers"
        assert REAL["VS Code (GitHub Copilot)"].entry(*COMMAND) == {
            "type": "stdio",
            "command": "/abs/uvx",
            "args": ["opengsc@0.2.0"],
        }
        assert REAL["Cursor"].entry(*COMMAND)["type"] == "stdio"
        assert REAL["Claude Desktop"].entry(*COMMAND) == {
            "command": "/abs/uvx",
            "args": ["opengsc@0.2.0"],
        }


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(connect.Path, "home", classmethod(lambda cls: tmp_path))
    for var in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "CODEX_HOME"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


class TestRealAppPaths:
    def test_claude_desktop_on_windows_includes_the_store_copy(self, home, monkeypatch):
        monkeypatch.setattr(connect.sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", str(home / "Roaming"))
        monkeypatch.setenv("LOCALAPPDATA", str(home / "Local"))
        classic = home / "Roaming" / "Claude" / "claude_desktop_config.json"
        store = (
            home / "Local" / "Packages" / "Claude_pzs8sxrjxfjjc"
            / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"
        )  # fmt: skip
        classic.parent.mkdir(parents=True)
        store.parent.mkdir(parents=True)
        assert REAL["Claude Desktop"].targets() == [classic, store]

    def test_claude_desktop_on_macos(self, home, monkeypatch):
        monkeypatch.setattr(connect.sys, "platform", "darwin")
        expected = home / "Library" / "Application Support" / "Claude"
        assert REAL["Claude Desktop"].targets() == [expected / "claude_desktop_config.json"]

    def test_vs_code_on_linux_follows_xdg(self, home, monkeypatch):
        monkeypatch.setattr(connect.sys, "platform", "linux")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "xdg"))
        assert REAL["VS Code (GitHub Copilot)"].targets() == [
            home / "xdg" / "Code" / "User" / "mcp.json"
        ]

    def test_windsurf_file_is_used_only_when_it_is_there(self, home, monkeypatch):
        monkeypatch.setattr(connect.sys, "platform", "linux")
        devin = home / ".config" / "devin" / "mcp_config.json"
        windsurf = home / ".codeium" / "windsurf" / "mcp_config.json"
        assert REAL["Windsurf / Devin Desktop"].targets() == [devin]
        windsurf.parent.mkdir(parents=True)
        assert REAL["Windsurf / Devin Desktop"].targets() == [windsurf]

    def test_gemini_is_not_found_from_the_folder_it_shares(self, home, monkeypatch):
        on_path(monkeypatch)
        (home / ".gemini" / "config").mkdir(parents=True)
        assert not REAL["Gemini CLI"].found()
        assert REAL["Google Antigravity"].found()
        (home / ".gemini" / "settings.json").write_text("{}")
        assert REAL["Gemini CLI"].found()


class TestCliApps:
    def test_claude_code_adds_a_user_scoped_server(self, launch, monkeypatch, capsys):
        on_path(monkeypatch, claude="/bin/claude")
        run = mock.Mock(return_value=(0, ""))
        monkeypatch.setattr(connect, "_run", run)
        monkeypatch.setattr("builtins.input", feed(""))

        assert connect.choose_and_connect([REAL["Claude Code"]]) == 0

        run.assert_called_once_with(
            ["/bin/claude", "mcp", "add", "--scope", "user", "opengsc", "--"]
            + ["/abs/uvx", "opengsc@0.2.0"]
        )
        assert "Next: Start a new Claude Code session." in capsys.readouterr().out

    @pytest.mark.parametrize("answer", ["n", "y"])
    def test_claude_code_replaces_an_existing_entry_only_after_a_yes(
        self, launch, monkeypatch, capsys, answer
    ):
        on_path(monkeypatch, claude="/bin/claude")
        run = mock.Mock(
            side_effect=[
                (1, "MCP server opengsc already exists in user config\n"),
                (0, ""),
                (0, ""),
            ]
        )
        monkeypatch.setattr(connect, "_run", run)
        monkeypatch.setattr("builtins.input", feed("", answer))

        assert connect.choose_and_connect([REAL["Claude Code"]]) == 0

        argvs = [c.args[0][1:3] for c in run.call_args_list]
        if answer == "n":
            assert argvs == [["mcp", "add"]]
            assert "Kept your existing opengsc entry" in capsys.readouterr().out
        else:
            assert argvs == [["mcp", "add"], ["mcp", "remove"], ["mcp", "add"]]
            assert "replaced the old opengsc entry" in capsys.readouterr().out

    @pytest.mark.parametrize("answer", ["n", "y"])
    def test_codex_asks_before_overwriting_its_entry(self, launch, monkeypatch, answer):
        # Codex itself answers whether it has an entry, in any TOML spelling.
        on_path(monkeypatch, codex="/bin/codex")
        run = mock.Mock(return_value=(0, ""))
        monkeypatch.setattr(connect, "_run", run)
        prompts = []
        answers = iter(["", answer])

        def reply(prompt=""):
            prompts.append(prompt)
            return next(answers)

        monkeypatch.setattr("builtins.input", reply)

        assert connect.choose_and_connect([REAL["Codex (OpenAI)"]]) == 0

        calls = [c.args[0] for c in run.call_args_list]
        assert calls[0] == ["/bin/codex", "mcp", "get", "opengsc"]
        assert "already has an opengsc entry" in prompts[1]
        if answer == "n":
            assert calls == calls[:1]
        else:
            assert calls[1:] == [
                ["/bin/codex", "mcp", "add", "opengsc", "--", "/abs/uvx", "opengsc@0.2.0"]
            ]

    def test_codex_adds_without_asking_when_it_has_no_entry(self, launch, monkeypatch):
        on_path(monkeypatch, codex="/bin/codex")
        run = mock.Mock(side_effect=[(1, "Error: No MCP server named 'opengsc' found."), (0, "")])
        monkeypatch.setattr(connect, "_run", run)
        monkeypatch.setattr("builtins.input", feed(""))
        assert connect.choose_and_connect([REAL["Codex (OpenAI)"]]) == 0
        assert run.call_args_list[1].args[0][1:3] == ["mcp", "add"]

    def test_claude_code_says_the_old_entry_is_gone_when_the_new_add_fails(
        self, launch, monkeypatch, capsys
    ):
        on_path(monkeypatch, claude="/bin/claude")
        monkeypatch.setattr(
            connect,
            "_run",
            mock.Mock(side_effect=[(1, "MCP server opengsc already exists"), (0, ""), (1, "boom")]),
        )
        monkeypatch.setattr("builtins.input", feed("", "y"))
        assert connect.choose_and_connect([REAL["Claude Code"]]) == 1
        out = capsys.readouterr().out
        assert "old entry was already removed" in out
        assert "claude mcp add --scope user opengsc -- /abs/uvx opengsc@0.2.0" in out

    def test_a_missing_cli_prints_the_command_to_run(self, launch, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", feed("1"))
        assert connect.choose_and_connect([REAL["Claude Code"]]) == 1
        out = capsys.readouterr().out
        assert "the 'claude' command was not found" in out
        assert "claude mcp add --scope user opengsc -- /abs/uvx opengsc@0.2.0" in out

    def test_a_failing_cli_reports_its_last_line(self, launch, monkeypatch, capsys):
        on_path(monkeypatch, codex="/bin/codex")
        monkeypatch.setattr(connect, "_run", mock.Mock(return_value=(2, "noise\nconfig locked\n")))
        monkeypatch.setattr("builtins.input", feed(""))
        assert connect.choose_and_connect([REAL["Codex (OpenAI)"]]) == 1
        assert "'codex mcp add' failed: config locked" in capsys.readouterr().out
