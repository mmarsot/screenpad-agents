"""agents.toml: the app's config, and the opt-in it is.

The app runs only with a config: without one it refuses to start, so
installing it changes nothing until you write one (docs/agents.md). The config
is strict, as touchbar.toml is: an unknown table or key, or a bad value, is a
ConfigError naming it.

  [herdr]
  command = "herdr"            # or a list: a wrapper and its arguments (a
                               # string is split into words like a shell
                               # would, quotes allowed; no shell runs it)
  session = "default"          # the Herdr session the agents run in
  poll = 2                     # seconds between two reads of Herdr
  agents_page = false          # with [firstmate], also give the Agents page
                               # (without firstmate it is always given); with
                               # it on and every page on, the calls page goes

  [firstmate]                  # optional: tasks and Captain's Calls
  home = "/path/to/firstmate"  # FM_HOME
  code = "/path/to/firstmate"  # the checkout with bin/fm-bearings-snapshot.sh
                               # and bin/fm-control.sh (and, for the
                               # decisions board, bin/fm-bearings-board.sh
                               # and bin/fm-inbox.sh)
  poll = 60                    # seconds, at least 60
  lavish = "lavish-axi"        # or a list: the program that lists Lavish's
                               # sessions, where the decisions board is open
  review_command = "/path/to/review {task}"
                               # optional, or a list: opens a change ready
                               # for review ({task} is the task id)

  [usage]                      # optional: the usage-limits tile and page
  command = "quota-axi"        # or a list: a wrapper and its arguments
  poll = 60                    # seconds between two runs, at least 60
  providers = ["claude"]       # the providers that count (default: every one
                               # quota-axi can read); the others are ignored
  terminal = ["ptyxis", "--new-window", "-x", "bash -c {command}"]
                               # a terminal window; {command} is what to run
                               # in it: Details opens firstmate's usage viewer
                               # (data/tools/usage-view.py), else `command --full`

  [runs]                       # optional: the Runs page (no-mistakes runs)
  repos = ["/path/to/repo"]    # repo directories to watch
  firstmate = true             # also firstmate's projects and task copies
                               # (only with [firstmate]; true by default)
  command = "no-mistakes"      # or a list: a wrapper and its arguments
  poll = 20                    # seconds between reads while a run is active
  idle = 120                   # seconds between reads while none is
  watch_command = "/path/to/watch {run}"
                               # optional, or a list: opens a live view of a
                               # run ({run} is the run id), for its card's
                               # Watch button
  [[runs.remote]]              # optional, repeatable: another machine whose
                               # runs the Runs page shows too, read over ssh
  name = "desktop"             # its label on the page
  ssh = "desktop"              # the ssh target (an alias in ~/.ssh/config)
  home = "/path/to/firstmate"  # its firstmate home: its projects and tasks
  code = "/path/to/firstmate"  # its checkout with the reader (default: home)
  repos = ["/path/to/repo"]    # repo directories there to watch
  command = "no-mistakes"      # no-mistakes there; or a list
  terminal = ["ptyxis", "--new-window", "-x", "bash -c {command}"]
                               # a terminal window here; {command} is the
                               # watch to run in it (with watch_script)
  watch_script = "/path/to/nm-watch.py"
                               # the viewer, sent to run there with the run id
"""

import os
import re
import shlex
import tomllib

from .common import (
    DOCS,
    FIRSTMATE_POLL,
    FIRSTMATE_POLL_RANGE,
    HERDR_POLL,
    HERDR_POLL_RANGE,
    RUN_PLACEHOLDER,
    RUNS_IDLE,
    RUNS_IDLE_RANGE,
    RUNS_POLL,
    RUNS_POLL_RANGE,
    TASK_PLACEHOLDER,
    USAGE_POLL,
    USAGE_POLL_RANGE,
    ConfigError,
)

MACHINE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,19}")
SSH_TARGET = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.@:-]{0,127}")
COMMAND_PLACEHOLDER = "{command}"

PROVIDER = re.compile(r"[a-z0-9][a-z0-9_.-]{0,31}")
SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
BEARINGS = os.path.join("bin", "fm-bearings-snapshot.sh")
CONTROL = os.path.join("bin", "fm-control.sh")
BOARD = os.path.join("bin", "fm-bearings-board.sh")
INBOX = os.path.join("bin", "fm-inbox.sh")
LAVISH = ["lavish-axi"]
TERMINAL = ["ptyxis", "--new-window", "-T", "Usage limits", "-x", "bash -c " + COMMAND_PLACEHOLDER]


