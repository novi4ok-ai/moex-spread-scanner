# SPEC — moex-spread-scanner v0.1

Status: accepted. Scope: ISS client, DB schema, ingest, computation core, scan,
tests, scheduling (roadmap items 16–22; the numbering is informational, the work
items are enumerated here so this document stays self-contained).

Every implementation decision must trace back to a section here. If something is
ambiguous — ask the user before coding. Ambiguities found during review of the
accepted draft are resolved in place; Appendix A records what changed and why.

## 1. Purpose

Daily end-of-day scanner that finds statistically abnormal price divergence
inside common/preferred share pairs of the same issuer on MOEX, and ranks
candidates by z-score. It narrows attention; it does not trade and does not
promise convergence. A flagged pair is a reason for a human to look, nothing
more.

## 2. Universe (v0.1)

Fixed list of pairs, defined as a module-level constant (not settings):

| common | preferred |
|--------|-----------|
| SBER   | SBERP     |
| TATN   | TATNP     |
| RTKM   | RTKMP     |
| BANE   | BANEP     |
| MTLR   | MTLRP     |

Board: TQBR only. Currency: RUB. No futures, no other boards.

Pair identifier used in storage and reports is `"{common}/{preferred}"`, e.g.
`SBER/SBERP`.

Note on the interaction with §6.6: the liquidity floor is expected to exclude
low-turnover legs, and BANE is the likely candidate to be excluded on most
dates. This is accepted behaviour of the filter, not a bug: the universe stays
as listed above. The default floor must be validated against real history during
the ingest work item, and the observed exclusion rate per pair recorded in the
pull request that introduces the scan. Changing the universe or the default is a
separate decision for the user, not an implementation choice.

## 3. Data source — MOEX ISS API

Base URL from settings (`iss_base_url`). No authentication, JSON, public.
Politeness: pause `request_pause_seconds` between HTTP requests.

### 3.1. Instrument metadata (per ticker)

```
GET /engines/stock/markets/shares/boards/TQBR/securities/{SECID}.json?iss.meta=off
```

→ block `securities`, columns: `SECID`, `SHORTNAME`, `LOTSIZE`.

### 3.2. Daily history (per ticker, date range)

```
GET /history/engines/stock/markets/shares/boards/TQBR/securities/{SECID}.json
    ?from={YYYY-MM-DD}&till={YYYY-MM-DD}&iss.meta=off&start={N}
```

→ block `history`, columns used: `TRADEDATE`, `CLOSE`, `VOLUME`, `VALUE`.

Pagination is cursor-driven: read the `history.cursor` block (`INDEX`, `TOTAL`,
`PAGESIZE`) and advance `start` by `PAGESIZE` until `INDEX + PAGESIZE >= TOTAL`.
If the cursor block is absent, fall back to advancing `start` by the number of
rows returned and stop on a short page. A hardcoded page size of 100 is not
acceptable: it silently skips rows if ISS ever changes the default.

### 3.3. Boundary parsing

Every ISS response is parsed into Pydantic models at the boundary (CLAUDE.md
rule). ISS returns a columnar shape (`{"columns": [...], "data": [[...]]}`), so
the client zips columns to rows by name — never by positional index — and
validates each row. Raw dicts must not leave the client module.

## 4. Storage (PostgreSQL 16)

Connection from `SCANNER_DATABASE_URL` (see §8). Schema:

