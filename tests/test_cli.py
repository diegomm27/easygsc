"""Tests for the CLI: serve (default), auth, doctor. All dependencies mocked."""

import json
from unittest import mock

import pytest

from opengsc import cli
from opengsc.api import ApiError


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    from opengsc import auth

    d = tmp_path / "opengsc-config"
    d.mkdir()
    monkeypatch.setattr(auth, "CONFIG_DIR", d)
    monkeypatch.setattr(auth, "TOKEN_PATH", d / "token.json")
    monkeypatch.setattr(auth, "CLIENT_SECRET_PATH", d / "client_secret.json")
    return d


class TestServe:
    def test_no_args_runs_mcp_server_over_stdio(self, monkeypatch):
        ran = {}
        monkeypatch.setattr(cli.server, "run", lambda: ran.setdefault("ran", True))
        assert cli.main([]) == 0
        assert ran.get("ran") is True

    def test_explicit_serve_also_works(self, monkeypatch):
        ran = {}
        monkeypatch.setattr(cli.server, "run", lambda: ran.setdefault("ran", True))
        assert cli.main(["serve"]) == 0
        assert ran.get("ran") is True


class TestAuth:
    def test_auth_runs_flow(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            cli.auth, "run_oauth_flow", lambda no_browser: seen.setdefault("nb", no_browser)
        )
        assert cli.main(["auth"]) == 0
        assert seen["nb"] is False

    def test_auth_no_browser(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            cli.auth, "run_oauth_flow", lambda no_browser: seen.setdefault("nb", no_browser)
        )
        assert cli.main(["auth", "--no-browser"]) == 0
        assert seen["nb"] is True

    def test_auth_failure_returns_1_and_reports_to_stderr(self, monkeypatch, capsys):
        def boom(no_browser):
            raise cli.auth.AuthError("no client configured")

        monkeypatch.setattr(cli.auth, "run_oauth_flow", boom)
        assert cli.main(["auth"]) == 1
        err = capsys.readouterr().err
        assert "no client configured" in err


class TestDoctor:
    def test_no_auth_exits_1_and_shows_paths_and_version(self, config_dir, monkeypatch, capsys):
        monkeypatch.delenv("OPENGSC_SERVICE_ACCOUNT_FILE", raising=False)
        code = cli.main(["doctor"])
        assert code == 1
        out = capsys.readouterr().out
        assert "opengsc" in out  # version
        assert str(config_dir) in out
        assert "none" in out  # auth mode

    def test_token_mode_counts_properties(self, config_dir, monkeypatch, capsys):
        monkeypatch.delenv("OPENGSC_SERVICE_ACCOUNT_FILE", raising=False)
        config_dir.joinpath("token.json").write_text(
            json.dumps(
                {
                    "refresh_token": "1//SECRET_REFRESH_VALUE",
                    "client_id": "c",
                    "client_secret": "s",
                    "token": "ya29.SECRET",
                    "expiry": "2026-03-01T00:00:00Z",
                }
            )
        )
        monkeypatch.setattr(
            cli.api,
            "list_sites",
            lambda *a, **k: {
                "siteEntry": [
                    {"siteUrl": "sc-domain:example.com", "permissionLevel": "siteOwner"},
                    {"siteUrl": "https://x.com/", "permissionLevel": "siteFullUser"},
                ]
            },
        )
        assert cli.main(["doctor"]) == 0
        out = capsys.readouterr().out
        assert "oauth-token" in out
        assert "2026-03-01T00:00:00Z" in out
        assert "2" in out  # readable property count
        assert "1//SECRET_REFRESH_VALUE" not in out
        assert "ya29.SECRET" not in out

    def test_service_account_mode(self, config_dir, monkeypatch, capsys):
        from tests.test_auth import SA_FILE

        sa_path = config_dir / "sa.json"
        sa_path.write_text(json.dumps(SA_FILE))
        monkeypatch.setenv("OPENGSC_SERVICE_ACCOUNT_FILE", str(sa_path))
        monkeypatch.setattr(
            cli.api, "list_sites", lambda *a, **k: {"siteEntry": [{"siteUrl": "s"}]}
        )
        assert cli.main(["doctor"]) == 0
        assert "service-account" in capsys.readouterr().out

    def test_api_failure_exits_1_and_reports(self, config_dir, monkeypatch, capsys):
        monkeypatch.delenv("OPENGSC_SERVICE_ACCOUNT_FILE", raising=False)
        config_dir.joinpath("token.json").write_text(json.dumps({"refresh_token": "r"}))
        monkeypatch.setattr(
            cli.api, "list_sites", mock.MagicMock(side_effect=ApiError(401, "denied"))
        )
        assert cli.main(["doctor"]) == 1
        assert "401" in capsys.readouterr().out

    def test_unknown_property_count_failure_does_not_mask_mode(
        self, config_dir, monkeypatch, capsys
    ):
        monkeypatch.delenv("OPENGSC_SERVICE_ACCOUNT_FILE", raising=False)
        config_dir.joinpath("token.json").write_text(json.dumps({"refresh_token": "r"}))
        monkeypatch.setattr(
            cli.api, "list_sites", mock.MagicMock(side_effect=ApiError(403, "denied"))
        )
        code = cli.main(["doctor"])
        out = capsys.readouterr().out
        assert code == 1
        assert "oauth-token" in out


class TestLogging:
    def test_logs_go_to_stderr_not_stdout(self, capsys):
        import logging

        # Bind the handler to the current (captured) stderr, exactly as a
        # fresh main() invocation would.
        cli._setup_logging()
        logging.getLogger("opengsc").error("an error line")
        captured = capsys.readouterr()
        assert "an error line" in captured.err
