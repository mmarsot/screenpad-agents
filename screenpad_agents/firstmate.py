"""firstmate: its tasks' endpoints and how many Captain's Calls wait.

Read through firstmate's own read-only reader, never its files:

  FM_HOME=<home> <code>/bin/fm-bearings-snapshot.sh --json --fields endpoints

prints the fm-bearings.v1 model. The Captain's Calls waiting are
len(decisions_open) + len(contributions.captain), each named as the model
gives it: a decision by its id and summary, a contribution by its task, its
kind and the reason it needs the captain; "endpoints" gives each
task's recorded endpoint, for Herdr "<session>:<pane id>", which joins a task
to the agent Herdr reports in that pane. "in_flight" gives the task's name
and what it is doing. With the Runs page discovering firstmate's projects,
the reader is asked for "endpoints,paths": "paths" gives each live task's
worktree, the repo copy its no-mistakes runs are made in. The reader takes about 3 s; app.py runs it off the
loop, at most once a minute plus on demand.

Interrupting a task's agent goes through firstmate's control plane, which
knows the task's harness and checks what it did:

  FM_HOME=<home> <code>/bin/fm-control.sh <task id> interrupt

It and the board's request below are the only firstmate commands that act;
fm-inbox.sh receipts, below, only reads.

Tapping Captain's Call opens firstmate's decisions board, the Lavish board
of /bearings lavish, in the browser on the main screen, where the decisions
are answered; the panel answers none. Its file is what firstmate says,

  FM_HOME=<home> <code>/bin/fm-bearings-board.sh path

and it is open when Lavish's own session listing (lavish-axi, run with no
argument) shows that file "open", with its session's URL. That URL, and only
a loopback http one, is handed to the desktop's URL handler in a transient
scope of its own (desktop.py),

  systemd-run --user --scope --collect --quiet -- gio open <url>

so a browser it starts is never in the app's unit. Without systemd-run
nothing is opened. With no session open
nothing is built or armed from here: firstmate composes the board. The panel
can ask it to, with one note in firstmate's inbox,

  FM_HOME=<home> <code>/bin/fm-inbox.sh note --json --request-id <id> -- <BOARD_REQUEST>

which wakes firstmate once; it then builds the board, and Lavish opens it.
The app keeps one request id per request, so a retry after a failure (the
note perhaps saved, firstmate not woken) replays that note rather than
queueing a second one. While it waits for the board, it reads whether
firstmate has handled that note or replied to it, with fm-inbox.sh's own
read-only view of its notes (it writes nothing and wakes no one),

  FM_HOME=<home> <code>/bin/fm-inbox.sh receipts

and checks for the board open as a tap does (boardrequest.py).
"""

import json
import os
import re
import subprocess

from .common import (
    BEARINGS_SCHEMA,
    BOARD_TIMEOUT,
    CONTROL_TIMEOUT,
    FIRSTMATE_TIMEOUT,
    INBOX_TIMEOUT,
    LAVISH_TIMEOUT,
)
from .desktop import OPENER, SCOPE, DesktopError, open_url

# A task id as fm-control.sh takes it: a bare id, never an option or an
# endpoint.
TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
# A row of lavish-axi's session listing after its file and comma:
# <status>,"<url>",... (the listing is TOON: sessions[N]{file,status,url,...}).
SESSION_ROW = re.compile(r'(?P<status>[^,]*),"(?P<url>[^"]*)"')
# The board's URL as Lavish serves it: on this machine only.
BOARD_URL = re.compile(r"http://(127\.0\.0\.1|localhost|\[::1\]):[0-9]{1,5}/[A-Za-z0-9._~/%-]*")
# The note that asks firstmate for its decisions board, what it asks first
# (firstmate's wake shows the note's start).
BOARD_REQUEST = (
    "Please open the decisions board: /bearings lavish. "
    "Asked from Captain's Call on the ScreenPad, where no decisions board is open."
)

# What fm-inbox.sh note --json and receipts print.
NOTE_SCHEMA = "fm-inbox-note.v1"
RECEIPTS_SCHEMA = "fm-inbox-receipts.v1"


class FirstmateError(Exception):
    pass


class Task:
    """A firstmate task whose endpoint is a Herdr pane."""

    __slots__ = ("doing", "id", "name")

    def __init__(self, id, name=None, doing=None):
        self.id, self.name, self.doing = id, name, doing

    def __eq__(self, other):
        return isinstance(other, Task) and (self.id, self.name, self.doing) == (other.id, other.name, other.doing)

    def __hash__(self):
        return hash((self.id, self.name, self.doing))

    def __repr__(self):
        return "Task(%r)" % self.id


class Call:
    """One Captain's Call waiting: a "decision" or a "contribution", its
    title (the task) and what it is about (or None)."""

    __slots__ = ("kind", "text", "title")

    def __init__(self, kind, title, text=None):
        self.kind, self.title, self.text = kind, title, text

    def __eq__(self, other):
        return isinstance(other, Call) and (self.kind, self.title, self.text) == (other.kind, other.title, other.text)

    def __hash__(self):
        return hash((self.kind, self.title, self.text))

    def __repr__(self):
        return "Call(%r, %r, %r)" % (self.kind, self.title, self.text)