```sql
instruments (
  secid       text PRIMARY KEY,
  shortname   text NOT NULL,
  lot_size    integer NOT NULL CHECK (lot_size > 0),
  updated_at  timestamptz NOT NULL DEFAULT now()
)

daily_candles (
  secid       text NOT NULL REFERENCES instruments(secid),
  trade_date  date NOT NULL,
  close       numeric(18,6) NOT NULL CHECK (close > 0),
  volume      bigint NOT NULL CHECK (volume >= 0),
  value       numeric(18,2) NOT NULL CHECK (value >= 0),
  PRIMARY KEY (secid, trade_date)
)

scan_runs (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  started_at  timestamptz NOT NULL,
  finished_at timestamptz,
  params      jsonb NOT NULL                    -- non-secret settings, see §8.2
)

scan_results (
  run_id      bigint NOT NULL REFERENCES scan_runs(id),
  pair        text NOT NULL,                    -- e.g. 'SBER/SBERP'
  trade_date  date NOT NULL,                    -- the scanned date
  skip_reason text,                             -- NULL for a computed result
  z           numeric(10,4),
  ratio       numeric(12,6),
  mean        numeric(12,6),
  std         numeric(12,6),
  direction   text,
  median_value_common numeric(18,2),
  median_value_pref   numeric(18,2),
  PRIMARY KEY (run_id, pair),
  CHECK (skip_reason IS NULL OR skip_reason IN
         ('insufficient_data', 'degenerate_std', 'illiquid', 'no_data_for_date')),
  CHECK (direction IS NULL OR direction IN ('common_rich', 'pref_rich')),
  -- a row is either a computed result or a skip, never both and never neither
  CHECK ((skip_reason IS NULL) <> (z IS NULL)),
  CHECK ((z IS NULL) = (mean IS NULL)),
  CHECK ((z IS NULL) = (std IS NULL)),
  CHECK ((z IS NULL) = (direction IS NULL))
)

signal_events (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  pair        text NOT NULL,
  trade_date  date NOT NULL,
  z           numeric(10,4) NOT NULL,
  direction   text NOT NULL CHECK (direction IN ('common_rich', 'pref_rich')),
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (pair, trade_date)
)
```

`scan_results` holds one row per pair per run, including skipped pairs, so that
the console table, the CSV and the database always agree. Two columns are
deliberately outside the result/skip grouping above:

- `ratio` is populated whenever the scanned date is aligned for the pair (§6.1),
  even if statistics could not be computed;
- `median_value_common` / `median_value_pref` are populated whenever the window
  medians could be computed — in particular they are always present for
  `skip_reason = 'illiquid'`, which is what makes such a skip auditable.

Ingest is idempotent: candles are written with
`INSERT ... ON CONFLICT (secid, trade_date) DO UPDATE`. Re-running any period
must never create duplicates or diverging rows.

Schema is created and evolved by numbered SQL migration files applied by the
`migrate` command (§12.3), not by an ORM and not automatically on startup.

## 5. Ingest semantics

- `ingest` loads instrument metadata and candles for all tickers of the
  universe. Metadata is upserted into `instruments` **before** candles, because
  `daily_candles.secid` carries a foreign key to it; a ticker whose metadata
  cannot be fetched is skipped entirely, with its candles left untouched.
- Default range is computed **per ticker**: from that ticker's last stored
  `trade_date` minus 5 calendar days (overlap, to pick up late corrections) to
  today. If that ticker has no stored candles — regardless of whether other
  tickers do — the range starts at `today - history_days`. Adding a new pair to
  the universe therefore backfills it without touching the others.
- `--since YYYY-MM-DD` overrides the start for all tickers.
- Rows with NULL or non-positive `CLOSE` are skipped and counted; the count is
  reported at the end.
- Rows that pass the `CLOSE` check but carry NULL `VOLUME` or NULL `VALUE` are
  stored with that field set to 0 and counted separately; the count is reported
  alongside the skipped rows. Such rows are legitimate (auction-only or
  otherwise thin days) and must not abort the run, but they do affect the
  liquidity filter, so they are never silently normalised.
- `today` and every other business date are resolved in `Europe/Moscow` (§12.5).

## 6. Computation core

All computations are pure functions on in-memory sequences (no DB access inside
the math), unit-tested on fixed fixtures.

### 6.1. Pair alignment

Inner join of the two legs on `trade_date`. A date missing in either leg is
dropped. No forward-fill, no interpolation.

### 6.2. Log ratio

`ratio_t = ln(close_common_t / close_pref_t)`

### 6.3. Rolling statistics

The window is the last `z_window_days` **aligned observations** up to and
including date `t` — a count of observations, not a span of calendar or trading
days. `mean` and `std` (sample, ddof=1) are computed over that window,
`ratio_t` included.

Two consequences are intended and must be reflected in tests:

