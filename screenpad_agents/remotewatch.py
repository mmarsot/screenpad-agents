"""A remote machine's part of the Runs page: one thread per [[runs.remote]].

Each thread reads its machine over ssh (ssh.py) off every other thread, so a
slow or dead machine delays nothing here: it reads the machine's projects
and runs the way runwatch.py reads this one (runscan.py), hands each Scan
(or why there is none: "unreachable" when ssh cannot connect,
"no-mistakes unavailable" when the machine answered but no-mistakes failed) to the app's queue as a "remote"
result, and, while a run of that machine has its card open, that run in
detail (and its steps' findings), like the local thread.

It polls no more often than this machine's reads: every [runs] poll seconds
while one of its runs is active, every [runs] idle seconds otherwise, and
not at all while the touch bar is disconnected. The machine's firstmate is
asked for its task worktrees at most every [firstmate] poll default (60 s),
and its projects directory is listed with each read.

Watch on one of its runs opens a window of a terminal here (the remote's
terminal words) running ssh to the machine and, there, the configured
viewer, sent over the connection with the run's id: nothing is installed or
changed on the machine, and the viewer only reads.
"""

import base64
import os
import queue
import shlex
import subprocess
import time

from . import desktop, ssh
from .common import FIRSTMATE_POLL, REMOTE_CONNECT, why
from .config import COMMAND_PLACEHOLDER
from .firstmate import FirstmateError
from .nomistakes import RUN_ID, NoMistakesError, Unreachable
from .runscan import read

# The viewer's source arrives as an argument; it is run as __main__ with the
# run's id as its own first argument.
RUNNER = (
    "import base64,sys;s=base64.b64decode(sys.argv[1]);sys.argv[1:]=sys.argv[2:];"
    "exec(compile(s,'viewer','exec'),{'__name__':'__main__','__file__':'/viewer'})"
)
KEY = "read -rsn1 -p 'Run view ended - press a key to close'"
MAX_STEPS_READ = 4


class RemoteWatch:
    def __init__(self, remote, client, settings, post, clock=time.monotonic, fm_poll=FIRSTMATE_POLL):
        self.remote, self.client, self.settings, self.post, self.clock = remote, client, settings, post, clock
        self.name, self.fm_poll = remote.name, fm_poll
        self._jobs: queue.Queue = queue.Queue()
        self._tasks: dict = {}
        self._found_at: float | None = None

    @property
    def can_watch(self):
        return bool(self.remote.terminal and self.remote.watch_script)

    # --- the thread ----------------------------------------------------------

    def worker(self):
        watching, showing, due = None, False, 0.0
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
            elif job[0] == "watch":
                watching = job[1]
                if watching is not None and showing:
                    self._read_card(watching)
            if not showing or self.clock() < due:
                continue
            active = False
            try:
                scan = self.scan()
                active = scan.active()
                self.post("remote", self.name, scan, None, False)
            except Exception as e:
                self.post("remote", self.name, None, why(e, NoMistakesError), isinstance(e, Unreachable))
            if watching is not None:
                self._read_card(watching)
            due = self.clock() + (self.settings.poll if active else self.settings.idle)

    def _read_card(self, run_id):
        try:
            detail = self.client.detail(run_id)
            for step in [s for s in detail.steps if s.findings][:MAX_STEPS_READ]:
                detail.findings += [(step.name, fid, sev) for fid, sev in self.client.findings(run_id, step.name)]
            self.post("run", run_id, detail, None)
        except Exception as e:
            self.post("run", run_id, None, why(e, NoMistakesError))

    def scan(self):
        """One read of the machine: a runs.Scan. Unreachable when it cannot
        be reached, NoMistakesError when no project could be read."""
        r = self.remote
        clones, tasks = self._discover()
        return read(self.client, r.repos, clones, sorted(tasks), machine=self.name, tasks=tasks, real=os.path.normpath)

    def _discover(self):
        """(the machine's clones, {worktree: task id}): the clones every
        read, the worktrees from its firstmate at most every fm_poll."""
        r = self.remote
        if not r.home:
            return [], {}
        clones = ssh.clones(self.client.ssh, r.home)
        now = self.clock()
        if self._found_at is None or now - self._found_at >= self.fm_poll:
            try:
                found = ssh.worktrees(self.client.ssh, r.home, r.code)
                self._tasks = {os.path.normpath(p): t for t, p in found.items()}
            except FirstmateError:
                pass  # the projects still show; its tasks' copies come with its reader
            self._found_at = now
        return clones, self._tasks

    # --- on the loop ---------------------------------------------------------

    def showing(self, connected):
        self._jobs.put(("showing", connected))

    def watch(self, run_id):
        """The run whose card is open (None: none): read it each poll."""
        self._jobs.put(("watch", run_id))

    def stop(self):
        self._jobs.put(None)

    def watch_argv(self, run_id):
        """The argv that opens a terminal window here watching run_id on
        the machine; None without a terminal and viewer configured.
        DesktopError when the viewer cannot be read or the id is no run's."""
        r = self.remote
        if not self.can_watch:
            return None
        if not RUN_ID.fullmatch(run_id):
            raise desktop.DesktopError("not a no-mistakes run id: %r" % run_id)
        try:
            with open(r.watch_script, "rb") as f:
                source = base64.b64encode(f.read()).decode()
        except OSError as e:
            raise desktop.DesktopError("cannot read %s: %s" % (r.watch_script, e.strerror))
        there = "python3 -I -c %s %s %s" % (shlex.quote(RUNNER), shlex.quote(source), shlex.quote(run_id))
        options = "-t -o BatchMode=yes -o ConnectTimeout=%d" % REMOTE_CONNECT
        line = "ssh %s -- %s %s; echo; %s" % (options, shlex.quote(r.ssh), shlex.quote(there), KEY)
        return [word.replace(COMMAND_PLACEHOLDER, shlex.quote(line)) for word in r.terminal]


def build(settings, post, clock=time.monotonic, run=subprocess.run):
    """{name: RemoteWatch} for the [[runs.remote]] machines of settings;
    run is subprocess.run (tests pass a stand-in that fakes ssh)."""
    return {
        r.name: RemoteWatch(r, ssh.RemoteNoMistakes(ssh.Ssh(r.ssh, run), r.command), settings, post, clock)
        for r in settings.remotes
    }
