"""The buttons of a change ready for review (reviewcall.py): what a tap
does, and the state it leaves.

Like the board's request (boardrequest.py), two sides run in two threads.
The loop's (choose, bearings, result) holds what the app knows of each
change, an Entry, and queues jobs; the control thread's (work) runs them:

- Review starts [firstmate] review_command with the task's id, detached
  (firstmate.open_review);
- Approve and Request changes send firstmate one inbox note
  (firstmate.review_note), and Request changes starts the review as well.
  The note's request id is the same for the same change and verdict, so a
  second press, or one after a restart, replays the note rather than
  queueing another, and once a verdict was sent the page offers no other
  note: only a failed one can be pressed again. Nothing here merges anything.

Whether firstmate handled the note is read from its receipts
(fm-inbox.sh receipts, read-only) right after each of the app's own reads
of firstmate (every [firstmate] poll, and on demand), and only while a note
is waiting: nothing polls for it. A change firstmate no longer lists is
forgotten.
"""

from . import reviewcall
from .common import why as _why
from .firstmate import FirstmateError
from .reviewcall import APPROVE, CHANGES, FAILED, HANDLED, OPEN, OPENED, OPENING, SENDING, SENT, Entry


class Reviews:
    def __init__(self, firstmate, control, post, log):
        self.firstmate, self.control, self.post, self.log = firstmate, control, post, log
        self.entries = {}  # (task, head) -> Entry
        self.checking = False  # a receipts check is on its way
        self.trouble = None  # the last check's error, logged once

    @property
    def can_open(self):
        """True when a review command is configured: Review and Request
        changes are shown only then."""
        return bool(getattr(self.firstmate, "review", None))

    def entry(self, review):
        return self.entries.get(reviewcall.key(review))

    # --- the loop's side -----------------------------------------------------

    def choose(self, widget, bearings):
        """A tap on the page's widget; True if the page changed."""
        call = reviewcall.first(bearings)
        if call is None:
            return False
        review = call.review
        what = reviewcall.action(widget, review, self.entry(review), self.can_open)
        changed = False
        if what in (OPEN, CHANGES):
            changed = self._open(review)
        if what in (APPROVE, CHANGES):
            changed = self._send(review, what) or changed
        return changed

    def ready(self, task, bearings):
        """The Review of task's change when it waits for review and a review
        command is configured, else None: the agent's terminal is focused
        as before. A task whose ready work is a pull request, with no
        code-review decision, is not one."""
        if task is None or bearings is None or not self.can_open:
            return None
        for call in bearings.waiting:
            if call.review is not None and call.review.task == task.id:
                return call.review
        return None

    def open(self, review):
        """Start the review command for this change; True if the page
        changed."""
        return self._open(review)

    def _entry(self, review):
        return self.entries.setdefault(reviewcall.key(review), Entry())

    def _open(self, review):
        entry = self._entry(review)
        if entry.opened == OPENING:
            return False
        entry.opened, entry.open_error = OPENING, None
        self.control.put(("review-open", reviewcall.key(review), review.task))
        return True

    def _send(self, review, verdict):
        entry = self._entry(review)
        if entry.locked():
            return False
        entry.verdict, entry.phase, entry.detail, entry.note = verdict, SENDING, None, None
        self.control.put(("review-note", reviewcall.key(review), review, verdict))
        return True

    def bearings(self, bearings):
        """firstmate was read: forget the changes it no longer lists, and
        look at what it did with the notes sent."""
        listed = {reviewcall.key(c.review) for c in bearings.waiting if c.review is not None}
        for k in [k for k in self.entries if k not in listed]:
            del self.entries[k]
        waiting = [(k, e.note) for k, e in self.entries.items() if e.phase == SENT and e.note]
        if waiting and not self.checking:
            self.checking = True
            self.control.put(("review-check", waiting))

    def result(self, what, *rest):
        """Take a result of the control thread in; True if the page changed."""
        if what == "review-opened":
            return self._opened(*rest)
        if what == "review-noted":
            return self._noted(*rest)
        if what == "review-checked":
            return self._checked(*rest)
        return False

    def _opened(self, key, error):
        entry = self.entries.get(key)
        if error:
            self.log("the review did not open: %s" % error)
        if entry is None:
            return False
        entry.opened, entry.open_error = (OPENED, None) if error is None else ("failed", error)
        return True

    def _noted(self, key, verdict, note, error):
        entry = self.entries.get(key)
        if error:
            self.log("the %s note to firstmate failed: %s" % (verdict, error))
        elif note is None:
            self.log("the %s note was handled by firstmate already" % verdict)
        else:
            self.log("told firstmate (%s): %s %s" % (verdict, note[0], note[1]))
        if entry is None or entry.verdict != verdict:
            return False
        if error:
            entry.phase, entry.detail = FAILED, error
        elif note is None:
            entry.phase, entry.detail = HANDLED, None
        else:
            entry.phase, entry.note = SENT, note[1]
        return True

    def _checked(self, results, error):
        self.checking = False
        if error != self.trouble:
            self.trouble = error
            self.log("checking what firstmate did with the review notes: %s" % (error or "answers again"))
        changed = False
        for key, acknowledged, reply in results:
            entry = self.entries.get(key)
            if entry is None or entry.phase != SENT:
                continue
            if acknowledged:
                entry.phase, changed = HANDLED, True
            if reply and reply != entry.detail:
                entry.detail, changed = reply, True
        return changed

    # --- the control thread's side -------------------------------------------

    def work(self, job):
        """Do a job of the reviews'; False if it is not one."""
        what = job[0]
        if what == "review-open":
            error = None
            try:
                self.firstmate.open_review(job[2])
            except Exception as e:
                error = _why(e, FirstmateError)
            self.post("review-opened", job[1], error)
        elif what == "review-note":
            _, key, review, verdict = job
            note = error = None
            try:
                note = self.firstmate.review_note(reviewcall.request_id(review, verdict), verdict, review)
            except Exception as e:
                error = _why(e, FirstmateError)
            self.post("review-noted", key, verdict, note, error)
        elif what == "review-check":
            results, errors = [], []
            for key, note in job[1]:
                try:
                    acknowledged, reply = self.firstmate.receipt(note)
                except Exception as e:
                    errors.append(_why(e, FirstmateError))
                    continue
                results.append((key, acknowledged, reply))
            self.post("review-checked", results, "; ".join(dict.fromkeys(errors)) or None)
        else:
            return False
        return True
