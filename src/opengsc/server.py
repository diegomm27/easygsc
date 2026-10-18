"""MCP server: the four tools.

Output rules: tabular data is TSV with a header (tabs/newlines escaped as
\\t and \\n); nested data (URL inspection, sitemap contents) is compact JSON
verbatim; ctr/position are never rounded; search_analytics always appends a
metadata block (date range, rows returned, more_may_exist, fixed data-quirk
notes); API errors are returned as formatted strings, never raised past the
tool boundary, never truncated silently.
"""

from __future__ import annotations

import datetime
import json

from mcp.server.fastmcp import FastMCP

from . import api
from .api import ApiError

mcp = FastMCP("opengsc")

VALID_DIMENSIONS = ("query", "page", "country", "device", "date", "searchAppearance")
VALID_OPERATORS = (
    "equals",
    "notEquals",
    "contains",
    "notContains",
    "includingRegex",
    "excludingRegex",
)
VALID_SEARCH_TYPES = ("web", "image", "video", "news", "discover", "googleNews")
VALID_DATA_STATES = ("final", "all")
MAX_ROW_LIMIT = 25000

# Fixed notes appended to every search_analytics result (see README).
NOTE_ANONYMIZATION = (
    "note: the API anonymizes rare queries, so sums over the query dimension "
    "will not match totals queried without dimensions."
)
NOTE_ROW_CAP = (
    "note: the API applies a per-day, per-search-type row cap, so very large "
    "sites cannot be fully exported regardless of pagination."
)

METRIC_KEYS = ("clicks", "impressions", "ctr", "position")


def _today() -> datetime.date:
    """Indirection so tests can pin the clock."""
    return datetime.date.today()


def _default_date_range() -> tuple[str, str]:
    """Last 28 days, ending 3 days ago (GSC data lag)."""
    end = _today() - datetime.timedelta(days=3)
    start = end - datetime.timedelta(days=27)
    return start.isoformat(), end.isoformat()


def _escape(value) -> str:
    """Escape tabs and newlines so TSV rows stay one line per row."""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def _tsv(header: list[str], rows: list[list]) -> str:
    lines = ["\t".join(header)]
    lines.extend("\t".join(_escape(cell) for cell in row) for row in rows)
    return "\n".join(lines)


def _error_text(err: ApiError) -> str:
    text = f"ERROR {err.status}: {err.message}"
    if err.hint:
        text += f"\nhint: {err.hint}"
    return text


def _validate(name: str, value, allowed) -> None:
    if value not in allowed:
        raise ValueError(f"invalid {name} {value!r}; allowed: {', '.join(allowed)}")


def _wrap(fn, *args, **kwargs) -> str:
    """Run an api call, returning formatted errors instead of raising."""
    try:
        return fn(*args, **kwargs)
    except ApiError as err:
        return _error_text(err)


@mcp.tool()
def list_sites() -> str:
    """List Search Console properties the account can read, with permission level.

    Returns TSV: site_url<TAB>permission_level. Use the site_url values as-is
    for the site_url argument of the other tools.
    """

    def run() -> str:
        data = api.list_sites()
        entries = data.get("siteEntry", [])
        rows = [[e.get("siteUrl", ""), e.get("permissionLevel", "")] for e in entries]
        if not rows:
            return "no properties found for this account"
        return _tsv(["site_url", "permission_level"], rows)

    return _wrap(run)