- because `ratio_t` is part of its own window, `|z|` is bounded above by
  `(N-1)/sqrt(N)` (≈ 7.62 for N = 60); a value near that bound means "as extreme
  as this window can express", not "infinitely extreme";
- because the window is a count, it is either full (`z_window_days` points) or
  short only when the pair's whole aligned history is shorter.

Minimum data: at least `min_observations` aligned points must be available in
the window, otherwise the pair is skipped for that date with reason
`insufficient_data`.

### 6.4. Z-score

`z_t = (ratio_t - mean) / std`

Guard: if `std < 1e-9`, skip the pair with reason `degenerate_std`.

### 6.5. Direction

`z >= 0` → `common_rich` (common expensive vs preferred), `z < 0` →
`pref_rich`. Exact zero is grouped with the positive side; it can never produce
a signal anyway, because §7 requires `|z| >= z_entry_threshold` and the
threshold is positive.

### 6.6. Liquidity filter

Median of `value` per leg over the same window as §6.3 (the aligned dates, so
both legs are measured over an identical set of dates). Both legs must have
median ≥ `min_median_value_rub`, otherwise skip with reason `illiquid`.

### 6.7. Skip precedence

More than one condition can hold at once. Exactly one reason is reported, chosen
in this fixed order, so that results are reproducible and testable:

1. `no_data_for_date` — the scanned date is not aligned for this pair (§7)
2. `insufficient_data` — fewer than `min_observations` aligned points (§6.3)
3. `degenerate_std` — `std < 1e-9` (§6.4)
4. `illiquid` — either leg below the liquidity floor (§6.6)

## 7. Scan semantics

- `scan` computes §6 for every pair as of a single date: the latest
  `trade_date` present in `daily_candles` across the whole universe, or
  `--date YYYY-MM-DD` when given. One date per run, so every row of a run is
  comparable.
- A pair that has no aligned observation on that date is reported with
  `skip_reason = 'no_data_for_date'` rather than being computed at its own,
  earlier date. Silently scanning different pairs at different dates would make
  the ranking meaningless.
- Output 1: console table sorted by `|z|` descending: pair, date, z, ratio,
  direction, median values. Skipped pairs are listed after the computed ones,
  with their reason.
- Output 2: CSV at `{report_dir}/scan_{date}.csv` with the same rows and the
  same order. The directory is created if missing; an existing file for the same
  date is overwritten, which keeps re-runs idempotent.
- Output 3: one row in `scan_runs` (written at start, `finished_at` filled at
  the end) and one row per pair in `scan_results`.
- If `|z| >= z_entry_threshold` **and** the pair was not skipped: upsert into
  `signal_events` with `ON CONFLICT (pair, trade_date) DO NOTHING`. A skipped
  pair never produces a signal. `DO NOTHING` is deliberate: the event records
  that a signal was raised at the time, so a later data correction does not
  rewrite history.

## 8. Settings

### 8.1. Keys

Existing keys stay: `iss_base_url`, `history_days`, `z_entry_threshold`,
`request_pause_seconds`. Additions:

| key | type | default | meaning |
|-----|------|---------|---------|
| `database_url` | `SecretStr \| None` | `None` | PostgreSQL DSN, shape `postgresql://<user>:<password>@<host>:5432/<database>` |
| `z_window_days` | `int` | 60 | rolling window length, **in aligned observations** (§6.3) |
| `min_observations` | `int` | 40 | min aligned points required in the window |
| `min_median_value_rub` | `Decimal` | 5000000 | liquidity floor per leg, RUB |
| `report_dir` | `str` | `reports` | directory for scan CSVs (§7) |

`database_url` is **optional in `Settings` and required at runtime** by the
commands that touch the database (`migrate`, `ingest`, `scan`), which fail with
an explicit message when it is unset. It must not be a required Pydantic field:
`Settings()` is constructed unconditionally by the console entrypoint, and the
CI job `image` runs the container with no environment at all, so a required
field would turn every environment without a database into a hard failure and
break a mandatory status check.

`z_window_days` keeps the name from the accepted draft even though it counts
observations rather than days; the unit above is authoritative. Renaming it to
`z_window_observations` is a reasonable follow-up but is a user-facing config
change, not an implementation decision.

