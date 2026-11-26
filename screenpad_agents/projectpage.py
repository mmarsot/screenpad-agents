"""The Projects page: firstmate's projects and their settings, switchable
from the touch bar, sent to firstmate only when the captain validates.

Pure: it turns the last Read of firstmate's files (projectmodel.py), the
draft and the changes asked for and not yet there into the "page" message,
and says what a touch means. It changes nothing itself. A tap on a preset or
a value only **stages** it in the draft (shown amber, `Off → On, draft`), and
nothing is sent until **Validate**, which gives the caller every drafted
change of every project to send firstmate in one note (projectwatch.py);
**Discard** drops the draft. The page then shows the changes pending until a
read reflects them.

Three views of one grid, six columns wide, a touch at a time:

  - the list: three projects to a page, each with its name and a line of its
    settings, the two presets (Iterate, Refine; the project's own is lit, a
    drafted one amber) and Settings; under them Previous, the span and Next
    (more than three projects), Discard and Validate;
  - a project's settings: Back, its name, the presets, six settings in large
    cells (a tap on Auto-merge or Annotated review stages the other value,
    one on another opens its values), the draft in words, Discard, Validate;
  - a setting's values: large buttons, the project's own lit, one tap staging
    that value and returning to the settings.

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
from .projectmodel import BUNDLES, CHOICES, Change, label, reflects

COLUMNS, ROWS, VALUE_ROWS, PER_PAGE = 6, 4, 3, 3
# Characters in a box: a name's cell (three columns) and its line, a
# two-column cell's text (two lines), a title.
NAME_TEXT, WIDE_TEXT, TITLE_TEXT = 50, 66, 100
# The settings the project's view lists, in order; Auto-merge and Annotated
# review are switched by one tap, the others open their values.
ORDER = ("validation", "auto_merge", "annotated", "where", "model", "effort")
TOGGLES = ("auto_merge", "annotated")
DELIVERY = {"full": "validated", "pr": "plain PR", "local": "local only", None: "delivery unknown"}
BACK, NOTE = "pj.back", "pj.note"
PREVIOUS, NEXT, DISCARD, VALIDATE = "pj.prev", "pj.next", "pj.discard", "pj.validate"


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
    first), the draft (the changes staged and not sent), the changes asked
    for and not yet there, and where the captain is: the project open and
    the setting whose values show."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.read = None
        self.draft: dict = {}  # (project, key) -> value, staged
        self.pending: dict = {}  # (project, key) -> (value, when asked)
        self.error = None  # why the last note was not sent
        self.project = None
        self.setting = None
        self.offset = 0
        self._actions: dict = {}

    # --- what the threads tell it ---------------------------------------------

    def set_read(self, read):
        """Take a Read in; what it reflects is no longer pending, nor is
        what was asked PENDING_HOLD seconds ago, and a draft that the files
        now have goes. A Read that could not read the registry changes
        nothing."""
        self.read = read
        if read.error is None:
            now = self.clock()
            for (name, key), (value, since) in list(self.pending.items()):
                p = read.find(name)
                if p is None or reflects(p, Change(name, key, value)) or now - since >= PENDING_HOLD:
                    del self.pending[(name, key)]
            for name in {n for n, _ in self.draft}:
                p = read.find(name)
                if p is None:
                    self.draft = {k: v for k, v in self.draft.items() if k[0] != name}
                else:
                    self._tidy(p)
            if self.project is not None and read.find(self.project) is None:
                self.project = self.setting = None
        self._widgets()

    def validate(self):
        """Validate chosen: the draft's changes, every project's, in order
        (a preset first), now pending and out of the draft; the caller
        sends them in one note."""
        changes = self.changes()
        for c in changes:
            self.pending[(c.project, c.key)] = (c.value, self.clock())
        self.draft = {}
        self.error = None
        self._widgets()
        return changes

    def failed(self, changes, why):
        """The note for changes was not sent: they are not pending, and
        are the draft again."""
        for c in changes:
            self.pending.pop((c.project, c.key), None)
            self.draft[(c.project, c.key)] = c.value
        self.error = "firstmate was not told: %s" % why
        self._widgets()

    def has_pending(self):
        return bool(self.pending)

    # --- the draft ----------------------------------------------------------------

    def changes(self):
        """The draft as Changes, project by project in the registry's order,
        a preset before the single settings that follow it."""
        found = []
        for p in self.read.projects if self.read else []:
            for key in ("preset",) + ORDER:
                if (p.name, key) in self.draft:
                    found.append(Change(p.name, key, self.draft[(p.name, key)]))
        return found

    def staged(self, p, key):
        """The value of key for p once the draft is applied: its own, else
        the one a drafted preset implies, else the file's."""
        if (p.name, key) in self.draft:
            return self.draft[(p.name, key)]
        return self._implied(p).get(key, p.value(key))

    def _implied(self, p):
        return BUNDLES.get(self.draft.get((p.name, "preset"), ""), {})

    def _stage(self, p, key, value):
        """Stage value for key of p, or take it back out of the draft when
        it is what the file (or a drafted preset) has already. A value
        already asked and pending is not staged again."""
        name = (p.name, key)
        if self.pending.get(name, (None,))[0] == value and name not in self.draft:
            return
        self.draft[name] = value
        self._tidy(p)

    def _tidy(self, p):
        """Drop the draft entries that change nothing: the preset p has
        already, a setting equal to what a drafted preset implies (or, with
        none, to the file's)."""
        if (p.name, "preset") in self.draft and self.draft[(p.name, "preset")] == p.value("preset"):
            del self.draft[(p.name, "preset")]
        implied = self._implied(p)
        for key in ORDER:
            if self.draft.get((p.name, key), self) == implied.get(key, p.value(key)):
                del self.draft[(p.name, key)]

    # --- what a touch means ---------------------------------------------------

    def touch(self, widget):
        """A tap on widget of the page last built: (the page changed, the
        Changes to send to firstmate: Validate's, else None)."""
        action = self._actions.get(widget)
        if action is None:
            return False, None
        what, sent = action[0], None
        if what == "stage":
            p = self.read.find(action[1]) if self.read else None
            if p is not None:
                self._stage(p, action[2], action[3])
            self.setting = None
        elif what == "validate":
            sent = self.validate() or None
        elif what == "discard":
            self.draft = {}
        elif what == "open":
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
        return True, sent

    # --- the message ----------------------------------------------------------

    def messages(self):
        return [self.page()]

    def summary(self):
        if self.read is None:
            return "reading firstmate…"
        if self.read.error:
            return "projects unreadable"
        text = "%d project%s" % (len(self.read.projects), "" if len(self.read.projects) == 1 else "s")
        text += " · %d to validate" % len(self.draft) if self.draft else ""
        return text + (" · %d asked" % len(self.pending) if self.pending else "")

    def page(self):
        widgets, rows = self._widgets()
        msg = {"op": "page", "page": PROJECTS_PAGE, "title": "Projects", "icon": icon(PROJECTS_ICON)}
        msg["text"] = clip(self.summary(), MAX_TILE_TEXT)
        waiting = len(self.draft) or len(self.pending)
        msg.update({"tone": "warning" if waiting else "neutral", "columns": COLUMNS, "rows": rows})
        msg["widgets"] = widgets
        if waiting:
            msg["badge"] = clip(str(waiting), MAX_BADGE)
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
            return self._detail(project), ROWS
        return self._values(project, self.setting), VALUE_ROWS

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

    def _said(self, p, entries, lead):
        """What entries (a draft or pending dict) hold for p, in words
        ("draft: Refine, Auto-merge Off"), or None."""
        wanted = [(key, v[0] if isinstance(v, tuple) else v) for (name, key), v in entries.items() if name == p.name]
        words = [
            label(k, v)
            if k in ("preset", "validation", "where", "model", "effort")
            else "%s %s" % (CHOICES[k][0], label(k, v))
            for k, v in wanted
        ]
        return "%s: %s" % (lead, ", ".join(words)) if words else None

    def _note_of(self, p):
        return self._said(p, self.draft, "draft") or self._said(p, self.pending, "asked firstmate")

    def _presets(self, p, col, row):
        """The two preset buttons: the project's own lit, a drafted or asked
        one amber; a tap stages the preset (or takes it back out)."""
        out = []
        for i, (value, words) in enumerate(model.PRESETS):
            own = p.effective_preset() == value and self.draft.get((p.name, "preset")) is None
            wanted = self.staged(p, "preset") == value or self.pending.get((p.name, "preset"), (None,))[0] == value
            tone = "accept" if own else "warning" if wanted else "neutral"
            action = None if own else ("stage", p.name, "preset", value)
            out.append(self._cell("pj.%s.%s" % (_hash(p.name), value[:4]), col + i, row, 1, words, action, tone=tone))
        return out

    def _send_row(self, row, col):
        """Discard and Validate: live while there is a draft."""
        n = len(self.changes())
        discard = ("discard",) if n else None
        validate = ("validate",) if n else None
        text = "send %d change%s to firstmate" % (n, "" if n == 1 else "s") if n else "nothing to send"
        return [
            self._cell(DISCARD, col, row, 1, "Discard", discard, tone="reject" if n else "neutral"),
            self._cell(VALIDATE, col + 1, row, 2, "Validate", validate, text=text, tone="accept" if n else "neutral"),
        ]

    # --- the list ---------------------------------------------------------------

    def _list(self, projects):
        many = len(projects) > PER_PAGE
        self.offset = min(self.offset, (len(projects) - 1) // PER_PAGE * PER_PAGE) // PER_PAGE * PER_PAGE
        out = []
        for row, p in enumerate(projects[self.offset : self.offset + PER_PAGE]):
            open_ = ("open", p.name)
            note = self._note_of(p)
            name = self._cell("pj." + _hash(p.name), 0, row, 3, p.name, open_, text=fit(note or summary(p), NAME_TEXT))
            name["tone"] = "warning" if note else "neutral"
            out += [name] + self._presets(p, 3, row)
            out.append(self._cell("pj.%s.s" % _hash(p.name), 5, row, 1, "Settings", open_))
        if many:
            last = self.offset + PER_PAGE >= len(projects)
            span = "%d-%d of %d" % (self.offset + 1, min(self.offset + PER_PAGE, len(projects)), len(projects))
            out += [
                self._cell(PREVIOUS, 0, PER_PAGE, 1, "Previous", ("page", -PER_PAGE) if self.offset else None),
                self._cell("pj.span", 1, PER_PAGE, 1, span),
                self._cell(NEXT, 2, PER_PAGE, 1, "Next", None if last else ("page", PER_PAGE)),
            ]
        return out + self._send_row(PER_PAGE, 3), ROWS

    # --- a project's settings -------------------------------------------------

    def _detail(self, p):
        title = self.error or self._note_of(p) or summary(p)
        out = [self._cell(BACK, 0, 0, 1, "Back", ("back",), icon=icon(BACK_ICON))]
        tone = "reject" if self.error else "warning" if self._note_of(p) else "neutral"
        out.append(self._cell("pj.title", 1, 0, 3, p.name, text=fit(title, TITLE_TEXT), tone=tone))
        out += self._presets(p, 4, 0)
        for i, key in enumerate(ORDER):
            out.append(self._setting(p, key, 2 * (i % 3), 1 + i // 3))
        n = len(self.changes())
        said = ", ".join("%s %s" % (c.project, label(c.key, c.value)) for c in self.changes())
        draft = self._cell("pj.draft", 0, 3, 3, "%d to validate" % n if n else "No changes", touch=None)
        draft["text"] = fit(said if n else "tap a value to stage it", TITLE_TEXT)
        draft["tone"] = "warning" if n else "neutral"
        return out + [draft] + self._send_row(3, 3)

    def _setting(self, p, key, col, row):
        """One setting's cell: its file value, and what the draft or an
        asked change makes of it."""
        name, now = CHOICES[key][0], p.value(key)
        staged, asked = self.staged(p, key), self.pending.get((p.name, key))
        text = label(key, now) if now is not None else "not set"
        action: tuple | None
        if staged != now or (p.name, key) in self.draft:
            text += " → %s, draft" % label(key, staged)
        elif asked:
            text += " → %s, asked" % label(key, asked[0])
        if key in TOGGLES:
            id = "pj.%s.%s" % (key[:5], "on" if not staged else "off")
            action = None if asked and staged == now else ("stage", p.name, key, not staged)
        else:
            id, action = "pj.%s" % key, ("choose", key)
        tone = "warning" if staged != now or asked else "neutral"
        return self._cell(id, col, row, 2, name, action, text=fit(text, WIDE_TEXT), tone=tone)

    # --- a setting's values ---------------------------------------------------

    def _values(self, p, key):
        name, choices = CHOICES[key]
        now, staged, asked = p.value(key), self.staged(p, key), self.pending.get((p.name, key))
        out = [self._cell(BACK, 0, 0, 1, "Back", ("back",), icon=icon(BACK_ICON))]
        said = "now %s; tap a value to stage it" % (label(key, now) if now is not None else "not set")
        out.append(self._cell("pj.title", 1, 0, 5, "%s · %s" % (p.name, name), text=fit(said, TITLE_TEXT)))
        for i, (value, words) in enumerate(choices):
            own = value == now and staged == now
            wanted = (staged == value and not own) or (asked is not None and asked[0] == value)
            tone = "accept" if own else "warning" if wanted else "neutral"
            action = (
                None
                if own or (asked is not None and asked[0] == value and staged == now)
                else ("stage", p.name, key, value)
            )
            out.append(self._cell("pj.v.%s" % str(value).lower(), 2 * (i % 3), 1 + i // 3, 2, words, action, tone=tone))
        return out
