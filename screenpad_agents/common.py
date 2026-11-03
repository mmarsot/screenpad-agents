"""Names, paths, timings and the errors of the agent app.

The touch bar's own limits, its socket's path and clip() are the client
library's (screenpad_app), as for any app.
"""

import os

import screenpad_app

# Who the app is on the touch bar's socket, and what it gives it.
APP = "agents"
FLEET_TILE = "agents"
CALLS_TILE = "calls"
PAGE = "agents"
RUNS_TILE = "runs"
RUNS_PAGE = "runs"

CONFIG = ("screenpad", "agents.toml")
# The app's icons: SVGs in icons/ next to the package, in the checkout as in
# the installed copy (install.sh), given to the touch bar by absolute path.
# Each is drawn on its own navy disc, so it reads on every tone.
ICONS = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "icons")
HELM, CAPTAIN, LIGHTHOUSE = "helm", "captain", "lighthouse"
BACK_ICON, FOCUS_ICON, INTERRUPT_ICON = "back", "spyglass", "anchor"
# What the config error points to: install.sh installs no docs.
DOCS = "https://github.com/mmarsot/screenpad-agents/blob/main/docs/agents.md"

# How often Herdr is asked (seconds), and the bounds a config may set.
HERDR_POLL = 2.0
HERDR_POLL_RANGE = (1.0, 60.0)
HERDR_TIMEOUT = 5.0
# firstmate's reader takes about 3 s; it runs at most once a minute, plus on
# demand when the Captain's Call tile or widget is tapped.
FIRSTMATE_POLL = 60.0
FIRSTMATE_POLL_RANGE = (60.0, 3600.0)
FIRSTMATE_TIMEOUT = 30.0
BEARINGS_SCHEMA = "fm-bearings.v1"
# The Runs page reads no-mistakes (each call about 30 ms) every RUNS_POLL
# seconds while a run is active, every RUNS_IDLE seconds while none is, and
# not at all while the touch bar is not connected.
RUNS_POLL = 20.0
RUNS_POLL_RANGE = (10.0, 300.0)
RUNS_IDLE = 120.0
RUNS_IDLE_RANGE = (30.0, 3600.0)
NO_MISTAKES_TIMEOUT = 15.0
# Waiting for the touch bar's daemon when it is not running.
RECONNECT = 5.0

# Herdr's agent states. Herdr is authoritative; anything else is "unknown".
STATES = ("working", "blocked", "idle", "done", "unknown")
STATE_TONES = {"working": "accept", "blocked": "warning"}

# The Agents page's grid: COLUMNS wide, MIN_ROWS rows or more as agents
# need, up to the touch bar's own limit (screenpad_app.MAX_ROWS).
COLUMNS = 4
MIN_ROWS = 2
# firstmate's interrupt (bin/fm-control.sh <task> interrupt) waits for the
# harness to acknowledge, about 5 s; past this it is reported failed.
CONTROL_TIMEOUT = 60.0
# Finding and opening the decisions board: fm-bearings-board.sh path, the
# Lavish session listing (node, about 0.5 s), and the URL handler.
BOARD_TIMEOUT = 15.0
LAVISH_TIMEOUT = 15.0
OPEN_TIMEOUT = 15.0
# Asking firstmate for the board: one note in its inbox (fm-inbox.sh note).
INBOX_TIMEOUT = 15.0
# The card that says no board is open stays this long, unless dismissed.
BOARD_CARD_TIMEOUT = 30
# After asking firstmate for the board, how long the app waits for it to be
# open (seconds; building it takes about a minute): taps meanwhile queue no
# second note, and the card then offers to ask again. While it waits it
# checks every BOARD_POLL seconds, and once firstmate has replied without
# the board open, it waits BOARD_REPLY_GRACE more at most.
BOARD_WAIT = 180.0
BOARD_POLL = 10.0
BOARD_REPLY_GRACE = 30.0
# How long a request keeps its id, so a retry replays its note rather than
# queueing a second; firstmate may have handled an older one.
BOARD_REQUEST_HOLD = 300.0


class AgentsError(Exception):
    """A problem the app reports in one line and exits on (code 2)."""


class ConfigError(AgentsError):
    pass


def why(error, expected):
    """What to show and log for an error a worker caught: an expected one
    says why itself; any other is a bug, named by its type."""
    return str(error) if isinstance(error, expected) else "%s: %s" % (type(error).__name__, error)


def socket_path():
    """The touch bar's socket, found the way any app finds it."""
    try:
        return screenpad_app.socket_path()
    except screenpad_app.TouchbarError as e:
        raise AgentsError(str(e))


def icon(name):
    """The absolute path of one of the app's icons."""
    return os.path.join(ICONS, name + ".svg")


def config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, *CONFIG)