### 8.2. Secret handling

The DSN carries a password, so:

- `database_url` is typed `SecretStr` and must never be printed. The existing
  entrypoint dumps every setting to stdout; it must redact this one, otherwise
  `make run` and the CI image smoke test print the password into logs.
- `scan_runs.params` stores an **explicit allowlist** of non-secret keys —
  `iss_base_url`, `history_days`, `z_entry_threshold`, `request_pause_seconds`,
  `z_window_days`, `min_observations`, `min_median_value_rub` — not a full
  `model_dump()`. Snapshotting all settings would persist the password into
  every run row.
- Tests must cover both: that the dump redacts the DSN, and that `params`
  contains no key outside the allowlist.

## 9. Scheduling

The daily run is driven by a systemd timer on the production VPS
(Ubuntu 24.04), not by GitHub Actions: a CI-driven schedule would require
production database credentials in CI and network access from CI to the
production database.

- `OnCalendar=01:00 Europe/Moscow`, `Persistent=true`.
- One unit runs `ingest`, then `scan` only if `ingest` exited 0.
- Rationale for the hour: the MOEX evening session closes at 23:50 MSK, and
  closing prices and turnover are final in ISS only after it. Running after
  midnight Moscow time means the scanner always processes a fully closed
  previous trading day instead of racing publication.
- Recovery: no retry loop in v0.1. The 5-day ingest overlap (§5) makes the next
  run repair whatever the failed one missed, and `Persistent=true` catches runs
  missed while the host was down. Failures are diagnosed via `journalctl`.
- Exit codes are part of the contract: 0 on success, non-zero on any failure, so
  the timer's status reflects reality.

## 10. Known data caveats (v0.1 accepts them)

- Dividend cut-offs make common/preferred diverge legitimately; v0.1 does not
  adjust for dividends. The README must state that a candidate is checked by a
  human for corporate events before any action. This is a release gate for
  v0.1.0, not part of the specification pull request.
- Splits produce ratio jumps; not adjusted in v0.1.
- ISS free feed is delayed ~15 minutes intraday — irrelevant for EOD data.
- `daily_candles` has no `updated_at`, so a correction picked up by the overlap
  window overwrites the old value without leaving a trace. Accepted for v0.1.

## 11. Non-goals for v0.1 (do not implement, do not scaffold)

Cointegration tests, futures/basis/calendar modules, intraday data, dividend
adjustment, backtesting engine, ML scoring, Telegram delivery, web API,
auto-trading of any kind.

## 12. Implementation constraints

### 12.1. Runtime dependencies

Two new runtime dependencies, each justified in the pull request that adds it
(CLAUDE.md rule): `httpx` for the ISS client, `psycopg[binary]` 3.x for
PostgreSQL. Nothing else. Synchronous I/O throughout: ten tickers at a polite
request pause gain nothing from concurrency and would pay for it in complexity.

### 12.2. Command-line surface

`argparse` from the standard library — no CLI framework dependency. Subcommands:
`migrate`, `ingest`, `scan`.

Invocation with no subcommand keeps its current behaviour, printing the settings
dump (redacted per §8.2). This is a CI contract, not a nicety: the mandatory
`image` job runs the image with no arguments and greps stdout for
`iss_base_url`. Turning the bare invocation into a usage error would fail that
check and block every merge.

### 12.3. Migrations

Numbered SQL files (`migrations/0001_*.sql`, …) applied in order by `migrate`,
which records applied versions in a `schema_migrations` table and is safe to
re-run. No Alembic: it would be a third runtime dependency for a schema of five
tables.

### 12.4. Numeric handling

`numeric` columns arrive as `Decimal` at the DB boundary; the math of §6 runs in
`float`; values are quantised on write to the column scale (z → 4 dp,
ratio/mean/std → 6 dp, monetary values → 2 dp). Unit tests compare floats with
an explicit tolerance rather than exact equality.

### 12.5. Time

All business dates (`trade_date`, `today`, `--since`, `--date`) are resolved in
`Europe/Moscow`. All `timestamptz` values are stored in UTC. The development
host, CI and the production VPS all run UTC system clocks, so deriving "today"
from the system date without an explicit timezone would shift the scanned date
near midnight.

