"""The Runs page: no-mistakes' runs per project, each joined to its agent
and firstmate task, and the runs tile.

Pure: it turns the last Scan (what runwatch.py read from no-mistakes) and
what the Agents page knows (fleet.py: Herdr's agents and firstmate's tasks)
into the "page" and "set" messages, and says what a touch means. One row per
project: the project's widget, then its active runs and its recent ones. A
run is joined to the repo copies whose own run (the one no-mistakes resolves
there) is of the run's branch, a copy to the Herdr agent whose cwd it is
and to the firstmate task whose worktree it is. More than one active run
for one agent, one repo copy or one branch is the warning: its project's
widget turns red. Tapping a run opens its card (runcard.py) in place of the
grid. Nothing here acts on a run.

A run whose pull request is ready for the captain (its newest run of the
branch, ended without failing, with a pull request on the forge, and joined
to a firstmate task) is a change ready for review: its card gets the same
Review, Approve and Request changes buttons as Captain's Call (View.review,
reviewcall.py), and Watch, which opens a live view of the run, when [runs]
watch_command is set.
"""

import hashlib
import os

from screenpad_app import clip
from screenpad_app.common import MAX_BADGE, MAX_LABEL, MAX_ROWS, MAX_TEXT, MAX_TILE_TEXT

from . import runcard
from .common import LIGHTHOUSE, RUNS_PAGE, RUNS_TILE, icon
from .runmodel import READY as READY
from .runmodel import Copy as Copy
from .runmodel import Project as Project
from .runmodel import Scan as Scan
from .runmodel import View as View
from .runmodel import widget_id as widget_id

COLUMNS = 5
MIN_ROWS = 2
RUN_CELLS = COLUMNS - 1


