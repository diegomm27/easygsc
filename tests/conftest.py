"""Guards shared by every test."""

from unittest import mock

import pytest

from easygsc import connect


@pytest.fixture(autouse=True)
def no_real_ai_apps(monkeypatch):
    """No test may edit or run the AI apps installed on the machine running it."""
    monkeypatch.setattr(connect, "APPS", (), raising=False)
    monkeypatch.setattr(
        connect, "_run", mock.Mock(side_effect=AssertionError("ran a real app CLI")), raising=False
    )
