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

It also opens a run's pull request, on Open PR on the run's card: the URL
no-mistakes gave (runs.View.pr_url), with the desktop's URL handler in a
scope of its own (desktop.py), the one command here that acts; it reads
nothing more for it.

With [runs] watch_command, Watch on a run's card starts that command with the
run's id (a Watch window of the run's steps), detached like the review
command (desktop.launch): never waited for beyond its grace, its input and
output to /dev/null, and it reads nothing of no-mistakes itself from here.

With [[runs.remote]] machines (remotewatch.py), each read in a thread of its
own, this thread also forwards the card's run to the machine it is on (and
starts Watch there through that machine's terminal command), and merges
what they post ("remote") into the page.
"""

import os
import queue
import time

from . import desktop
from . import runs as model
from .common import RUN_PLACEHOLDER, why
from .nomistakes import RUN_ID, NoMistakesError
from .runcard import BACK, FOCUS, PR, WATCH
from .runscan import read

# A card's findings: the steps' rounds read at most.
MAX_STEPS_READ = 4


def open_pr(url):
    """Open a pull request's URL in the browser on the main screen."""
    desktop.open_url(url, "opening the PR")


def start_watch(argv):
    """Start the watch command argv, detached, in a scope of its own."""
    desktop.launch(argv, "the watch command")


class RunsWatch:
    def __init__(
        self, settings, client, home, post, clock=time.monotonic, opener=open_pr, launcher=start_watch, remotes=None
    ):
        self.settings, self.client, self.home, self.post, self.clock = settings, client, home, post, clock
        self.opener, self.launcher = opener, launcher
        self.remotes = dict(remotes or {})  # the remote machines' threads, by name (remotewatch.py)
        can = {n for n, r in self.remotes.items() if r.can_watch}
        self.board = model.Runs(bool(settings.watch), list(self.remotes), can)
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
            elif job[0] == "open":
                self._open(*job[1:])
            elif job[0] == "launch":
                self._launch(*job[1:])
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

    def _open(self, run_id, url):
        try:
            self.opener(url)
        except Exception as e:
            self.post("opened", run_id, url, why(e, desktop.DesktopError))
        else:
            self.post("opened", run_id, url, None)

    def _launch(self, run_id, argv):
        try:
            self.launcher(argv)
        except Exception as e:
            self.post("launched", run_id, why(e, desktop.DesktopError))
        else:
            self.post("launched", run_id, None)

    def scan(self, worktrees=(), cwds=()):
        """One read of every project and copy of this machine: a
        runs.Scan; NoMistakesError when no project could be read at all."""
        worktrees = worktrees if self.settings.firstmate else ()
        return read(self.client, self.settings.repos, self._clones(), worktrees, cwds)

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
            for remote in self.remotes.values():
                remote.showing(connected)

    def _watch_card(self, run_id):
        """Tell the thread of the machine run_id is on to read it (and every
        other thread to read no card); None: none."""
        machine = self.board.machine_of(run_id) if run_id else None
        self._jobs.put(("watch", run_id if run_id and machine is None else None))
        for name, remote in self.remotes.items():
            remote.watch(run_id if run_id and machine == name else None)

    def result(self, what, *rest):
        """Take one of the thread's results in; True: the page changed."""
        if what == "runs":
            had = self.board.card
            self.board.set_scan(*rest)
            if had is not None and self.board.card is None:
                self._watch_card(None)
        elif what == "remote":
            had = self.board.card
            self.board.set_remote(*rest)
            if had is not None and self.board.card is None:
                self._watch_card(None)
        elif what == "opened":
            self.board.set_opened(*rest)
        elif what == "launched":
            self.board.set_launched(*rest)
        else:
            self.board.set_detail(*rest)
        return True

    def touch(self, widget, touch, fleet):
        """A touch on the Runs page: (the page changed, a pane to focus).
        A tap on a run opens its card; Open PR on the card opens its pull
        request."""
        if touch != "tap":
            return False, None
        board = self.board
        if board.card is not None:
            if widget == BACK:
                board.close_card()
                self._watch_card(None)
                return True, None
            if widget == PR:
                return self._open_pr(fleet), None
            if widget == WATCH:
                return self._watch(), None
            return False, board.card_pane(fleet) if widget == FOCUS else None
        run_id = board.run_of(widget)
        if run_id is not None and board.open_card(run_id) is not None:
            self._watch_card(run_id)
            return True, None
        return False, None

    def _watch(self):
        """Start the watch command for the open card's run, unless it is
        being started: True when the card changed. The id goes into the
        command only when it is a run id as no-mistakes prints it."""
        card = self.board.card
        if card is None or not RUN_ID.fullmatch(card.run_id):
            return False
        remote = self.remotes.get(self.board.machine_of(card.run_id) or "")
        command = remote.can_watch if remote is not None else self.settings.watch
        if not command or not card.start_watch():
            return False
        try:
            argv = remote.watch_argv(card.run_id) if remote is not None else None
        except desktop.DesktopError as e:
            card.watch_ended(str(e))
            return True
        if remote is None:
            argv = [w.replace(RUN_PLACEHOLDER, card.run_id) for w in self.settings.watch]
        self._jobs.put(("launch", card.run_id, argv))
        return True

    def _open_pr(self, fleet):
        """Open the open card's pull request, unless an open is on its way:
        True when the card changed."""
        card = self.board.card
        if card is None:
            return False
        url = self.board.pr_of(fleet, card.run_id)
        if url is None or not card.open_pr(url):
            return False
        self._jobs.put(("open", card.run_id, url))
        return True

    def stop(self):
        self._jobs.put(None)
        for remote in self.remotes.values():
            remote.stop()
