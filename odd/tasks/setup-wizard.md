# opengsc — guided setup wizard (`opengsc setup`)

Add an interactive `setup` command that walks the Google Cloud steps, finds and
validates the downloaded Desktop OAuth client, installs it, then runs auth and
doctor. Standard library only; no new runtime dependencies.

## Specs

- S1: Branch and delivery. "Create and work on `feat/setup-wizard` from an
  up-to-date `main`. Do not push and do not open a PR; I will review first."
  Later correction: "Cuando acabes, haz push." → push `feat/setup-wizard` at
  the end (no PR) and show `git log --oneline main..HEAD`.
- S2: Short-circuit. "If a valid client_secret.json exists (or
  OPENGSC_CLIENT_ID/SECRET are set), say so and offer to jump straight to auth.
  If a token also exists and `doctor`-style checks pass, say everything is
  ready and exit 0."
- S3: Walkthrough. "Walks the Google Cloud steps one at a time. For each step:
  print a short explanation (1 to 3 lines), open the exact URL with
  `webbrowser.open`, and wait for Enter." Steps and URLs exactly:
  - Create a project: https://console.cloud.google.com/projectcreate
  - Enable the API: https://console.cloud.google.com/apis/library/searchconsole.googleapis.com
  - Consent screen: https://console.cloud.google.com/auth/overview (External, app name, emails)
  - Publish the app: https://console.cloud.google.com/auth/audience (explain in one line that publishing does not expose the user's data and avoids the 7-day token expiry)
  - Create a Desktop app client and download the JSON: https://console.cloud.google.com/auth/clients
  "Add `--no-browser` to print URLs instead of opening them."
- S4: Discovery. "Look in the user's Downloads folder (Path.home() / "Downloads";
  handle Windows, macOS and Linux) for files matching `client_secret*.json`,
  including the `*.json.json` double-extension case. Pick the most recently
  modified. If none or several ambiguous ones are found, ask for a path (accept
  paste with surrounding quotes, as Windows "Copy as path" adds them)."
- S5: Validation. "It must be valid JSON with a top-level `installed` key
  containing `client_id` and `client_secret`. If it has `web` instead, explain
  that a Desktop app client is required and loop back to the client step.
  Never print the secret."
- S6: Install. "Copy (do not move) it to ~/.config/opengsc/client_secret.json,
  creating the directory, with 0600 permissions (best effort on Windows, same
  approach as save_token). If a different file already exists there, ask before
  overwriting. After success, offer to delete the original from Downloads
  (default: no)."
- S7: Auth, doctor, next step. "Call the existing run_oauth_flow (respecting
  --no-browser) and then the doctor logic, and finish with a short "next step"
  message showing the Claude Desktop JSON snippet and the `claude mcp add`
  command."
- S8: Interrupt. "Ctrl+C at any step exits cleanly with code 130 and a one-line
  hint that `opengsc setup` can be re-run."
- S9: Constraints. "No new runtime dependencies. Standard library only
  (webbrowser, json, pathlib, shutil, input). All network traffic must still go
  through the existing allowlist guard. setup itself must not make any HTTP
  request except through run_oauth_flow and the doctor check. Keep the code
  small and readable, consistent with the project's style. Target well under
  200 lines for the new module. Prompts and output go to stdout; logs keep going
  to stderr. Keep `auth`, `doctor` and `serve` behaviour unchanged."
- S10: Tests, in tests/test_setup.py, "with everything mocked (input,
  webbrowser.open, filesystem via tmp_path, run_oauth_flow, api). Cover at
  least: already configured, short-circuits; finds the newest
  client_secret*.json in Downloads, including the .json.json case; rejects a
  `web` client and explains why; rejects invalid JSON; asks before overwriting
  an existing different file; strips quotes from a pasted path; --no-browser
  prints URLs and never calls webbrowser.open; KeyboardInterrupt exits with 130;
  the secret never appears in stdout." Gates: "Run `uv run pytest -q`,
  `uv run ruff check src tests` and `uv run ruff format --check src tests`; all
  must pass."
- S11: Docs. "In Setup, make `opengsc setup` the recommended path (one command),
  keeping the existing manual steps under a collapsible "Manual setup" section."
  Install form: PyPI check gate — "If PyPI publishing for 0.1.0 has succeeded by
  the time you check (https://pypi.org/pypi/opengsc/json returns 200), use
  `uvx opengsc setup` everywhere instead and also update .mcp.json and the
  Claude Desktop snippet to `uvx opengsc@<version>`." (Check returned 200,
  version 0.1.0 → PyPI form wins.) "Add `setup` to the CLI commands mentioned in
  the README."
- S12: Version. "Bump the version to 0.2.0 in pyproject.toml,
  src/opengsc/__init__.py and .claude-plugin/plugin.json."
- S13: Commits and report. "Make small, focused commits (module, tests, CLI
  wiring, docs, version bump) with conventional commit messages. At the end,
  show me `git log --oneline main..HEAD` and a short summary of what changed and
  anything you were unsure about."

## Tasks

- T1 [S2-S9] src/opengsc/setup.py: wizard, discovery, validation, install,
  auth/doctor/next-step, interrupt-safe prompts — commit —
- T2 [S2,S3,S8] src/opengsc/cli.py: `setup` subcommand + `--no-browser`,
  KeyboardInterrupt → 130 — commit —
- T3 [S10] tests/test_setup.py — commit —
- T4 [S11] README setup rewrite + CLI commands, .mcp.json PyPI form — commit —
- T5 [S12] version 0.2.0 in pyproject.toml, __init__.py, plugin.json, uv.lock — commit —
- T6 [S1,S13] full gates (pytest, ruff check, ruff format), report, push — commit —

## Log

- L1 (user request): "Implement a guided setup command for opengsc on a new
  branch." followed by the full specification quoted in S1-S13, including
  "Do not push and do not open a PR; I will review first", "Target well under
  200 lines for the new module", the mocked test list, the PyPI gate, and
  "Cuando acabes, haz push."
- L2 (environment incident, pre-branch): `.venv` was a broken partial venv
  (only `pyvenv.cfg` and a `lib64` symlink); `uv run` failed with "Acceso
  denegado" removing `.venv/lib64`. Removed the ignored `.venv`, `uv sync`
  recreated it; baseline 81 passed, 1 skipped.
- L3 (evidence): PyPI `opengsc` JSON returns 200 with version 0.1.0 only → S11
  PyPI form applies (`uvx opengsc`, pinned `uvx opengsc@<version>` in MCP
  snippets).
