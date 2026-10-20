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
  verifier DONE (B1 + A1 fixed in fd170d4, recheck FIXED); native review APPROVED and
  acknowledged (authority burned) for bbbc2a4..d4a351e — DONE

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
- L7 (independent verifier on bbbc2a4..46bccba): S1, S2, S3, S5, S6, S7, S8 and the
  help invariants PASS; S4 PARTIAL. Blocker B1: a config that is not UTF-8 (UTF-16
  from PowerShell 5.1, cp1252 from old Notepad) raised an uncaught UnicodeDecodeError,
  so no manual steps were printed and the following apps never ran. A1 was raised to a
  blocker because it breaks S4: the `config.toml` regex missed inline, dotted and quoted
  TOML spellings, and `codex mcp add` then overwrote the entry, env included, without
  asking. Advisories: A2 symlinked configs, A3 unclear message after Claude Code
  remove + failed add, A4 manual step named the wrong copy, A5 temp file left behind
  for a read-only config on Windows, A6 backup name reused within one second, A7
  re-runs asked again or asked to quit for nothing, A8 out-of-domain inputs.
- L8 (correction batch, fd170d4): one batch fixes B1, A1, A2, A3, A4, A5 and A7.
  `codex mcp get opengsc` was probed against a scratch CODEX_HOME: exit 0 for the
  inline form, 1 when there is no entry. RED: 10 new tests failed; GREEN: 169 passed,
  2 skipped; ruff clean. Deferred as advisories: A6, and A8 (git subdirectory, UNC
  paths, env auth not copied into app entries, README manual block showing
  `uvx opengsc@0.2.0` until the release). The consent prompt shown for target
  sha256:3004e20e… is superseded, because the candidate changed.
- L9 (recheck limited to B1 and A1, fd170d4): both FIXED. B1: UTF-16 and cp1252
  `~/.cursor/mcp.json` print "is not UTF-8 text, so opengsc left it untouched." plus
  manual steps, hash unchanged, VS Code still connected, exit 1, no traceback. A1: a
  fake codex answering `mcp get` from tomllib asked before overwrite for the table,
  double-quoted, single-quoted, inline, dotted and `.env` sub-table spellings, with no
  `mcp add` after "n"; the real codex-cli 0.163.0 (scratch CODEX_HOME) exits 0 for
  those forms and 1 when there is no entry. Verifier scratch removed by the parent.
- L10 (native review, lineage review-9a20d0aae32ff417, target sha256:20cb4748…, whole
  branch vs main, 19 files / 2525 lines, user answered "1" = granted): 4 lenses, budget
  200. Three captures first failed in the reviewer transport ("Claude's response
  exceeded the 32000 output token maximum"); bound STATUS re-offered the same slots and
  they were relaunched with CLAUDE_CODE_MAX_OUTPUT_TOKENS=64000 in the child env only.
  Result: APPROVED, `review.acknowledge-approved` -> `authority: burned`. 14 non-blocking
  findings, left as later work: R1-001/R4-002 backup name has 1-second precision (each
  config copy lives in its own folder, so only same-file re-runs collide), R1-002 CLI
  error lines not passed through `_redact`, R4-001 no feedback while an app CLI runs (up
  to 120 s), R4-003 Devin path on macOS unverified, R4-004 `_known_secrets` and a
  non-dict client value, R2-001/R3-004 setup imports `cli._doctor`, R2-002 a backup
  failure reads as "Cannot write", R2-003 `_connect_cli` branching, R2-004 conftest
  `raising=False` can hide a rename, R3-001 `load_client` and non-UTF-8 client files,
  R3-002 untested doctor-failure branch in `_authenticate`, R3-003 the help assertion
  depends on subcommand order.
- L11 (outside this feature): commits 66ee2e3 and 0a5a740 appeared on the branch
  while this session was paused (author diegomm27; not made by this session). They come
  after the reviewed candidate, so they are not covered by review-9a20d0aae32ff417.
  Gates at 0a5a740: 182 passed, 3 skipped; ruff clean.
