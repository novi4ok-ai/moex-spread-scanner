# PROGRESS — moex-spread-scanner

Durable state for resuming work after a break, a lost session or a compacted
context. `git log` says what changed; this file says where the project stands,
what is half-finished, and what happens next.

Update rules live in `CLAUDE.md` (`## Progress log`) — they are binding, and
this file is kept in the shape they describe.

## Now

Date: 2026-08-08

The v0.1 specification is accepted and merged. Scaffolding is complete and
green; **no implementation work has started yet** — there is no ISS client, no
database code and no scanner logic. The next work item is the ISS client
(`docs/SPEC.md` §3).

- In flight: nothing. The working tree is clean and `main` is green.
- Blocked on: nothing.
- Last verified green: `main` at pull request #5 — `make check` locally, both
  required CI checks (`checks`, `image`) green. Run `git log -1` for the exact
  commit.

## Next

Ordered work items, all defined by `docs/SPEC.md`. The spec's preamble mentions
roadmap numbering 16–22; that numbering lives outside the repository, so treat
this list as the authoritative one.

1. **ISS client** (§3) — instrument metadata and daily history, cursor-driven
   pagination, Pydantic models at the boundary, columnar rows zipped by column
   name. Adds `httpx` (§12.1).
2. **Schema and migrations** (§4, §12.3) — numbered SQL files applied by a
   re-runnable `migrate` command with a `schema_migrations` table. Adds
   `psycopg[binary]` 3.x. No ORM, no Alembic.
3. **Ingest** (§5) — per-ticker ranges with a 5-day overlap, instruments
   upserted before candles, idempotent candle upsert.
4. **Computation core** (§6) — pure functions: alignment, log ratio, rolling
   statistics over aligned observations, z-score, direction, liquidity filter,
   fixed skip precedence.
5. **Scan** (§7) — one date per run, console table, CSV, `scan_runs` /
   `scan_results` / `signal_events`.
6. **Scheduling** (§9) — systemd timer at 01:00 Europe/Moscow, `Persistent=true`,
   `scan` only if `ingest` exited 0.

Tests are not a separate item: §12.7 lists what each of the above must ship with.

## Known open items

Small pre-existing inconsistencies on `main`. Each is already specified — fix it
when its work item is touched, not as a separate cleanup pass.

- `compose.yaml` passes `SCANNER_DATABASE_URL`, but `Settings` has no
  `database_url` field and `extra="ignore"` swallows it silently. The DSN is
  configured today and read by nothing. Fix with item 2 (§8.1).
- The entrypoint prints every setting via `model_dump()`. The moment
  `database_url` exists, that prints the password into local and CI logs. It
  must redact before the field lands (§8.2).
- `reports/` is not in `.gitignore` (§12.6).
- In the image `/app` is owned by root while the process runs as `appuser`, so
  the report directory has to be a mounted writable volume in `compose.yaml`;
  writing to the image filesystem will fail (§12.6).
- Bare `moex-spread-scanner` must keep printing the settings dump when
  subcommands are added: the required `image` job greps its stdout for
  `iss_base_url` (§12.2).

## Done

- 2026-08-08 — this progress log and its update rules in `CLAUDE.md`, plus
  `CLAUDE.md` pointers to both documents (#5).
- 2026-08-08 — v0.1 specification, `docs/SPEC.md`, with sixteen review
  resolutions in Appendix A (#4).
- 2026-08-07 — project rules for Claude Code, `CLAUDE.md` (#3).
- 2026-08-07 — CI: `checks` and `image` jobs on `ubuntu-24.04`; full clone so
  gitleaks can scan history (#1, #2).
- 2026-08-07 — scaffolding, direct commits on `main` before branch protection
  existed: uv package with src layout on Python 3.12; ruff, pyright strict and
  pre-commit with gitleaks; typed settings via pydantic-settings; pytest plus
  `make check` as the single entrypoint; multi-stage Docker build with
  `--no-editable` and a non-root runtime; `compose.yaml` with PostgreSQL 16.

## Decisions not visible in the code

- The five contradictions that made the accepted spec draft unimplementable, and
  the eleven ambiguities that would have split the implementation, are resolved
  in `docs/SPEC.md` Appendix A with the reason for each. Read that table before
  re-litigating any of those choices.
- `z_window_days` counts **aligned observations**, not days. The name was kept
  from the accepted draft because renaming a settings key is a user-facing
  change; §8.1 states the unit authoritatively. Renaming it to
  `z_window_observations` is an open, user-owned follow-up.
- The universe stays at five pairs even though the 5,000,000 RUB liquidity floor
  is expected to exclude BANE on most dates. The floor must be validated against
  real history during item 3, recording the observed exclusion rate per pair in
  that pull request. Narrowing the universe is the user's call.
- The README statement required by §10 (a human checks corporate events before
  acting on a candidate) is a v0.1.0 release gate, deliberately not written yet:
  there is nothing to disclaim until the scanner runs.

## Infrastructure state

- `main` is protected by the `main-protection` ruleset: pull request required,
  **squash the only allowed merge method**, required status checks `checks` and
  `image`, strict up-to-date policy, no force-push, no deletion.
- Repository auto-merge was enabled on 2026-08-08, so the normal flow is
  `gh pr merge --auto --squash` followed by `gh pr checks --watch`.
- Merged branches are not deleted automatically
  (`delete_branch_on_merge = false`); `docs/spec` is still present locally and
  on the remote.
