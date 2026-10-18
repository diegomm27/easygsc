# opengsc

A minimal, transparent MCP server for Google Search Console. It pulls GSC data
(properties, search analytics, sitemaps, URL inspection) so an AI assistant can
help with SEO — read-only, small, and auditable in one sitting.

Packaged as a Claude Code plugin; works with Claude Desktop and any MCP client
over stdio.

## What it does NOT do (on purpose)

- **No writes.** Every tool is read-only. The OAuth scope requested is
  `https://www.googleapis.com/auth/webmasters.readonly`. There is no sitemap
  submit/delete, no property management, no user management.
- **No analysis.** It returns Google's data faithfully (TSV rows or verbatim
  JSON). It does not rank, score, summarize or interpret anything server-side.
- **No extras.** Exactly four endpoints, four tools, no bundled skills,
  prompts or slash commands. No telemetry, no update checks.

## Transparency

Everything below is verifiable in `src/opengsc/` (~600 lines total).

**OAuth scope (the only one requested):**
`https://www.googleapis.com/auth/webmasters.readonly`

**The exact four endpoints contacted:**

1. `GET https://www.googleapis.com/webmasters/v3/sites`
2. `POST https://www.googleapis.com/webmasters/v3/sites/{siteUrl}/searchAnalytics/query`
3. `GET https://www.googleapis.com/webmasters/v3/sites/{siteUrl}/sitemaps`
4. `POST https://searchconsole.googleapis.com/v1/urlInspection/index:inspect`

**Host allowlist.** All outbound HTTP goes through one guarded
`requests.Session.send()` override (`src/opengsc/allowlist.py`). Any request to
a host outside this set raises before it is sent — including redirects:

- `www.googleapis.com`
- `searchconsole.googleapis.com`
- `oauth2.googleapis.com`
- `accounts.google.com` (OAuth flow only)

