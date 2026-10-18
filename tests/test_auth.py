"""Tests for credential resolution, the OAuth flow, and token storage.

No network: the flow and all HTTP are mocked. Config paths are redirected
into a temporary directory via monkeypatching opengsc.auth module constants.
"""

import json
import os
import stat
from unittest import mock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.oauth2 import service_account as ga_service_account

from opengsc import auth
from opengsc.allowlist import GuardedSessionMixin


# A throwaway RSA key so service-account loading runs for real (no network).
def _make_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return pem.decode()


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    d = tmp_path / "opengsc-config"
    d.mkdir()
    monkeypatch.setattr(auth, "CONFIG_DIR", d)
    monkeypatch.setattr(auth, "TOKEN_PATH", d / "token.json")
    monkeypatch.setattr(auth, "CLIENT_SECRET_PATH", d / "client_secret.json")
    return d


SA_FILE = {
    "type": "service_account",
    "project_id": "p",
    "private_key_id": "k",
    "private_key": _make_pem(),
    "client_email": "sa@p.iam.gserviceaccount.com",
    "client_id": "123",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
}


class TestResolutionOrder:
    def test_service_account_env_var_wins(self, config_dir, monkeypatch):
        sa_path = config_dir / "sa.json"
        sa_path.write_text(json.dumps(SA_FILE))
        (config_dir / "token.json").write_text(json.dumps({"refresh_token": "r"}))
        monkeypatch.setenv("OPENGSC_SERVICE_ACCOUNT_FILE", str(sa_path))
        creds = auth.resolve_credentials()
        assert isinstance(creds, ga_service_account.Credentials)

    def test_token_json_next(self, config_dir, monkeypatch):
        monkeypatch.delenv("OPENGSC_SERVICE_ACCOUNT_FILE", raising=False)
        token = {
            "refresh_token": "r",
            "client_id": "cid",
            "client_secret": "sek",
            "token": "t",
            "token_uri": "https://oauth2.googleapis.com/token",
            "scopes": [auth.SCOPES[0]],
        }
        (config_dir / "token.json").write_text(json.dumps(token))
        creds = auth.resolve_credentials()
        assert creds.refresh_token == "r"

    def test_nothing_resolvable_raises_with_hint(self, config_dir, monkeypatch):
        monkeypatch.delenv("OPENGSC_SERVICE_ACCOUNT_FILE", raising=False)
        with pytest.raises(auth.AuthError, match="opengsc auth"):
            auth.resolve_credentials()

    def test_service_account_scoped_readonly(self, config_dir, monkeypatch):
        sa_path = config_dir / "sa.json"
        sa_path.write_text(json.dumps(SA_FILE))
        monkeypatch.setenv("OPENGSC_SERVICE_ACCOUNT_FILE", str(sa_path))
        creds = auth.resolve_credentials()
        assert creds.scopes == [auth.SCOPES[0]]

    def test_refresh_token_env_beats_token_json(self, config_dir, monkeypatch):
        monkeypatch.delenv("OPENGSC_SERVICE_ACCOUNT_FILE", raising=False)
        (config_dir / "token.json").write_text(json.dumps({"refresh_token": "from-file"}))
        monkeypatch.setenv("OPENGSC_REFRESH_TOKEN", "from-env")
        monkeypatch.setenv("OPENGSC_CLIENT_ID", "cid")
        monkeypatch.setenv("OPENGSC_CLIENT_SECRET", "sek")
        creds = auth.resolve_credentials()
        assert creds.refresh_token == "from-env"
        assert creds.client_id == "cid"
        assert creds.scopes == [auth.SCOPES[0]]

    def test_refresh_token_env_without_client_raises_with_hint(self, config_dir, monkeypatch):
        monkeypatch.delenv("OPENGSC_SERVICE_ACCOUNT_FILE", raising=False)
        monkeypatch.delenv("OPENGSC_CLIENT_ID", raising=False)
        monkeypatch.delenv("OPENGSC_CLIENT_SECRET", raising=False)
        monkeypatch.setenv("OPENGSC_REFRESH_TOKEN", "from-env")
        with pytest.raises(auth.AuthError, match="OPENGSC_CLIENT_ID"):
            auth.resolve_credentials()

    def test_service_account_beats_refresh_token_env(self, config_dir, monkeypatch):
        sa_path = config_dir / "sa.json"
        sa_path.write_text(json.dumps(SA_FILE))
        monkeypatch.setenv("OPENGSC_SERVICE_ACCOUNT_FILE", str(sa_path))
        monkeypatch.setenv("OPENGSC_REFRESH_TOKEN", "from-env")
        creds = auth.resolve_credentials()
        assert isinstance(creds, ga_service_account.Credentials)