class Runs:
    """What the Runs page last knew: the Scan (or why there is none), and
    the run whose card is open. With remote machines (machines: their
    names; local: this one's) the scan is this machine's and theirs
    together, every run labelled with its machine, and a machine that could
    not be read is a notice in place of its projects (down, why)."""

    def __init__(self, watch=False, machines=(), local="laptop", can_watch=()):
        self.watch = watch  # [runs] watch_command is set: cards get Watch
        self.machines, self.local, self.can_watch = list(machines), local, set(can_watch)
        self.scan = None
        self.error = None
        self.card = None
        self.down: dict = {}
        self._mine: Scan | None = None
        self._theirs: dict = {}
        self._runs: dict = {}
        self._real: dict = {}

    def set_scan(self, scan, error=None):
        """This machine's read (or why it failed: its last read stays)."""
        if error:
            self.error = error
            return
        self._mine, self.error = scan, None
        self._merge()

    def set_remote(self, name, scan, error=None):
        """A remote machine's read, or why it could not be reached: then its
        runs are gone from the page, and a notice says so."""
        if error:
            self._theirs.pop(name, None)
            self.down[name] = error
        else:
            self._theirs[name] = scan
            self.down.pop(name, None)
        self._merge()

    def _merge(self):
        """scan: this machine's read and every remote's, in order."""
        scans = ([self._mine] if self._mine is not None else []) + [
            self._theirs[n] for n in self.machines if n in self._theirs
        ]
        if len(scans) <= 1:
            self.scan = scans[0] if scans else None
        else:
            self.scan = Scan(
                [p for sc in scans for p in sc.projects],
                [c for sc in scans for c in sc.copies],
                {k: d for sc in scans for k, d in sc.details.items()},
            )
        if self.card is not None and self.find(self.card.run_id) is None:
            self.card = None

    def machine_of(self, run_id):
        """The remote machine run_id is on, None for this one."""
        found = self.find(run_id)
        return found[0].machine if found is not None else None

    def label(self, project):
        """What the page calls the machine of project: nothing until there
        are remote machines."""
        return (project.machine or self.local) if self.machines else None

    def find(self, run_id):
        for p in self.scan.projects if self.scan else []:
            for r in p.runs:
                if r.id == run_id:
                    return p, r
        return None

    # --- the joins -----------------------------------------------------------

    def views(self, fleet):
        """{repo: [View]} for every run listed, joined."""
        if self.scan is None:
            return {}
        copies = self._copies(fleet)
        out: dict = {}
        keys: dict = {}
        for p in self.scan.projects:
            views = out[p.key] = []
            newest = set()
            for r in p.runs:
                v = View(r, p, self.scan.details.get(r.id), self.label(p))
                v.copies = [c for c in copies if c[3:] == (p.key, r.branch)]
                v.pane = next((c[1] for c in v.copies if c[1]), None)
                v.task = next((c[2] for c in v.copies if c[2]), None)
                first = v.newest = r.branch not in newest
                newest.add(r.branch)
                v.attention = r.active and v.detail is not None and v.detail.waiting
                v.attention = v.attention or (first and r.status == "failed")
                views.append(v)
                if r.active:
                    for key in self._keys(p, v):
                        keys.setdefault(key, []).append(v)
        for same in keys.values():
            if len(same) > 1:
                for v in same:
                    v.duplicate = True
        return out

    def _keys(self, project, view):
        keys: set[tuple] = {("branch", project.key, view.run.branch)}
        keys |= {("copy", c[0].machine, c[0].path) for c in view.copies}
        if view.pane:
            keys.add(("pane", view.pane))
        return keys

    def _copies(self, fleet):
        """[(Copy, its agent's pane, its task id, project key, branch)] for the
        copies whose run is listed: repo and branch are that run's (a copy
        on a detached HEAD or an older no-mistakes names no branch itself)."""
        tasks, panes = {}, {}
        bearings = fleet.bearings
        if bearings is not None:
            for target, task in bearings.tasks.items():
                session, _, pane = target.partition(":")
                if session == fleet.session:
                    panes[task.id] = pane
            tasks = {self._realpath(path): tid for tid, path in bearings.worktrees.items()}
        agents = {self._realpath(a.cwd): a for a in fleet.agents or [] if a.cwd}
        out = []
        for c in self.scan.copies if self.scan else []:
            found = self.find(c.run_id) if c.run_id else None
            if found is None:
                continue
            if c.machine:  # a remote machine's copy: its task, and none of this machine's agents
                out.append((c, None, c.task, found[0].key, found[1].branch))
                continue
            task, agent = tasks.get(c.path), agents.get(c.path)
            pane = agent.pane if agent is not None else panes.get(task) if task else None
            if task is None and agent is not None:
                agent_task = fleet.task(agent)
                task = agent_task.id if agent_task else None
            out.append((c, pane, task, found[0].key, found[1].branch))
        return out

    def _realpath(self, path):
        if path not in self._real:
            if len(self._real) > 512:
                self._real.clear()
            self._real[path] = os.path.realpath(path)
        return self._real[path]

    # --- counts and touches --------------------------------------------------

    def counts(self, views):
        every = [v for vs in views.values() for v in vs]
        active = sum(v.run.active for v in every)
        return active, sum(v.attention for v in every), sum(v.duplicate for v in every)

    def run_of(self, widget):
        """The run id a run widget of the page last built stands for."""
        return self._runs.get(widget)

    def open_card(self, run_id):
        self.card = runcard.RunCard(run_id) if self.find(run_id) is not None else None
        return self.card

    def close_card(self):
        self.card = None

    def set_detail(self, run_id, detail, error=None):
        """A fresh read of the open card's run; ignored for any other run."""
        if self.card is not None and self.card.run_id == run_id:
            self.card.detail, self.card.error = (self.card.detail, error) if error else (detail, None)

    def set_opened(self, run_id, url, error=None):
        """The open of the open card's pull request ended; ignored for any
        other run."""
        if self.card is not None and self.card.run_id == run_id:
            self.card.pr_opened(url, error)

    def pr_of(self, fleet, run_id):
        """The pull request URL of run_id to open (View.pr_url), with the
        open card's own detail when it is that run's."""
        view = self._view(fleet, run_id)
        if view is None:
            return None
        card = self.card
        return view.pr_url(card.detail if card is not None and card.run_id == run_id else None)

    def card_review(self, fleet):
        """The change ready for review the open card's run leaves, if any."""
        view = self._view(fleet, self.card.run_id) if self.card is not None else None
        return view.review() if view is not None else None

    def ready_reviews(self, fleet):
        """Every change ready for review a run listed leaves (View.review):
        the ones whose entries a firstmate read keeps, open card or not."""
        return [r for vs in self.views(fleet).values() for v in vs if (r := v.review()) is not None]

    def pane_review(self, fleet, pane):
        """The change ready for review that a run of the agent in pane
        leaves, if any: what focusing that agent opens instead of its
        terminal once it is done."""
        for vs in self.views(fleet).values():
            for v in vs:
                if v.pane == pane and v.review() is not None:
                    return v.review()
        return None

    def set_launched(self, run_id, error=None):
        """The watch command of the open card's run started or failed;
        ignored for any other run."""
        if self.card is not None and self.card.run_id == run_id:
            self.card.watch_ended(error)

    def card_pane(self, fleet):
        """The pane of the agent of the open card's run, if any."""
        if self.card is None:
            return None
        view = self._view(fleet, self.card.run_id)
        return view.pane if view is not None else None

    def first_attention_pane(self, fleet):
        views = self.views(fleet)
        return next((v.pane for vs in views.values() for v in vs if v.attention and v.pane), None)

    def _view(self, fleet, run_id):
        return next((v for vs in self.views(fleet).values() for v in vs if v.run.id == run_id), None)

    # --- the messages --------------------------------------------------------

    def messages(self, fleet):
        views = self.views(fleet)
        return [self.page(fleet, views), self.tile(views)]

    def summary(self, views):
        if self.scan is None:
            if self.down:
                return " · ".join("%s unreachable" % n for n in self.down)
            return "no-mistakes unavailable" if self.error else "reading no-mistakes…"
        active, attention, duplicate = self.counts(views)
        parts = ["%d active" % active if active else "no active run"]
        if attention:
            parts.append("%d need%s you" % (attention, "s" if attention == 1 else ""))
        if duplicate:
            parts.append("%d on one agent" % duplicate)
        return " · ".join(parts + ["%s unreachable" % n for n in self.down])

    def tone(self, views):
        active, attention, duplicate = self.counts(views)
        if duplicate:
            return "reject"
        return "warning" if attention or self.down else "accept" if active else "neutral"

    def tile(self, views):
        active, attention, _ = self.counts(views)
        msg = {"op": "set", "tile": RUNS_TILE, "label": "Runs", "tone": self.tone(views)}
        if self.error:
            msg["text"] = "no-mistakes unavailable"
        elif self.scan is not None or self.down:
            text = "%d active" % active if active else "none active"
            if attention:
                text += " · %d need%s you" % (attention, "s" if attention == 1 else "")
            text = " · ".join([text] + ["%s unreachable" % n for n in self.down])
            msg["text"] = clip(text, MAX_TILE_TEXT)
            msg["icon"] = icon(LIGHTHOUSE)
        if attention:
            msg["badge"] = clip(str(attention), MAX_BADGE)
        return msg

    def page(self, fleet, views):
        _, attention, _ = self.counts(views)
        card = self.card
        found = self.find(card.run_id) if card is not None else None
        if card is not None and found is not None:
            self._runs = {}
            view = next(v for v in views[found[0].key] if v.run.id == card.run_id)
            watch = view.remote() in self.can_watch if view.remote() else self.watch
            widgets = card.widgets(view, self._review_of(fleet, view), watch)
            columns, rows = runcard.COLUMNS, runcard.ROWS
        else:
            widgets, rows = self._grid(views)
            columns = COLUMNS
        msg = {"op": "page", "page": RUNS_PAGE, "title": "Runs", "icon": icon(LIGHTHOUSE)}
        msg["text"] = clip(self.summary(views), MAX_TILE_TEXT)
        msg.update({"tone": self.tone(views), "columns": columns, "rows": rows, "widgets": widgets})
        if attention:
            msg["badge"] = clip(str(attention), MAX_BADGE)
        return msg

    def _review_of(self, fleet, view):
        """(review, its entry, can_open) for the card's buttons, or None."""
        review, reviews = view.review(), getattr(fleet, "reviews", None)
        if review is None or reviews is None or not (reviews.can_open or review.head):
            return None
        return review, reviews.entry(review), reviews.can_open

    def _grid(self, views):
        self._runs = {}
        projects = self.scan.projects if self.scan else []
        # A machine that could not be read comes first, a row of its own.
        top = [self._unreachable(row, name, why) for row, (name, why) in enumerate(self.down.items())]
        if not projects and not top:
            return [self._note()], MIN_ROWS
        room = MAX_ROWS - len(top)
        if len(projects) > room:
            # The projects with runs going (or needing you) first.
            busy = {p.key for p in projects if any(v.run.active or v.attention for v in views[p.key])}
            projects = sorted(projects, key=lambda p: p.key not in busy)
            hidden = len(projects) - room + 1
            projects = projects[: room - 1]
        else:
            hidden = 0
        cells = [c for row in top for c in row]
        for row, p in enumerate(projects, start=len(top)):
            cells += self._row(row, p, views[p.key])
        used = len(top) + len(projects)
        rows = max(MIN_ROWS, used + (1 if hidden else 0))
        if hidden:
            more = {"id": "runs.more", "col": 0, "row": used, "cols": COLUMNS, "touch": "none"}
            cells.append(dict(more, label="+%d more projects" % hidden))
        return cells, rows

    def _unreachable(self, row, name, why):
        """The row that says a remote machine could not be read, and why:
        its runs are not on the page, so it never looks like it has none."""
        cell = {"id": widget_id("runs.down.", name), "col": 0, "row": row, "cols": COLUMNS, "touch": "none"}
        return [dict(cell, label=clip("%s unreachable" % name, MAX_LABEL), text=clip(why, MAX_TEXT), tone="reject")]

    def _row(self, row, project, views):
        head = {"id": widget_id("proj.", hashlib.sha256(project.key.encode()).hexdigest()[:16]), "touch": "none"}
        head.update({"col": 0, "row": row, "label": clip(project.name, MAX_LABEL)})
        active = [v for v in views if v.run.active]
        if len(active) > RUN_CELLS:
            shown, more = active[: RUN_CELLS - 1], len(active) - RUN_CELLS + 1
        else:
            # Then the recent ones, the newest of each branch not shown yet.
            shown, more = list(active), 0
            branches = {v.run.branch for v in shown}
            for v in views:
                if len(shown) < RUN_CELLS and not v.run.active and v.run.branch not in branches:
                    shown.append(v)
                    branches.add(v.run.branch)
        doubled = [v for v in active if v.duplicate]
        if project.error:
            head.update({"text": clip(project.error, MAX_TEXT), "tone": "warning"})
        elif doubled:
            head.update({"tone": "reject", "badge": clip(str(len(doubled)), MAX_BADGE)})
            head["text"] = clip("%d active runs for %s: at most one each" % (len(doubled), doubled[0].name()), MAX_TEXT)
        else:
            attention = sum(v.attention for v in views)
            parts = ["%d active" % len(active) if active else "no active run"]
            parts += ["%d need%s you" % (attention, "s" if attention == 1 else "")] if attention else []
            parts += [] if views else ["no runs yet"]
            parts = [self.label(project)] + parts if self.machines else parts
            head.update({"text": " · ".join(parts), "tone": "warning" if attention else "neutral"})
        cells = [head]
        for col, v in enumerate(shown, start=1):
            wid = widget_id("run.", v.run.id)
            self._runs[wid] = v.run.id
            cell = {"id": wid, "col": col, "row": row, "label": clip(v.name(), MAX_LABEL), "tone": v.tone()}
            cell["text"] = clip(v.said(), MAX_TEXT)
            if v.duplicate:
                cell["badge"] = "2+"
            cells.append(cell)
        if more:
            cells.append({"id": widget_id("runs.more.", head["id"][5:]), "col": COLUMNS - 1, "row": row})
            cells[-1].update({"label": "+%d active" % more, "touch": "none"})
        return cells

    def _note(self):
        return dict(self._note_look(), col=0, row=0, cols=COLUMNS)

    def _note_look(self):
        if self.error:
            note = {"id": "runs.note", "label": "no-mistakes unavailable", "text": clip(self.error, MAX_TEXT)}
            return dict(note, touch="none")
        if self.scan is None:
            return {"id": "runs.note", "label": "Reading no-mistakes…", "touch": "none"}
        return {
            "id": "runs.note",
            "label": "No projects",
            "text": "no-mistakes watches none of the repos configured or found",
            "touch": "none",
        }
