---
name: install
description: Load before changing install.sh (install, uninstall), the user unit in systemd/, or any installed path - and whenever a program file, package or the client library's place is added, renamed or moved.
---

# Install and the user unit

Owning files: `install.sh`, `systemd/screenpad-agents.service`.

Read first:

- [README.md](../../../README.md#install): installing, updating and uninstalling, and what `install.sh` installs where. It is the user-facing contract; keep it in step.
- [docs/agents.md](../../../docs/agents.md#turning-it-on): configuring and turning the app on, which install never does.

## Rules

- **The installed paths are a contract**: the variables at the top of `install.sh` (`LIB`, `BIN`, `UNIT`, `CONFIG`) must match the unit's `ExecStart` (`%h/.local/bin/screenpad-agents`) and `ConditionPathExists` (`%E/screenpad/agents.toml`), `DOCS` and `CONFIG` in `screenpad_agents/common.py`, the launcher's docstring, the README and the tests. Moving one updates all of them in the same change, and `uninstall` must remove the new and the old location so an update leaves nothing behind.
- **`install.sh` is POSIX `sh`, run as your user, never as root, and needs no `sudo`**: everything goes under `$HOME/.local` and `$XDG_DATA_HOME` (`~/.local/share`). It refuses root (`id -u`).
- **It never enables or starts the unit**: it runs `systemctl --user daemon-reload` only. The unit starts only once its config exists (`ConditionPathExists`); the app itself refuses to run without it, and a config error (exit 2) is not restarted (`RestartPreventExitStatus=2`). It belongs to the graphical session (`PartOf=graphical-session.target`) and orders after the touch bar's unit. `uninstall` disables and stops it, and keeps the user's `agents.toml`.
- **The program lives in `LIB`** (`~/.local/lib/screenpad-agents/`): `agents.py`, every module of `screenpad_agents/`, and the client library in `vendor/`, installed with `/usr/bin/python3 -m pip install --no-deps --target` from `pyproject.toml`'s pinned URL (or `SCREENPAD_APP`, which the tests set to a local wheel). The copy is built in `LIB.new` and then replaces `LIB` whole, so a failed step keeps the previous install and no old module lingers. `BIN` is a relative link to `agents.py`; `uninstall` removes it only when it is a link.
- New files to install get a line in `install_all`, their removal in `uninstall_all`, and a check in `tests/test_install.py`. A new module in the package needs none of that.

## Tests

- `tests/test_install.py` runs `install.sh` against a temporary `HOME`, `XDG_DATA_HOME` and `XDG_CONFIG_HOME`, with stub `id` and `systemctl` first on `PATH` (checked to shadow the real ones) and `SCREENPAD_APP` a wheel built from `vendor/`, so nothing is fetched and your user manager is never asked anything. They are skipped when run as root.
- Never run `install.sh` in your own session to test a change; for a manual check, run it with a throwaway `HOME` and XDG directories and a stub `systemctl` first on `PATH`.
