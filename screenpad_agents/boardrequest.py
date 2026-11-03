"""Captain's Call's decisions board: opening it on a tap, asking firstmate
for one when none is open, and waiting for it to be open.

Its two sides run in two threads. The loop's (tap, choose, result, tick)
holds the request and the wait, and asks the bar's card; the control
thread's (timeout, work) runs firstmate.py's commands for it and posts
their results to the loop.

A tap opens the board when Lavish has it open; with none, the card asks
whether to request one. Request asks firstmate with one inbox note and the
card says at once that the board is opening; the Captain's Call widget says
so too while the app waits. Meanwhile the control thread checks every
BOARD_POLL seconds whether the board is open (fm-bearings-board.sh path and
Lavish's listing, as a tap does) and what firstmate did with the note
(fm-inbox.sh receipts, read-only): handled, or replied to. The wait ends

- when the board is open: the card says so, and its Open opens it as a tap
  does;
- after BOARD_WAIT seconds, or BOARD_REPLY_GRACE after firstmate replied
  with no board open: the card says no board came, with firstmate's reply
  if it gave one, and Retry asks again;
- when the note fails: the card says why, and Retry asks again.

The Captain's Call count is read again right after a request and when the
board is open, so the count and the board agree as soon as they can; the
checks run only while the app waits, and nothing of the wait is kept on
disk, so a restart starts with none.

Each request has its own id, kept after a failed note or a wait that ended
for BOARD_REQUEST_HOLD, so trying again meanwhile replays a note
fm-inbox.sh may have saved rather than queueing a second; later a retry is
a new request. A replay of a note firstmate already handled wakes nothing,
so the same job asks again at once under a new id.
"""

import secrets
import time

from . import callcard
from .common import BOARD_POLL, BOARD_REPLY_GRACE, BOARD_REQUEST_HOLD, BOARD_WAIT
from .common import why as _why
from .firstmate import FirstmateError


class BoardRequest:
    def __init__(self, firstmate, fleet, control, post, ask, asked, log, refresh, clock):
        self.firstmate, self.fleet, self.control, self.post = firstmate, fleet, control, post
        self.ask, self.asked, self.log, self.refresh, self.clock = ask, asked, log, refresh, clock
        # The loop's side.
        self.opening = False  # a tap's look for the board is on its way
        self.id = None  # the id of the request a retry repeats
        self.made = None  # when that id was made
        self.since = None  # when the wait for the board began; None: no wait
        self.note = None  # the inbox note waited on, once fm-inbox.sh saved it
        self.reply = None  # what firstmate replied to it
        self.replied = None  # when that reply was first seen
        self.card = None  # the id of the card saying the board is opening
        self.trouble = None  # the last check's error, logged once
        # The control thread's side.
        self.poll = BOARD_POLL
        self._watching = None  # the note whose board it checks for
        self._due = 0.0

    # --- the loop's side -----------------------------------------------------

    def waiting(self):
        return self.since is not None

    def tap(self):
        """A tap on Captain's Call: look for the board and open it (one at a
        time: taps while it is looked for add nothing)."""
        self.refresh()
        if not self.opening:
            self.opening = True
            self.control.put(("board",))

    def choose(self, option):
        """An answer chosen on the card; True if the page changed."""
        if option == callcard.REQUEST:
            return self.request()
        if option == callcard.OPEN:
            self.tap()
        return False

    def request(self):
        """Ask firstmate for the board with one note, unless the app waits
        for one already (then the card says it is opening); True if the
        page changed."""
        if self.waiting():
            self._show_opening()
            return False
        now = self.clock()
        if self.id is None or now - self.made >= BOARD_REQUEST_HOLD:
            self.id, self.made = _request_id(), now
        self.since, self.note, self.reply, self.replied, self.trouble = now, None, None, None, None
        self.fleet.board_opening = True
        self._show_opening()
        self.control.put(("request", self.id))
        return True

    def result(self, what, *rest):
        """Take a result of the control thread in; True if the page changed."""
        if what == "board":
            return self._board(*rest)
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
        self.ask(callcard.late(self.reply))
        return True

    def _board(self, url, error):
        self.opening = False
        if url is not None:
            self.log("opened the decisions board: %s" % url)
            self.id = None  # the board is there: a later request asks anew
            return self._end()
        if error is not None:
            self.log("the decisions board did not open: %s" % error)
            self.ask(callcard.not_opened(error))
        elif self.waiting():
            self.log("no decisions board is open yet; firstmate was asked for one")
            self._show_opening()
        else:
            self.log("no decisions board is open")
            self.ask(callcard.no_board())
        return False

    def _requested(self, request_id, note, error):
        if request_id != self.id:
            self.id, self.made = request_id, self.clock()
        if error is not None:
            self.log("the request for the decisions board failed: %s" % error)
            changed = self._end()
            self.ask(callcard.not_requested(error))
            return changed
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
        if reply and self.reply is None:
            self.reply, self.replied = reply, self.clock()
            self.log("firstmate replied to the board request: %s" % reply)
            if self.card is not None and self.asked() == self.card:
                self._show_opening()
        if url is None:
            return False
        self.log("firstmate opened the decisions board: %s" % url)
        self.id = None
        self.refresh()
        changed = self._end()
        self.ask(callcard.opened())
        return changed

    def _show_opening(self):
        self.card = self.ask(callcard.opening(self.reply))

    def _end(self):
        """Stop waiting; True if the page changed."""
        if not self.waiting():
            return False
        self.since = self.note = self.card = None
        self.fleet.board_opening = False
        self.control.put(("watch", None))
        return True

    # --- the control thread's side -------------------------------------------

    def timeout(self):
        """Seconds until the next check for the board, None when none is due."""
        return None if self._watching is None else max(0.0, self._due - self.clock())

    def work(self, job):
        """Do a job of the board's; False if it is not one."""
        what = job[0]
        if what == "board":
            try:
                self.post("board", self.firstmate.open_board(), None)
            except Exception as e:
                self.post("board", None, _why(e, FirstmateError))
        elif what == "request":
            self._request(job[1])
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
            note = self.firstmate.request_board(request_id)
            if note is None:
                request_id = _request_id()
                note = self.firstmate.request_board(request_id)
            if note is None:
                raise FirstmateError("fm-inbox.sh says a new request was handled already")
            self.post("requested", request_id, note, None)
        except Exception as e:
            self.post("requested", request_id, None, _why(e, FirstmateError))

    def _check(self, note):
        url = receipt = None
        errors = []
        try:
            url = self.firstmate.board_url()
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
