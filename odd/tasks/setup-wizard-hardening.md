# opengsc — setup wizard hardening (follow-up of review-9afcdcc8dbf2e58d)

Fixes the non-blocking review findings R1-001, R1-002 and R3-obtain-client-loop-on-eof,
and adds the missing auth-failure test. The burned receipt's candidate stays immutable:
this is a new candidate made of new commits on `feat/setup-wizard`.

## Specs

- S1: "R1-001 y R1-002: manejo seguro del client secret en setup.py (no imprimirlo,
  no dejarlo en logs, permisos restrictivos del fichero donde se guarde)."
- S2: "R3-obtain-client-loop-on-eof: que el bucle de setup.py:129-136 termine limpio
  ante EOF/Ctrl+D en lugar de quedarse colgado."
- S3: "R3-auth-failure-test-missing: añade el test del fallo de autenticación en
  tests/test_setup.py."
- S4: "Deja fuera R2, el resto de R3 y R4-2…R4-6; anótalos como follow-up pendiente."
- S5 (answers to plan doubts): (1) suppress the refresh token in setup with an
  optional parameter in auth (default unchanged, so `opengsc auth` is untouched);
  setup confirms auth worked and says where the token was saved, without its value.
  (2) `q`/`quit` is a clean exit in every wizard prompt, same behavior as EOF:
  `run()` returns a non-zero code and a clear cancellation message. (3) redact the
  client_secret and the refresh token if they appear in any exception text before
  printing it, with a test.
- S6: Test first where applicable; gates: `uv run pytest -q`,
  `uv run ruff check src tests`, `uv run ruff format --check src tests`.
- S7: Do not reopen `review-9afcdcc8dbf2e58d`; the new candidate gets a fresh review.
- S8 (usability follow-up, user request L6): the wizard must say which downloaded
  client file it is using and where it installed it, so a person can see whether it
  picked the file they just downloaded. It must never end in a Python traceback: a
  malformed or edited client file, or a network failure during login, prints one
  actionable line on stderr with the secrets redacted (part of the R4-2…R4-6
  error-branch follow-up). The Downloads search also covers a OneDrive-redirected
  `Downloads` folder, and the path prompt names every folder it searched.
- S9 (review follow-up, L8): fix the findings of the blocked review payload
  `review-resilience-1-eee509194f48.json` that hold against the code: (a)
  `connect._write_atomic` must leave the rewritten app config writable by its
  owner even when the app's file was read-only, keeping its other permission
  bits; (b) cancelling `connect` after some apps were already written must say
  which files changed before it reports the cancellation; (c) the `_ask_replace`
  claim (one question per app, two Claude Desktop copies) and the S8/T9 wording
  about "offers to log in again" are checked against the code and either refuted
  with evidence or corrected in this document.

## Tasks

- T1 [S1] install the client secret atomically with 0600 from creation (no
  world-readable window), tests first — commit e6e53bb — DONE
- T2 [S2,S5] clean cancellation on EOF and on `q`/`quit` at any prompt, exit 2
  with a clear message, tests first — commit a1b05b9 — DONE
- T3 [S1,S3,S5] keep secrets out of setup output: suppress the refresh-token
  print in setup, confirm success + token path, redact client_secret/refresh token
  in error text, tests first — commit fa75ca9 — DONE
- T4 [S4] record pending follow-ups and evidence — this doc commit — DONE
- T5 [S6,S7] full gates, then fresh review for the new target — gates done; the
  review is the next lifecycle step and no code commit — DONE
- T6 [S8] report the discovered client file and the install destination, cover a
  OneDrive `Downloads` folder — commit with T7 — DONE
- T7 [S8] no traceback from the login step: `ValueError`/`OSError` from the OAuth
  flow print `auth failed: …` plus the fix, redacted — commit with T6 — DONE
- T8 [S8,GATES] gates and README wording for the discovery and the new error row —
  same commit — DONE
- T9 [S8] the doctor check inside setup cannot traceback either: `_doctor_ok()`
  reports a crashing check (a revoked token makes google-auth raise
  `RefreshError`) and the wizard reports it instead of crashing — same commit — DONE
- T10 [S9] fix the review findings that hold: `_write_atomic` keeps the owner
  write bit, a cancel after partial writes names the files already changed,
  `_ask_replace` checked with evidence, and the T9 wording corrected — see L8 —
  DONE (S9c refuted, no behaviour change)

## Pending follow-ups (out of scope)

- Release 0.2.0: merge `feat/setup-wizard` to `main`, push, `gh release create
  v0.2.0` so `release.yml` publishes to PyPI, then delete the pre-release
  "Status: 0.2.0 is not on PyPI yet" block from the README Setup section and the
  matching Troubleshooting row. Until that release the README documents a state
  the index does not serve.
