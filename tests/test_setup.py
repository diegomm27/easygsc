"""Tests for the guided setup wizard: input, browser, files and HTTP all mocked."""

import json
import os
import stat
from unittest import mock

import pytest

from opengsc import api, cli, setup

SECRET = "SECRET-XYZ-123"
REFRESH = "1//REFRESH-SECRET"


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    from opengsc import auth

    d = tmp_path / "opengsc-config"
    monkeypatch.setattr(auth, "CONFIG_DIR", d)
    monkeypatch.setattr(auth, "TOKEN_PATH", d / "token.json")
    monkeypatch.setattr(auth, "CLIENT_SECRET_PATH", d / "client_secret.json")
    for var in (
        "OPENGSC_CLIENT_ID",
        "OPENGSC_CLIENT_SECRET",
        "OPENGSC_SERVICE_ACCOUNT_FILE",
        "OPENGSC_REFRESH_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)
    return d


@pytest.fixture
def downloads(tmp_path, monkeypatch):
    d = tmp_path / "Downloads"
    d.mkdir()
    monkeypatch.setattr(setup, "DOWNLOADS_DIR", d)
    return d


def write_client(path, client_id="cid", secret=SECRET, key="installed"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({key: {"client_id": client_id, "client_secret": secret}}))
    return path


# One Enter per walkthrough step, decline deleting the download, then Enter at the
# connect menu (conftest leaves no real apps, so Enter shows the settings to copy).
WALKTHROUGH = ("",) * 8


def feed(*answers):
    answers = iter(answers)
    return lambda prompt="": next(answers)


def write_token(config_dir):
    config_dir.mkdir(parents=True, exist_ok=True)
    token = {
        "refresh_token": REFRESH,
        "client_id": "cid",
        "client_secret": SECRET,
        "token": "ya29.ACCESS-SECRET",
    }
    (config_dir / "token.json").write_text(json.dumps(token))


def fake_auth(config_dir, calls=None, kwargs_seen=None):
    def run(no_browser=False, **kwargs):
        if calls is not None:
            calls.append(no_browser)
        if kwargs_seen is not None:
            kwargs_seen.append(kwargs)
        write_token(config_dir)

    return run


def doctor_ok(monkeypatch):
    monkeypatch.setattr(api, "list_sites", lambda *a, **k: {"siteEntry": [{"siteUrl": "s"}]})


class TestFindDownloaded:
    def test_picks_the_newest_including_json_json(self, downloads):
        old = write_client(downloads / "client_secret_old.json")
        new = write_client(downloads / "client_secret_new.json.json")
        os.utime(old, (1_000, 1_000))
        os.utime(new, (2_000, 2_000))
        assert setup.find_downloaded(downloads) == new

    def test_ignores_unrelated_json(self, downloads):
        (downloads / "notes.json").write_text("{}")
        assert setup.find_downloaded(downloads) is None

    def test_returns_none_for_an_empty_folder(self, downloads):
        assert setup.find_downloaded(downloads) is None

    def test_a_tie_is_ambiguous(self, downloads):
        a = write_client(downloads / "client_secret_a.json")
        b = write_client(downloads / "client_secret_b.json")
        os.utime(a, (5_000, 5_000))
        os.utime(b, (5_000, 5_000))
        assert setup.find_downloaded(downloads) is None


class TestLoadClient:
    def test_accepts_an_installed_client(self, tmp_path):
        path = write_client(tmp_path / "client_secret.json")
        assert setup.load_client(path)["installed"]["client_id"] == "cid"

    def test_rejects_a_web_client_and_explains_why(self, tmp_path):
        path = write_client(tmp_path / "web.json", key="web")
        with pytest.raises(setup.WebClientError, match="Desktop app"):
            setup.load_client(path)

    def test_rejects_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json")
        with pytest.raises(setup.SetupError, match="not valid JSON"):
            setup.load_client(path)

    def test_rejects_json_that_is_not_an_object(self, tmp_path):
        path = tmp_path / "array.json"
        path.write_text("[]")
        with pytest.raises(setup.SetupError, match="no 'installed' key"):
            setup.load_client(path)

    def test_rejects_installed_without_secret(self, tmp_path):
        path = tmp_path / "partial.json"
        path.write_text(json.dumps({"installed": {"client_id": "cid"}}))
        with pytest.raises(setup.SetupError, match="client_id/client_secret"):
            setup.load_client(path)


class TestObtainClient:
    def test_strips_quotes_from_a_pasted_path(self, downloads, tmp_path, monkeypatch, capsys):
        good = write_client(tmp_path / "downloaded" / "client_secret.json")
        monkeypatch.setattr("builtins.input", feed(f'  "{good}"  '))
        assert setup._obtain_client(no_browser=True) == good
        assert SECRET not in capsys.readouterr().out

    def test_web_client_loops_back_to_the_client_step(self, downloads, monkeypatch, capsys):
        web = write_client(downloads / "client_secret_web.json", key="web")
        desktop = write_client(downloads / "client_secret_desktop.json")
        monkeypatch.setattr(setup, "find_downloaded", mock.Mock(side_effect=[web, desktop]))
        monkeypatch.setattr("builtins.input", feed(""))
        assert setup._obtain_client(no_browser=True) == desktop
        out = capsys.readouterr().out
        assert setup.CLIENT_URL in out
        assert setup.PUBLISH_URL not in out
        assert "Desktop app" in out

    def test_invalid_json_asks_for_a_path(self, downloads, monkeypatch, capsys):
        bad = downloads / "client_secret_bad.json"
        bad.write_text("{not json")
        good = write_client(downloads / "client_secret_good.json")
        monkeypatch.setattr(setup, "find_downloaded", mock.Mock(side_effect=[bad, good]))
        monkeypatch.setattr("builtins.input", feed(str(good)))
        assert setup._obtain_client(no_browser=True) == good
        assert "not valid JSON" in capsys.readouterr().out


class TestInstallClient:
    def test_copies_without_moving_the_source(self, config_dir, tmp_path):
        source = write_client(tmp_path / "Downloads" / "client_secret.json")
        dest = setup.install_client(source)
        assert dest == config_dir / "client_secret.json"
        assert source.is_file()
        assert json.loads(dest.read_text())["installed"]["client_secret"] == SECRET

    @pytest.mark.skipif(os.name != "posix", reason="0600 permissions are POSIX-only")
    def test_installed_file_has_0600(self, config_dir, tmp_path):
        source = write_client(tmp_path / "client_secret.json")
        dest = setup.install_client(source)
        assert stat.S_IMODE(os.stat(dest).st_mode) == 0o600

    def test_asks_before_overwriting_a_different_file(self, config_dir, tmp_path, monkeypatch):
        dest = write_client(config_dir / "client_secret.json", secret="OLD-SECRET")
        source = write_client(tmp_path / "client_secret.json", secret="NEW-SECRET")
        monkeypatch.setattr("builtins.input", feed("n"))
        setup.install_client(source)
        assert json.loads(dest.read_text())["installed"]["client_secret"] == "OLD-SECRET"
        monkeypatch.setattr("builtins.input", feed("y"))
        setup.install_client(source)
        assert json.loads(dest.read_text())["installed"]["client_secret"] == "NEW-SECRET"

    def test_failed_replace_keeps_the_previous_file(self, config_dir, tmp_path, monkeypatch):
        dest = write_client(config_dir / "client_secret.json", secret="OLD-SECRET")
        source = write_client(tmp_path / "client_secret.json", secret="NEW-SECRET")
        monkeypatch.setattr("builtins.input", feed("y"))
        monkeypatch.setattr(setup.os, "replace", mock.Mock(side_effect=OSError("boom")))
        with pytest.raises(OSError):
            setup.install_client(source)
        assert json.loads(dest.read_text())["installed"]["client_secret"] == "OLD-SECRET"
        assert sorted(p.name for p in config_dir.iterdir()) == ["client_secret.json"]

    def test_writes_no_temporary_files(self, config_dir, tmp_path):
        source = write_client(tmp_path / "client_secret.json")
        setup.install_client(source)
        assert sorted(p.name for p in config_dir.iterdir()) == ["client_secret.json"]

    def test_identical_file_does_not_prompt(self, config_dir, tmp_path, monkeypatch):
        dest = write_client(config_dir / "client_secret.json", secret=SECRET)
        source = write_client(tmp_path / "client_secret.json", secret=SECRET)
        monkeypatch.setattr("builtins.input", mock.Mock(side_effect=AssertionError("prompted")))
        setup.install_client(source)
        assert json.loads(dest.read_text())["installed"]["client_secret"] == SECRET


class TestShortCircuit:
    def test_ready_when_client_and_token_work(self, config_dir, downloads, monkeypatch, capsys):
        write_client(config_dir / "client_secret.json")
        write_token(config_dir)
        doctor_ok(monkeypatch)
        run_flow = mock.Mock()
        monkeypatch.setattr(setup.auth, "run_oauth_flow", run_flow)
        opener = mock.Mock(return_value=True)
        monkeypatch.setattr(setup.webbrowser, "open", opener)
        monkeypatch.setattr("builtins.input", feed(""))

        assert setup.run() == 0
        out = capsys.readouterr().out
        assert "Everything is ready" in out
        assert "Connect opengsc to your AI apps" in out
        assert "console.cloud.google.com" not in out
        assert SECRET not in out
        run_flow.assert_not_called()
        opener.assert_not_called()

    def test_offers_auth_when_the_client_exists_but_the_token_does_not(
        self, config_dir, downloads, monkeypatch, capsys
    ):
        write_client(config_dir / "client_secret.json")
        doctor_ok(monkeypatch)
        calls = []
        monkeypatch.setattr(setup.auth, "run_oauth_flow", fake_auth(config_dir, calls))
        monkeypatch.setattr("builtins.input", feed("", ""))
        opener = mock.Mock(return_value=True)
        monkeypatch.setattr(setup.webbrowser, "open", opener)

        assert setup.run(no_browser=True) == 0
        assert calls == [True]
        out = capsys.readouterr().out
        assert "already has an OAuth client" in out
        assert "console.cloud.google.com" not in out
        opener.assert_not_called()

    def test_env_client_is_reported(self, config_dir, downloads, monkeypatch, capsys):
        monkeypatch.setenv("OPENGSC_CLIENT_ID", "env-id")
        monkeypatch.setenv("OPENGSC_CLIENT_SECRET", "env-secret")
        doctor_ok(monkeypatch)
        monkeypatch.setattr(setup.auth, "run_oauth_flow", fake_auth(config_dir))
        monkeypatch.setattr("builtins.input", feed("", ""))

        assert setup.run(no_browser=True) == 0
        out = capsys.readouterr().out
        assert "OPENGSC_CLIENT_ID" in out
        assert "env-secret" not in out


class TestWalkthrough:
    def test_no_browser_prints_urls_and_never_opens_a_browser(
        self, config_dir, downloads, monkeypatch, capsys
    ):
        write_client(downloads / "client_secret_1.json")
        doctor_ok(monkeypatch)
        calls = []
        monkeypatch.setattr(setup.auth, "run_oauth_flow", fake_auth(config_dir, calls))
        opener = mock.Mock(return_value=True)
        monkeypatch.setattr(setup.webbrowser, "open", opener)
        monkeypatch.setattr("builtins.input", feed(*WALKTHROUGH))

        assert setup.run(no_browser=True) == 0
        out = capsys.readouterr().out
        for url, _ in setup.STEPS:
            assert url in out
        assert calls == [True]
        opener.assert_not_called()
        # Setup ends at the connect menu; its settings start this exact opengsc.
        command, args = setup.connect.launch_command()
        assert "Connect opengsc to your AI apps" in out
        assert f"Command:  {command}" in out
        assert all(f"      {arg}\n" in out for arg in args)

    def test_default_mode_opens_the_browser_for_every_step(
        self, config_dir, downloads, monkeypatch
    ):
        write_client(downloads / "client_secret_1.json")
        doctor_ok(monkeypatch)
        monkeypatch.setattr(setup.auth, "run_oauth_flow", fake_auth(config_dir))
        opener = mock.Mock(return_value=True)
        monkeypatch.setattr(setup.webbrowser, "open", opener)
        monkeypatch.setattr("builtins.input", feed(*WALKTHROUGH))

        assert setup.run() == 0
        # The client is created right after the consent screen, as the console offers
        # it there; Google only lets you publish once Branding has its links.
        assert [c.args[0] for c in opener.call_args_list] == [
            setup.PROJECT_URL,
            setup.API_URL,
            setup.CONSENT_URL,
            setup.CLIENT_URL,
            setup.BRANDING_URL,
            setup.PUBLISH_URL,
        ]

    def test_branding_step_lists_the_links_and_warns_about_the_logo(
        self, config_dir, downloads, monkeypatch, capsys
    ):
        write_client(downloads / "client_secret_1.json")
        doctor_ok(monkeypatch)
        monkeypatch.setattr(setup.auth, "run_oauth_flow", fake_auth(config_dir))
        monkeypatch.setattr("builtins.input", feed(*WALKTHROUGH))

        assert setup.run(no_browser=True) == 0
        out = capsys.readouterr().out
        branding = out[out.index("Fill in Branding") : out.index(setup.BRANDING_URL)]
        # The consent screen belongs to the user's own app: it points at their site,
        # whose domain they already verified in Search Console.
        assert "your website" in branding
        assert "your domain" in branding
        assert "logo" in branding.lower()
        # Fallback for sites without a privacy page.
        assert setup.PRIVACY_URL in branding

    def test_the_secret_never_reaches_stdout(self, config_dir, downloads, monkeypatch, capsys):
        write_client(downloads / "client_secret_1.json")
        doctor_ok(monkeypatch)
        monkeypatch.setattr(setup.auth, "run_oauth_flow", fake_auth(config_dir))
        monkeypatch.setattr(setup.webbrowser, "open", mock.Mock(return_value=True))
        monkeypatch.setattr("builtins.input", feed(*WALKTHROUGH))

        assert setup.run(no_browser=True) == 0
        captured = capsys.readouterr()
        assert SECRET not in captured.out
        assert SECRET not in captured.err


class TestSecretOutput:
    def test_auth_suppresses_the_refresh_token_and_reports_the_token_path(
        self, config_dir, downloads, monkeypatch, capsys
    ):
        write_client(config_dir / "client_secret.json")
        doctor_ok(monkeypatch)
        seen = []
        monkeypatch.setattr(setup.auth, "run_oauth_flow", fake_auth(config_dir, kwargs_seen=seen))
        monkeypatch.setattr("builtins.input", feed("", ""))

        assert setup.run(no_browser=True) == 0
        out = capsys.readouterr().out
        assert seen == [{"print_refresh_token": False}]
        assert "Authenticated" in out
        assert str(config_dir / "token.json") in out
        assert "OPENGSC_REFRESH_TOKEN" not in out
        assert SECRET not in out

    def test_auth_failure_returns_1_and_reports_on_stderr(self, config_dir, monkeypatch, capsys):
        write_client(config_dir / "client_secret.json")
        monkeypatch.setattr(
            setup.auth,
            "run_oauth_flow",
            mock.Mock(side_effect=setup.auth.AuthError("denied")),
        )
        monkeypatch.setattr("builtins.input", feed(""))

        assert setup.run(no_browser=True) == 1
        captured = capsys.readouterr()
        assert "auth failed: denied" in captured.err
        assert "opengsc setup" in captured.err
        assert "Connect opengsc to your AI apps" not in captured.out

    def test_error_text_redacts_client_secret_and_refresh_token(
        self, config_dir, monkeypatch, capsys
    ):
        write_client(config_dir / "client_secret.json")
        write_token(config_dir)
        monkeypatch.setattr(
            setup.auth,
            "run_oauth_flow",
            mock.Mock(side_effect=setup.auth.AuthError(f"bad {SECRET} / {REFRESH}")),
        )

        assert setup._authenticate(no_browser=True) == 1
        err = capsys.readouterr().err
        assert SECRET not in err
        assert REFRESH not in err
        assert "***" in err

    def test_setup_error_message_redacts_secrets(self, config_dir, monkeypatch, capsys):
        write_client(config_dir / "client_secret.json")
        monkeypatch.setattr(
            setup, "_run", mock.Mock(side_effect=setup.SetupError(f"boom {SECRET}"))
        )

        assert setup.run() == 1
        err = capsys.readouterr().err
        assert SECRET not in err
        assert "***" in err

    def test_obtain_client_error_is_redacted(self, config_dir, downloads, monkeypatch, capsys):
        write_client(config_dir / "client_secret.json")
        monkeypatch.setattr(setup, "find_downloaded", lambda: downloads / "x.json")
        monkeypatch.setattr(
            setup, "load_client", mock.Mock(side_effect=setup.SetupError(f"bad {SECRET}"))
        )
        monkeypatch.setattr("builtins.input", mock.Mock(side_effect=EOFError))

        with pytest.raises(setup.Cancelled):
            setup._obtain_client(no_browser=True)
        out = capsys.readouterr().out
        assert SECRET not in out
        assert "***" in out


class TestCancellation:
    def test_eof_at_the_path_prompt_cancels(self, config_dir, downloads, monkeypatch, capsys):
        monkeypatch.setattr(setup.webbrowser, "open", mock.Mock(return_value=True))
        monkeypatch.setattr("builtins.input", mock.Mock(side_effect=EOFError))
        assert setup.run() == 2
        err = capsys.readouterr().err
        assert "cancelled" in err
        assert "opengsc setup" in err

    def test_quit_at_a_step_prompt_cancels(self, config_dir, downloads, monkeypatch, capsys):
        monkeypatch.setattr(setup.webbrowser, "open", mock.Mock(return_value=True))
        monkeypatch.setattr("builtins.input", feed("q"))
        assert setup.run() == 2
        assert "cancelled" in capsys.readouterr().err

    def test_quit_at_a_confirm_prompt_cancels(self, config_dir, downloads, monkeypatch, capsys):
        write_client(config_dir / "client_secret.json")
        monkeypatch.setattr("builtins.input", feed("quit"))
        assert setup.run(no_browser=True) == 2
        assert "cancelled" in capsys.readouterr().err

    def test_quit_at_the_connect_menu_says_the_login_is_saved(
        self, config_dir, downloads, monkeypatch, capsys
    ):
        write_client(config_dir / "client_secret.json")
        doctor_ok(monkeypatch)
        monkeypatch.setattr(setup.auth, "run_oauth_flow", fake_auth(config_dir))
        monkeypatch.setattr("builtins.input", feed("", "q"))

        assert setup.run(no_browser=True) == 2
        captured = capsys.readouterr()
        assert "Authenticated" in captured.out
        assert "login is saved" in captured.err
        assert "opengsc connect" in captured.err


class TestInterrupt:
    def test_keyboard_interrupt_exits_130(self, config_dir, monkeypatch, capsys):
        monkeypatch.setattr(setup.webbrowser, "open", mock.Mock(return_value=True))
        monkeypatch.setattr("builtins.input", mock.Mock(side_effect=KeyboardInterrupt))

        assert cli.main(["setup"]) == 130
        err = capsys.readouterr().err
        assert "opengsc setup" in err
        assert "again" in err
