# Project rules for Claude Code

## What this is
MOEX spread scanner: finds statistically abnormal price deviations in related
instrument pairs (common/preferred shares), ranked by z-score. Python 3.12,
uv-managed, strict typing, PostgreSQL storage, Docker delivery.

## Non-negotiable workflow
- `make check` must be green before every commit. Red check = no commit.
- All changes reach `main` only via pull request with green CI
  (branch protection enforces this; do not attempt direct pushes).
- Branch names: `feat/...`, `fix/...`, `ci/...`, `docs/...`, `test/...`.
- Commits: English, Conventional Commits (`feat:`, `fix:`, `ci:`, `docs:`,
  `test:`, `build:`, `chore:`). Small and focused.
- After pushing, verify pipeline yourself: `gh pr checks --watch`;
  on failure read `gh run view --log-failed`, fix, push again.

## Code standards
- Pyright strict is the law. Never silence errors with `# type: ignore`
  or config loosening; fix the types instead.
- All external data (ISS API responses, env, files) enters through
  Pydantic models. No raw dicts crossing module boundaries.
- Settings only via `moex_spread_scanner.config.Settings`
  (env prefix `SCANNER_`). Never read `os.environ` elsewhere.
- Tests for every computational function and every parser. Protective
  behaviour (validation failures) is tested too.
- No new runtime dependencies without a short justification in the PR body.

## Secrets
- Never write tokens, passwords or keys into any tracked file.
  Local secrets live in `.env` (gitignored); CI/prod secrets live in
  GitHub Actions secrets.

## Environment facts
- Dev runs inside WSL2 Ubuntu 24.04; CI runs `ubuntu-24.04`; prod will be
  Ubuntu 24.04 VPS. Docker: multi-stage build via uv, final `uv sync`
  uses `--no-editable` (venv must not reference /app/src).
- Local stack: `docker compose up -d db` (PostgreSQL 16), scanner runs
  via `docker compose run --rm scanner` or `uv run moex-spread-scanner`.

## Language
- Code, comments, commits, PRs: English.
- Conversation with the user: Russian.