class TestClientConfig:
    def test_env_vars_build_client_config(self, config_dir, monkeypatch):
        monkeypatch.setenv("OPENGSC_CLIENT_ID", "cid")
        monkeypatch.setenv("OPENGSC_CLIENT_SECRET", "sek")
        cfg = auth.client_config()
        assert cfg["installed"]["client_id"] == "cid"
        assert cfg["installed"]["client_secret"] == "sek"

    def test_client_secret_file_used_when_no_env(self, config_dir, monkeypatch):
        monkeypatch.delenv("OPENGSC_CLIENT_ID", raising=False)
        monkeypatch.delenv("OPENGSC_CLIENT_SECRET", raising=False)
        (config_dir / "client_secret.json").write_text(
            json.dumps({"installed": {"client_id": "file-cid", "client_secret": "file-sek"}})
        )
        cfg = auth.client_config()
        assert cfg["installed"]["client_id"] == "file-cid"

    def test_env_vars_win_over_file(self, config_dir, monkeypatch):
        monkeypatch.setenv("OPENGSC_CLIENT_ID", "env-cid")
        monkeypatch.setenv("OPENGSC_CLIENT_SECRET", "env-sek")
        (config_dir / "client_secret.json").write_text(
            json.dumps({"installed": {"client_id": "file-cid", "client_secret": "file-sek"}})
        )
        assert auth.client_config()["installed"]["client_id"] == "env-cid"

    def test_no_client_config_raises_with_hint(self, config_dir, monkeypatch):
        monkeypatch.delenv("OPENGSC_CLIENT_ID", raising=False)
        monkeypatch.delenv("OPENGSC_CLIENT_SECRET", raising=False)
        with pytest.raises(auth.AuthError, match="client_secret.json"):
            auth.client_config()


class TestTokenStorage:
    def make_creds(self):
        creds = mock.MagicMock()
        creds.to_json.return_value = json.dumps({"refresh_token": "r", "token": "t"})
        return creds

    @pytest.mark.skipif(os.name != "posix", reason="0600 permissions are POSIX-only")
    def test_token_file_has_0600(self, config_dir):
        auth.save_token(self.make_creds())
        mode = stat.S_IMODE(os.stat(auth.TOKEN_PATH).st_mode)
        assert mode == 0o600

    def test_token_file_content_is_credentials_json(self, config_dir):
        auth.save_token(self.make_creds())
        assert json.loads(auth.TOKEN_PATH.read_text())["refresh_token"] == "r"

    def test_atomic_write_keeps_old_token_on_failure(self, config_dir):
        old = {"refresh_token": "old"}
        auth.TOKEN_PATH.write_text(json.dumps(old))
        bad = mock.MagicMock()
        bad.to_json.side_effect = RuntimeError("boom")
        with pytest.raises(RuntimeError):
            auth.save_token(bad)
        assert json.loads(auth.TOKEN_PATH.read_text()) == old

    def test_atomic_write_leaves_no_temp_files(self, config_dir):
        auth.save_token(self.make_creds())
        leftovers = [p for p in config_dir.iterdir() if p.name != "token.json"]
        assert leftovers == []

    def test_load_token_info_masks_nothing_but_reports_expiry(self, config_dir):
        token = {
            "expiry": "2026-01-01T00:00:00Z",
            "refresh_token": "1//SECRET_REFRESH_VALUE",
            "token": "ya29.SECRET_ACCESS_VALUE",
        }
        auth.TOKEN_PATH.write_text(json.dumps(token))
        info = auth.token_info()
        assert info["expiry"] == "2026-01-01T00:00:00Z"
        dumped = json.dumps(info)
        assert "1//SECRET_REFRESH_VALUE" not in dumped
        assert "ya29.SECRET_ACCESS_VALUE" not in dumped


