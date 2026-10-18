# opengsc

[![CI](https://github.com/diegomm27/opengsc/actions/workflows/ci.yml/badge.svg)](https://github.com/diegomm27/opengsc/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A minimal, transparent MCP server for Google Search Console. It pulls GSC data
(properties, search analytics, sitemaps, URL inspection) so Claude or any MCP
client can help you with SEO — read-only, small, and auditable in one sitting.

- **4 tools, 4 endpoints, ~700 lines of Python.** You can read the whole thing.
- **Read-only.** It requests only
  `https://www.googleapis.com/auth/webmasters.readonly`. It cannot submit
  sitemaps, change properties, or manage users.
- **Faithful data.** Raw API output as TSV or verbatim JSON — no scoring, no
  summarizing, no rounding.
- **Network-locked.** Every outbound request passes one transport-level guard
  that only allows the four Google hosts below. Anything else raises.

## What it does NOT do (on purpose)

- No writes: no sitemap submit/delete, no property changes.
- No analysis: it returns data; your assistant does the thinking.
- No telemetry, no update checks, no CDNs.
- No bundled skills, prompts, or slash commands.

## Transparency

**OAuth scope (the only one requested):**
`https://www.googleapis.com/auth/webmasters.readonly`

**The exact four endpoints contacted:**

1. `GET https://www.googleapis.com/webmasters/v3/sites`
2. `POST https://www.googleapis.com/webmasters/v3/sites/{siteUrl}/searchAnalytics/query`
3. `GET https://www.googleapis.com/webmasters/v3/sites/{siteUrl}/sitemaps`
4. `POST https://searchconsole.googleapis.com/v1/urlInspection/index:inspect`

**Host allowlist.** All outbound HTTP goes through one guarded
`requests.Session.send()` override (`src/opengsc/allowlist.py`). Any request to
a host outside this set raises before it is sent — redirects included:

- `www.googleapis.com`
- `searchconsole.googleapis.com`
- `oauth2.googleapis.com`
- `accounts.google.com` (OAuth flow only)

The same guard wraps token refresh and the OAuth code exchange; tests prove
each path hits it.

**Files written** (same location on every OS):

| Path | Content |
| --- | --- |
| `~/.config/opengsc/client_secret.json` | optional; your OAuth client credentials (you provide it) |
| `~/.config/opengsc/token.json` | OAuth token, written atomically with `0600` permissions (best effort on Windows) |

**Dependencies.** Runtime, pinned exactly (`uvx` resolves from these ranges,
not from `uv.lock`):

- `mcp==1.30.0` — official Model Context Protocol SDK (`mcp.server.fastmcp`)
- `google-auth==2.62.0`
- `google-auth-oauthlib==1.5.0`

Transitive dependencies are not pinned and float per install; `uv.lock` pins
them for development and CI only. Dev-only: `pytest`, `ruff`. That is the
entire list.

## Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/) (provides `uvx`)
- Python 3.10+ (installed automatically by `uvx` if missing)
- A Google account with access to at least one Search Console property

## One-time Google Cloud setup

1. Go to [console.cloud.google.com](https://console.cloud.google.com/) and
   create (or pick) a project.
2. **Enable the Search Console API**: *APIs & Services → Library* → search
   "Search Console API" → **Enable**.
3. **Configure the consent screen**: *APIs & Services → OAuth consent screen*
   → External → fill in the minimum → add yourself as a test user if you keep
   it in Testing.
4. **Publish the app** (consent screen → "PUBLISH APP"). If you leave it in
   *Testing*, refresh tokens stop working after 7 days and you will have to
   re-authenticate weekly.
5. **Create an OAuth client**: *APIs & Services → Credentials → Create
   credentials → OAuth client ID* → Application type **Desktop app**. Download
   the `client_secret.json` file and copy the client ID/secret.

## Install

### Claude Code (plugin, one command)

```bash
claude plugin marketplace add diegomm27/opengsc
claude plugin install opengsc@opengsc
```

The plugin bundles the MCP server config; it launches `uvx opengsc@0.1.0`.

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

### Any other MCP client (stdio)

Same shape as above: run the command `uvx opengsc@0.1.0` over stdio.

### Authenticate

```bash
uvx opengsc@0.1.0 auth                # opens the browser
uvx opengsc@0.1.0 auth --no-browser   # prints the URL; still completes on localhost
```

The client ID/secret come from `~/.config/opengsc/client_secret.json` (the
file you downloaded from Google Cloud Console) or from env vars
`OPENGSC_CLIENT_ID` / `OPENGSC_CLIENT_SECRET`.

After the flow, the token is stored at `~/.config/opengsc/token.json` (0600)
and the command prints `OPENGSC_REFRESH_TOKEN=...` once — for stateless setups
(pass it as that env var plus the client ID/secret instead of the token file).

**Credential resolution order** (also printed by `opengsc doctor`):

1. `OPENGSC_SERVICE_ACCOUNT_FILE` — service account JSON (optional; share the
   property with the service account's email)
2. `~/.config/opengsc/token.json` — saved OAuth token
3. otherwise: run `opengsc auth`

Check everything: `uvx opengsc@0.1.0 doctor` — shows auth mode, token expiry,
readable property count, config paths, version. Exits 1 if auth fails. Secrets
are never printed; logs go to stderr (WARNING by default).

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

Example: top queries and device for the default range (last 28 days, ending
3 days ago to respect GSC's data lag), filtered to mobile:

```
search_analytics(
  site_url="sc-domain:example.com",
  dimensions=["query", "device"],
  filters=[{"dimension": "device", "operator": "equals", "expression": "MOBILE"}],
  row_limit=25
)
```

Output is TSV with a header (`query  device  clicks  impressions  ctr
position`), `ctr`/`position` at full API precision (never rounded), then a
metadata block:

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

- `more_may_exist: true` means the page was full (`rows == row_limit`);
  paginate with `start_row`.
- Tabs and newlines inside values are escaped as `\t` / `\n`.
- `row_limit` max 25000; out-of-range values are rejected, never clamped.
- Dimensions: `query`, `page`, `country`, `device`, `date`, `searchAppearance`.
- Search types: `web`, `image`, `video`, `news`, `discover`, `googleNews`.
- `data_state`: `final` (default) or `all` (includes fresh, unfinished data).
- Filter operators: `equals`, `notEquals`, `contains`, `notContains`,
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
  was left in *Testing* — see setup step 4 — or the refresh token was
  rotated). Run `opengsc auth` again.
- **429 / `rateLimitExceeded` / `quotaExceeded`** — Search Console enforces
  per-day, per-property quotas; URL Inspection is limited to 2,000
  queries/day per property. Wait or reduce volume.
- **Empty results for old dates** — Search Console only keeps 16 months of
  data; earlier dates return nothing.
- **Query sums don't match** — rare queries are anonymized; sums over the
  `query` dimension will not match totals queried without dimensions.
  Google-side behavior, not a bug.
- **Very large sites return fewer rows than expected** — there is a per-day,
  per-search-type row cap; pagination cannot export beyond it.

## Development

```bash
git clone https://github.com/diegomm27/opengsc.git
cd opengsc
uv sync          # install with dev deps
uv run pytest    # tests (no network; HTTP is mocked)
uv run ruff check src tests && uv run ruff format --check src tests
claude plugin validate .   # plugin manifest check
```

CI runs lint + tests on Linux, macOS and Windows (Python 3.10/3.12).
Releases go to PyPI via Trusted Publishing (no API token secrets).

## License

MIT — see [LICENSE](LICENSE).
