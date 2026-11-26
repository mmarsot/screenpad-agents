"""Captain's Call's decisions board: finding and opening it, asking
firstmate for one when none is open, and waiting for it to be open.

Its two sides run in two threads. The loop's (look, tap, choose, request,
result, tick) holds the request and the wait, and the board's state
(callpage.Board) the Captain's Call page shows on its button; the control
thread's (timeout, work) runs firstmate.py's commands for it and posts
their results to the loop.

Opening the Captain's Call view on the Agents page looks for the board, so
the button says Open board or Request board; the button's Open board looks
again and opens it when Lavish has it open, and the calls tile opens it
straight away. Request board asks firstmate with one inbox note, and the
button and the Captain's Call widget say at once that the board is opening;
the note is written only when a look just before finds no board open (a
board found ends the wait, and the button opens it).
Meanwhile the control thread checks every BOARD_POLL seconds whether the
board is open (fm-bearings-board.sh path and Lavish's listing) and what
firstmate did with the note (fm-inbox.sh receipts, read-only): handled, or
replied to. The wait ends

- when the board is open: the button opens it;
- after BOARD_WAIT seconds, or BOARD_REPLY_GRACE after firstmate replied
  with no board open: the button says no board came, with firstmate's reply
  if it gave one, and its Retry asks again;
- when the note fails: the button says why, and its Retry asks again.

The Captain's Call count is read again right after a request and when the
board is open, so the count and the board agree as soon as they can; the
checks run only while the app waits, and nothing of the wait is kept on
disk, so a restart starts with none.

Each request has its own id, kept after a failed note or a wait that ended
for BOARD_REQUEST_HOLD, so trying again meanwhile replays a note
fm-inbox.sh may have saved rather than queueing a second; later a retry is
a new request. A replay of a note firstmate already handled wakes nothing,
so the same job asks again at once under a new id.

Bearings (rebuild, the bearings tile) is the one-tap form of all this: a
board that is open and was built within BOARD_FRESH seconds (its file's age)
is opened at once; otherwise firstmate is asked, with its own note, to
rebuild it, and the wait ends by opening the board, not by saying it is
ready, as soon as it is open and its file is newer than the request.
"""

import secrets
import time

from . import callpage
from .common import BOARD_FRESH, BOARD_POLL, BOARD_REPLY_GRACE, BOARD_REQUEST_HOLD, BOARD_WAIT
from .common import why as _why
from .firstmate import REBUILD_REQUEST, FirstmateError

# How much older than the request a board's file may be, and still be the one
# firstmate rebuilt for it (seconds: clocks and file times are coarse).
REBUILT_SLACK = 2.0


