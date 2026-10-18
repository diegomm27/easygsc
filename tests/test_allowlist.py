"""Tests for the transport-level host allowlist.

Every test asserts that traffic to a non-allowed host raises
DisallowedHostError before anything leaves the machine, and that the
documented flows (plain requests, token refresh, OAuth code exchange,
redirect chains) all route through the guard.
"""

from unittest import mock

import io

import pytest
import requests
import requests_oauthlib
from google.auth.transport.requests import Request as GoogleAuthRequest

from opengsc.allowlist import (
    ALLOWED_HOSTS,
    DisallowedHostError,
    GuardedAuthorizedSession,
    GuardedSession,
    attach_guard,
    check_allowed,
)


def make_response(status_code=200, url="https://www.googleapis.com/x", body=b"{}"):
    response = requests.Response()
    response.status_code = status_code
    response.url = url
    response._content = body
    response._content_consumed = True
    response.raw = io.BytesIO(body)  # redirect machinery calls raw.close()/read()
    response.headers["Content-Type"] = "application/json"
    # requests' redirect machinery reads response.request (rebuild_auth).
    response.request = requests.Request("GET", url).prepare()
    return response


def prepare(url):
    return requests.Request("GET", url).prepare()


class RecordingAdapter(requests.adapters.HTTPAdapter):
    """Adapter that records calls and returns queued responses, no network."""

    def __init__(self, responses):
        super().__init__()
        # A requests.Response is itself iterable (over content chunks), so
        # never bare-list() it.
        self.responses = [responses] if not isinstance(responses, list) else list(responses)
        self.calls = []

    def send(self, request, **kwargs):
        self.calls.append(request.url)
        return self.responses.pop(0)


@pytest.fixture
def mounted():
    """A GuardedSession with a recording adapter for allowed-host requests."""

    def factory(responses):
        session = GuardedSession()
        adapter = RecordingAdapter(responses)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session, adapter

    return factory


class TestPreSendGuard:
    def test_disallowed_host_raises_before_any_send(self, mounted):
        session, adapter = mounted([make_response()])
        with pytest.raises(DisallowedHostError, match="evil.example.com"):
            session.send(prepare("https://evil.example.com/steal"))
        assert adapter.calls == []  # nothing reached the adapter

    def test_every_allowed_host_passes(self, mounted):
        for host in ALLOWED_HOSTS:
            session, adapter = mounted([make_response(url=f"https://{host}/ok")])
            response = session.send(prepare(f"https://{host}/ok"))
            assert response.status_code == 200
            assert adapter.calls == [f"https://{host}/ok"]

    def test_http_scheme_is_checked_too(self, mounted):
        session, _ = mounted(make_response())
        # The allowlist is on the host, not the scheme: http to an allowed
        # host passes.
        response = session.send(prepare("http://www.googleapis.com/"))
        assert response.status_code == 200
        # http to a non-allowed host raises.
        with pytest.raises(DisallowedHostError):
            session.send(prepare("http://evil.example.com/"))

    def test_missing_or_invalid_host_raises(self):
        # A URL with no host part is rejected by the check itself.
        with pytest.raises(DisallowedHostError):
            check_allowed("https:///no-host")


class TestRedirectGuard:
    def test_redirect_to_disallowed_host_raises(self, mounted):
        """requests re-calls Session.send() for each redirect hop; the guard
        must fire on the hop pointing outside the allowlist."""
        redirect = make_response()
        redirect.status_code = 302
        redirect.headers["Location"] = "https://evil.example.com/exfil"
        session, adapter = mounted(redirect)
        with pytest.raises(DisallowedHostError, match="evil.example.com"):
            session.send(prepare("https://www.googleapis.com/start"), allow_redirects=True)
        # The first hop was attempted; the redirect target never was.
        assert adapter.calls == ["https://www.googleapis.com/start"]

    def test_redirect_within_allowlist_passes(self, mounted):
        redirect = make_response()
        redirect.status_code = 302
        redirect.headers["Location"] = "https://www.googleapis.com/final"
        session, adapter = mounted(
            [redirect, make_response(url="https://www.googleapis.com/final")]
        )
        response = session.send(prepare("https://www.googleapis.com/start"), allow_redirects=True)
        assert response.status_code == 200
        assert len(adapter.calls) == 2

    def test_final_url_check_catches_off_allowlist_endpoints(self, mounted):
        """Defense in depth: even if redirects were followed below send(), the
        final response URL is checked."""
        with mock.patch.object(
            requests.Session, "send", return_value=make_response(url="https://evil.example.com/final")
        ):
            session = GuardedSession()
            with pytest.raises(DisallowedHostError, match="evil.example.com"):
                session.send(prepare("https://www.googleapis.com/start"))