### 12.6. Report directory

`report_dir` defaults to `reports`, which must be added to `.gitignore` —
generated CSVs are not tracked, and an untracked report directory would
otherwise be scanned by gitleaks and offered for commit. In the container the
process runs as non-root (`appuser`) while `/app` is owned by root, so the
report directory has to be a mounted, writable volume declared in
`compose.yaml`; writing to the image filesystem will fail.

### 12.7. Tests

Per CLAUDE.md: every computational function and every parser is tested,
including protective behaviour. Specifically required by this spec:

- §6.1–§6.6 on fixed fixtures, including the `|z|` bound of §6.3 and each skip
  reason;
- §6.7 precedence, with a fixture where several conditions hold at once;
- ISS parsing from recorded columnar payloads, including a NULL `CLOSE` row and
  a NULL `VOLUME` row, and cursor pagination across more than one page;
- ingest idempotency: the same period ingested twice yields identical rows;
- §8.2 redaction and the `params` allowlist.

## Appendix A. Review decisions

Resolutions applied to the accepted draft, with the reason each was needed.

| # | Draft said | Resolved as | Why |
|---|-----------|-------------|-----|
| 1 | `database_url` "required for DB commands" | optional field, checked at use (§8.1) | a required Pydantic field breaks the mandatory `image` CI job, which runs the container with no environment |
| 2 | `params` = "snapshot of Settings used" | non-secret allowlist; DSN as `SecretStr`, redacted in output (§8.2) | the entrypoint prints all settings and `params` persists them, so the DB password would reach both CI logs and every run row |
| 3 | skipped pairs reported, but `scan_results` metrics all `NOT NULL` and no reason column | `skip_reason` plus nullable metrics and paired `CHECK`s (§4) | as drafted, a skipped pair was impossible to insert, so DB and CSV could not agree |
| 4 | window "aligned observations" (§6.3) vs "trading days" (§8) | count of aligned observations; unit stated in §8.1 | the two definitions differ whenever a date is missing in one leg, and they change whether `min_observations` ever applies |
| 5 | scheduling in scope, specified nowhere | §9 | in-scope work item with no requirements attached |
| 6 | window membership of `ratio_t` unstated | inclusive, with the `|z|` bound made explicit (§6.3) | changes every z value and caps the achievable maximum |
| 7 | "latest date with data" | global maximum, non-aligned pairs skipped as `no_data_for_date` (§7) | a per-pair date would rank pairs measured at different dates |
| 8 | several skip reasons could apply | fixed precedence (§6.7) | otherwise the reported reason depends on evaluation order and tests cannot pin it |
| 9 | only NULL `CLOSE` handled; `volume`/`value` `NOT NULL` | NULL `VOLUME`/`VALUE` stored as 0 and counted (§5) | a NULL in either column would violate the schema and abort ingest |
| 10 | `instruments` referenced by FK, never written | ingest upserts metadata first (§5) | candles cannot be inserted before their instrument row exists |
| 11 | "if the table is empty" | per ticker (§5) | a new pair added to a populated database would otherwise get no backfill |
| 12 | dates without a timezone | `Europe/Moscow` for business dates, UTC for timestamps (§12.5) | hosts run UTC, so the scanned date would shift near midnight |
| 13 | pagination "+100 or cursor" | cursor, with a short-page fallback (§3.2) | a hardcoded page size silently drops rows if ISS changes its default |
| 14 | CSV path `reports/`, not in settings | `report_dir` setting, `.gitignore` entry, mounted volume (§12.6) | CLAUDE.md requires config through `Settings`; the image runs as non-root against a root-owned `/app`, so the write would fail |
| 15 | storage/HTTP/CLI stack unspecified | `psycopg[binary]`, `httpx`, `argparse`, SQL migrations (§12.1–§12.3) | each is a new runtime dependency needing justification, and the bare CLI invocation is constrained by CI |
| 16 | `direction` without a constraint | `CHECK` on both tables (§4) | the draft constrains `lot_size` and `close` but left an enum-like column open |
