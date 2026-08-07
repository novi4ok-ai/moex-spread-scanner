.RECIPEPREFIX := >
.PHONY: check lint type test run

check: lint type test          ## всё сразу — единая точка входа

lint:
> uv run pre-commit run --all-files

type:
> uv run pyright

test:
> uv run pytest

run:
> uv run moex-spread-scanner
