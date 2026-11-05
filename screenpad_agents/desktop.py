"""Opening a URL in the browser on the main screen.

The decisions board (firstmate.py) and a run's pull request (runwatch.py)
are opened the same way: the desktop's URL handler, in a transient scope of
its own,

  systemd-run --user --scope --collect --quiet -- gio open <url>

so a browser it starts is never in the app's unit, whose MemoryMax (64M) it
would count against: a browser started there got the app and itself
OOM-killed. Without systemd-run nothing is opened. The handler is detached:
it gets no pipe, so a browser it leaves running holds none; its output goes
nowhere and its errors to the app's own (the journal), in a session of its
own. It gets none of the FM_* variables of the app's environment.

Which URLs are opened is the caller's check: a loopback board URL, or a
pull request's on the forge (nomistakes.pr_url).

A configured command (the review launcher, [firstmate] review_command) is
started the same way but never waited for (launch): its input and output go
to /dev/null, it is a session of its own, and only a failure within
LAUNCH_GRACE seconds is reported.
"""

import os
import shutil
import subprocess
import threading

from .common import LAUNCH_GRACE, OPEN_TIMEOUT

# The desktop's URL handler, and the transient scope (a cgroup of its own,
# outside the app's unit) it runs in.
OPENER = ("gio", "open")
SCOPE = ("systemd-run", "--user", "--scope", "--collect", "--quiet", "--")


class DesktopError(Exception):
    pass


def open_url(url, what, run=None, scope=SCOPE, opener=OPENER, timeout=OPEN_TIMEOUT):
    """Hand url to the opener in a scope of its own; what names the open in
    an error. DesktopError when systemd-run is missing or fails (then the
    opener did not run) or the opener fails."""
    run = run or subprocess.run
    found = shutil.which(scope[0])
    if not found:
        raise DesktopError("%s not found" % scope[0])
    argv = [found] + list(scope[1:]) + list(opener) + [url]
    env = {k: v for k, v in os.environ.items() if not k.startswith("FM_")}
    try:
        done = run(
            argv,
            text=True,
            timeout=timeout,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as e:
        raise DesktopError("%s: %s" % (argv[0], e.strerror))
    except subprocess.TimeoutExpired:
        raise DesktopError("%s gave no answer in %g s" % (what, timeout))
    if done.returncode != 0:
        why = (done.stderr or "").strip().splitlines()
        raise DesktopError("%s failed: %s" % (what, why[-1] if why else "exit %d" % done.returncode))


def launch(command, what, scope=SCOPE, popen=None, grace=LAUNCH_GRACE):
    """Start command (a list) in a scope of its own and leave it running:
    stdin and stdout go to /dev/null, errors to the app's own, and the
    command is not waited for beyond grace seconds, so a terminal window it
    opens (and the program in it) outlives the call. DesktopError when
    systemd-run is missing or the command cannot start or exits non-zero
    within grace."""
    popen = popen or subprocess.Popen
    found = shutil.which(scope[0])
    if not found:
        raise DesktopError("%s not found" % scope[0])
    argv = [found] + list(scope[1:]) + list(command)
    env = {k: v for k, v in os.environ.items() if not k.startswith("FM_")}
    try:
        child = popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        raise DesktopError("%s: %s" % (argv[0], e.strerror))
    try:
        code = child.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        threading.Thread(target=child.wait, daemon=True).start()  # reaped when it ends
        return
    if code != 0:
        raise DesktopError("%s failed: exit %d" % (what, code))
