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
    ConfigError,
)

SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
BEARINGS = os.path.join("bin", "fm-bearings-snapshot.sh")
CONTROL = os.path.join("bin", "fm-control.sh")
BOARD = os.path.join("bin", "fm-bearings-board.sh")
INBOX = os.path.join("bin", "fm-inbox.sh")
LAVISH = ["lavish-axi"]


class Config:
    """The settings: Herdr's command and session, and firstmate's paths
    and the commands that find its decisions board and ask for one (home
    None when the config has no [firstmate])."""

    __slots__ = (
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
    )

    def __init__(
        self, path, herdr, session, herdr_poll, home=None, bearings=None, firstmate_poll=FIRSTMATE_POLL, control=None
    ):
        self.path, self.herdr, self.session, self.herdr_poll = path, herdr, session, herdr_poll
        self.home, self.bearings, self.firstmate_poll, self.control = home, bearings, firstmate_poll, control
        self.board, self.inbox, self.lavish = None, None, list(LAVISH)
        self.review = None  # the command that opens a change for review, with its {task} word
        self.runs = None


class Runs:
    """[runs]: the repo directories to watch, whether firstmate's projects
    and task copies are watched too, no-mistakes' command and the two
    intervals, and the command that opens a live view of a run (watch,
    with its {run} word; None: no Watch button)."""

    __slots__ = ("command", "firstmate", "idle", "poll", "repos", "watch")

    def __init__(self, repos=(), firstmate=False, command=("no-mistakes",), poll=RUNS_POLL, idle=RUNS_IDLE, watch=None):
        self.repos, self.firstmate, self.command = list(repos), firstmate, list(command)
        self.poll, self.idle, self.watch = poll, idle, list(watch) if watch else None


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
    _known(path, data, {"herdr", "firstmate", "runs"}, "table")
    herdr = _table(path, data, "herdr")
    if herdr is None:
        raise ConfigError("%s: [herdr] is required, with at least its session" % path)
    _known(path, herdr, {"command", "session", "poll"}, "key in [herdr]")
    command = _command(path, herdr.get("command", "herdr"), "[herdr] command", "herdr")
    session = herdr.get("session")
    if not isinstance(session, str) or not SESSION.fullmatch(session):
        raise ConfigError('%s: [herdr] session must be a Herdr session name, like "default"' % path)
    herdr_poll = _seconds(path, herdr, "herdr", HERDR_POLL, HERDR_POLL_RANGE)
    config = Config(path, command, session, herdr_poll)
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
    return config


def _review(path, value):
    command = _command(path, value, "[firstmate] review_command", "/path/to/review")
    if not any(TASK_PLACEHOLDER in word for word in command):
        raise ConfigError("%s: [firstmate] review_command must hold {task}, where the task id goes" % path)
    return command


def _runs(path, table, firstmate):
    _known(path, table, {"repos", "firstmate", "command", "poll", "idle", "watch_command"}, "key in [runs]")
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
    if not repos and not discover:
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
    return Runs(list(dict.fromkeys(os.path.normpath(r) for r in repos)), discover, command, poll, idle, watch)


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
