"""The usage thread: quota-axi, read off the loop, at most once a minute.

It runs `quota-axi --json` (the configured command; JSON on its standard
output) every [usage] poll seconds, never less than USAGE_POLL, and only
while the touch bar is connected: nothing would show it, and a read asks each
vendor, so a page nobody sees costs nothing. Details (the Limits page's
button, and a tap on the tile) opens a terminal viewer in a new window of the
configured terminal: firstmate's `data/tools/usage-view.py` when [firstmate]
home has one, else `<command> --full`. It is the one thing here that acts,
started detached like Watch (desktop.launch) and never waited for past its
grace. It reads nothing for that.
"""

import os
import queue
import shlex
import subprocess
import time

from . import desktop
from .common import USAGE_TIMEOUT, why
from .config import COMMAND_PLACEHOLDER
from .usage import UsageError, parse

# What the window runs after the report, so it stays until a key is pressed.
KEY = "echo; read -rsn1 -p 'Press a key to close'"
# firstmate's viewer of the limits, in its home (a file of firstmate's, run, never read).
VIEWER = os.path.join("data", "tools", "usage-view.py")


class UsageWatch:
    def __init__(self, settings, post, clock=time.monotonic, run=subprocess.run, launcher=None, home=None):
        self.settings, self.post, self.clock, self._run, self.home = settings, post, clock, run, home
        self.launcher = launcher or (lambda argv: desktop.launch(argv, "the usage window"))
        self._jobs: queue.Queue = queue.Queue()
        self._showing = False

    # --- the thread ----------------------------------------------------------

    def worker(self):
        showing, due, last = False, 0.0, None
        while True:
            try:
                job = self._jobs.get(timeout=max(0.0, due - self.clock()) if showing else None)
            except queue.Empty:
                job = ("tick",)
            if job is None:
                return
            if job[0] == "showing":
                showing = job[1]
                # Back on the bar: read when a poll has passed since the last.
                due = 0.0 if showing and last is None else (last or 0.0) + self.settings.poll
            elif job[0] == "open":
                self._open()
            if not showing or self.clock() < due:
                continue
            self._read()
            last = self.clock()
            due = last + self.settings.poll

    def read(self):
        """One read: the providers; UsageError when quota-axi cannot be run
        or prints no quota."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("FM_")}
        argv = list(self.settings.command) + ["--json"]
        try:
            done = self._run(
                argv, text=True, timeout=USAGE_TIMEOUT, env=env, stdin=subprocess.DEVNULL, capture_output=True
            )
        except OSError as e:
            raise UsageError("%s: %s" % (argv[0], e.strerror))
        except subprocess.TimeoutExpired:
            raise UsageError("quota-axi gave no answer in %g s" % USAGE_TIMEOUT)
        if done.returncode != 0:
            tail = (done.stderr or "").strip().splitlines()
            raise UsageError("quota-axi failed: %s" % (tail[-1] if tail else "exit %d" % done.returncode))
        return parse(done.stdout or "", self.settings.providers)

    def _read(self):
        try:
            self.post("usage", self.read(), None)
        except Exception as e:
            self.post("usage", None, why(e, UsageError))

    def _open(self):
        try:
            self.launcher(self.view_argv())
        except Exception as e:
            self.post("usage-view", why(e, desktop.DesktopError))
        else:
            self.post("usage-view", None)

    # --- on the loop ---------------------------------------------------------

    def view_argv(self):
        """The argv that opens the viewer in a terminal window: the terminal's
        words with {command} the viewer's line: firstmate's viewer when its
        home has one, else the full report of quota-axi."""
        viewer = os.path.join(self.home, VIEWER) if self.home else None
        words = ["python3", viewer] if viewer and os.path.isfile(viewer) else list(self.settings.command) + ["--full"]
        line = "%s; %s" % (shlex.join(words), KEY)
        return [word.replace(COMMAND_PLACEHOLDER, shlex.quote(line)) for word in self.settings.terminal]

    def showing(self, connected):
        """Whether the touch bar is connected: told to the thread when it
        changes, not at every turn of the loop (the thread then sleeps)."""
        if connected != self._showing:
            self._showing = connected
            self._jobs.put(("showing", connected))

    def open_view(self):
        """Details: the viewer in a terminal window."""
        self._jobs.put(("open",))

    def stop(self):
        self._jobs.put(None)
