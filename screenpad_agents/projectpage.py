"""The Projects page: firstmate's projects and their settings, switchable
from the touch bar.

Pure: it turns the last Read of firstmate's files (projectmodel.py) and the
changes asked for and not yet there into the "page" message, and says what
a touch means. It changes nothing itself: a tap that picks a setting gives
the caller a Change, which the app sends to firstmate as a note
(projectwatch.py); the page shows it pending until a read reflects it.

Three views of one grid, six columns wide, a touch at a time:

  - the list: one row per project, its name and a line of its settings, the
    two presets (Iterate, Refine; the project's own is lit) and Settings;
    more than four projects take pages of three rows, with Previous and Next
    under them;
  - a project's settings: Back, its name, the presets, and six settings in
    large cells: a tap on Auto-merge or Annotated review asks for the other
    value at once, one on another opens its values;
  - a setting's values: large buttons, the project's own lit, one tap asking
    firstmate for that value and returning to the settings.

A widget's id names what a tap on it does, and a tap on an id the page no
longer shows does nothing. Every cell is fitted to its box (the grid is 1920
px by about 728 px, so a cell of one column is 320 px wide; callpage.py says
how a box's size gives the characters it holds).
"""

import hashlib
import time

from screenpad_app import clip
from screenpad_app.common import MAX_BADGE, MAX_LABEL, MAX_TILE_TEXT

from . import projectmodel as model
from .callpage import fit
from .common import BACK_ICON, PENDING_HOLD, PROJECTS_ICON, PROJECTS_PAGE, icon
from .projectmodel import CHOICES, Change, label, reflects

COLUMNS, LIST_ROWS, DETAIL_ROWS = 6, 4, 3
# Characters in a box: a name's cell (three columns) and its line, a
# two-column cell's text (two lines), a title.
NAME_TEXT, WIDE_TEXT, TITLE_TEXT = 50, 66, 100
# The settings the project's view lists, in order; Auto-merge and Annotated
# review are switched by one tap, the others open their values.
ORDER = ("validation", "auto_merge", "annotated", "where", "model", "effort")
TOGGLES = ("auto_merge", "annotated")
DELIVERY = {"full": "validated", "pr": "plain PR", "local": "local only", None: "delivery unknown"}
BACK, NOTE = "pj.back", "pj.note"
PREVIOUS, NEXT = "pj.prev", "pj.next"


def _hash(name):
    return hashlib.sha256(name.encode()).hexdigest()[:8]


def summary(p):
    """A project's settings in a line."""
    parts = [DELIVERY[p.delivery]]
    if p.delivery != "local":
        parts.append("auto-merge" if p.auto_merge else "you merge")
    parts.append(label("where", p.where).lower())
    parts.append(p.model + ("" if p.effort == "default" else " " + p.effort))
    if not p.annotated:
        parts.append("no annotated review")
    return " · ".join(parts)