- `origin/feat/setup-wizard` is 10+ commits behind this branch: the README's
  "run the current code straight from GitHub" fallback installs a build without
  `connect`, without the Branding step and without this hardening. Pushing the
  branch is the user's call and is the cheapest way to make that fallback true.
- R2-001 readability `setup.py:109-121`
- R2-002 readability `setup.py:118`
- R2-003 readability `tests/test_setup.py:16`
- R3-cli-help-unchanged reliability `src/opengsc/cli.py:96-101`
- R3-install-client-read-bytes-eof reliability `setup.py:141-145`
- R3-no-browser-branch-test-gap reliability `setup.py:52-56`
- R3-setup-downloads-snapshot reliability `setup.py:84-85`
- R3-setup-import-cycle reliability `setup.py:17`
- R4-2, R4-3, R4-4, R4-5, R4-6 resilience (setup.py error branches)

## Log

- L1 (user request): "Sí, sigamos. Abre un candidato nuevo (sin reabrir el receipt
  review-9afcdcc8dbf2e58d) con este alcance: 1. R1-001 y R1-002: manejo seguro del
  client secret en setup.py (no imprimirlo, no dejarlo en logs, permisos restrictivos
  del fichero donde se guarde). 2. R3-obtain-client-loop-on-eof: que el bucle de
  setup.py:129-136 termine limpio ante EOF/Ctrl+D en lugar de quedarse colgado.
  3. R3-auth-failure-test-missing: añade el test del fallo de autenticación en
  tests/test_setup.py. Test primero donde aplique. Deja fuera R2, el resto de R3 y
  R4-2…R4-6; anótalos como follow-up pendiente. Antes de tocar código, dime el plan
  y cualquier duda."
- L2 (approval): "Plan aprobado. Respuestas a las dudas: 1. Refresh token: sí,
  suprímelo en setup con un parámetro opcional en auth (por defecto igual, para no
  cambiar `opengsc auth`). En su lugar, setup debe confirmar que la autenticación
  fue correcta e indicar dónde se ha guardado el token, sin mostrar su valor.
  2. q/quit: sí, añádelo como salida limpia en todos los prompts del wizard, además
  del test de EOF. Mismo comportamiento que EOF: run() devuelve código distinto de
  0 y mensaje claro de cancelación. 3. Redacción: sí, redacta el client_secret y
  también el refresh token si aparecen en el texto de cualquier excepción antes de
  imprimirla, con su test. Adelante con los tests primero."
- L3 (review context): approved receipt `review-9afcdcc8dbf2e58d`, target
  `sha256:46542138c5e0e6ff383ab43416097b34419b5f29b27738cb0c58722d8f8ed409`,
  tree `c80a46b`; R4-1 CRITICAL was refuted; all others informational. HEAD tree
  matched the reviewed tree before this work started.

## Verification evidence

- Test-first per unit, RED observed before each implementation:
  - T1: `test_failed_replace_keeps_the_previous_file` failed with `DID NOT RAISE
    OSError` (copyfile overwrote the dest) before `mkstemp` + `os.replace`.
  - T2: the three cancellation tests failed (EOF returned 1; `q` was treated as
    a path/answer and the loop continued) before `Cancelled`.
  - T3: suppression/redaction tests failed (no `print_refresh_token` kwarg raw
    secret printed) before the auth parameter and `_redact`.
  - T10: `test_a_read_only_config_is_rewritten_and_stays_writable_by_its_owner`
    failed with `ConnectError: Cannot write …: [WinError 5] Acceso denegado`
    (copying the read-only mode to the temporary file makes `os.replace` refuse
    the read-only destination; on POSIX the replace succeeds but the mode stays
    `0o444`) and
    `test_a_cancel_after_a_connected_app_names_what_was_already_written` failed
    with `ValueError: substring not found` (nothing was printed about the first
    app) before `_write_atomic` restored the owner write bit and
    `choose_and_connect` printed the writes before the cancel.
- `uv run pytest -q` after T10 and the parent's review of the fix: 182 passed,
  3 skipped. The parent narrowed `_write_atomic`: the owner write bit is only
  added to the *destination* on Windows, where `os.replace` refuses a read-only
  target; on POSIX the old file keeps its mode until the replace succeeds, so a
  failed write cannot widen an app's permissions. Pinned by the new POSIX-only
  `test_a_failed_replace_leaves_a_protected_config_read_only`.
