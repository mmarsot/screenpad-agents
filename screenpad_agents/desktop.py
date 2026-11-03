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
"""

import os
import shutil
import subprocess

from .common import OPEN_TIMEOUT

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
