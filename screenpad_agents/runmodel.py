"""The Runs page's data: the projects read, the repo copies, a scan of both,
and a run as the page shows it (View). Plain data and what it says of itself;
runs.py joins it and builds the page."""

import hashlib
import os

from screenpad_app.common import ID as WIDGET_ID

from .firstmate import HEAD, Review
from .nomistakes import pr_url

# A run that ended without failing, its pull request waiting for the captain.
READY = ("completed", "checks_passed", "passed")


class Project:
    """A repository no-mistakes watches (repo, as it names it), its newest
    runs, or why it could not be read; machine is the remote machine it is
    on (None: this one), whose repo paths are its own: key tells projects
    of two machines apart."""

    __slots__ = ("error", "key", "machine", "name", "repo", "runs")

    def __init__(self, repo, runs=(), error=None, name=None, machine=None):
        self.repo, self.runs, self.error, self.machine = repo, list(runs), error, machine
        self.key = "%s:%s" % (machine, repo) if machine else repo
        self.name = name or os.path.basename(repo.rstrip("/")) or repo

    def __eq__(self, other):
        return isinstance(other, Project) and self._key() == other._key()

    def __hash__(self):
        return hash(self.key)

    def _key(self):
        return (self.key, tuple(self.runs), self.error, self.name)


class Copy:
    """A repo copy (a real path): its current branch and that branch's run.
    One on a remote machine (machine) also has its firstmate task there,
    which the machine's own firstmate gave (task)."""

    __slots__ = ("branch", "machine", "path", "run_id", "task")

    def __init__(self, path, branch, run_id, machine=None, task=None):
        self.path, self.branch, self.run_id, self.machine, self.task = path, branch, run_id, machine, task

    def _key(self):
        return (self.path, self.branch, self.run_id, self.machine, self.task)

    def __eq__(self, other):
        return isinstance(other, Copy) and self._key() == other._key()

    def __hash__(self):
        return hash((self.machine, self.path))


class Scan:
    """One read: the projects in order, the copies, the active runs' details."""

    __slots__ = ("copies", "details", "projects")

    def __init__(self, projects=(), copies=(), details=None):
        self.projects, self.copies, self.details = list(projects), list(copies), dict(details or {})

    def __eq__(self, other):
        return isinstance(other, Scan) and (self.projects, self.copies, self.details) == (
            other.projects,
            other.copies,
            other.details,
        )

    def __hash__(self):
        return hash(len(self.projects))

    def active(self):
        return any(r.active for p in self.projects for r in p.runs)


class View:
    """A run as the page shows it: its project, its detail when read, the
    copies of its branch, its agent's pane and its task, and whether it
    needs you or is one of several active runs for one agent, copy or branch."""

    __slots__ = (
        "attention",
        "copies",
        "detail",
        "duplicate",
        "machine",
        "newest",
        "pane",
        "project",
        "run",
        "task",
    )

    def __init__(self, run, project, detail, machine=None):
        self.run, self.project, self.detail = run, project, detail
        self.machine = machine  # the machine's label, when the page labels them
        self.copies: list = []
        self.pane = self.task = None
        self.attention = self.duplicate = self.newest = False

    def name(self):
        return self.task or self.run.branch

    def phrase(self):
        """What the run is doing, in a few words."""
        d, run = self.detail, self.run
        step = d.step() if d is not None else None
        if run.active and d is not None and d.waiting:
            words = ["waiting on you"]
        elif run.active:
            words = [step.status if step is not None and step.status != "running" else "running"]
        else:
            words = [{"completed": "passed", "checks_passed": "checks passed"}.get(run.status, run.status)]
        if step is not None and (run.active or run.status == "failed"):
            words.append(step.name)
        number = run.pr.rstrip("/").rpartition("/")[2] if run.pr else ""
        if number.isdigit():
            words.append("PR #" + number)
        return " · ".join(words)

    def said(self):
        """phrase, led by the machine's label when the page has them."""
        return "%s · %s" % (self.machine, self.phrase()) if self.machine else self.phrase()

    def remote(self):
        """The remote machine the run is on, or None for this one."""
        return self.project.machine

    def pr_url(self, detail=None):
        """The URL of the run's pull request to open: what no-mistakes gives
        (detail's, the view's own detail's, else the run list's), and only a
        pull request's on the forge (nomistakes.pr_url); None otherwise."""
        detail = detail or self.detail
        return pr_url(detail.pr if detail is not None and detail.pr else self.run.pr)

    def review(self):
        """The change this run leaves ready for review: its task, its head
        and its pull request; None unless it is the newest run of its
        branch, ended without failing, with a pull request on the forge, in
        a task's copy on this machine (a remote machine's task is not one of
        this firstmate's)."""
        run, url = self.run, self.pr_url()
        if self.remote() or self.task is None or not self.newest or run.status not in READY or url is None:
            return None
        return Review(self.task, run.head if run.head and HEAD.fullmatch(run.head) else None, url)

    def tone(self):
        if self.attention:
            return "reject" if self.run.status == "failed" else "warning"
        return "accept" if self.run.active else "neutral"


def widget_id(prefix, key):
    wid = prefix + key
    return wid if WIDGET_ID.fullmatch(wid) else prefix + "h" + hashlib.sha256(key.encode()).hexdigest()[:20]