class Config:
    """The settings: Herdr's command and session, and firstmate's paths
    and the commands that find its decisions board and ask for one (home
    None when the config has no [firstmate])."""

    __slots__ = (
        "agents_page",
        "bearings",
        "board",
        "control",
        "firstmate_poll",
        "herdr",
        "herdr_poll",
        "home",
        "inbox",
        "lavish",
        "path",
        "review",
        "runs",
        "session",
        "usage",
    )

    def __init__(
        self, path, herdr, session, herdr_poll, home=None, bearings=None, firstmate_poll=FIRSTMATE_POLL, control=None
    ):
        self.path, self.herdr, self.session, self.herdr_poll = path, herdr, session, herdr_poll
        self.home, self.bearings, self.firstmate_poll, self.control = home, bearings, firstmate_poll, control
        self.board, self.inbox, self.lavish = None, None, list(LAVISH)
        self.agents_page = False  # [herdr] agents_page: the Agents page with firstmate too
        self.review = None  # the command that opens a change for review, with its {task} word
        self.runs = None
        self.usage = None


class Usage:
    """[usage]: quota-axi's command, the seconds between two runs of it, the
    terminal window Details opens its viewer in ({command} is the line to run
    in it) and the providers that count (None: every one quota-axi can read)."""

    __slots__ = ("command", "poll", "providers", "terminal")

    def __init__(self, command=("quota-axi",), poll=USAGE_POLL, terminal=TERMINAL, providers=None):
        self.command, self.poll, self.terminal = list(command), poll, list(terminal)
        self.providers = list(providers) if providers is not None else None


class Runs:
    """[runs]: the repo directories to watch, whether firstmate's projects
    and task copies are watched too, no-mistakes' command and the two
    intervals, and the command that opens a live view of a run (watch,
    with its {run} word; None: no Watch button)."""

    __slots__ = ("command", "firstmate", "idle", "poll", "remotes", "repos", "watch")

    def __init__(self, repos=(), firstmate=False, command=("no-mistakes",), poll=RUNS_POLL, idle=RUNS_IDLE, watch=None):
        self.repos, self.firstmate, self.command = list(repos), firstmate, list(command)
        self.poll, self.idle, self.watch = poll, idle, list(watch) if watch else None
        self.remotes: list = []


class Remote:
    """[[runs.remote]]: another machine, read over ssh: its label (name), the
    ssh target, its firstmate home and checkout (None: no firstmate there),
    its repo directories, its no-mistakes program, and how Watch opens a
    run there: terminal (a laptop terminal's words, {command} the line to
    run in it) and watch_script (the local viewer sent to run on that
    machine); both set or neither."""

    __slots__ = ("code", "command", "home", "name", "repos", "ssh", "terminal", "watch_script")

    def __init__(self, name, ssh, home=None, code=None, repos=(), command=("no-mistakes",), terminal=None, script=None):
        self.name, self.ssh, self.home, self.code = name, ssh, home, code or home
        self.repos, self.command = list(repos), list(command)
        self.terminal, self.watch_script = (list(terminal) if terminal else None), script


def load(path):
    """The Config in path; ConfigError when it is missing or wrong."""
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError("%s does not exist; the agent app runs only once you write it (see %s)" % (path, DOCS))
    except OSError as e:
        raise ConfigError("cannot read %s: %s" % (path, e.strerror))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError("%s: %s" % (path, e))
    return parse(path, data)


