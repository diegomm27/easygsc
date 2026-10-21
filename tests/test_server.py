"""Tests for the MCP tools: defaults, validation, TSV output, metadata block.

HTTP is mocked by patching easygsc.api functions; no network. The date is
pinned by patching easygsc.server._today.
"""

import json
from unittest import mock

import pytest

from easygsc import server
from easygsc.api import ApiError


@pytest.fixture
def pinned_today(monkeypatch):
    import datetime

    monkeypatch.setattr(server, "_today", lambda: datetime.date(2026, 2, 20))


@pytest.fixture
def analytics(monkeypatch):
    calls = {}

    def fake(site_url, body, session=None):
        calls["site_url"] = site_url
        calls["body"] = body
        rows = {
            "rows": [
                {
                    "keys": ["foo bar"],
                    "clicks": 12,
                    "impressions": 340.0,
                    "ctr": 0.03529411764705882,
                    "position": 3.6441176470588235,
                }
            ]
        }
        return rows

    monkeypatch.setattr(server.api, "search_analytics", fake)
    return calls


# ---------------------------------------------------------------- defaults


class TestSearchAnalyticsDefaults:
    def test_default_range_is_28_days_ending_3_days_ago(self, analytics, pinned_today):
        server.search_analytics("sc-domain:example.com")
        body = analytics["body"]
        assert body["startDate"] == "2026-01-21"  # 28 days before the end, inclusive
        assert body["endDate"] == "2026-02-17"  # 3 days ago from 2026-02-20

    def test_explicit_dates_win(self, analytics, pinned_today):
        server.search_analytics(
            "sc-domain:example.com", start_date="2025-01-01", end_date="2025-01-31"
        )
        body = analytics["body"]
        assert body["startDate"] == "2025-01-01"
        assert body["endDate"] == "2025-01-31"

    def test_defaults_dimensions_type_state_and_limit(self, analytics, pinned_today):
        server.search_analytics("sc-domain:example.com")
        body = analytics["body"]
        assert body["dimensions"] == ["query"]
        assert body["type"] == "web"
        assert body["dataState"] == "final"
        assert body["rowLimit"] == 1000
        assert body["startRow"] == 0
        assert "dimensionFilterGroups" not in body


# ------------------------------------------------------------- validation


class TestSearchAnalyticsValidation:
    def test_invalid_dimension_rejected(self, analytics, pinned_today):
        out = server.search_analytics("sc-domain:example.com", dimensions=["bogus"])
        assert out.startswith("ERROR")
        assert "bogus" in out

    def test_invalid_search_type_rejected(self, analytics, pinned_today):
        assert server.search_analytics("sc-domain:example.com", search_type="blog").startswith(
            "ERROR"
        )

    def test_invalid_data_state_rejected(self, analytics, pinned_today):
        assert server.search_analytics("sc-domain:example.com", data_state="realtime").startswith(
            "ERROR"
        )

    def test_row_limit_above_25000_rejected_not_clamped(self, analytics, pinned_today):
        assert server.search_analytics("sc-domain:example.com", row_limit=25001).startswith("ERROR")

    def test_row_limit_zero_or_negative_rejected(self, analytics, pinned_today):
        assert server.search_analytics("sc-domain:example.com", row_limit=0).startswith("ERROR")

    def test_invalid_filter_operator_rejected(self, analytics, pinned_today):
        out = server.search_analytics(
            "sc-domain:example.com",
            filters=[{"dimension": "query", "operator": "like", "expression": "x"}],
        )
        assert out.startswith("ERROR")
        assert "like" in out

    def test_valid_filter_passes_through(self, analytics, pinned_today):
        server.search_analytics(
            "sc-domain:example.com",
            filters=[{"dimension": "device", "operator": "equals", "expression": "MOBILE"}],
        )
        groups = analytics["body"]["dimensionFilterGroups"]
        assert groups == [
            {
                "groupType": "and",
                "filters": [{"dimension": "device", "operator": "equals", "expression": "MOBILE"}],
            }
        ]


# ------------------------------------------------------------- TSV output


