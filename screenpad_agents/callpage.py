"""Captain's Call's page: how many calls wait, which ones, and the decisions
board's button, laid out by the app in large boxes.

The same view is the app's "calls" page on the apps page (a page item on
the bar, page = "calls", opens it) and, in place of the grid, what a tap on
the Agents page's Captain's Call widget shows, with Back. Pure: it turns
firstmate's last bearings and the board's state (Board, kept by
boardrequest.py) into widgets, and says what a tap on the board's button
means.

A grid of COLUMNS by ROWS. The top row holds the count, over three cells
(two beside Back), and the board's button in the last; the two rows under
it the calls waiting, each over two cells (and both rows, for one or two),
as firstmate's reader lists them (a decision by its task and summary, a
contribution by its task, kind and reason), MAX_SHOWN at most, the last
cell counting the rest when there are more. The panel's grid is 1920 px by 728 under a bar 208 px high (less the
header), so a cell is a box of about 456 by 219 px, its label 44 px and its
text 30 px, wrapping, under the label: by the extension's sizes
(screenpad-linux's gnome-shell widgets.js), a one-cell box holds about 16
characters of label and three lines of text, about 72 characters
(TEXT_CHARS), a two-cell box about 36 and 150 (WIDE_TEXT_CHARS); a call's
label is fitted to MAX_LABEL (32, the protocol's label limit), within those 36. Every text
is fitted to its box at a word, with an ellipsis, so nothing is cut by the
box; the whole of a call is on firstmate's decisions board. A lower bar
(160 px by default) gives taller boxes, and the same words fit.

The board's button says what a tap does now, and its id names that state
(BOARD + state), so a tap on a button the page no longer shows does
nothing (action returns None for it).
"""

from screenpad_app import clip
from screenpad_app.common import MAX_BADGE, MAX_LABEL, MAX_TILE_TEXT

from .common import BACK_ICON, BOARD_WAIT, CALLS_PAGE, CAPTAIN, icon

COLUMNS, ROWS = 4, 3
# What each box holds (characters), measured as above.
LABEL_CHARS, TEXT_CHARS, WIDE_TEXT_CHARS = 16, 72, 150
# The calls named on the page at most: two rows of two.
MAX_SHOWN = 4

COUNT, BACK, MORE, NONE = "call.count", "call.back", "call.more", "call.none"
BOARD = "call.board."
CALL = "call.item."