- S9c is refuted, so no behaviour changed: `_ask_replace`
  (`src/opengsc/connect.py:367-376`) caches the first answer in `answers`, and
  `_connect_json` (`src/opengsc/connect.py:414-418`) builds one callable per app
  and passes that same callable to every config copy, so each app is asked once
  however many copies it has. `tests/test_connect.py:385`
  `test_every_existing_config_copy_is_updated_after_one_question` feeds exactly
  one `y` for two copies in the same call (a second question would exhaust the
  `feed` iterator and raise `StopIteration`), and
  `test_claude_code_replaces_an_existing_entry_only_after_a_yes` feeds one answer
  too. `_authenticate` (`src/opengsc/setup.py:293-306`) prints
  `auth check failed; see the report above.` and returns 1 with no retry, so
  `setup.py` is unchanged.
- S9b output: a cancel now ends with `Already written before the cancel:`, the
  app name, its status line and its `Settings file:`/`Backup of the previous
  file:` notes; `run()` and `setup._connect_apps` keep exit code 2 and their
  existing messages. S9a keeps `stat.S_IREAD | stat.S_IWRITE` for the owner and
  copies the rest of the original mode, and it changes nothing when the config
  was already writable.
- `uv run pytest -q`: 114 passed, 2 skipped (0600 tests are POSIX-only).
- `uv run ruff check src tests`: clean.
- `uv run ruff format --check src tests`: clean.
- `setup.py` is 253 lines after the hardening. `install_client` now uses
  `tempfile.mkstemp(dir=dest.parent, ...)` + `os.replace`, so the destination is
  0600 from creation and a failed replace leaves the previous file intact.
- `run()` returns 0 success, 1 failure, 2 cancelled; Ctrl+C still reaches the CLI
  (130). `q`/`quit` and EOF share the cancellation path.
- `auth.run_oauth_flow` gained keyword-only `print_refresh_token=True`; default
  behavior of `opengsc auth` is unchanged and the existing test still passes.
  Setup calls it with `False` and prints `Authenticated; token saved to <path>.`
- `_known_secrets()` collects `OPENGSC_CLIENT_SECRET`, `OPENGSC_REFRESH_TOKEN`,
  the installed client secret and token.json's client_secret/refresh_token;
  `_redact()` replaces them with `***` in auth failures, `setup failed` messages
  and `_obtain_client` errors.

## Log (continued)

- L4 (slice boundary): the branch is now ~962 authored lines across 10 commits
  since `main` (the hardening adds 3 code commits plus this doc). Still one
  cohesive feature branch; split into review-sized PR slices at PR time if
  desired (wizard / hardening / docs+version). No PR opened.
- L5 (new candidate): commits e6e53bb, a1b05b9 and fa75ca9 are additive on top of
  df4af0b. The reviewed tree `c80a46b` is unchanged in history, so
  `review-9afcdcc8dbf2e58d` remains a valid burned receipt for its own target.
- L6 (user request, usability follow-up): "Adelante. Arregla todo." — after a
  read-only audit that found: PyPI still serves 0.1.0 so `uvx opengsc setup`
  fails; `origin/feat/setup-wizard` is 10 commits behind, so the README fallback
  installs a build without `connect`/Branding/hardening; the wizard installs the
  client silently; a malformed client raises `ValueError` from
  google-auth-oauthlib as a raw traceback; and `~/Downloads` misses a
  OneDrive-redirected folder. Scope taken for code (S8): the three wizard gaps.
  Push, PR and release stay with the user (connect-any-ai S6).
- L7 (RED then GREEN): the 10 new tests failed first (no `_download_dirs`, no
  install/announce message, traceback instead of `auth failed`, and
  `test_a_crashing_doctor_check_does_not_traceback`). GREEN:
  `180 passed, 2 skipped`; `ruff check` and `ruff format --check` clean.
  Runtime check with a temporary HOME: `Using the client file you downloaded:
  …\Downloads\client_secret_123.json`, `Installed the client as
  …\.config\opengsc\client_secret.json.`, then a malformed client produced
  `auth failed: Client secrets is not in the correct format.` plus the fix line
  and no traceback. `_download_dirs()` on this machine returns the real
  `~/Downloads` path. `auth --help`, `setup --help`, the top-level help and
  `doctor` are unchanged; only `setup` output changed.
- L8 (new candidate after the blocked review): the `review-resilience` payload
  that Go refused for missing proof references (preserved at
  `.git/gentle-ai/rejected-results/review-b19c27339f622fdd/`) is unadmitted, so
  its findings are leads, not authority. Checked against the code: the
  `_write_atomic` read-only mode loss (S9a) and the unreported partial writes on
  cancel (S9b) hold; the `_ask_replace` claim does not (the closure already
  caches one answer per app, as its docstring and tests say); and the review was
  right that T9 overstated the doctor failure path, which prints
  `auth check failed` and returns 1. User decision L9.
- L9 (user decision): "Corregir el candidato y review nuevo" — fix those items,
  commit, push, and start a new review lineage for the new candidate.
