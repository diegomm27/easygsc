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

## Pending follow-ups (out of scope)

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
