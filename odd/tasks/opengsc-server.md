# opengsc — minimal read-only GSC MCP server

Minimal, transparent MCP server (Claude Code plugin) pulling data from Google Search
Console. Read-only, small, auditable in one sitting. Python >= 3.10, MIT, package/CLI
`opengsc`, under ~600 lines in `src/opengsc/`.

## Specs

- S1: Scope `https://www.googleapis.com/auth/webmasters.readonly` only. No tool may modify anything (no sitemap submit/delete, no property changes).
- S2: Network: code may only contact `www.googleapis.com`, `searchconsole.googleapis.com`, `oauth2.googleapis.com`, `accounts.google.com` (OAuth flow only). No telemetry, no analytics, no update checks, no CDNs. Enforce with a single allowlist in the HTTP layer that raises on any other host, and a test that proves it. Enforce at transport level: one guarded `requests.Session` subclass (override `send()`) that checks the host of every outgoing request, redirects included. Use that single session everywhere: `AuthorizedSession(credentials, auth_request=Request(session=guarded))`, `credentials.refresh(Request(session=guarded))`, and mount the same guard on the flow's `oauth2session`. Tests must prove token refresh, the auth code exchange, and a redirect to a non-allowed host all hit the guard.
- S3: Dependencies at runtime: `mcp` (official SDK, `mcp.server.fastmcp` — NOT the third-party `fastmcp` package), `google-auth`, `google-auth-oauthlib`. Nothing else. No `google-api-python-client`; call REST directly through `google.auth.transport.requests.AuthorizedSession`.
- S4: Pin runtime deps with `==` in pyproject.toml (application); keep `uv.lock` committed for dev/CI; note in README Transparency that transitive dependencies still float (uvx ignores uv.lock).
- S5: REST endpoints wrapped (nothing else): `GET https://www.googleapis.com/webmasters/v3/sites`; `POST https://www.googleapis.com/webmasters/v3/sites/{siteUrl}/searchAnalytics/query`; `GET https://www.googleapis.com/webmasters/v3/sites/{siteUrl}/sitemaps`; `POST https://searchconsole.googleapis.com/v1/urlInspection/index:inspect`. `siteUrl` must be URL-encoded (supports `sc-domain:example.com` and `https://example.com/`).
- S6: MCP tools exactly: `list_sites()`; `search_analytics(site_url, start_date=None, end_date=None, dimensions=["query"], filters=None, search_type="web", data_state="final", row_limit=1000, start_row=0)`; `list_sitemaps(site_url)`; `inspect_url(site_url, url)`.
- S7: search_analytics defaults: last 28 days ending 3 days ago (GSC lag). dimensions from query, page, country, device, date, searchAppearance. filters: list of `{dimension, operator, expression}` with operators equals, notEquals, contains, notContains, includingRegex, excludingRegex. search_type: web, image, video, news, discover, googleNews. data_state: final, all. row_limit max 25000. Always return metadata: date range used, rows returned, whether more rows may exist. Never truncate silently.
- S8: Metadata block fixed notes (also in README): (a) the API anonymizes rare queries, so sums over the query dimension will not match totals without dimensions; (b) there is a per-day, per-search-type row cap, so very large sites cannot be fully exported regardless of pagination.
- S9: `more_may_exist = (rows returned == row_limit)`. No silent truncation.
- S10: Output: rows as TSV with header line, plus short metadata block. Escape tabs and newlines inside values (`\t`, `\n`) and document it. Do not round ctr or position — return API values as is. `inspect_url` and the sitemaps `contents` array are nested, not tabular: return those as compact JSON exactly as Google sends them; state this in README.
- S11: Do not post-process or analyse data server-side; return raw API data faithfully. API errors surface Google's message and HTTP status, plus one-line hints for: 403 wrong property format; 401 invalid_grant; 429/quota covering BOTH `rateLimitExceeded` and `quotaExceeded` reasons.
- S12: Auth: default OAuth Desktop app client. Client ID/secret via `~/.config/opengsc/client_secret.json` or env `OPENGSC_CLIENT_ID`/`OPENGSC_CLIENT_SECRET`. `opengsc auth` runs local browser flow (with `--no-browser`), stores token at `~/.config/opengsc/token.json` written atomically with 0600 permissions (best effort on Windows), prints `OPENGSC_REFRESH_TOKEN` for stateless setup. Optional service account via `OPENGSC_SERVICE_ACCOUNT_FILE`. Resolution order documented in README and printed by `doctor`. Never log or return secrets/tokens. Logs to stderr only, default WARNING.
- S13: CLI: `opengsc` (no args) runs MCP server over stdio; `opengsc auth` OAuth flow; `opengsc doctor` shows auth mode, token expiry, number of readable properties, config paths, version; masks secrets; exit 1 if auth fails.
- S14: Config dir `~/.config/opengsc/` on ALL OSes. Cross-platform (Windows, macOS, Linux).
- S15: Plugin packaging: `.claude-plugin/plugin.json` and `.mcp.json` launching `uvx opengsc@<pinned version>` (manifest per current Claude Code plugin docs). Also document plain `claude_desktop_config.json` snippet for Claude Desktop. No bundled skills, prompts or slash commands in v1.
- S16: Tests: pytest, no network in tests (mock HTTP session). Cover: URL encoding of site URLs, default date range, request body building, pagination metadata, error mapping, token file permissions, host allowlist (non-allowed host raises), token refresh hits guard, auth code exchange hits guard, redirect to non-allowed host hits guard. Lint/format with ruff. GitHub Actions CI (lint + tests, 3 OSes). Release workflow with PyPI Trusted Publishing (no API token secrets).
- S17: README (English): what it does/does NOT do; Transparency section (exact scope, exact four endpoints, host allowlist, where files are written, full dependency list, transitive-deps-float note); Google Cloud setup step-by-step (enable Search Console API, consent screen, publish app to avoid 7-day testing refresh expiry, Desktop OAuth client); install for Claude Code + Claude Desktop with pinned version; tool reference with one example call each; troubleshooting (property format `sc-domain:` vs URL prefix with trailing slash, invalid_grant, quotas incl. URL Inspection 2,000/day per property, 16-month data limit); TSV escaping and nested-JSON output note.