def parse(path, data):
    _known(path, data, {"herdr", "firstmate", "runs", "usage"}, "table")
    herdr = _table(path, data, "herdr")
    if herdr is None:
        raise ConfigError("%s: [herdr] is required, with at least its session" % path)
    _known(path, herdr, {"command", "session", "poll", "agents_page"}, "key in [herdr]")
    command = _command(path, herdr.get("command", "herdr"), "[herdr] command", "herdr")
    session = herdr.get("session")
    if not isinstance(session, str) or not SESSION.fullmatch(session):
        raise ConfigError('%s: [herdr] session must be a Herdr session name, like "default"' % path)
    herdr_poll = _seconds(path, herdr, "herdr", HERDR_POLL, HERDR_POLL_RANGE)
    config = Config(path, command, session, herdr_poll)
    config.agents_page = herdr.get("agents_page", False)
    if not isinstance(config.agents_page, bool):
        raise ConfigError("%s: [herdr] agents_page must be true or false" % path)
    fm = _table(path, data, "firstmate")
    if fm is not None:
        _known(path, fm, {"home", "code", "poll", "lavish", "review_command"}, "key in [firstmate]")
        config.home = _directory(path, fm, "home")
        code = _directory(path, fm, "code")
        config.bearings, config.control = os.path.join(code, BEARINGS), os.path.join(code, CONTROL)
        # Checked when Captain's Call is tapped, not here: a checkout without
        # them still runs the rest of the app.
        config.board, config.inbox = os.path.join(code, BOARD), os.path.join(code, INBOX)
        config.lavish = _command(path, fm.get("lavish", LAVISH), "[firstmate] lavish", "lavish-axi")
        if "review_command" in fm:
            config.review = _review(path, fm["review_command"])
        for script in (BEARINGS, CONTROL):
            if not os.access(os.path.join(code, script), os.X_OK):
                raise ConfigError("%s: [firstmate] code has no executable %s" % (path, script))
        config.firstmate_poll = _seconds(path, fm, "firstmate", FIRSTMATE_POLL, FIRSTMATE_POLL_RANGE)
    runs = _table(path, data, "runs")
    if runs is not None:
        config.runs = _runs(path, runs, config.home is not None)
    usage = _table(path, data, "usage")
    if usage is not None:
        config.usage = _usage(path, usage)
    return config


def _usage(path, table):
    _known(path, table, {"command", "poll", "terminal", "providers"}, "key in [usage]")
    command = _command(path, table.get("command", "quota-axi"), "[usage] command", "quota-axi")
    poll = _seconds(path, table, "usage", USAGE_POLL, USAGE_POLL_RANGE)
    terminal = _command(path, table.get("terminal", TERMINAL), "[usage] terminal", "ptyxis")
    if not any(COMMAND_PLACEHOLDER in word for word in terminal):
        raise ConfigError("%s: [usage] terminal must hold {command}, where the report's line goes" % path)
    providers = table.get("providers")
    if providers is not None:
        names = providers if isinstance(providers, list) else None
        if not names or not all(isinstance(n, str) and PROVIDER.fullmatch(n) for n in names):
            raise ConfigError(
                '%s: [usage] providers must be a list of provider names such as ["claude"]'
                " (lower case letters, digits, -, _ or .)" % path
            )
        providers = list(dict.fromkeys(names))
    return Usage(command, poll, terminal, providers)


def _review(path, value):
    command = _command(path, value, "[firstmate] review_command", "/path/to/review")
    if not any(TASK_PLACEHOLDER in word for word in command):
        raise ConfigError("%s: [firstmate] review_command must hold {task}, where the task id goes" % path)
    return command


def _runs(path, table, firstmate):
    keys = {"repos", "firstmate", "command", "poll", "idle", "watch_command", "remote"}
    _known(path, table, keys, "key in [runs]")
    repos = table.get("repos", [])
    if not isinstance(repos, list) or not all(isinstance(r, str) and os.path.isabs(r) for r in repos):
        raise ConfigError("%s: [runs] repos must be a list of absolute paths" % path)
    for r in repos:
        if not os.path.isdir(r):
            raise ConfigError("%s: [runs] repos: %s is not a directory" % (path, r))
    discover = table.get("firstmate", True)
    if not isinstance(discover, bool):
        raise ConfigError("%s: [runs] firstmate must be true or false" % path)
    discover = discover and firstmate
    remotes = _remotes(path, table.get("remote", []))
    if not repos and not discover and not remotes:
        raise ConfigError("%s: [runs] has no repos, and no [firstmate] to find projects in" % path)
    command = _command(path, table.get("command", "no-mistakes"), "[runs] command", "no-mistakes")
    poll = _seconds(path, table, "runs", RUNS_POLL, RUNS_POLL_RANGE)
    idle = _seconds(path, table, "runs", RUNS_IDLE, RUNS_IDLE_RANGE, key="idle")
    if idle < poll:
        raise ConfigError("%s: [runs] idle must be at least its poll" % path)
    watch = None
    if "watch_command" in table:
        watch = _command(path, table["watch_command"], "[runs] watch_command", "/path/to/watch")
        if not any(RUN_PLACEHOLDER in word for word in watch):
            raise ConfigError("%s: [runs] watch_command must hold {run}, where the run id goes" % path)
    runs = Runs(list(dict.fromkeys(os.path.normpath(r) for r in repos)), discover, command, poll, idle, watch)
    runs.remotes = remotes
    return runs


