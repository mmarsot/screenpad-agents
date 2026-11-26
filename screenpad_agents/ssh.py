"""Reading another machine over ssh, and only reading.

The Runs page shows a remote machine's no-mistakes runs (docs/runs.md) by
running there the same read-only commands it runs here (nomistakes.py):

  ssh <target> 'cd <dir> && no-mistakes axi status'

and, to find that machine's projects, two reads of its firstmate home: the
directory names in <home>/projects, and the task worktrees its own reader
gives (FM_HOME=<home> <code>/bin/fm-bearings-snapshot.sh --json --fields
endpoints,paths). Nothing else runs there: RemoteNoMistakes refuses any
command NoMistakes would, and nothing here drives a run.

Every call uses BatchMode (never a prompt) and a short connect timeout, so
a machine that is off or unreachable fails within seconds (Unreachable), and
one ssh connection is shared by the calls of a poll (ControlMaster, kept
60 s: ssh_control_path). The target is checked at load time (config.py) not
to look like an option, and goes after "--" anyway.
"""

import json
import os
import shlex
import subprocess

from .common import FIRSTMATE_TIMEOUT, REMOTE_CONNECT, REMOTE_TIMEOUT, ssh_control_path
from .config import BEARINGS
from .firstmate import FirstmateError, parse
from .nomistakes import NoMistakes, NoMistakesError, NotARepo, Unreachable, read_only

OPTIONS = (
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=%d" % REMOTE_CONNECT,
    "-o",
    "ControlMaster=auto",
    "-o",
    "ControlPersist=60",
    "-o",
    "LogLevel=ERROR",
    "-a",
    "-x",
)


class Ssh:
    """ssh to one target; run is subprocess.run (tests pass a stand-in)."""

    def __init__(self, target, run=subprocess.run, timeout=REMOTE_TIMEOUT, control=ssh_control_path):
        self.target, self._run, self.timeout, self._control = target, run, timeout, control

    def argv(self, script):
        control = self._control()
        options = list(OPTIONS) + (["-o", "ControlPath=" + control] if control else [])
        return ["ssh"] + options + ["--", self.target, script]

    def call(self, script, timeout=None):
        """Run the shell line script there; its CompletedProcess, whatever
        it exited with. Unreachable when ssh cannot connect (its own exit
        255) or the machine gives no answer in time."""
        timeout = timeout or self.timeout
        env = {k: v for k, v in os.environ.items() if not k.startswith("FM_")}
        try:
            done = self._run(
                self.argv(script),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                stdin=subprocess.DEVNULL,
            )
        except OSError as e:
            raise Unreachable("ssh: %s" % e.strerror)
        except subprocess.TimeoutExpired:
            raise Unreachable("no answer from %s in %g s" % (self.target, timeout))
        if done.returncode == 255:
            lines = (done.stderr or "").strip().splitlines()
            raise Unreachable(lines[-1] if lines else "ssh to %s failed" % self.target)
        return done


class RemoteNoMistakes(NoMistakes):
    """no-mistakes on another machine: the same client, each read-only
    command run there over ssh, in the directory it is asked about."""

    def __init__(self, ssh, command):
        super().__init__(command, run=ssh.call)
        self.ssh = ssh

    def _exec(self, argv, cwd):
        words = argv[len(self.command) :]
        if not read_only(words):
            raise NoMistakesError("not a read-only no-mistakes command: %s" % " ".join(words))
        script = " ".join(shlex.quote(w) for w in argv)
        if cwd is not None:
            script = "cd %s && %s" % (shlex.quote(cwd), script)
        done = self.ssh.call(script)
        if cwd is not None and done.returncode != 0 and "cd: " in (done.stderr or ""):
            raise NotARepo("%s is not a directory" % cwd)
        return done


def clones(ssh, home):
    """The directories in <home>/projects there: firstmate's registered
    clones. Unreachable when the machine is; [] when there are none."""
    root = os.path.join(home, "projects")
    done = ssh.call("find -L %s -mindepth 1 -maxdepth 1 -type d ! -name '.*' 2>/dev/null | sort" % shlex.quote(root))
    return [line for line in (done.stdout or "").splitlines() if os.path.isabs(line)]


def worktrees(ssh, home, code):
    """{task id: worktree} of the live tasks there, from firstmate's own
    reader. FirstmateError when it fails; Unreachable when the machine is."""
    reader = shlex.quote(os.path.join(code, BEARINGS))
    done = ssh.call("FM_HOME=%s %s --json --fields endpoints,paths" % (shlex.quote(home), reader), FIRSTMATE_TIMEOUT)
    if done.returncode != 0:
        lines = (done.stderr or "").strip().splitlines()
        raise FirstmateError("firstmate's reader failed: %s" % (lines[-1] if lines else "exit %d" % done.returncode))
    try:
        model = json.loads(done.stdout)
    except ValueError:
        raise FirstmateError("firstmate's reader printed no JSON")
    return parse(model).worktrees
