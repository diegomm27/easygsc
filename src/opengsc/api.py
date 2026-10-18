"""Thin REST wrapper around the four Search Console endpoints.

Nothing more: each function maps one endpoint, URL-encodes the siteUrl, and
maps errors. All HTTP goes through a guarded AuthorizedSession from auth.
Responses are returned exactly as Google sent them; formatting lives in
server.py.
"""

from __future__ import annotations

import json
from urllib.parse import quote

import requests

from .auth import make_authorized_session as make_session

SITES_URL = "https://www.googleapis.com/webmasters/v3/sites"
INSPECT_URL = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"


class ApiError(RuntimeError):
    """Google API error with status, Google's message, and a hint (or None)."""

    def __init__(self, status: int, message: str, hint: str | None = None):
        self.status = status
        self.message = message
        self.hint = hint
        super().__init__(f"Google API error {status}: {message}")


def _hint(status: int, reason: str | None) -> str | None:
    if status == 403:
        return (
            "Check the property format: 'sc-domain:example.com' for domain "
            "properties vs 'https://example.com/' (with trailing slash) for "
            "URL-prefix properties, and confirm the account has access."
        )
    if status == 401 or reason == "invalid_grant":
        return "The token is expired or revoked; run 'opengsc auth' again."
    if status == 429 or reason in ("rateLimitExceeded", "quotaExceeded"):
        return (
            "Quota exceeded. Search Console enforces per-day/per-property "
            "quotas; wait or reduce request volume. URL Inspection is limited "
            "to 2,000 queries/day per property."
        )
    return None


def _request(session, method: str, url: str, **kwargs) -> dict:
    try:
        response = session.request(method, url, timeout=60, **kwargs)
    except requests.exceptions.RequestException as exc:
        raise ApiError(0, f"Request failed: {exc}") from exc
    if response.status_code >= 400:
        message = response.text
        reason = None
        try:
            err = response.json().get("error", {})
            message = err.get("message") or message
            reasons = err.get("errors") or [{}]
            reason = reasons[0].get("reason")
        except (ValueError, AttributeError, json.JSONDecodeError):
            pass
        raise ApiError(response.status_code, message, _hint(response.status_code, reason))
    try:
        return response.json()
    except ValueError as exc:
        raise ApiError(response.status_code, f"Non-JSON response: {response.text[:200]}") from exc


def _site_url(site_url: str) -> str:
    return quote(site_url, safe="")


def _session():
    return make_session()


def list_sites(session=None) -> dict:
    """GET /webmasters/v3/sites — properties the account can read."""
    session = session or _session()
    return _request(session, "GET", SITES_URL)


def search_analytics(site_url: str, body: dict, session=None) -> dict:
    """POST /sites/{siteUrl}/searchAnalytics/query with the caller-built body."""
    session = session or _session()
    url = f"{SITES_URL}/{_site_url(site_url)}/searchAnalytics/query"
    return _request(session, "POST", url, json=body)


def list_sitemaps(site_url: str, session=None) -> dict:
    """GET /sites/{siteUrl}/sitemaps."""
    session = session or _session()
    url = f"{SITES_URL}/{_site_url(site_url)}/sitemaps"
    return _request(session, "GET", url)


def inspect_url(site_url: str, url: str, session=None) -> dict:
    """POST /v1/urlInspection/index:inspect (index:inspect method)."""
    session = session or _session()
    body = {"inspectionUrl": url, "siteUrl": site_url, "languageCode": "en-US"}
    return _request(session, "POST", INSPECT_URL, json=body)