@mcp.tool()
def search_analytics(
    site_url: str,
    start_date: str | None = None,
    end_date: str | None = None,
    dimensions: list[str] | None = None,
    filters: list[dict] | None = None,
    search_type: str = "web",
    data_state: str = "final",
    row_limit: int = 1000,
    start_row: int = 0,
) -> str:
    """Query search analytics for one property.

    site_url: property from list_sites. start_date/end_date: YYYY-MM-DD
    (default: last 28 days ending 3 days ago). dimensions: subset of query,
    page, country, device, date, searchAppearance. filters: list of
    {dimension, operator, expression} with operators equals, notEquals,
    contains, notContains, includingRegex, excludingRegex. search_type: web,
    image, video, news, discover, googleNews. data_state: final or all.
    row_limit: 1..25000; start_row: pagination offset.

    Returns TSV rows plus a metadata block (date range, rows returned,
    more_may_exist: true when rows == row_limit, so paginate with start_row).
    """
    dimensions = dimensions if dimensions is not None else ["query"]
    try:
        for d in dimensions:
            _validate("dimension", d, VALID_DIMENSIONS)
        _validate("search_type", search_type, VALID_SEARCH_TYPES)
        _validate("data_state", data_state, VALID_DATA_STATES)
        if not isinstance(row_limit, int) or not 1 <= row_limit <= MAX_ROW_LIMIT:
            raise ValueError(f"row_limit must be an integer in [1, {MAX_ROW_LIMIT}]")
        if start_row < 0:
            raise ValueError("start_row must be >= 0")
        for f in filters or []:
            _validate("filter operator", f.get("operator"), VALID_OPERATORS)
            if "dimension" not in f or "expression" not in f:
                raise ValueError("each filter needs dimension, operator, expression")
    except ValueError as exc:
        return f"ERROR: {exc}"

    if start_date is None or end_date is None:
        default_start, default_end = _default_date_range()
        start_date = start_date or default_start
        end_date = end_date or default_end

    body: dict = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": dimensions,
        "rowLimit": row_limit,
        "startRow": start_row,
        "type": search_type,
        "dataState": data_state,
    }
    if filters:
        body["dimensionFilterGroups"] = [{"groupType": "and", "filters": filters}]

    def run() -> str:
        data = api.search_analytics(site_url, body)
        rows = data.get("rows", [])
        header = [*dimensions, *METRIC_KEYS]
        table = [[*r.get("keys", []), *(r.get(k) for k in METRIC_KEYS)] for r in rows]
        meta = [
            f"date_range: {start_date}..{end_date}",
            f"search_type: {search_type}",
            f"rows_returned: {len(rows)}",
            f"row_limit: {row_limit}",
            f"start_row: {start_row}",
            f"more_may_exist: {'true' if len(rows) == row_limit else 'false'}",
            NOTE_ANONYMIZATION,
            NOTE_ROW_CAP,
        ]
        if not table:
            return "\n".join(["no rows"] + meta)
        return "\n".join([_tsv(header, table), *meta])

    return _wrap(run)


@mcp.tool()
def list_sitemaps(site_url: str) -> str:
    """List submitted sitemaps for one property with status and counts.

    Top-level fields are TSV; the nested contents array is compact JSON
    exactly as the API sends it.
    """

    def run() -> str:
        data = api.list_sitemaps(site_url)
        sitemaps = data.get("sitemap", [])
        if not sitemaps:
            return "no sitemaps found"
        header = [
            "path",
            "last_downloaded",
            "errors",
            "warnings",
            "is_sitemaps_index",
            "type",
            "contents",
        ]
        rows = [
            [
                s.get("path", ""),
                s.get("lastDownloaded", ""),
                s.get("errors", ""),
                s.get("warnings", ""),
                s.get("isSitemapsIndex", ""),
                s.get("type", ""),
                json.dumps(s.get("contents", []), separators=(",", ":")),
            ]
            for s in sitemaps
        ]
        return _tsv(header, rows)

    return _wrap(run)


@mcp.tool()
def inspect_url(site_url: str, url: str) -> str:
    """Run URL Inspection for one URL inside one property.

    Returns the result as compact JSON exactly as the API sends it: index
    status, coverage, canonical, last crawl, mobile usability if present.
    Counts against Google's 2,000/day per-property quota.
    """

    def run() -> str:
        data = api.inspect_url(site_url, url)
        return json.dumps(data, separators=(",", ":"))

    return _wrap(run)


def run() -> None:
    """Run the MCP server over stdio (the default CLI command)."""
    mcp.run()