class Projects:
    """What the page last knew: the Read of the files (None before the
    first), the changes asked for and not yet there, and where the captain
    is: the project open and the setting whose values show."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.read = None
        self.pending: dict = {}  # (project, key) -> (value, when asked)
        self.error = None  # why the last note was not sent
        self.project = None
        self.setting = None
        self.offset = 0
        self._actions: dict = {}

    # --- what the threads tell it ---------------------------------------------

    def set_read(self, read):
        """Take a Read in; what it reflects is no longer pending, nor is
        what was asked PENDING_HOLD seconds ago. A Read that could not read
        the registry changes nothing pending."""
        self.read = read
        if read.error is None:
            now = self.clock()
            for (name, key), (value, since) in list(self.pending.items()):
                p = read.find(name)
                if p is None or reflects(p, Change(name, key, value)) or now - since >= PENDING_HOLD:
                    del self.pending[(name, key)]
        if self.project is not None and (read.find(self.project) is None and read.error is None):
            self.project = self.setting = None
        self._widgets()

    def ask(self, change):
        """change was sent to firstmate: show it pending."""
        self.pending[(change.project, change.key)] = (change.value, self.clock())
        self.error = None
        self._widgets()

    def failed(self, change, why):
        """change did not reach firstmate."""
        self.pending.pop((change.project, change.key), None)
        self.error = "firstmate was not told: %s" % why
        self._widgets()

    def has_pending(self):
        return bool(self.pending)

    # --- what a touch means ---------------------------------------------------

    def touch(self, widget):
        """A tap on widget of the page last built: (the page changed, the
        Change to send to firstmate or None)."""
        action = self._actions.get(widget)
        if action is None:
            return False, None
        what = action[0]
        if what == "set":
            change = action[1]
            if self.pending.get((change.project, change.key), (None,))[0] == change.value:
                return False, None  # asked already
            self.setting = None
            self._widgets()
            return True, change
        if what == "open":
            self.project, self.setting = action[1], None
        elif what == "choose":
            self.setting = action[1]
        elif what == "back":
            if self.setting is not None:
                self.setting = None
            else:
                self.project = None
        elif what == "page":
            self.offset = max(0, self.offset + action[1])
        self._widgets()  # the next tap is on what is drawn now
        return True, None

    # --- the message ----------------------------------------------------------

    def messages(self):
        return [self.page()]

    def summary(self):
        if self.read is None:
            return "reading firstmate…"
        if self.read.error:
            return "projects unreadable"
        text = "%d project%s" % (len(self.read.projects), "" if len(self.read.projects) == 1 else "s")
        return text + (" · %d asked" % len(self.pending) if self.pending else "")

    def page(self):
        widgets, rows = self._widgets()
        msg = {"op": "page", "page": PROJECTS_PAGE, "title": "Projects", "icon": icon(PROJECTS_ICON)}
        msg["text"] = clip(self.summary(), MAX_TILE_TEXT)
        msg.update({"tone": "warning" if self.pending else "neutral", "columns": COLUMNS, "rows": rows})
        msg["widgets"] = widgets
        if self.pending:
            msg["badge"] = clip(str(len(self.pending)), MAX_BADGE)
        return msg

    def _widgets(self):
        self._actions = {}
        read = self.read
        if read is None:
            return [self._note("Reading firstmate…")], 2
        if read.error:
            return [self._note("Projects unreadable", read.error)], 2
        if not read.projects:
            return [self._note("No projects", "firstmate's registry lists none")], 2
        project = read.find(self.project) if self.project else None
        if project is None:
            return self._list(read.projects)
        if self.setting is None:
            return self._detail(project), DETAIL_ROWS
        return self._values(project, self.setting), DETAIL_ROWS

    @staticmethod
    def _note(title, text=None):
        note = {"id": NOTE, "col": 0, "row": 0, "cols": COLUMNS, "rows": 2, "touch": "none", "label": title}
        return dict(note, text=fit(text, TITLE_TEXT)) if text else note

    def _cell(self, id, col, row, cols, words, action=None, **look):
        """A widget; a tap on it does action (None: it is only shown)."""
        cell = {"id": id, "col": col, "row": row, "cols": cols, "label": clip(words, MAX_LABEL)}
        cell.update(look)
        if action is None:
            cell["touch"] = "none"
        else:
            self._actions[id] = action
        return cell

    def _asked(self, p):
        """What was asked for p and is not there yet, in words, or None."""
        wanted = [label(key, value) for (name, key), (value, _) in self.pending.items() if name == p.name]
        return "asked firstmate: " + ", ".join(wanted) if wanted else None

    def _presets(self, p, col, row):
        """The two preset buttons: the project's own lit, one asked for amber."""
        out = []
        for i, (value, words) in enumerate(model.PRESETS):
            own, asked = p.effective_preset() == value, self.pending.get((p.name, "preset"), (None,))[0] == value
            tone = "accept" if own else "warning" if asked else "neutral"
            action = None if own else ("set", Change(p.name, "preset", value))
            out.append(self._cell("pj.%s.%s" % (_hash(p.name), value[:4]), col + i, row, 1, words, action, tone=tone))
        return out

    # --- the list ---------------------------------------------------------------

    def _list(self, projects):
        many = len(projects) > LIST_ROWS
        per = LIST_ROWS - 1 if many else LIST_ROWS
        self.offset = min(self.offset, (len(projects) - 1) // per * per) // per * per
        out = []
        for row, p in enumerate(projects[self.offset : self.offset + per]):
            open_ = ("open", p.name)
            asked = self._asked(p)
            name = self._cell("pj." + _hash(p.name), 0, row, 3, p.name, open_, text=fit(asked or summary(p), NAME_TEXT))
            name["tone"] = "warning" if asked else "neutral"
            out += [name] + self._presets(p, 3, row)
            out.append(self._cell("pj.%s.s" % _hash(p.name), 5, row, 1, "Settings", open_))
        if many:
            last = self.offset + per >= len(projects)
            span = "%d-%d of %d" % (self.offset + 1, min(self.offset + per, len(projects)), len(projects))
            out += [
                self._cell(PREVIOUS, 0, per, 2, "Previous", ("page", -per) if self.offset else None),
                self._cell("pj.span", 2, per, 2, span),
                self._cell(NEXT, 4, per, 2, "Next", None if last else ("page", per)),
            ]
        return out, LIST_ROWS

    # --- a project's settings -------------------------------------------------

    def _detail(self, p):
        title = self.error or self._asked(p) or summary(p)
        out = [self._cell(BACK, 0, 0, 1, "Back", ("back",), icon=icon(BACK_ICON))]
        out.append(
            self._cell(
                "pj.title", 1, 0, 3, p.name, text=fit(title, TITLE_TEXT), tone="reject" if self.error else "neutral"
            )
        )
        out += self._presets(p, 4, 0)
        for i, key in enumerate(ORDER):
            name, value = CHOICES[key][0], p.value(key)
            asked = self.pending.get((p.name, key))
            text = label(key, value) if value is not None else "not set"
            if asked:
                text += " → %s, asked" % label(key, asked[0])
            action: tuple
            if key in TOGGLES:
                target = not (asked[0] if asked else value)
                id, action = "pj.%s.%s" % (key[:5], "on" if target else "off"), ("set", Change(p.name, key, target))
            else:
                id, action = "pj.%s" % key, ("choose", key)
            tone = "warning" if asked else "neutral"
            out.append(self._cell(id, 2 * (i % 3), 1 + i // 3, 2, name, action, text=fit(text, WIDE_TEXT), tone=tone))
        return out

    # --- a setting's values ---------------------------------------------------

    def _values(self, p, key):
        name, choices = CHOICES[key]
        now, asked = p.value(key), self.pending.get((p.name, key))
        out = [self._cell(BACK, 0, 0, 1, "Back", ("back",), icon=icon(BACK_ICON))]
        said = "now %s; tap a value, firstmate applies it" % (label(key, now) if now is not None else "not set")
        out.append(self._cell("pj.title", 1, 0, 5, "%s · %s" % (p.name, name), text=fit(said, TITLE_TEXT)))
        for i, (value, words) in enumerate(choices):
            own, wanted = value == now and not asked, asked is not None and asked[0] == value
            tone = "accept" if own else "warning" if wanted else "neutral"
            action = None if own or wanted else ("set", Change(p.name, key, value))
            out.append(self._cell("pj.v.%s" % str(value).lower(), 2 * (i % 3), 1 + i // 3, 2, words, action, tone=tone))
        return out