## Tasks

- T1 [S4,S14,S15] Scaffold: pyproject (== pins, ruff), LICENSE MIT, .gitignore, .claude-plugin/plugin.json, .mcp.json, workflows (ci, release-trusted-publishing). Commit: scaffold
- T2 [S2,S16] allowlist.py: guarded Session.send() + factory wiring (AuthorizedSession auth_request, refresh, flow oauth2session) + tests (blocked host, redirect, refresh, code exchange). Commit: allowlist
- T3 [S1,S3,S12,S14,S16] auth.py: credential resolution, OAuth flow, atomic 0600 token write, refresh-token print + tests. Commit: auth
- T4 [S5,S11,S16] api.py: four REST calls, URL encoding, error mapping with hints + tests. Commit: api
- T5 [S6,S7,S8,S9,S10] server.py: four FastMCP tools, defaults, validation, TSV escaping, metadata block + tests. Commit: server
- T6 [S13,S14,S16] cli.py: serve/auth/doctor, masked output, exit codes + tests. Commit: cli
- T7 [S17] README. Commit: readme
- T8 [S16] uv lock, pytest green, ruff clean, final report (line count, uv tree, deliberate omissions). Commit: finalize

## Log

- L0: Slice boundary note: commit b26a789 (T1+T2) is ~1757 authored lines (mostly
  test scaffolding and lockfile); later slices stay under ~400 lines each.
- L1 (user request): "# Build \"opengsc\": a minimal, transparent MCP server for Google Search Console ..." (full original request in conversation; hard requirements, four endpoints, four MCP tools, auth, CLI, plugin packaging, tests, README, process step 1: show tree + signatures, wait for OK).
- L2 (user amendments after tree/signature review): (1) allowlist at transport level via guarded requests.Session.send(), redirects included, used for AuthorizedSession auth_request + credentials.refresh + flow oauth2session, with tests for refresh, code exchange, redirect bypass; (2) TSV: escape \t and \n, document; inspect_url and sitemaps contents array returned as compact JSON as Google sends, stated in README; do not round ctr/position; (3) add fixed metadata notes: rare-query anonymization breaks query-dimension sums; per-day per-search-type row cap prevents full export of very large sites; (4) 429/quota hint covers rateLimitExceeded AND quotaExceeded; (5) pin runtime deps with == in pyproject (uvx ignores uv.lock), uv.lock for dev/CI, Transparency notes transitives float; use official mcp SDK's mcp.server.fastmcp, not third-party fastmcp. "Go ahead with these changes."