# What the board's button does: look for the board and open it, or ask
# firstmate for one.
OPEN, REQUEST = "open", "request"
# The board's states, and the button each shows: (label, text, tone, what a
# tap does). Text None is the state's detail (firstmate's reply, an error).
OPENING_TEXT = "firstmate is building it, about a minute"
LATE_TEXT = "no board in %d minutes: ask firstmate again" % (BOARD_WAIT // 60)
BUTTONS = {
    "idle": ("Open board", "or Request one when none is open", "accept", OPEN),
    "none": ("Request board", "none is open: firstmate builds it in about a minute", "accept", REQUEST),
    "opening": ("Opening board…", OPENING_TEXT, "neutral", OPEN),
    "open": ("Open board", "the board is ready: show it on the main screen", "accept", OPEN),
    "shown": ("Open board", "shown on the main screen", "accept", OPEN),
    "late": ("Retry", LATE_TEXT, "warning", REQUEST),
    "failed": ("Retry", "the request failed", "reject", REQUEST),
    "unopened": ("Open board", "not opened", "reject", OPEN),
}
# What firstmate replied, or what failed, ahead of its words.
DETAIL = {"opening": "firstmate: ", "late": "firstmate: ", "failed": "request failed: ", "unopened": "not opened: "}


class Board:
    """The decisions board as the app last knew it: its state (a key of
    BUTTONS) and the detail it shows (firstmate's reply, or an error)."""

    __slots__ = ("detail", "state")

    def __init__(self, state="idle", detail=None):
        self.state, self.detail = state, detail

    def set(self, state, detail=None):
        """Change the state; True if the page changed."""
        changed = (state, detail) != (self.state, self.detail)
        self.state, self.detail = state, detail
        return changed


def fit(text, limit):
    """text on one line, cut to at most limit characters at a word (or mid
    word, when a word takes most of the room), ending in an ellipsis when
    something was left out."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if text[limit - 1] != " " and space >= limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:.-") + "…"


def summary(bearings, error):
    """The count in a few words, for the count's box, the page's line in the
    home list and the Captain's Call widget."""
    if bearings is None:
        return "firstmate unreadable" if error else "reading firstmate…"
    text = "%s waiting" % (badge(bearings) or "none")
    return text + " (stale)" if error else text


def badge(bearings):
    if bearings is None or not (bearings.calls or bearings.more):
        return None
    return clip("%d+" % bearings.calls if bearings.more else str(bearings.calls), MAX_BADGE)


def tone(bearings):
    return "warning" if badge(bearings) else "neutral"


def widgets(bearings, error, board, back=False):
    """The view's widgets: back adds Back, for the Agents page."""
    count = {"id": COUNT, "col": 0, "row": 0, "cols": 2 if back else 3, "touch": "none"}
    count.update({"label": summary(bearings, error), "tone": tone(bearings)})
    if bearings is None:
        count["text"] = fit(error, WIDE_TEXT_CHARS) if error else "firstmate's reader takes a few seconds"
    else:
        words = "answered on firstmate's decisions board"
        count["text"] = fit("%s; %s" % (words, error) if error else words, WIDE_TEXT_CHARS)
    out = [count]
    if back:
        out.append({"id": BACK, "col": 2, "row": 0, "label": "Back", "icon": icon(BACK_ICON)})
    out.append(button(board))
    return out + _calls(bearings)


def button(board):
    label, text, tone_, _ = BUTTONS[board.state]
    if board.detail and board.state in DETAIL:
        text = DETAIL[board.state] + board.detail
    return {
        "id": BOARD + board.state,
        "col": COLUMNS - 1,
        "row": 0,
        "label": label,
        "text": fit(text, TEXT_CHARS),
        "tone": tone_,
    }


def action(widget, board):
    """What a tap on widget does: OPEN or REQUEST for the board's button as
    the page shows it now, None for anything else."""
    if widget == BOARD + board.state:
        return BUTTONS[board.state][3]
    return None


def _calls(bearings):
    if bearings is None:
        return []
    calls = bearings.waiting
    if not calls:
        none = {"id": NONE, "col": 0, "row": 1, "cols": COLUMNS, "rows": ROWS - 1, "touch": "none"}
        if bearings.calls or bearings.more:
            return [dict(none, label="On the board", text="firstmate's reader named none of the calls waiting")]
        return [dict(none, label="Nothing waits for you", text="no decision and no contribution needs you")]
    total = max(bearings.calls, len(calls))
    # All of them, or one cell fewer and the last saying how many more.
    whole = total <= MAX_SHOWN and not bearings.more
    shown = calls[:MAX_SHOWN] if whole else calls[: MAX_SHOWN - 1]
    out = []
    for i, c in enumerate(shown):
        w = {"id": CALL + str(i), "label": fit(c.title, MAX_LABEL), "tone": "warning"}
        kind = "decision" if c.kind == "decision" else "contribution"
        w["text"] = fit("%s: %s" % (kind, c.text) if c.text else kind, WIDE_TEXT_CHARS)
        out.append(w)
    if not whole:
        rest = "+%d%s more" % (total - len(shown), "+" if bearings.more else "")
        out.append({"id": MORE, "label": rest, "text": "on firstmate's decisions board"})
    # One or two calls take both rows, three or four a row each.
    tall = ROWS - 1 if len(out) <= 2 else 1
    for i, w in enumerate(out):
        w.update({"col": 2 * (i % 2), "row": 1 + i // 2, "cols": 2, "rows": tall, "touch": "none"})
    return out


def page(bearings, error, board):
    """The "calls" page for the apps page."""
    msg = {"op": "page", "page": CALLS_PAGE, "title": "Captain's Call", "icon": icon(CAPTAIN)}
    msg["text"] = clip(summary(bearings, error), MAX_TILE_TEXT)
    msg.update({"tone": tone(bearings), "columns": COLUMNS, "rows": ROWS, "widgets": widgets(bearings, error, board)})
    if badge(bearings):
        msg["badge"] = badge(bearings)
    return msg
