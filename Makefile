# Development checks; none of them needs root, the hardware or a touch bar.
#   make vendor        fetch the client library into vendor/ (the tests need it)
#   make check         everything CI runs: format-check, lint, typecheck, test
#   make format        apply ruff formatting
# The Python tools (ruff, mypy) come from uv (pyproject.toml, uv.lock); the
# client library from the git URL pyproject.toml's dependencies give.

UV = uv run --frozen --only-group dev
LIBRARY = $(shell python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["dependencies"][0])')

.PHONY: check format format-check lint typecheck test

check: format-check lint typecheck test

format:
	$(UV) ruff format .

format-check:
	$(UV) ruff format --check .

lint:
	$(UV) ruff check .
	sh -n install.sh

typecheck: vendor
	$(UV) mypy

test: vendor
	python3 -m unittest discover -s tests

vendor: pyproject.toml
	rm -rf vendor
	python3 -m pip install --quiet --disable-pip-version-check --no-deps --target vendor "$(LIBRARY)"
	@touch vendor
