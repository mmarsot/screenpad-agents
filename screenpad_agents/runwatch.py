"""The Runs page's thread, and what the loop does for it.

The thread reads no-mistakes (nomistakes.py) off the loop and hands each
Scan to it through the app's queue:

- which repo directories: [runs] repos, then, with [runs] firstmate,
  firstmate's registered clones (the directories in <home>/projects) and the
  worktrees firstmate records for its live tasks; no-mistakes' "repo:" for
  each names the project, so a clone and its worktrees are one project;
- in each of those and in each Herdr agent's cwd, the current branch and its
  run (axi status), which joins a run to its repo copy;
- each active run in detail (axi status --run), to tell a run waiting on a
  decision from one working; and, while a run's card is open, that run and
  its steps' findings (axi rounds).

It reads every [runs] poll seconds while a run is active, every [runs] idle
seconds while none is, at once when a card opens, and not at all while the
touch bar is not connected (nothing would show it). The loop tells it the
copies to look in when Herdr's agents or firstmate's tasks change.
"""

import os
import queue
import time

from . import runs as model
from .common import why
from .nomistakes import NoMistakesError, NotARepo
from .runcard import BACK, FOCUS

# A card's findings: the steps' rounds read at most.
MAX_STEPS_READ = 4


class RunsWatch:
    def __init__(self, settings, client, home, post, clock=time.monotonic):
        self.settings, self.client, self.home, self.post, self.clock = settings, client, home, post, clock
        self.board = model.Runs()
        self._jobs: queue.Queue = queue.Queue()
        self._places = None
        self._showing = False

    # --- the thread ----------------------------------------------------------

    def worker(self):
        places, watching, showing, due, last = ((), ()), None, False, 0.0, None
        while True:
            try:
                job = self._jobs.get(timeout=max(0.0, due - self.clock()) if showing else None)
            except queue.Empty:
                job = ("tick",)
            if job is None:
                return
            if job[0] == "places":
                # New copies are looked at within a poll, even when idle.
                places = job[1]
                due = min(due, (last or 0.0) + self.settings.poll)
            elif job[0] == "showing":
                showing = job[1]
                due = 0.0 if showing else due
            elif job[0] == "watch":
                watching = job[1]
                if watching is not None and showing:
                    self._read_card(watching)
            if not showing or self.clock() < due:
                continue
            active = False
            try:
                scan = self.scan(*places)
                active = scan.active()
                self.post("runs", scan, None)
            except Exception as e:
                self.post("runs", None, why(e, NoMistakesError))
            if watching is not None:
                self._read_card(watching)
            last = self.clock()
            due = last + (self.settings.poll if active else self.settings.idle)

    def _read_card(self, run_id):
        try:
            detail = self.client.detail(run_id)
            for step in [s for s in detail.steps if s.findings][:MAX_STEPS_READ]:
                detail.findings += [(step.name, fid, sev) for fid, sev in self.client.findings(run_id, step.name)]
            self.post("run", run_id, detail, None)
        except Exception as e:
            self.post("run", run_id, None, why(e, NoMistakesError))

    def scan(self, worktrees=(), cwds=()):
        """One read of every project and copy: a runs.Scan;
        NoMistakesError when no project could be read at all."""
        configured = list(self.settings.repos)
        worktrees = list(worktrees) if self.settings.firstmate else []
        dirs = configured + self._clones() + worktrees
        projects: dict = {}
        seen, errors = set(), []
        for d in dirs:
            real = os.path.realpath(d)
            if real in seen:
                continue
            seen.add(real)
            try:
                repo, listed = self.client.listing(d)
            except NoMistakesError as e:
                if not isinstance(e, NotARepo):
                    errors.append(str(e))
                if d in configured:
                    projects.setdefault(real, model.Project(real, error=str(e)))
                continue
            projects.setdefault(repo, model.Project(repo, listed))
        if errors and not any(p.error is None for p in projects.values()):
            raise NoMistakesError(errors[0])
        copies, looked = [], set()
        for d in configured + worktrees + list(cwds):
            real = os.path.realpath(d)
            if real in looked:
                continue
            looked.add(real)
            try:
                branch, run_id = self.client.current(d)
            except NoMistakesError:
                continue
            if run_id is not None:
                copies.append(model.Copy(real, branch, run_id))
        details = {}
        for p in projects.values():
            for r in p.runs:
                if r.active:
                    try:
                        details[r.id] = self.client.detail(r.id)
                    except NoMistakesError:
                        pass
        return model.Scan(projects.values(), copies, details)

    def _clones(self):
        """firstmate's registered clones: the directories in <home>/projects."""
        if not self.settings.firstmate or not self.home:
            return []
        root = os.path.join(self.home, "projects")
        try:
            names = sorted(os.listdir(root))
        except OSError:
            return []
        return [os.path.join(root, n) for n in names if not n.startswith(".") and os.path.isdir(os.path.join(root, n))]

    # --- on the loop ---------------------------------------------------------

    def places(self, fleet):
        """(the live tasks' worktrees, the Herdr agents' cwds): the copies
        scan looks in besides the projects."""
        worktrees = ()
        if self.settings.firstmate and fleet.bearings is not None:
            worktrees = tuple(sorted(set(fleet.bearings.worktrees.values())))
        cwds = tuple(sorted({a.cwd for a in fleet.agents or [] if a.cwd and os.path.isabs(a.cwd)}))
        return worktrees, cwds

    def update(self, fleet):
        """Tell the thread the copies to look in, when they changed."""
        places = self.places(fleet)
        if places != self._places:
            self._places = places
            self._jobs.put(("places", places))

    def showing(self, connected):
        if connected != self._showing:
            self._showing = connected
            self._jobs.put(("showing", connected))

    def result(self, what, *rest):
        """Take one of the thread's results in; True: the page changed."""
        if what == "runs":
            had = self.board.card
            self.board.set_scan(*rest)
            if had is not None and self.board.card is None:
                self._jobs.put(("watch", None))
        else:
            self.board.set_detail(*rest)
        return True

    def touch(self, widget, touch, fleet):
        """A touch on the Runs page: (the page changed, a pane to focus)."""
        if touch != "tap":
            return False, None
        board = self.board
        if board.card is not None:
            if widget == BACK:
                board.close_card()
                self._jobs.put(("watch", None))
                return True, None
            return False, board.card_pane(fleet) if widget == FOCUS else None
        run_id = board.run_of(widget)
        if run_id is not None and board.open_card(run_id) is not None:
            self._jobs.put(("watch", run_id))
            return True, None
        return False, None

    def stop(self):
        self._jobs.put(None)
