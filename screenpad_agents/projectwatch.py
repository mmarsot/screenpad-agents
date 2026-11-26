"""The Projects page's thread: firstmate's two files read, and its notes sent.

Off the loop, so a touch is handled at once:

  - it reads <home>/data/projects.md and data/project-settings.toml
    (projectmodel.read: two small files, read-only) every PROJECTS_POLL
    seconds, every PENDING_POLL while a change the captain asked for is not
    yet in them, and not at all while the touch bar is not connected;
  - it sends the captain's request for a change to firstmate, with one note
    through its capture surface (Firstmate.note: fm-inbox.sh note --json
    --request-id <id> -- <text>, one wake), and then reads sooner.

It never writes those files: firstmate applies a request and records it
(docs/projects.md), and the page shows the change pending until a read
reflects it.
"""

import queue
import secrets
import time

from . import projectmodel as model
from .common import PENDING_POLL, PROJECTS_POLL
from .common import why as _why
from .firstmate import FirstmateError


def request_id():
    """A new id for one request, as fm-inbox.sh note --request-id takes it:
    each tap is its own note."""
    return "screenpad-project-%d-%s" % (time.time(), secrets.token_hex(4))


class ProjectsWatch:
    def __init__(self, home, firstmate, post, clock=time.monotonic, reader=model.read):
        self.home, self.firstmate, self.post, self.clock, self.reader = home, firstmate, post, clock, reader
        self._jobs: queue.Queue = queue.Queue()
        self._showing = False
        self._pending = False

    # --- the thread ----------------------------------------------------------

    def worker(self):
        showing, pending, due = False, False, 0.0
        while True:
            try:
                job = self._jobs.get(timeout=max(0.0, due - self.clock()) if showing else None)
            except queue.Empty:
                job = ("tick",)
            if job is None:
                return
            if job[0] == "showing":
                showing = job[1]
                due = 0.0 if showing else due
            elif job[0] == "pending":
                pending = job[1]
            elif job[0] == "note":
                self._note(*job[1:])
                due = min(due, self.clock() + PENDING_POLL)
            if not showing or self.clock() < due:
                continue
            self._read()
            due = self.clock() + (PENDING_POLL if pending else PROJECTS_POLL)

    def _read(self):
        try:
            self.post("projects", self.reader(self.home))
        except Exception as e:
            self.post("projects", model.Read(error=_why(e, OSError)))

    def _note(self, change, rid):
        try:
            if self.firstmate.note(rid, change.text()) is None:
                raise FirstmateError("fm-inbox.sh says the request was handled already")
        except Exception as e:
            self.post("project-note", change, _why(e, FirstmateError))
        else:
            self.post("project-note", change, None)

    # --- on the loop ---------------------------------------------------------

    def showing(self, connected):
        if connected != self._showing:
            self._showing = connected
            self._jobs.put(("showing", connected))

    def pending(self, pending):
        """Whether a change is waiting to show in the files: read sooner."""
        if pending != self._pending:
            self._pending = pending
            self._jobs.put(("pending", pending))

    def send(self, change):
        """Ask firstmate for change, in a note of its own."""
        self._jobs.put(("note", change, request_id()))

    def stop(self):
        self._jobs.put(None)