The same guard wraps token refresh (`google-auth`'s refresh session) and the
OAuth code exchange (`google-auth-oauthlib`'s session). A test proves each of
these paths hits the guard.

**Files written** (same location on every OS):

| Path | Content |
| --- | --- |
| `~/.config/opengsc/client_secret.json` | optional; your OAuth client credentials (you provide it) |
| `~/.config/opengsc/token.json` | OAuth token, written atomically with `0600` permissions (best effort on Windows) |

**Dependencies.** Runtime (pinned exactly, because `uvx` resolves from these
ranges, not from `uv.lock`):

- `mcp==1.30.0` — official Model Context Protocol SDK (`mcp.server.fastmcp`)
- `google-auth==2.62.0`
- `google-auth-oauthlib==1.5.0`

Transitive dependencies (of `mcp` and the google-auth stack) are **not**
pinned and still float with each install; `uv.lock` pins them for development
and CI only. Dev-only: `pytest`, `ruff`. That is the entire list.

## Google Cloud setup (one time)

1. Go to [console.cloud.google.com](https://console.cloud.google.com/) and
   create (or pick) a project.
2. **Enable the Search Console API**: *APIs & Services → Library* → search
   "Search Console API" → **Enable**.
3. **Configure the consent screen**: *APIs & Services → OAuth consent screen*
   → External → fill the minimum → add yourself as a test user if you keep it
   in Testing.
4. **Publish the app** (consent screen → "PUBLISH APP"). If you leave it in
   *Testing*, refresh tokens stop working after 7 days and you will have to
   re-run `opengsc auth` weekly.
5. **Create an OAuth client**: *APIs & Services → Credentials → Create
   credentials → OAuth client ID* → Application type **Desktop app**. Copy the
   client ID and secret.

## Install

### Claude Code (plugin)

This repository is a Claude Code plugin. Install it from your clone:

```bash
claude plugin install <path-to-this-repo>
```

or add it via a marketplace. The bundled `.mcp.json` launches the pinned
version, equivalent to:

```json
{
  "mcpServers": {
    "opengsc": { "command": "uvx", "args": ["opengsc@0.1.0"] }
  }
}
```

### Claude Desktop

Add to `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "opengsc": {
      "command": "uvx",
      "args": ["opengsc@0.1.0"]
    }
  }
}
```

### Authenticate

```bash
uvx opengsc@0.1.0 auth            # opens the browser
uvx opengsc@0.1.0 auth --no-browser  # prints the URL; still completes on localhost
```

The client ID/secret come from `~/.config/opengsc/client_secret.json` (the
file you download from Google Cloud Console) or from env vars
`OPENGSC_CLIENT_ID` / `OPENGSC_CLIENT_SECRET`.

After the flow, the token is stored at `~/.config/opengsc/token.json` (0600)
and the command prints `OPENGSC_REFRESH_TOKEN=...` once, for stateless setups
(pass it as that env var plus the client ID/secret instead of relying on the
token file).

**Credential resolution order** (also printed by `opengsc doctor`):

1. `OPENGSC_SERVICE_ACCOUNT_FILE` — service account JSON (optional; share the
   property with the service account's email)
2. `~/.config/opengsc/token.json` — saved OAuth token
3. otherwise: run `opengsc auth`

Check everything: `uvx opengsc@0.1.0 doctor` — shows auth mode, token expiry,
readable property count, config paths, version. Exit 1 if auth fails. Secrets
are never printed; logs go to stderr (level WARNING by default).

## Tool reference

### `list_sites()`

Properties the account can read, with permission level. Use the `site_url`
values verbatim in the other tools.

```
site_url	permission_level
sc-domain:example.com	siteOwner
https://example.com/	siteFullUser
```

### `search_analytics(site_url, start_date=None, end_date=None, dimensions=["query"], filters=None, search_type="web", data_state="final", row_limit=1000, start_row=0)`

Example: top queries, last 28 days (default), filtered to mobile:

```
search_analytics(
  site_url="sc-domain:example.com",
  dimensions=["query", "device"],
  filters=[{"dimension": "device", "operator": "equals", "expression": "MOBILE"}],
  row_limit=25
)
```

Output is TSV with a header (`query  device  clicks  impressions  ctr
position`), values `ctr`/`position` at full API precision (never rounded),
then a metadata block:

```
date_range: 2026-01-21..2026-02-17
search_type: web
rows_returned: 25
row_limit: 25
start_row: 0
more_may_exist: true
note: the API anonymizes rare queries, so sums over the query dimension will not match totals queried without dimensions.
note: the API applies a per-day, per-search-type row cap, so very large sites cannot be fully exported regardless of pagination.
```

`more_may_exist: true` means the page was full (`rows == row_limit`); paginate
with `start_row`. Tabs and newlines inside values are escaped as `\t` / `\n`.
`row_limit` max 25000; out-of-range values are rejected, never clamped.
Search types: `web`, `image`, `video`, `news`, `discover`, `googleNews`.
`data_state`: `final` (default) or `all` (includes fresh data).
Filters operators: `equals`, `notEquals`, `contains`, `notContains`,
`includingRegex`, `excludingRegex`.

### `list_sitemaps(site_url)`

Submitted sitemaps with last download, error/warning counts. Top-level fields
are TSV; the nested `contents` array is returned as compact JSON exactly as
Google sends it.

### `inspect_url(site_url, url)`

URL Inspection: index status, coverage, canonical, last crawl, mobile
usability if present. Returned as compact JSON verbatim. Counts against
Google's quota of 2,000 queries/day per property.

## Troubleshooting

- **403 / "User does not have permission"** — property format. Domain
  properties are `sc-domain:example.com` (no scheme, no path); URL-prefix
  properties are the full URL **with trailing slash** (`https://example.com/`).
  `list_sites()` prints the exact strings to use. Also confirm the account has
  access to the property.
- **401 / `invalid_grant`** — the token expired or was revoked (e.g. the app
  was left in *Testing*, see setup step 4, or the refresh token was rotated).
  Run `opengsc auth` again.
- **429 / `rateLimitExceeded` / `quotaExceeded`** — Search Console enforces
  per-day, per-property quotas; URL Inspection is limited to 2,000
  queries/day per property. Wait or reduce volume.
- **Empty results for old dates** — Search Console only keeps 16 months of
  data; earlier dates return nothing.
- **Query sums don't match** — rare queries are anonymized; sums over the
  `query` dimension will not match totals without dimensions. This is a
  Google-side behavior, not a bug.
- **Very large sites return fewer rows than expected** — there is a per-day,
  per-search-type row cap; pagination cannot export beyond it.

## Development

```bash
uv sync          # install with dev deps
uv run pytest    # tests (no network; HTTP is mocked)
uv run ruff check src tests && uv run ruff format --check src tests
```

CI runs lint + tests on Linux, macOS and Windows (Python 3.10/3.12).
Releases go to PyPI via Trusted Publishing (no API token secrets).

## License

MIT — see [LICENSE](LICENSE).
