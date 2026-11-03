---
name: contributing
description: Load before any change - the checks (make check, format, lint, typecheck, tests) and CI, the client library in vendor/, the file size limit, documenting what you write, working in steps, no-mistakes review, and keeping skills current. Then load the skill of each area the change touches.
---

# Contributing

The general rules for any change. Each area's own rules are in its skill: after this one, load the skill of every area the change touches, from the index in [AGENTS.md](../../../AGENTS.md).

Read first, as needed:

- [README.md](../../../README.md): what the app does, what it needs, what was tested, installing and removing it.
- [docs/development.md](../../../docs/development.md): the code layout, the checks, and what the tests cover.

## Commands

One command each; none needs root, a touch bar, Herdr or firstmate. The Python tools run through [uv](https://docs.astral.sh/uv/).

- `make check`: everything CI runs, in order: format check, lint, typecheck, tests. **Run it before finishing every change.**
- `make vendor`: fetches the touch bar's client library `screenpad_app` into `vendor/` (not committed) with pip, from the git URL pinned in `pyproject.toml`'s `dependencies`. `make typecheck` and `make test` run it first; it fetches again only when `pyproject.toml` is newer than `vendor/`.
- `make format-check`: `ruff format --check`; `make format` applies it.
- `make lint`: `ruff check`, and `sh -n install.sh`.
- `make typecheck`: mypy with `check_untyped_defs` on the launcher `agents.py`, its package `screenpad_agents/` and `tests/` (the library from `vendor/`).
- `make test`: `python3 -m unittest discover -s tests`, stdlib only once `vendor/` is there.
- The tool versions are pinned: ruff and mypy in `pyproject.toml` (`[dependency-groups] dev`) and `uv.lock`. Their settings live in `pyproject.toml`. ruff formats only `*.py`; never run it on `docs/` or `README.md`, where it would rewrite hand-kept tables and snippets.
- CI (`.github/workflows/ci.yml`) runs the format check, lint and typecheck in one job and the tests on Python 3.11 and 3.14 in another, on every push and pull request. `.no-mistakes.yaml` gives the no-mistakes pipeline the same commands.

## Rules

- **The checks pass before a change is done.** Formatting, lint, typecheck and tests are all green under `make check`. Fix the code rather than silencing a check; a `# type: ignore[code]` or `# noqa: CODE` names its code and says why on the same line.
- **The program stays standard-library Python 3.11+**, plus the client library `screenpad_app`, the only dependency: `agents.py` and `screenpad_agents/` run from the checkout and as the installed copy with no other third-party import. Tooling goes in the dev dependency group, never in what `install.sh` installs.
- **The client library is pinned to a screenpad-linux commit, in one place**: `pyproject.toml`'s `dependencies`, which `make vendor` and `install.sh` read. No version ranges or tags; moving to a newer library is changing that commit (`test_the_library_is_pinned_to_a_commit_and_vendored_from_it`).
- **Keep files small: about 500 lines per module is the soft limit.** Split a module along its responsibilities instead of growing it past that, and put new code in the module of its area. Every file is under it today, the tests included (tests go one file per area); keep it so.
- **Document what you write, in the same change.** A behavior, command, setting, file or installed path that changes updates the page that describes it (README and `docs/`, see below), the test list in [docs/development.md](../../../docs/development.md#tests) when tests change, and the matching skill.
- **Work in steps.** A step is one coherent change with its tests, docs and skill update, `make check` green, and committed. A large change goes in as several such steps (and pull requests), each complete on its own.
- **Every change goes through no-mistakes review.** Commit on a branch and run it through the no-mistakes gate (the `/no-mistakes` skill, or `git push no-mistakes <branch>`): it reviews, tests, lints, pushes, opens the pull request and watches CI. Never push to `main` directly.
- **Never touch the machine you work on.** Tests and manual checks use temporary directories, a temporary `HOME` and XDG directories, stub commands, the stand-in touch bar, an isolated Herdr session and a throwaway firstmate home; never run `install.sh`, the app or `systemctl --user` against your own session, its config or its running agents as part of a change.

## Where docs go

| Page | Owns |
|---|---|
| [README.md](../../../README.md) | overview, what it needs, what was tested, installing, updating and uninstalling, troubleshooting the install |
| [docs/agents.md](../../../docs/agents.md) | the agent app: what it shows, its config, turning it on, how it reads and acts, troubleshooting |
| [docs/development.md](../../../docs/development.md) | code layout, the client library's pin, the checks, what the tests cover, the screenshots |

The touch bar, its config and the app protocol are documented in [screenpad-linux](https://github.com/mmarsot/screenpad-linux); link its pages by URL rather than copying them.

## Tests

- `tests/` holds stdlib `unittest` tests, one file per area: `test_agents_*.py` (the agent app; the [agents](../agents/SKILL.md) skill lists them), `test_install.py` (`install.sh` and the library's pin), `test_skills.py` (the skills and this index). `agents_support.py` holds what the app's tests share and puts the checkout and `vendor/` on `sys.path`; `bar_support.py` is the stand-in touch bar. isort keeps the support modules imported before the package (`[tool.ruff.lint.isort]` in `pyproject.toml`).
- A new test goes in the file of its area; a new area gets its own file, added to the test modules listed under `[[tool.mypy.overrides]]` in `pyproject.toml`.

## Skills are part of the code

- The skills live in `.agents/skills/<name>/SKILL.md`; `.claude/skills` is a committed symlink to `.agents/skills`. Edit only the `.agents/skills/` copy.
- **Update the matching skill in the same change** whenever you change an area's rules, invariants, owning files or tests. No approval is needed to add, edit, split or prune a skill.
- Skills point and the docs explain: behavior and rationale go in `docs/`; a skill keeps only what an implementer must check, and links the doc page instead of copying it.
- A new skill is a folder named like its `name`, a `SKILL.md` with `name` and a `description` saying which files and changes it covers, and a row in the AGENTS.md index. `tests/test_skills.py` checks all of that and that every relative link in a skill resolves.
- Keep a skill to what nearly every change in its area needs, and keep entries concise. Prefer rewriting or pruning an entry over appending one.
