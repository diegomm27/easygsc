# opengsc — connect any AI app from the wizard

Objective: after login, the wizard connects opengsc to the user's AI apps with a launch
command that works today. Branch `feat/setup-wizard`; delivery: work-unit commits, PR
slicing left to the user; runner `uv run pytest -q`.

## Specs

- S1: "Que se pueda usar con CUALQUIER IA". After a successful login, the wizard offers
  to connect opengsc to the AI apps on this computer: a list of supported apps plus an
  "another app" choice that prints the generic settings (command, arguments, JSON) any
  MCP client accepts. Assumption: "any AI" means any app that can run a local MCP
  server; browser-only chats cannot start a program on the user's computer, so they
  are documented as unsupported, not implemented.
- S2: "ahora mismo". The command written into each app must work today, before 0.2.0
  is on PyPI. It is derived from how this opengsc was installed: index release ->
  `uvx opengsc@<version>`; git install -> `uvx --from git+<url>@<commit> opengsc`;
  local clone -> `uv run --directory <clone> opengsc`. Use the absolute path of
  `uv`/`uvx` when found, so GUI apps without the shell PATH can start it.
- S3: "Que sea interactivo y fácil de seguir". Numbered menu; apps found on this
  computer are marked and chosen by pressing Enter; each result is one plain line that
  says what changed and what to do next (restart the app), then one example question
  to ask the AI. `q`/`quit`/EOF cancel like every other wizard prompt (exit 2, clear
  message that says the login is already saved).
- S4 (assumption, from the risk policy): editing an app's existing config never loses
  data. Only plain valid JSON is edited; anything else gets printed manual steps. A
  backup is written before any change, the file is replaced atomically, other entries
  stay untouched, and a different existing `opengsc` entry is replaced only after a
  yes.
- S5 (design choice): `opengsc connect` runs only this step, so apps can be added later;
  `opengsc setup` runs the same flow at the end, including when everything was
  already set up.
- S6: "No te añadas como coauthor; todo lo hago yo." Commits carry no Co-Authored-By or
  AI attribution. Push, PR and release stay with the user.
- S7: test first where applicable; gates `uv run pytest -q`,
  `uv run ruff check src tests`, `uv run ruff format --check src tests`.
- S8: README Step 2 describes the wizard-driven connection, the supported apps and the
  manual route for any other MCP app; CLI table and help list `connect`.

## Tasks

- T1 [S2,S4] connect core: launch command from `direct_url.json` + safe JSON config
  merge (backup, atomic replace, refuse non-JSON, ask before replacing) — inline (no
  writer trigger: depends on nothing, T2 depends on it) — commit dcfb333 — DONE
- T2 [S1,S3,S5,S8] interactive connect flow: app registry, menu, app CLIs, `opengsc
  connect`, setup wiring, help and README — inline (depends on T1) — commits fec1983
  (menu + registry) and the commit that adds this line (setup/CLI wiring + docs) — DONE
- T3 [S6,S7] gates, independent verifier (Risk item 1), RDD review — gates DONE;
  native review of T1 waits for the user's consent; verifier pending

## Log

- L1 (user request, 2026-10-20): "Que se pueda usar con CUALQUIER IA ahora mismo. Que
  sea interactivo y fácil de seguir. Adelante. No te añadas como coauthor; todo lo hago
  yo." It answers the question "¿Querés que el wizard además escriba solo la config de
  Claude Desktop, o corra `claude mcp add` por el usuario, para sacar el paso de editar
  JSON a mano?"
- L2 (evidence): PyPI serves only 0.1.0; `direct_url.json` reports
  `{"dir_info": {"editable": true}}` under `uv run` and `vcs_info.commit_id` for a git
  install, so the install source is detectable offline. Line forecast: ~700 authored
  lines on top of ~962 already on the branch; PR slicing is the user's call (S6).
- L3 (research, read-only worker): Claude Desktop paths per OS and `mcpServers` shape
  (modelcontextprotocol.io/docs/develop/build-server); the Microsoft Store build reads
  `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\` (UNVERIFIED, community
  reports), so every existing copy gets the entry. `claude mcp add` refuses a duplicate
  name (code.claude.com/docs/en/mcp); `codex mcp add` overwrites silently
  (openai/codex `mcp_cmd.rs`), so `config.toml` is checked first. VS Code uses
  `servers` + `"type": "stdio"` (code.visualstudio.com/docs/agents/reference/
  mcp-configuration); its user `mcp.json` path is inferred from the settings.json
  locations. Windsurf is now Devin Desktop (docs.devin.ai/desktop/cascade/mcp). Gemini
  CLI and Zed allow comments: a commented file gets manual steps; Zed is left to
  "another app". ChatGPT supports only remote MCP
  (developers.openai.com/api/docs/guides/custom-mcp-server), confirming S1's assumption.
- L4 (test evidence): T1 RED = collection error (no `opengsc.connect`), GREEN 18 passed.
  T2's tests were written after its code; RED was observed by running them against the
  dcfb333 source: collection error in test_connect (no `APPS`) plus 8 failures in
  test_setup/test_cli. GREEN: 161 passed, 2 skipped; ruff check and format clean.
  fec1983 alone (git archive snapshot): 155 passed, 2 skipped.
- L5 (runtime evidence): `printf "10\n" | uv run opengsc connect` marked Claude Desktop,
  Claude Code, Codex and VS Code as found (matches this machine) and printed the
  `uv run --directory <clone> opengsc` settings; that command answered an MCP
  `initialize` + `tools/list` with the 4 tools. A git install yields
  `uvx --from git+<url>@<full sha> opengsc`. Differential vs dcfb333: `auth`, `doctor`,
  `serve` and `setup` help unchanged; top-level help and the invalid-choice error only
  add `connect` (intended).
- L6 (RDD): `review assess --base-ref bbbc2a4 --committed-only` on dcfb333 = high
  (executable change + escalated item 1); review START waits for the user's consent.
  Commits carry no Co-Authored-By (S6 overrides the harness attribution reminder).