class BoardRequest:
    def __init__(self, firstmate, control, post, log, refresh, clock, wall=time.time):
        self.firstmate, self.control, self.post = firstmate, control, post
        self.log, self.refresh, self.clock, self.wall = log, refresh, clock, wall
        # The loop's side.
        self.board = callpage.Board()  # what the page's button shows
        self.busy = set()  # the look ("look") or open ("board") on its way
        self.id = None  # the id of the request a retry repeats
        self.made = None  # when that id was made
        self.kind = None  # the job that id was made for
        self.since = None  # when the wait for the board began; None: no wait
        self.note = None  # the inbox note waited on, once fm-inbox.sh saved it
        self.reply = None  # what firstmate replied to it
        self.replied = None  # when that reply was first seen
        self.trouble = None  # the last check's error, logged once
        # The control thread's side.
        self.poll = BOARD_POLL
        self._watching = None  # the note whose board it checks for
        self._due = 0.0
        self._since = None  # when Bearings asked (wall clock): the board it opens is newer

    # --- the loop's side -----------------------------------------------------

    def waiting(self):
        return self.since is not None

    def look(self):
        """The Captain's Call view opened: find out whether the board is
        open, so its button says what a tap does."""
        self.refresh()
        self._job("look")

    def tap(self):
        """Open the board: look for it and open it when it is open."""
        self.refresh()
        self._job("board")

    def _job(self, what):
        if what not in self.busy:
            self.busy.add(what)
            self.control.put((what,))

    def choose(self, widget):
        """A tap on the page's widget; True if the page changed."""
        what = callpage.action(widget, self.board)
        if what == callpage.REQUEST:
            return self.request()
        if what == callpage.OPEN:
            self.tap()
        return False

    def request(self):
        """Ask firstmate for the board with one note, unless the app waits
        for one already; True if the page changed."""
        return self._begin(("request",))

    def rebuild(self):
        """Bearings: open the board when it is open and fresh, else ask
        firstmate to rebuild it and open it once it is; True if the page
        changed (nothing happens while a wait is on)."""
        return self._begin(("rebuild", self.wall()))

    def _begin(self, job):
        if self.waiting():
            return False
        now = self.clock()
        if self.id is None or self.kind != job[0] or now - self.made >= BOARD_REQUEST_HOLD:
            self.id, self.made, self.kind = _request_id(), now, job[0]
        self.since, self.note, self.reply, self.replied, self.trouble = now, None, None, None, None
        self.board.set("opening")
        self.control.put((job[0], self.id) + job[1:])
        return True

    def result(self, what, *rest):
        """Take a result of the control thread in; True if the page changed."""
        if what in ("board", "look"):
            return self._found(what, *rest)
        if what == "requested":
            return self._requested(*rest)
        if what == "watched":
            return self._watched(*rest)
        return False

    def tick(self):
        """End a wait that lasted too long; True if the page changed."""
        if not self.waiting():
            return False
        now = self.clock()
        if now - self.since < BOARD_WAIT and (self.replied is None or now - self.replied < BOARD_REPLY_GRACE):
            return False
        self.log("no decisions board came after asking firstmate%s" % (": " + self.reply if self.reply else ""))
        self._end()
        return self.board.set("late", self.reply) or True

    def _found(self, what, url, error):
        """What a look ("look") or an open ("board") found."""
        self.busy.discard(what)
        opened = what == "board"
        if url is not None:
            if opened:
                self.log("opened the decisions board: %s" % url)
            self.id = None  # the board is there: a later request asks anew
            if self.waiting():
                self.refresh()
            self._end()
            return self.board.set("shown" if opened else "open")
        if error is not None:
            self.log("the decisions board %s: %s" % ("did not open" if opened else "could not be found", error))
            return False if self.waiting() else self.board.set("unopened", error)
        if self.waiting():
            if opened:
                self.log("no decisions board is open yet; firstmate was asked for one")
            return False
        if opened:
            self.log("no decisions board is open")
        return self.board.set("none")

    def _requested(self, request_id, note, error):
        if request_id != self.id:
            self.id, self.made = request_id, self.clock()
        if error is not None:
            self.log("the request for the decisions board failed: %s" % error)
            self._end()
            return self.board.set("failed", error) or True
        self.log("asked firstmate for the decisions board: %s %s" % note)
        self.refresh()
        if self.waiting():
            self.note = note[1]
            self.control.put(("watch", self.note))
        return False

    def _watched(self, note, url, receipt, error):
        if not self.waiting() or note != self.note:
            return False
        if error != self.trouble:
            self.trouble = error
            self.log("checking for the decisions board: %s" % (error or "answers again"))
        reply = receipt[1] if receipt else None
        changed = False
        if reply and self.reply is None:
            self.reply, self.replied = reply, self.clock()
            self.log("firstmate replied to the board request: %s" % reply)
            changed = self.board.set("opening", reply)
        if url is None:
            return changed
        self.log("firstmate opened the decisions board: %s" % url)
        self.id = None
        self.refresh()
        self._end()
        return self.board.set("open") or True

    def _end(self):
        """Stop waiting."""
        if self.waiting():
            self.since = self.note = None
            self.control.put(("watch", None))

    # --- the control thread's side -------------------------------------------

    def timeout(self):
        """Seconds until the next check for the board, None when none is due."""
        return None if self._watching is None else max(0.0, self._due - self.clock())

    def work(self, job):
        """Do a job of the board's; False if it is not one."""
        what = job[0]
        if what in ("board", "look"):
            find = self.firstmate.open_board if what == "board" else self.firstmate.board_url
            try:
                self.post(what, find(), None)
            except Exception as e:
                self.post(what, None, _why(e, FirstmateError))
        elif what == "request":
            self._since = None
            self._request(job[1])
        elif what == "rebuild":
            self._rebuild(job[1], job[2])
        elif what == "watch":
            self._watching, self._due = job[1], self.clock() + self.poll
        elif what == "check":
            if self._watching is not None:
                self._check(self._watching)
                self._due = self.clock() + self.poll
        else:
            return False
        return True

    def _request(self, request_id):
        try:
            url = self.firstmate.board_url()
        except Exception:
            url = None
        if url is not None:
            self.post("look", url, None)
            return
        self._ask(request_id)

    def _rebuild(self, request_id, since):
        self._since = since
        try:
            fresh = self.firstmate.board_url() is not None and self.firstmate.board_age() <= BOARD_FRESH
        except Exception:
            fresh = False  # it cannot be told to be: ask firstmate
        if fresh:
            try:
                url = self.firstmate.open_board()
            except Exception as e:
                self.post("requested", request_id, None, _why(e, FirstmateError))
                return
            if url is not None:
                self.post("board", url, None)
                return
        self._ask(request_id, REBUILD_REQUEST)

    def _ask(self, request_id, text=None):
        """Ask firstmate with one note; text None is the board request's."""
        args = () if text is None else (text,)
        try:
            note = self.firstmate.request_board(request_id, *args)
            if note is None:
                request_id = _request_id()
                note = self.firstmate.request_board(request_id, *args)
            if note is None:
                raise FirstmateError("fm-inbox.sh says a new request was handled already")
            self.post("requested", request_id, note, None)
        except Exception as e:
            self.post("requested", request_id, None, _why(e, FirstmateError))

    def _rebuilt(self, url):
        """Whether the board, open at url (None: it is not), was rebuilt by
        firstmate since Bearings asked (its file is newer than the ask)."""
        if url is None:
            return False
        return self.firstmate.board_age() <= max(0.0, self.wall() - self._since) + REBUILT_SLACK

    def _check(self, note):
        url = receipt = None
        errors = []
        try:
            url = self.firstmate.board_url()
            if self._since is not None:
                found, url = url, None  # a board that is not the rebuilt one ends no wait
                if self._rebuilt(found):
                    self.post("board", self.firstmate.open_board(), None)
                    return
        except Exception as e:
            errors.append(_why(e, FirstmateError))
        try:
            receipt = self.firstmate.receipt(note)
        except Exception as e:
            errors.append(_why(e, FirstmateError))
        self.post("watched", note, url, receipt, "; ".join(errors) or None)


def _request_id():
    """A new id for a request of the decisions board, as fm-inbox.sh note
    --request-id takes it."""
    return "screenpad-board-%d-%s" % (time.time(), secrets.token_hex(4))
