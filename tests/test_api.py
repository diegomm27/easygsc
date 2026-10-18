"""Tests for the thin REST wrapper: endpoint URLs, siteUrl encoding, request
bodies, and error mapping. HTTP is mocked; nothing leaves the machine."""

import json
from unittest import mock

import pytest
import requests

from opengsc import api


class FakeResponse:
    def __init__(self, status_code, body=None, text=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = text if text is not None else json.dumps(self._body)

    def json(self):
        if isinstance(self._body, dict) and "error" in self._body:
            return self._body
        return self._body


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.fixture
def session():
    s = FakeSession(FakeResponse(200, {"siteEntry": []}))
    with mock.patch.object(api, "make_session", return_value=s):
        yield s


class TestSiteUrlEncoding:
    def test_domain_property_is_encoded(self, session):
        api.list_sitemaps("sc-domain:example.com")
        assert session.calls[0]["url"] == (
            "https://www.googleapis.com/webmasters/v3/sites/sc-domain%3Aexample.com/sitemaps"
        )

    def test_url_prefix_property_is_encoded(self, session):
        api.list_sitemaps("https://example.com/folder/")
        url = session.calls[0]["url"]
        assert url.startswith("https://www.googleapis.com/webmasters/v3/sites/")
        assert url.endswith("/sitemaps")
        # every reserved character of the property is percent-encoded
        assert (
            url[len("https://www.googleapis.com/webmasters/v3/sites/") : -len("/sitemaps")]
            == "https%3A%2F%2Fexample.com%2Ffolder%2F"
        )

    def test_search_analytics_encodes_site_url(self, session):
        api.search_analytics("sc-domain:example.com", {"dimensions": ["query"]})
        assert "sites/sc-domain%3Aexample.com/searchAnalytics/query" in session.calls[0]["url"]

    def test_inspect_url_uses_searchconsole_host_and_encodes(self, session):
        api.inspect_url("sc-domain:example.com", "https://example.com/page")
        call = session.calls[0]
        assert call["url"] == "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
        # siteUrl goes in the body, url-encoded as a JSON value
        assert call["json"]["siteUrl"] == "sc-domain:example.com"
        assert call["json"]["inspectionUrl"] == "https://example.com/page"


class TestEndpointsAndBodies:
    def test_list_sites(self, session):
        api.list_sites()
        call = session.calls[0]
        assert call["method"] == "GET"
        assert call["url"] == "https://www.googleapis.com/webmasters/v3/sites"

    def test_search_analytics_posts_body(self, session):
        body = {
            "startDate": "2026-01-01",
            "endDate": "2026-01-28",
            "dimensions": ["query", "page"],
            "rowLimit": 1000,
            "startRow": 0,
            "type": "web",
            "dataState": "final",
        }
        api.search_analytics("https://example.com/", body)
        call = session.calls[0]
        assert call["method"] == "POST"
        assert call["json"] == body

    def test_search_analytics_defaults_to_no_extras(self, session):
        """api.py adds nothing: the body it receives is the body it sends."""
        api.search_analytics("sc-domain:example.com", {"dimensions": ["query"]})
        assert session.calls[0]["json"] == {"dimensions": ["query"]}

    def test_list_sitemaps_is_get(self, session):
        api.list_sitemaps("sc-domain:example.com")
        assert session.calls[0]["method"] == "GET"

    def test_inspect_url_is_post(self, session):
        api.inspect_url("sc-domain:example.com", "https://example.com/")
        assert session.calls[0]["method"] == "POST"


class TestErrorMapping:
    def google_error(self, status, reason, message):
        return FakeResponse(
            status,
            {"error": {"code": status, "message": message, "errors": [{"reason": reason}]}},
        )

    def test_403_hint_mentions_property_format(self, session):
        session.response = self.google_error(403, "forbidden", "User does not have permission")
        with pytest.raises(api.ApiError) as excinfo:
            api.list_sites()
        err = excinfo.value
        assert err.status == 403
        assert "Google" in str(err) and "permission" in str(err).lower()
        assert "sc-domain" in err.hint

    def test_401_invalid_grant_hint(self, session):
        session.response = self.google_error(401, "invalid_grant", "Token has been expired")
        with pytest.raises(api.ApiError) as excinfo:
            api.list_sites()
        assert "opengsc auth" in excinfo.value.hint

    def test_429_rate_limit_hint_covers_both_reasons(self, session):
        for reason in ("rateLimitExceeded", "quotaExceeded", None):
            session.response = self.google_error(429, reason, "Quota exceeded")
            with pytest.raises(api.ApiError) as excinfo:
                api.list_sites()
            assert "quota" in excinfo.value.hint.lower()

    def test_other_errors_surface_google_message_and_status(self, session):
        session.response = self.google_error(400, "badRequest", "Invalid dimensions")
        with pytest.raises(api.ApiError) as excinfo:
            api.list_sites()
        assert excinfo.value.status == 400
        assert "Invalid dimensions" in str(excinfo.value)
        assert excinfo.value.hint is None

    def test_transport_error_surfaces_message(self, session):
        session.response = requests.exceptions.ConnectionError("connection reset")
        with pytest.raises(api.ApiError) as excinfo:
            api.list_sites()
        assert "connection reset" in str(excinfo.value)