class TestTokenRefreshGuard:
    def test_refresh_transport_request_goes_through_guard(self, mounted):
        """credentials.refresh() sends through google.auth's Request; the
        Request must be built on a guarded session."""
        session, adapter = mounted(
            [make_response(body=b'{"access_token":"x","expires_in":3600}')]
        )
        request = GoogleAuthRequest(session=session)
        # google.auth Request.__call__ signature: (url, method=..., body=...);
        # it returns a _Response wrapper exposing .status.
        response = request("https://oauth2.googleapis.com/token", method="POST", body="grant_type=x")
        assert response.status == 200
        assert adapter.calls == ["https://oauth2.googleapis.com/token"]

    def test_refresh_to_disallowed_token_uri_raises(self, mounted):
        session, adapter = mounted([make_response()])
        request = GoogleAuthRequest(session=session)
        with pytest.raises(DisallowedHostError):
            request("https://evil.example.com/token", method="POST", body="grant_type=x")
        assert adapter.calls == []


class TestAuthorizedSessionGuard:
    def test_authorized_session_is_guarded(self):
        credentials = mock.MagicMock()
        session = GuardedAuthorizedSession(credentials)
        assert isinstance(session, GuardedAuthorizedSession)
        with pytest.raises(DisallowedHostError):
            session.send(prepare("https://evil.example.com/"))

    def test_authorized_session_auth_request_uses_guarded_session(self):
        """The refresh channel (auth_request) must be a guarded session too."""
        session = GuardedAuthorizedSession(mock.MagicMock())
        auth_session = session._auth_request.session
        assert isinstance(auth_session, GuardedSession)


class TestOAuthFlowGuard:
    def test_attach_guard_covers_code_exchange(self):
        """The OAuth2Session used by InstalledAppFlow, after attach_guard(),
        routes its token exchange through the guard."""
        oauth2session = requests_oauthlib.OAuth2Session(
            client_id="cid",
            redirect_uri="urn:ietf:wg:oauth:2.0:oob",
        )
        attach_guard(oauth2session)

        sent_urls = []

        def fake_send(_session, prepared, **kwargs):
            sent_urls.append(prepared.url)
            return make_response(
                body=b'{"access_token":"tok","token_type":"Bearer","expires_in":3600,"refresh_token":"r"}'
            )

        with mock.patch.object(requests.Session, "send", side_effect=fake_send):
            token = oauth2session.fetch_token(
                token_url="https://oauth2.googleapis.com/token",
                code="abc",
                client_secret="sekrit",
            )
        assert token["access_token"] == "tok"
        assert sent_urls == ["https://oauth2.googleapis.com/token"]

    def test_attach_guard_blocks_disallowed_token_uri(self):
        oauth2session = requests_oauthlib.OAuth2Session(client_id="cid")
        attach_guard(oauth2session)
        sent = []

        def fake_send(_session, prepared, **kwargs):
            sent.append(prepared.url)
            return make_response()

        with mock.patch.object(requests.Session, "send", side_effect=fake_send):
            with pytest.raises(DisallowedHostError, match="evil.example.com"):
                oauth2session.fetch_token(
                    token_url="https://evil.example.com/token",
                    code="abc",
                    client_secret="sekrit",
                )
        assert sent == []  # the exchange never happened
