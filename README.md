# opengsc

[![CI](https://github.com/diegomm27/opengsc/actions/workflows/ci.yml/badge.svg)](https://github.com/diegomm27/opengsc/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Let Claude (or any MCP client) read your **Google Search Console** data and help you with SEO.

- **Read-only.** It can see your data, never change it.
- **Small.** 4 tools, ~900 lines of Python you can audit in one sitting.
- **Private.** Talks only to Google. No telemetry, no third-party servers.

Ask things like *"Which queries get impressions but few clicks?"* or *"Is this page indexed?"* and Claude pulls the real numbers from Search Console.

---

## Setup (about 5 minutes)

You need:

- A Google account with access to at least one [Search Console](https://search.google.com/search-console) property.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) installed. It also installs Python for you if needed.
  - Windows: `winget install astral-sh.uv`
  - macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`

### Step 1. Run the guided setup

```bash
uvx opengsc setup
```

It walks you through the Google Cloud steps one at a time, opening the right page in your browser and waiting for you to finish:

1. Create a project.
2. Enable the Search Console API.
3. Configure the consent screen (**External**).
4. Create a **Desktop app** OAuth client and download its JSON.
5. Fill in Branding with your website's links (no logo).
6. Publish the app.

Then it finds the JSON in your Downloads folder (or asks for the path), checks it is a Desktop client, copies it to `~/.config/opengsc/client_secret.json` with `0600` permissions, runs the Google login, checks that your properties are readable, and prints the snippet to connect Claude.

- It never overwrites a different client file without asking, and only deletes your download if you say yes.
- No browser? Add `--no-browser` to print the URLs instead.
- Ctrl+C at any point is safe; run `uvx opengsc setup` again to resume.

### Step 2. Connect it to Claude

opengsc runs on your computer, so it works in **Claude Desktop** and **Claude Code** (not in claude.ai in the browser).

**Claude Desktop:** open *Settings → Developer → Edit Config* and add `opengsc` to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "opengsc": {
      "command": "uvx",
      "args": ["opengsc@0.2.0"]
    }
  }
}
```

If the file already has other servers, add only the `"opengsc": {...}` block inside `mcpServers`. Then **quit Claude Desktop completely** (including the tray/menu bar icon) and reopen it.

**Claude Code** (pick one):

```bash
# as a plugin
claude plugin marketplace add diegomm27/opengsc
claude plugin install opengsc@opengsc

# or as a plain MCP server
claude mcp add opengsc -- uvx opengsc@0.2.0
```

**Any other MCP client:** run `uvx opengsc@0.2.0` over stdio.

---

## CLI commands

| Command | What it does |
| --- | --- |
| `opengsc setup` | Guided setup: Google Cloud steps, client file, login, check. |
| `opengsc auth` | Run the Google login (`--no-browser` prints the URL). |
| `opengsc doctor` | Auth mode, token expiry, readable properties, config paths, version. |
| `opengsc serve` | Run the MCP server over stdio (also the default with no arguments). |

<details>
<summary>Manual setup</summary>

### 1. Create a Google OAuth client

This gives opengsc permission to ask Google for your data. You do it once.

1. **Create a project.** Open [console.cloud.google.com/projectcreate](https://console.cloud.google.com/projectcreate), name it `opengsc` and click **Create**. Make sure it is selected in the project picker at the top.

   *Tip: use a dedicated project. The consent screen is shared by everything in a project.*

2. **Enable the API.** Open the [Search Console API page](https://console.cloud.google.com/apis/library/searchconsole.googleapis.com) and click **Enable**.

3. **Set up the consent screen.** Open [Google Auth Platform](https://console.cloud.google.com/auth/overview) and click **Get started**:
   - App name: `opengsc`
   - User support email: your email
   - Audience: **External**
   - Contact email: your email
   - Accept the policy and click **Create**.

4. **Create the client.** Open [Clients](https://console.cloud.google.com/auth/clients), click **Create client**:
   - Application type: **Desktop app** (not *Web application*)
   - Name: `opengsc`
   - Click **Create**, then **Download JSON** right away. Google won't show the secret again.

5. **Fill in Branding.** Open [Branding](https://console.cloud.google.com/auth/branding). Google won't let you publish without these links:
   - App logo: leave it **empty**. Uploading one forces Google verification.
   - Application home page: your website, e.g. `https://example.com`
   - Privacy policy link: your website's privacy page. If it has none, use `https://github.com/diegomm27/opengsc#security-and-transparency`
   - Terms of service link: leave it empty.
   - Authorized domains: your domain, e.g. `example.com` (the one you verified in Search Console). Add `github.com` too if you used the link above.
   - Click **Save**.

6. **Publish the app.** Open [Audience](https://console.cloud.google.com/auth/audience) and click **Publish app**, then confirm. The status should read **In production**.

   - *Why:* in *Testing* mode, Google expires your login every 7 days.
   - *Is it safe?* Yes. Publishing does **not** make your data public. Anyone who logs in through it only sees their own Search Console, and nobody can read yours without your Google login.

### 2. Put the JSON file in place

Rename the downloaded file to `client_secret.json` and move it here:

| OS | Location |
| --- | --- |
| Windows | `C:\Users\<you>\.config\opengsc\client_secret.json` |
| macOS / Linux | `~/.config/opengsc/client_secret.json` |

**Windows (PowerShell):**

```powershell
mkdir $HOME\.config\opengsc -Force
Move-Item $HOME\Downloads\client_secret_*.json $HOME\.config\opengsc\client_secret.json
```

**macOS / Linux:**

```bash
mkdir -p ~/.config/opengsc
mv ~/Downloads/client_secret_*.json ~/.config/opengsc/client_secret.json
```

> **Windows gotcha:** if you rename the file in Explorer with extensions hidden, it can end up as `client_secret.json.json`. Check with `dir $HOME\.config\opengsc`.

### 3. Log in and check

```bash
uvx opengsc auth
```

Your browser opens:

1. Pick the Google account that has access to Search Console.
2. You'll see **"Google hasn't verified this app"**. That's expected for a personal app: click **Advanced → Go to opengsc**.
3. Allow read access to Search Console.

Your login is saved to `~/.config/opengsc/token.json`. On a machine without a browser, add `--no-browser` and open the printed URL yourself.

Check that everything works:

```bash
uvx opengsc doctor
```

You should see `auth check: OK` and a property count above 0.

</details>

---

## Try it

Start a new chat and ask:

- "List my Search Console properties."
- "Top 50 queries by impressions in the last 28 days for sc-domain:example.com."
- "Which pages have lots of impressions but a CTR under 2%?"
- "Queries where I rank between 5 and 15 on mobile."
- "Check the status of my sitemaps."
- "Is https://example.com/blog/post indexed?"

Start with the first one: it returns the exact property names (`sc-domain:...` or `https://.../`) the other tools need.

---

## Tools

| Tool | What it returns |
| --- | --- |
| `list_sites()` | Properties you can read, with your permission level. |
| `search_analytics(site_url, ...)` | Clicks, impressions, CTR and position, by query, page, country, device, date or search appearance. Supports filters. |
| `list_sitemaps(site_url)` | Submitted sitemaps, last download, errors and warnings. |
| `inspect_url(site_url, url)` | Index status, canonical, last crawl, mobile usability. Limited by Google to 2,000 calls/day per property. |

Data comes back unprocessed (TSV or Google's raw JSON), so Claude works with exact numbers.

<details>
<summary><code>search_analytics</code> parameters</summary>

| Parameter | Default | Options |
| --- | --- | --- |
| `start_date`, `end_date` | last 28 days, ending 3 days ago (GSC data lag) | `YYYY-MM-DD` |
| `dimensions` | `["query"]` | `query`, `page`, `country`, `device`, `date`, `searchAppearance` |
| `filters` | none | list of `{"dimension", "operator", "expression"}`; operators `equals`, `notEquals`, `contains`, `notContains`, `includingRegex`, `excludingRegex` |
| `search_type` | `web` | `web`, `image`, `video`, `news`, `discover`, `googleNews` |
| `data_state` | `final` | `final`, `all` (includes fresh data) |
| `row_limit` | `1000` | 1 to 25000 |
| `start_row` | `0` | for pagination |

The output ends with a metadata block. `more_may_exist: true` means the page was full; ask for the next one with `start_row`.

</details>

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `No OAuth client configured` | Run `opengsc setup`, or check the path and name (Manual setup, step 2). |
| `auth` fails right away with a valid-looking file | The client must be **Desktop app**. Open the JSON: it should start with `{"installed":`. If it starts with `{"web":`, create a new Desktop client. |
| "Google hasn't verified this app" | Normal. Click **Advanced → Go to opengsc**. |
| `401` / `invalid_grant` | Login expired or was revoked. Usually the app was left in *Testing*: publish it (Manual setup, step 1.6), then run `opengsc auth` again. |
| `403` / "User does not have permission" | Wrong property name or no access. Use the exact string from `list_sites()`: `sc-domain:example.com` for domain properties, `https://example.com/` (with the trailing slash) for URL-prefix ones. |
| `doctor` shows 0 properties | You logged in with an account that has no Search Console access. Run `auth` again with the right one. |
| Claude doesn't see the tools | Fully restart Claude Desktop. In Claude Code, run `claude mcp list`. |
| `429` / quota exceeded | Google's daily limits. Wait and retry. |
| No data for old dates | Search Console only keeps 16 months. |
| Query totals don't add up | Google hides rare queries for privacy, so per-query sums are lower than the site total. |

To revoke access at any time: [myaccount.google.com/permissions](https://myaccount.google.com/permissions) → opengsc → **Remove access**.

---

## Security and transparency

- **Permission requested:** only `https://www.googleapis.com/auth/webmasters.readonly`. opengsc cannot submit sitemaps, edit properties or manage users.
- **Network lock:** every request goes through one guard ([`src/opengsc/allowlist.py`](src/opengsc/allowlist.py)) that only allows `www.googleapis.com`, `searchconsole.googleapis.com`, `oauth2.googleapis.com` and `accounts.google.com`. Anything else, redirects included, fails before it's sent.
- **Endpoints used:** `sites.list`, `searchAnalytics.query`, `sitemaps.list`, `urlInspection.index.inspect`. Nothing else.
- **Files on disk:** `~/.config/opengsc/client_secret.json` (yours, installed by `opengsc setup` with `0600` permissions) and `~/.config/opengsc/token.json` (your login, also `0600`; best effort on Windows). **Keep `token.json` private:** whoever has it can read your Search Console.
- **Dependencies:** `mcp`, `google-auth`, `google-auth-oauthlib`, pinned exactly. That's all.
- **Not included on purpose:** writes, analysis or scoring, telemetry, update checks, bundled prompts.

<details>
<summary>Advanced: other ways to authenticate</summary>

opengsc looks for credentials in this order (`doctor` shows which one it used):

1. **Service account:** set `OPENGSC_SERVICE_ACCOUNT_FILE` to the path of a service account JSON key. Then add the service account's email as a user of your property in Search Console (*Settings → Users and permissions*). No browser login needed, good for servers.
2. **Refresh token from the environment:** `opengsc auth` prints `OPENGSC_REFRESH_TOKEN=...` once. Set that variable (plus the OAuth client, see below) to run without a `token.json` file, for example in a container. Treat it like a password.
3. **Saved login:** `~/.config/opengsc/token.json`, created by `opengsc auth`.

Instead of `client_secret.json`, you can provide the OAuth client with the `OPENGSC_CLIENT_ID` and `OPENGSC_CLIENT_SECRET` environment variables.

</details>

---

## Development

```bash
git clone https://github.com/diegomm27/opengsc.git
cd opengsc
uv sync                      # install with dev dependencies
uv run pytest                # tests (no network, HTTP is mocked)
uv run ruff check src tests && uv run ruff format --check src tests
claude plugin validate .     # check the plugin manifest
```

CI runs lint and tests on Linux, macOS and Windows (Python 3.10 and 3.12). Releases are published to PyPI through Trusted Publishing.

## License

MIT. See [LICENSE](LICENSE).