class TestSearchAnalyticsOutput:
    def test_header_and_rows_are_tsv(self, analytics, pinned_today):
        out = server.search_analytics("sc-domain:example.com")
        lines = out.splitlines()
        assert lines[0].split("\t") == ["query", "clicks", "impressions", "ctr", "position"]
        values = lines[1].split("\t")
        assert values[0] == "foo bar"
        assert values[1] == "12"
        # ctr and position must NOT be rounded: full API precision
        assert values[3] == "0.03529411764705882"
        assert values[4] == "3.6441176470588235"

    def test_metadata_block_present(self, analytics, pinned_today):
        out = server.search_analytics("sc-domain:example.com")
        assert "date_range: 2026-01-21..2026-02-17" in out
        assert "rows_returned: 1" in out
        assert "more_may_exist:" in out
        assert "row_limit: 1000" in out

    def test_more_may_exist_true_when_full_page(self, analytics, monkeypatch, pinned_today):
        rows = {"rows": [{"keys": ["a"], "clicks": 1}]}  # rows == row_limit
        monkeypatch.setattr(server.api, "search_analytics", lambda *a, **k: rows)
        out = server.search_analytics("sc-domain:example.com", row_limit=1)
        assert "more_may_exist: true" in out

    def test_more_may_exist_false_when_short_page(self, analytics, pinned_today):
        out = server.search_analytics("sc-domain:example.com")
        assert "more_may_exist: false" in out

    def test_fixed_notes_present(self, analytics, pinned_today):
        out = server.search_analytics("sc-domain:example.com")
        assert "anonymizes" in out  # rare-query anonymization note
        assert "row cap" in out  # per-day per-search-type row cap note

    def test_tabs_and_newlines_in_values_escaped(self, analytics, monkeypatch, pinned_today):
        rows = {"rows": [{"keys": ["weird\tvalue\nline"], "clicks": 1}]}
        monkeypatch.setattr(server.api, "search_analytics", lambda *a, **k: rows)
        out = server.search_analytics("sc-domain:example.com")
        data_line = out.splitlines()[1]
        assert "\\t" in data_line and "\\n" in data_line
        assert data_line.split("\t")[0] == "weird\\tvalue\\nline"

    def test_empty_result_reports_zero_rows(self, analytics, monkeypatch, pinned_today):
        monkeypatch.setattr(server.api, "search_analytics", lambda *a, **k: {})
        out = server.search_analytics("sc-domain:example.com")
        assert "rows_returned: 0" in out
        assert len(out.strip().splitlines()) == 1 or "no rows" in out


class TestSearchAnalyticsErrors:
    def test_api_error_returns_formatted_message_with_hint(self, monkeypatch, pinned_today):
        def boom(*a, **k):
            raise ApiError(403, "User does not have permission", hint="check sc-domain: format")

        monkeypatch.setattr(server.api, "search_analytics", boom)
        out = server.search_analytics("sc-domain:example.com")
        assert "ERROR" in out and "403" in out
        assert "User does not have permission" in out
        assert "check sc-domain: format" in out


# ----------------------------------------------------------------- sites


class TestListSites:
    def test_lists_site_url_and_permission_level(self, monkeypatch):
        monkeypatch.setattr(
            server.api,
            "list_sites",
            lambda *a, **k: {
                "siteEntry": [
                    {"siteUrl": "sc-domain:example.com", "permissionLevel": "siteOwner"},
                    {"siteUrl": "https://other.com/", "permissionLevel": "siteFullUser"},
                ]
            },
        )
        out = server.list_sites()
        lines = out.splitlines()
        assert lines[0] == "site_url\tpermission_level"
        assert "sc-domain:example.com\tsiteOwner" in lines
        assert "https://other.com/\tsiteFullUser" in lines

    def test_api_error_formatted(self, monkeypatch):
        monkeypatch.setattr(
            server.api,
            "list_sites",
            mock.MagicMock(side_effect=ApiError(401, "invalid", hint="run easygsc auth")),
        )
        assert "run easygsc auth" in server.list_sites()


# -------------------------------------------------------------- sitemaps


class TestListSitemaps:
    def test_top_level_tsv_and_contents_as_compact_json(self, monkeypatch):
        payload = {
            "sitemap": [
                {
                    "path": "https://example.com/sitemap.xml",
                    "lastDownloaded": "2026-02-01T10:00:00.000Z",
                    "errors": "1",
                    "warnings": "0",
                    "isSitemapsIndex": False,
                    "type": "sitemap",
                    "contents": [{"type": "web", "submitted": 100, "indexed": 80}],
                }
            ]
        }
        monkeypatch.setattr(server.api, "list_sitemaps", lambda *a, **k: payload)
        out = server.list_sitemaps("sc-domain:example.com")
        lines = out.splitlines()
        header = lines[0].split("\t")
        assert header[:6] == [
            "path",
            "last_downloaded",
            "errors",
            "warnings",
            "is_sitemaps_index",
            "type",
        ]
        assert "contents" in header
        data = lines[1].split("\t")
        contents = json.loads(data[header.index("contents")])
        assert contents == [{"type": "web", "submitted": 100, "indexed": 80}]

    def test_empty_result(self, monkeypatch):
        monkeypatch.setattr(server.api, "list_sitemaps", lambda *a, **k: {})
        out = server.list_sitemaps("sc-domain:example.com")
        assert "0" in out or "no sitemaps" in out


# ---------------------------------------------------------------- inspect


class TestInspectUrl:
    def test_returns_compact_json_verbatim(self, monkeypatch):
        payload = {
            "inspectionResult": {
                "inspectionResultLink": "https://searchconsole.googleapis.com/m/...",
                "indexStatusResult": {"verdict": "PASS", "coverageState": "Submitted and indexed"},
            }
        }
        monkeypatch.setattr(server.api, "inspect_url", lambda *a, **k: payload)
        out = server.inspect_url("sc-domain:example.com", "https://example.com/")
        assert json.loads(out) == payload
        assert ": " not in out  # compact separators, no pretty spacing

    def test_api_error_formatted(self, monkeypatch):
        monkeypatch.setattr(
            server.api,
            "inspect_url",
            mock.MagicMock(side_effect=ApiError(429, "Quota exceeded", hint="2,000/day")),
        )
        out = server.inspect_url("sc-domain:example.com", "https://example.com/")
        assert "429" in out and "2,000/day" in out