class TestOAuthFlow:
    def fake_flow(self, refresh_token="r-123"):
        flow = mock.MagicMock()
        oauth2session = mock.MagicMock(spec=["send", "fetch_token"])
        flow.oauth2session = oauth2session
        creds = mock.MagicMock()
        creds.to_json.return_value = json.dumps({"refresh_token": refresh_token})
        creds.refresh_token = refresh_token
        flow.run_local_server.return_value = creds
        return flow, creds

    def test_run_oauth_flow_writes_token_and_prints_refresh_token(
        self, config_dir, monkeypatch, capsys
    ):
        flow, creds = self.fake_flow()
        monkeypatch.setenv("OPENGSC_CLIENT_ID", "cid")
        monkeypatch.setenv("OPENGSC_CLIENT_SECRET", "sek")
        with mock.patch.object(auth, "InstalledAppFlow") as flow_cls:
            flow_cls.from_client_config.return_value = flow
            returned = auth.run_oauth_flow(no_browser=True)
        assert returned is creds
        flow.run_local_server.assert_called_once()
        assert flow.run_local_server.call_args.kwargs.get("open_browser") is False
        assert json.loads(auth.TOKEN_PATH.read_text())["refresh_token"] == "r-123"
        out = capsys.readouterr().out
        assert "OPENGSC_REFRESH_TOKEN=r-123" in out

    def test_run_oauth_flow_can_suppress_the_refresh_token_print(
        self, config_dir, monkeypatch, capsys
    ):
        flow, _ = self.fake_flow()
        monkeypatch.setenv("OPENGSC_CLIENT_ID", "cid")
        monkeypatch.setenv("OPENGSC_CLIENT_SECRET", "sek")
        with mock.patch.object(auth, "InstalledAppFlow") as flow_cls:
            flow_cls.from_client_config.return_value = flow
            auth.run_oauth_flow(no_browser=True, print_refresh_token=False)
        assert "OPENGSC_REFRESH_TOKEN" not in capsys.readouterr().out

    def test_run_oauth_flow_guards_the_flow_session(self, config_dir, monkeypatch):
        flow, _ = self.fake_flow()
        monkeypatch.setenv("OPENGSC_CLIENT_ID", "cid")
        monkeypatch.setenv("OPENGSC_CLIENT_SECRET", "sek")
        with mock.patch.object(auth, "InstalledAppFlow") as flow_cls:
            flow_cls.from_client_config.return_value = flow
            auth.run_oauth_flow(no_browser=True)
        # The flow's OAuth2Session must carry the guarded send(), bound to it.
        send = flow.oauth2session.send
        assert send.__func__ is GuardedSessionMixin.send
        assert send.__self__ is flow.oauth2session

    def test_no_browser_waits_on_localhost(self, config_dir, monkeypatch):
        """--no-browser still uses the loopback redirect: it only skips
        opening a browser window."""
        flow, _ = self.fake_flow()
        monkeypatch.setenv("OPENGSC_CLIENT_ID", "cid")
        monkeypatch.setenv("OPENGSC_CLIENT_SECRET", "sek")
        with mock.patch.object(auth, "InstalledAppFlow") as flow_cls:
            flow_cls.from_client_config.return_value = flow
            auth.run_oauth_flow(no_browser=True)
        assert flow.run_local_server.call_args.kwargs.get("open_browser") is False