def _remotes(path, value):
    """The [[runs.remote]] tables as Remotes."""
    if not isinstance(value, list) or not all(isinstance(t, dict) for t in value):
        raise ConfigError("%s: [[runs.remote]] must be an array of tables" % path)
    out: list[Remote] = []
    for table in value:
        keys = {"name", "ssh", "home", "code", "repos", "command", "terminal", "watch_script"}
        _known(path, table, keys, "key in [[runs.remote]]")
        name, target = table.get("name"), table.get("ssh")
        if not isinstance(name, str) or not MACHINE.fullmatch(name):
            raise ConfigError('%s: [[runs.remote]] name must be a short name, like "desktop"' % path)
        if name in {r.name for r in out}:
            raise ConfigError("%s: two [[runs.remote]] are named %s" % (path, name))
        if not isinstance(target, str) or not SSH_TARGET.fullmatch(target):
            raise ConfigError('%s: [[runs.remote]] %s: ssh must be an ssh target, like "desktop"' % (path, name))
        home, code = (_remote_path(path, name, table, k) for k in ("home", "code"))
        repos = table.get("repos", [])
        if not isinstance(repos, list) or not all(isinstance(r, str) and os.path.isabs(r) for r in repos):
            raise ConfigError("%s: [[runs.remote]] %s: repos must be a list of absolute paths" % (path, name))
        if code and not home:
            raise ConfigError("%s: [[runs.remote]] %s: code needs home" % (path, name))
        if not repos and not home:
            raise ConfigError("%s: [[runs.remote]] %s has no repos and no home to find projects in" % (path, name))
        command = _command(path, table.get("command", "no-mistakes"), "[[runs.remote]] command", "no-mistakes")
        terminal = script = None
        if ("terminal" in table) != ("watch_script" in table):
            raise ConfigError("%s: [[runs.remote]] %s: terminal and watch_script go together" % (path, name))
        if "terminal" in table:
            terminal = _command(path, table["terminal"], "[[runs.remote]] terminal", "ptyxis")
            if not any(COMMAND_PLACEHOLDER in word for word in terminal):
                raise ConfigError("%s: [[runs.remote]] %s: terminal must hold {command}" % (path, name))
            script = table["watch_script"]
            if not isinstance(script, str) or not os.path.isabs(script) or not os.path.isfile(script):
                raise ConfigError(
                    "%s: [[runs.remote]] %s: watch_script must be a file, by absolute path" % (path, name)
                )
        out.append(Remote(name, target, home, code, [os.path.normpath(r) for r in repos], command, terminal, script))
    return out


def _remote_path(path, name, table, key):
    value = table.get(key)
    if value is not None and (not isinstance(value, str) or not os.path.isabs(value)):
        raise ConfigError("%s: [[runs.remote]] %s: %s must be an absolute path" % (path, name, key))
    return os.path.normpath(value) if value else None


def _known(path, table, allowed, what):
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError("%s: unknown %s %s" % (path, what, ", ".join(repr(k) for k in unknown)))


def _table(path, data, name):
    table = data.get(name)
    if table is not None and not isinstance(table, dict):
        raise ConfigError("%s: %s must be a table, [%s]" % (path, name, name))
    return table


def _command(path, value, key, example):
    # A string is split into words as a shell would (quotes allowed), but no
    # shell runs it; a list is the words as they are.
    words = value
    if isinstance(value, str):
        try:
            words = shlex.split(value)
        except ValueError as e:
            raise ConfigError("%s: %s cannot be split into words: %s" % (path, key, e))
    if not isinstance(words, list) or not words or not all(isinstance(w, str) and w for w in words):
        raise ConfigError('%s: %s must be a program, or a list of words like ["%s"]' % (path, key, example))
    return list(words)


def _seconds(path, table, name, default, bounds, key="poll"):
    value = table.get(key, default)
    low, high = bounds
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ConfigError("%s: [%s] %s must be %g to %g seconds" % (path, name, key, low, high))
    return float(value)


def _directory(path, table, key):
    value = table.get(key)
    if not isinstance(value, str) or not os.path.isabs(value):
        raise ConfigError("%s: [firstmate] %s must be an absolute path" % (path, key))
    if not os.path.isdir(value):
        raise ConfigError("%s: [firstmate] %s: %s is not a directory" % (path, key, value))
    return value
