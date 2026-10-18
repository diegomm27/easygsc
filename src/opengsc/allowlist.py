"""Transport-level network allowlist.

This is the single chokepoint for all outbound HTTP in opengsc. Only the four
Google hosts required for Search Console and OAuth may be contacted; anything
else raises :class:`DisallowedHostError` before a request is sent.

The guard lives at the ``requests`` transport layer (``Session.send``), not in
application code, because several independent sessions exist:

- our own API calls (a plain :class:`requests.Session`),
- token refresh (``google.auth`` refreshes through a separate
  ``google.auth.transport.requests.Request`` session, and
  ``AuthorizedSession`` has its own auth-request session),
- the OAuth code exchange (``requests_oauthlab``/``InstalledAppFlow`` uses its
  own ``OAuth2Session``).

Redirects are covered: ``requests`` resolves redirects by re-calling
``Session.send`` for every hop (its HTTPAdapter sends with
``redirect=False``, so urllib3 never follows redirects internally), and the
final response URL is checked as defense in depth.
"""

from __future__ import annotations

import types
from urllib.parse import urlparse

import requests
from google.auth.transport.requests import AuthorizedSession as _AuthorizedSession
from google.auth.transport.requests import Request as _GoogleAuthRequest

ALLOWED_HOSTS = frozenset(
    {
        "www.googleapis.com",  # webmasters/v3 REST API
        "searchconsole.googleapis.com",  # urlInspection/index:inspect
        "oauth2.googleapis.com",  # token refresh and code exchange
        "accounts.google.com",  # OAuth authorization flow
    }
)


class DisallowedHostError(Exception):
    """Raised when an outgoing request targets a host outside ALLOWED_HOSTS."""


def check_allowed(url: str) -> str:
    """Raise DisallowedHostError unless *url*'s host is allowed. Returns the host."""
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if host not in ALLOWED_HOSTS:
        raise DisallowedHostError(
            f"Blocked request to non-allowed host {host or '(none)'!r}: {url}. "
            f"opengsc only talks to: {', '.join(sorted(ALLOWED_HOSTS))}."
        )
    return host


class GuardedSessionMixin:
    """Mixin overriding send() to enforce the host allowlist, redirects included."""

    def send(self, request, **kwargs):  # type: ignore[override]
        check_allowed(request.url)
        # Explicit Session.send: works both for real subclasses (MRO) and for
        # instances that receive this function via attach_guard (MethodType),
        # where zero-arg super() cannot resolve. Neither AuthorizedSession nor
        # OAuth2Session overrides send(), so nothing is bypassed.
        response = requests.Session.send(self, request, **kwargs)
        # Defense in depth: a response whose final URL left the allowlist
        # (e.g. redirects followed below send()) is rejected after the fact.
        check_allowed(response.url)
        return response


class GuardedSession(GuardedSessionMixin, requests.Session):
    """A requests.Session that may only talk to ALLOWED_HOSTS."""


class GuardedAuthorizedSession(GuardedSessionMixin, _AuthorizedSession):
    """An AuthorizedSession whose own traffic and refresh channel are guarded."""

    def __init__(self, credentials, **kwargs):
        super().__init__(
            credentials, auth_request=_GoogleAuthRequest(session=GuardedSession()), **kwargs
        )


def attach_guard(oauth2session) -> None:
    """Attach the send() guard to an existing OAuth2Session instance.

    ``requests_oauthlib.OAuth2Session`` subclasses ``requests.Session``, so an
    instance-level ``send`` override covers every request it makes, including
    the token exchange performed by ``InstalledAppFlow``.
    """
    oauth2session.send = types.MethodType(GuardedSessionMixin.send, oauth2session)