class Bearings:
    """What one read gave: the Captain's Calls waiting (more when the reader
    left some out) and each of them the reader listed, the tasks by endpoint
    target, and the live tasks' worktrees by task id (when the reader was
    asked for paths)."""

    __slots__ = ("calls", "more", "tasks", "waiting", "worktrees")

    def __init__(self, calls, more, tasks, worktrees=None, waiting=()):
        self.calls, self.more, self.tasks, self.worktrees = calls, more, tasks, worktrees or {}
        self.waiting = list(waiting)

    def __eq__(self, other):
        return isinstance(other, Bearings) and (
            self.calls,
            self.more,
            self.tasks,
            self.worktrees,
            self.waiting,
        ) == (other.calls, other.more, other.tasks, other.worktrees, other.waiting)

    def __hash__(self):
        return hash((self.calls, self.more))


class Firstmate:
    def __init__(
        self,
        home,
        bearings,
        control,
        run=subprocess.run,
        timeout=FIRSTMATE_TIMEOUT,
        board=None,
        inbox=None,
        lavish=("lavish-axi",),
        opener=OPENER,
        scope=SCOPE,
        paths=False,
    ):
        self.home, self.bearings, self.control, self._run, self.timeout = home, bearings, control, run, timeout
        self.board, self.inbox, self.lavish, self.opener = board, inbox, list(lavish), list(opener)
        self.scope = list(scope)
        self.fields = "endpoints,paths" if paths else "endpoints"

    def read(self):
        """The Bearings now; FirstmateError when the reader fails."""
        done = self._call([self.bearings, "--json", "--fields", self.fields], "firstmate's reader", self.timeout)
        try:
            model = json.loads(done.stdout)
        except ValueError:
            raise FirstmateError("firstmate's reader printed no JSON")
        return parse(model)

    def interrupt(self, task_id):
        """Interrupt task_id's agent through fm-control.sh; what it reported,
        or FirstmateError when it refused or failed."""
        if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
            raise FirstmateError("not a firstmate task id: %r" % (task_id,))
        done = self._call([self.control, task_id, "interrupt"], "fm-control.sh interrupt", CONTROL_TIMEOUT)
        out = (done.stdout or "").strip().splitlines()
        return out[-1] if out else "interrupted"

    def board_url(self):
        """The URL of firstmate's decisions board when Lavish has it open,
        None when it has not; FirstmateError when either cannot say."""
        if not self.board or not os.access(self.board, os.X_OK):
            raise FirstmateError("firstmate has no bin/fm-bearings-board.sh")
        done = self._call([self.board, "path"], "fm-bearings-board.sh path", BOARD_TIMEOUT)
        lines = (done.stdout or "").strip().splitlines()
        if len(lines) != 1 or not os.path.isabs(lines[0]):
            raise FirstmateError("fm-bearings-board.sh path printed no board path")
        listing = self._call(self.lavish, "lavish-axi", LAVISH_TIMEOUT, home=False)
        return listed_url(listing.stdout or "", os.path.realpath(lines[0]))

    def open_board(self):
        """Open the decisions board in the browser, the opener in a scope of
        its own: its URL, or None when no board is open (then nothing is
        opened); FirstmateError on a failure, a missing or failed systemd-run
        (then the opener did not run) or the opener's."""
        url = self.board_url()
        if url is None:
            return None
        try:
            open_url(url, "opening the board", self._run, self.scope, self.opener)
        except DesktopError as e:
            raise FirstmateError(str(e))
        return url

    def request_board(self, request_id):
        """Ask firstmate to build and open its decisions board, with one note
        in its inbox (one wake) under request_id: what fm-inbox.sh reported,
        (outcome, note id), the outcome "created", or "replay" for a
        request_id it already has; None when that note is one firstmate has
        already handled, acknowledged or moved to handled/ (its replay wakes
        nothing: ask again under a new id); FirstmateError when it refused or
        failed."""
        argv = [self._inbox(), "note", "--json", "--request-id", request_id, "--", BOARD_REQUEST]
        done = self._call(argv, "fm-inbox.sh note", INBOX_TIMEOUT)
        try:
            note = json.loads(done.stdout or "")
        except ValueError:
            note = None
        if not isinstance(note, dict) or note.get("schema") != NOTE_SCHEMA:
            raise FirstmateError("fm-inbox.sh note printed no %s" % NOTE_SCHEMA)
        path = note.get("path")
        if note.get("acknowledged") is True or (
            isinstance(path, str) and os.path.basename(os.path.dirname(path)) == "handled"
        ):
            return None
        return str(note.get("outcome")), str(note.get("id"))

    def receipt(self, note_id):
        """What firstmate did with its inbox note note_id, from fm-inbox.sh
        receipts (read-only): (acknowledged, reply), acknowledged True once
        it is in handled/ and reply the text firstmate replied with, or None;
        (None, None) when the view does not list that note (its bounds left
        it out); FirstmateError when it fails or prints no receipts."""
        done = self._call([self._inbox(), "receipts"], "fm-inbox.sh receipts", INBOX_TIMEOUT)
        try:
            view = json.loads(done.stdout or "")
        except ValueError:
            view = None
        if not isinstance(view, dict) or view.get("schema") != RECEIPTS_SCHEMA:
            raise FirstmateError("fm-inbox.sh receipts printed no %s" % RECEIPTS_SCHEMA)
        for note in _list(view, "pending") + _list(view, "handled"):
            if isinstance(note, dict) and note.get("id") == note_id:
                reply = note.get("reply")
                body = _text(reply.get("body")) if isinstance(reply, dict) else None
                return note.get("acknowledged") is True, body
        return None, None

    def _inbox(self):
        if not self.inbox or not os.access(self.inbox, os.X_OK):
            raise FirstmateError("firstmate has no bin/fm-inbox.sh")
        return self.inbox

    def _call(self, argv, what, timeout, home=True):
        """Run one of firstmate's commands with FM_HOME (or, home False,
        another program without it), and none of the other FM_* variables of
        this environment."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("FM_")}
        if home:
            env["FM_HOME"] = self.home
        try:
            done = self._run(argv, text=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL, capture_output=True)
        except OSError as e:
            raise FirstmateError("%s: %s" % (argv[0], e.strerror))
        except subprocess.TimeoutExpired:
            raise FirstmateError("%s gave no answer in %g s" % (what, timeout))
        if done.returncode != 0:
            why = (done.stderr or "").strip().splitlines()
            raise FirstmateError("%s failed: %s" % (what, why[-1] if why else "exit %d" % done.returncode))
        return done


def parse(model):
    """Bearings from an fm-bearings.v1 model; FirstmateError if it is not one."""
    if not isinstance(model, dict) or model.get("schema") != BEARINGS_SCHEMA:
        raise FirstmateError("firstmate's reader is not %s" % BEARINGS_SCHEMA)
    decisions = _list(model, "decisions_open")
    contributions = model.get("contributions")
    captain = _list(contributions, "captain") if isinstance(contributions, dict) else []
    more = any(
        isinstance(o, dict) and str(o.get("surface", "")).startswith("decisions_open") for o in _list(model, "omitted")
    )
    if isinstance(contributions, dict) and isinstance(contributions.get("captain_omitted"), int):
        more = more or contributions["captain_omitted"] > 0
    flights = {f["id"]: f for f in _list(model, "in_flight") if isinstance(f, dict) and isinstance(f.get("id"), str)}
    tasks = {}
    for e in _list(model, "endpoints"):
        if not isinstance(e, dict) or e.get("backend") != "herdr":
            continue
        task_id, target = e.get("id"), e.get("target")
        if not isinstance(task_id, str) or not isinstance(target, str) or ":" not in target:
            continue
        flight = flights.get(task_id, {})
        tasks[target] = Task(task_id, _text(flight.get("name")), _text(flight.get("doing")))
    worktrees = {}
    for p in _list(model, "paths"):
        if isinstance(p, dict) and isinstance(p.get("id"), str) and isinstance(p.get("worktree"), str):
            if os.path.isabs(p["worktree"]):
                worktrees[p["id"]] = p["worktree"]
    waiting = [c for c in map(_decision, decisions) if c] + [c for c in map(_contribution, captain) if c]
    return Bearings(len(decisions) + len(captain), more, tasks, worktrees, waiting)


def _decision(d):
    """A decision_open row as a Call: its id (else its key) and summary."""
    if not isinstance(d, dict):
        return None
    title = _text(d.get("id")) or _text(d.get("key"))
    return Call("decision", title, _text(d.get("summary"))) if title else None


def _contribution(c):
    """A captain contribution row as a Call: its task, and its kind with the
    reason it needs the captain (else its URL)."""
    if not isinstance(c, dict) or not _text(c.get("task")):
        return None
    about = _text(c.get("reason")) or _text(c.get("url"))
    kind = _text(c.get("kind"))
    text = "%s: %s" % (kind, about) if kind and about else about or kind
    return Call("contribution", _text(c.get("task")), text)


def listed_url(listing, path):
    """The URL lavish-axi's listing gives the session open on path (a real
    path; a row's file is resolved too), None when it lists none open;
    FirstmateError for a URL off this machine."""
    for line in listing.splitlines():
        line = line.strip()
        if line.startswith(path + ","):
            rest = line[len(path) + 1 :]
        else:
            file, comma, rest = line.partition(",")
            if not comma or not os.path.isabs(file) or os.path.realpath(file) != path:
                continue
        row = SESSION_ROW.match(rest)
        if row is None or row["status"] != "open":
            continue
        if not BOARD_URL.fullmatch(row["url"]):
            raise FirstmateError("Lavish lists the board at %r, not a local URL" % row["url"])
        return row["url"]
    return None


def _list(model, key):
    value = model.get(key) if isinstance(model, dict) else None
    return value if isinstance(value, list) else []


def _text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None
