"""A change ready for review on Captain's Call: its three buttons.

A decision whose key is code-review (firstmate.REVIEW_KEY) is a change
ready for the reviewer. Captain's Call gives the first such call the page's
two rows in place of the plain calls: the call on the left, and on the
right Review (opens the change in the configured review command), Approve
and Request changes (which opens the review too). Approve and Request
changes each tell firstmate with one inbox note, once: after one was sent
(or while it is being sent) both stay on the page as its state, and only a
failed one can be pressed again. Without [firstmate] review_command there
is no Review, and no Request changes (it would open nothing): Approve takes
the right half. A change is one round of review by its task and the head it
is ready at; a call that names no head has no Approve or Request changes
(their note could not tell this round from the last), only Review, and
without a review command it is a plain call.

Pure, as callpage.py is: it turns the call and what the app knows of it
(Entry, kept by reviewrequest.py) into widgets, and says what a tap on one
of them means. A button's id names its state and the call it is for
(token), so a tap on a button the page no longer shows does nothing.
"""

import hashlib

OPEN, APPROVE, CHANGES = "open", "approve", "changes"
# The note's state: being sent, sent (firstmate not yet through it), handled
# by firstmate, failed (a press tries again).
SENDING, SENT, HANDLED, FAILED = "sending", "sent", "handled", "failed"
# What opening the review did: on its way, started, or failed.
OPENING, OPENED = "opening", "opened"

PREFIX = "call.rv."
# What each verdict's button says: its label, the label once sent, its hint.
WORDS = {
    APPROVE: ("Approve", "Approved", "tell firstmate the change is approved"),
    CHANGES: ("Request changes", "Changes requested", "opens the review, and tells firstmate changes were requested"),
}


class Entry:
    """What the app knows of one change ready for review: the verdict sent
    (APPROVE or CHANGES, None while none was) and its phase, firstmate's
    reply or why it failed (detail), the inbox note once saved, and what
    opening the review did."""

    __slots__ = ("detail", "note", "open_error", "opened", "phase", "verdict")

    def __init__(self):
        self.verdict = self.phase = self.detail = self.note = self.opened = self.open_error = None

    def locked(self):
        """True once a verdict was sent or is being sent: no other note."""
        return self.phase in (SENDING, SENT, HANDLED)


def first(bearings, can_open):
    """The first call ready for review in bearings that has a button (with
    can_open, a review command is configured), None when none is."""
    for call in bearings.waiting if bearings is not None else ():
        if call.review is not None and (can_open or call.review.head):
            return call
    return None


def key(review):
    return (review.task, review.head)


def token(review):
    """Six characters that name the change, for the buttons' ids."""
    return hashlib.sha256(("%s@%s" % key(review)).encode()).hexdigest()[:6]


def request_id(review, verdict):
    """The id of the note for this verdict on this change: the same every
    time, so the second press (or one after a restart) replays the note
    instead of sending another."""
    digest = hashlib.sha256(("%s@%s/%s" % (review.task, review.head, verdict)).encode()).hexdigest()
    return "screenpad-review-%s-%s" % (verdict, digest[:24])


def buttons(review, entry, can_open):
    """The buttons shown: dicts with the widget's fields and "act", what a
    tap does (None for a button that only shows a state)."""
    entry = entry or Entry()
    tok = token(review)
    out = []
    if can_open:
        label, text, tone, state = "Review", "open the change for review", "accept", entry.opened or "idle"
        if entry.opened == OPENING:
            text = "starting the review…"
        elif entry.opened == OPENED:
            text = "opened on the main screen"
        elif entry.opened:
            text, tone = "not opened: %s" % entry.open_error, "reject"
        out.append(
            {"act": OPEN, "id": "%sopen.%s.%s" % (PREFIX, state, tok), "label": label, "text": text, "tone": tone}
        )
    if review.head:
        for act in (APPROVE, CHANGES) if can_open else (APPROVE,):
            out.append(_verdict(act, review, entry, tok))
    return out


def _verdict(act, review, entry, tok):
    ask, done, hint = WORDS[act]
    mine = entry.verdict == act
    if not mine:
        if entry.locked():
            label, text, tone, state, live = ask, "the other answer is sent", "neutral", "locked", False
        else:
            label, text, tone, state, live = ask, hint, "accept", "idle", True
    elif entry.phase == SENDING:
        label, text, tone, state, live = "Sending…", "telling firstmate", "neutral", SENDING, False
    elif entry.phase == FAILED:
        label, text, tone, state, live = "Retry", "not sent: %s" % entry.detail, "reject", FAILED, True
    elif entry.phase == HANDLED:
        label, text, tone, state, live = done, "handled by firstmate", "neutral", HANDLED, False
    else:
        label, text, tone, state, live = done, "sent to firstmate", "neutral", SENT, False
        if entry.detail:
            text = "firstmate: %s" % entry.detail
    out = {
        "act": act if live else None,
        "id": "%s%s.%s.%s" % (PREFIX, act, state, tok),
        "label": label,
        "text": text,
        "tone": tone,
    }
    if not live:
        out["touch"] = "none"
    return out


def action(widget, review, entry, can_open):
    """What a tap on widget does for this change: OPEN, APPROVE or CHANGES
    for a button as the page shows it now, None for anything else."""
    for b in buttons(review, entry, can_open):
        if b["id"] == widget:
            return b["act"]
    return None
