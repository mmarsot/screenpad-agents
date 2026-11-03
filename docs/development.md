# Development

## Layout

| Path | What it is |
|---|---|
| `agents.py`, `screenpad_agents/` | the [agent app](agents.md), a client of the touch bar's socket through the client library `screenpad_app`, installed as `~/.local/bin/screenpad-agents` |
| `vendor/` | not committed: the client library `screenpad_app`, fetched by `make vendor` (and by `install.sh` next to the installed copy) from the git URL in `pyproject.toml` |
| `systemd/screenpad-agents.service` | the app's user unit |
| `install.sh` | installs and uninstalls, as your user |
| `tests/` | unit tests |
| `docs/` | this documentation; `docs/images/` holds the screenshots |
| `AGENTS.md`, `.agents/skills/` | the guide for contributors and coding agents: an index and one skill per area (`.claude/skills` links to it; `CLAUDE.md` imports `AGENTS.md`) |
| `Makefile`, `pyproject.toml`, `uv.lock` | the development checks and their pinned tools, and the client library's pinned URL; nothing here is installed |
| `.github/workflows/ci.yml` | CI: the same checks on every push and pull request |
| `.no-mistakes.yaml` | the commands the no-mistakes review pipeline runs |

The program is Python 3 (3.11 or newer, standard library only, plus the touch bar's client library) and runs from the checkout once `make vendor` has fetched the library: `./agents.py show`. `agents.py` is a small launcher: run in isolated mode (`python3 -I`), it puts the directory it really lives in and its `vendor/` on `sys.path`, says what to run when the library is missing, and calls `main()` in `screenpad_agents`. `install.sh` copies it with its package to `~/.local/lib/screenpad-agents/`, installs the library into `vendor/` there, and links `~/.local/bin/screenpad-agents` to it, so the checkout and the installed copy have the same layout. The touch bar daemon lives in [screenpad-linux](https://github.com/mmarsot/screenpad-linux): `screenpad_agents` is an app like any other, on the socket, through `screenpad_app`, and imports nothing of the daemon.

The client library is pinned to a screenpad-linux commit in `pyproject.toml`'s `dependencies`, the one place that names it: `make vendor` and `install.sh` read it from there. To move to a newer library, change the commit there, run `make check` (which fetches it again), and update the app if the [protocol](https://github.com/mmarsot/screenpad-linux/blob/main/docs/app-api.md) changed.

The package has one module per concern, each under about 500 lines:

| Module | What it holds |
|---|---|
| `screenpad_agents/common.py` | the agent app's names, paths, timings and layout, the errors |
| `screenpad_agents/config.py` | `agents.toml`: parsing and loading, the opt-in |
| `screenpad_agents/herdr.py` | Herdr's CLI for one session: the agents, one agent, focusing a pane, reading its screen, sending keys |
| `screenpad_agents/keymap.py` | the per-harness keymap of the blocked card: which dialogs it answers, with which keys, and the interrupt keys |
| `screenpad_agents/screen.py` | a pane's screen as the card draws it, and the guard every answer goes through |
| `screenpad_agents/firstmate.py` | firstmate's reader (the Captain's Call count and the tasks by endpoint), its interrupt (`fm-control.sh`), finding and opening its decisions board (`fm-bearings-board.sh path`, Lavish's session listing, the URL handler), and asking firstmate for one (`fm-inbox.sh note`) |
| `screenpad_agents/card.py` | an agent's card: its screen, Back, Focus, Interrupt and the answers, and what a touch on them means |
| `screenpad_agents/fleet.py` | the Agents page (the grid or an open card) and the two tiles as socket messages, what a touch on them means |
| `screenpad_agents/app.py` | the loop, and the threads that call Herdr and firstmate |
| `screenpad_agents/cli.py` | `run` and `show` |

The imports between them go one way (no cycles): `common`, `config`, `herdr`, `keymap`, `screen`, `firstmate`, `card`, `fleet`, `app`, `cli`.

## Checks

```sh
make check
```

runs, in order, everything CI runs; each step is also a target of its own:

| Command | What it checks | Tools |
|---|---|---|
| `make format-check` | formatting; `make format` applies it | ruff format |
| `make lint` | likely mistakes, and `install.sh`'s syntax | ruff check, `sh -n` |
| `make typecheck` | types | mypy, with `check_untyped_defs`, on the program and the tests |
| `make test` | the unit tests below | `python3 -m unittest`, standard library only |

The Python tools run through [uv](https://docs.astral.sh/uv/) (versions pinned in `pyproject.toml` and `uv.lock`). `make typecheck` and `make test` first run `make vendor`, which fetches the client library with pip when `vendor/` is missing or older than `pyproject.toml`; that is the only step that needs the network. CI (`.github/workflows/ci.yml`) runs the format check, lint and typecheck once and the tests on Python 3.11 and 3.14, on every push and pull request.

Changes go through the [no-mistakes](https://github.com/kunchenguid/no-mistakes) review pipeline before they reach GitHub; the rules for contributors and agents are in [AGENTS.md](../AGENTS.md) and its skills.

## Tests

```sh
make test   # or, once 'make vendor' has run: python3 -m unittest discover -s tests
```

They need no root, no touch bar, no Herdr and no firstmate. There is one file per area: `test_agents_config.py`, `test_agents_sources.py`, `test_agents_fleet.py`, `test_agents_card.py`, `test_agents_app.py`, `test_agents_answers.py` and `test_agents_board.py` the agent app, `test_install.py` `install.sh` and the library's pin, and `test_skills.py` the skills (their front matter, the index in `AGENTS.md`, the `.claude/skills` link, and that their links and repository paths resolve). `agents_support.py` holds what the app's tests share and puts the checkout and `vendor/` on `sys.path`; `bar_support.py` is a stand-in for the touch bar daemon's side of the socket; `desktop_support.py` holds the stand-ins for the desktop programs the decisions board goes through (`lavish-axi`, the URL handler, `systemd-run`).

The touch bar is `bar_support.py`: its `Apps` and `AppServer` take the app's messages the way screenpad-linux's daemon does, checking each against the app protocol, version 2 ([app API](https://github.com/mmarsot/screenpad-linux/blob/main/docs/app-api.md)): hello and welcome, tiles, pages and their widgets, questions and their answers, with the protocol's limits written out there rather than taken from the client library, so the app is checked against the protocol, not against its own library. A test touches the app's widgets and tiles through it (`press`, `event`) and answers its questions (`asks`). It draws nothing and arms nothing: the touch bar's own rules (arming, cancels) are screenpad-linux's, and tested there.

The agent app's tests use stand-ins only: a fake `herdr` script, and a fake firstmate checkout whose `bin/fm-bearings-snapshot.sh` prints an `fm-bearings.v1` model and whose `bin/fm-control.sh`, `bin/fm-bearings-board.sh` and `bin/fm-inbox.sh` record their calls (in the fake checkout, never a firstmate home), a fake `lavish-axi` printing a session listing, a stand-in for the URL handler that only records the URL (so nothing opens on the screen) and one for `systemd-run` that records its arguments and runs what follows `--` (so no unit is made), all in a temporary directory, and fake clients for the loop. They cover:

- the config: every setting (with `lavish`), the errors, no default pointing at a firstmate home, and the command refusing to run without a config (the opt-in);
- Herdr: every call naming the session (agent list, get, focus and send-keys, pane read), a wrapper command, the states, `state_change_seq` and odd entries, its errors (a command missing or not executable, a pane it does not know), a hang and an answer with no result;
- firstmate's reader: run with only `FM_HOME` of the `FM_*` variables and the arguments `--json --fields endpoints`, the Captain's Call count (decisions and the captain's contributions, more when some were left out), tasks joined by their Herdr endpoint, and its failures; its interrupt: `fm-control.sh <task> interrupt` with only `FM_HOME`, its failure, and task ids it refuses;
- the blocked card: the lines it draws (frame and blank lines dropped, the last 16, each clipped), the Claude Code keymap (Allow once, Always only when the dialog offers it, Deny; never the folder-trust, external-imports or bypass dialogs, nor an unknown harness), its widgets through the stand-in touch bar's validation, touches mapped only to the screen drawn, a changed screen being new buttons, and the guard: keys sent only when the pane is still blocked with the same `state_change_seq` and the same text, and nothing sent when the dialog changed between draw and tap (`npm test` turned `rm -rf build`), the state changed, or another agent is in the pane;
- the page and tiles, through the stand-in touch bar's validation: a widget per agent in Herdr's order, tones by state, the grid growing then "+N more", names clipped to the limits, odd pane ids, without firstmate, Herdr failing or reporting nothing, the Captain's Call states;
- the loop against the stand-in touch bar's socket server: hello, the page and tiles, a tap opening an agent's card and its Focus focusing the pane, nothing else doing so, a refused focus logged with the loop going on, the agents tile focusing the first blocked agent, Captain's Call taps reading firstmate again (and opening the board), changes sent and the rest not, Herdr failing and coming back, an unexpected error in either thread shown, logged and survived, the touch bar going and coming back, without firstmate, `welcome` and `error` logged; the package importing nothing of the daemon (`screenpad_touchbar`); and `run` serving the bar and stopping on SIGTERM;
- the card in the loop: Allow once, Always and Deny sending their keys and closing the card, a dialog that changes between draw and tap answered with nothing and drawn again with new buttons that need a fresh tap (the old ones then doing nothing), a state change likewise, the card following its screen and closing when its agent goes, Interrupt through `fm-control.sh` for a firstmate task and through Herdr's keys for another agent, an unknown harness read-only, and a failed send shown;
- the decisions board: its path from `fm-bearings-board.sh path` with only `FM_HOME` (and never `build`), the session Lavish lists `open` for that file (both paths resolved, so a row listed through a symlink or with `//` or `.` matches) opened with the URL handler in a scope of its own (`systemd-run --user --scope --collect --quiet -- gio open <url>`, through a stand-in `systemd-run` that runs the opener after `--`), no `systemd-run` opening it directly and saying so, a scope that cannot be made opening nothing, none open (ended, another file, nothing listed) opening nothing, only a loopback `http` URL opened, `lavish-axi`, the opener and a missing script failing with why; asking firstmate for it with one `fm-inbox.sh note --json --request-id <id> -- <text>` with only `FM_HOME`, a refused note (exit 3, saved but not woken), a missing script or an answer that is no `fm-inbox-note.v1` failing with why, the same id again replayed, and a replay of a note firstmate has handled (acknowledged, or in `handled/`) told apart; and in the loop: a tap or a lift on the `calls` tile opening it (not a cancel, a long press or a lift off the tile), taps while it opens opening it once, no board open showing its card (a second tap replacing it, OK doing nothing and asking nothing), Open decisions board asking firstmate once while its request is pending (taps then saying it was requested), asking again once the board was seen open or the hold has passed, a failed request shown and tried again under the same request id (a new id once that id is older than the hold, or once the board was seen open, and one new note under a new id when the replayed note was already handled), a failure shown on that card, an opener with no scope logged, a card the bar cannot show logged, and nothing sent to an agent or firstmate's control.

The `install.sh` tests run it as the user against a temporary `HOME`, `XDG_DATA_HOME` and `XDG_CONFIG_HOME`, with stub `id` and `systemctl` first on `PATH` (so the real user manager is never asked anything) and the client library from a wheel built from `vendor/` (so nothing is fetched): the program, its package and the library under `~/.local/lib/screenpad-agents/`, the command's link, the unit installed but not enabled (parsed: its command, its config condition, not restarted after a config error), the installed command running in isolated mode and refusing to run without its config (and saying what to do without the library), an update replacing the copy whole and keeping the config, a failed library install keeping the previous copy, root refused, and uninstall disabling the unit, removing what install put in place and keeping the config. They are skipped when run as root. Another test checks that the library is pinned to a screenpad-linux commit and that `vendor/` holds that commit.

## The screenshots

`docs/images/agents-page.png` and `docs/images/agents-card.png` were rendered in screenpad-linux, before the app moved here: by the touch bar's extension in a headless GNOME Shell 50.1 fed the scenes the daemon publishes, with the agent app's `App` connected to the daemon's own `AppServer` and fed the tests' `FakeHerdr` and `FakeFirstmate` (the card after a tap on the blocked agent), then scaled to half. screenpad-linux's [development guide](https://github.com/mmarsot/screenpad-linux/blob/main/docs/development.md) describes the rendering setup.
