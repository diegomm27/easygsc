"""Tests for connecting opengsc to AI apps: files, PATH and app CLIs all faked."""

import json
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
