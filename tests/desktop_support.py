"""Stand-ins for the desktop programs the decisions board goes through:
lavish-axi's session listing, the URL handler (gio open) and systemd-run,
the scope it runs in. Scripts in a temporary directory, so the real client
runs them; nothing opens on the screen and no unit is made.
"""

import os

from agents_support import write_script


def lavish_listing(*rows):
    """lavish-axi's output with no argument: rows are (file, status, url)."""
    lines = ["bin: ~/.local/bin/lavish-axi", 'description: "Lavish Editor"']
    lines.append("sessions[%d]{file,status,url,pending_prompts,listener}:" % len(rows))
    lines += ['  %s,%s,"%s",0,none' % row for row in rows]
    lines.append('help[1]: "Run `lavish-axi <html-file>` to open or resume a session"')
    return "\n".join(lines) + "\n"


def fake_lavish(directory):
    """A lavish-axi stand-in: prints listing.txt next to it (fails when it
    says "fail"), and records its arguments and FM_* in lavish.jsonl."""
    with open(os.path.join(directory, "listing.txt"), "w") as f:
        f.write(lavish_listing())
    return write_script(
        os.path.join(directory, "lavish-axi"),
        """
        import json, os, sys
        here = os.path.dirname(os.path.abspath(__file__))
        fm = sorted(k for k in os.environ if k.startswith("FM_"))
        with open(os.path.join(here, "lavish.jsonl"), "a") as f:
            f.write(json.dumps({"fm": fm, "args": sys.argv[1:]}) + "\\n")
        with open(os.path.join(here, "listing.txt")) as f:
            listing = f.read()
        if listing == "fail":
            print("lavish-axi: server unreachable", file=sys.stderr)
            sys.exit(1)
        sys.stdout.write(listing)
        """,
    )


def fake_opener(directory):
    """A stand-in for gio open, so nothing opens on the screen: records its
    arguments in opened.jsonl, fails when opener.fail exists, and when
    opener.linger exists leaves a child holding its output open, as a browser
    gio starts does (its pid in linger.pid)."""
    return write_script(
        os.path.join(directory, "opener"),
        """
        import json, os, subprocess, sys
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "opened.jsonl"), "a") as f:
            f.write(json.dumps(sys.argv[1:]) + "\\n")
        if os.path.exists(os.path.join(here, "opener.linger")):
            child = subprocess.Popen(["sleep", "30"])
            with open(os.path.join(here, "linger.pid"), "w") as f:
                f.write(str(child.pid))
        if os.path.exists(os.path.join(here, "opener.fail")):
            print("gio: no handler for the URL", file=sys.stderr)
            sys.exit(2)
        """,
    )


def fake_scope(directory):
    """A stand-in for systemd-run, so no unit is made: records its arguments
    and the FM_* names it got in scoped.jsonl, fails when scope.fail exists
    (running nothing, as systemd-run does when it cannot make the scope),
    and otherwise runs what follows -- in its own place, as --scope does."""
    return write_script(
        os.path.join(directory, "systemd-run"),
        """
        import json, os, sys
        here = os.path.dirname(os.path.abspath(__file__))
        fm = sorted(k for k in os.environ if k.startswith("FM_"))
        with open(os.path.join(here, "scoped.jsonl"), "a") as f:
            f.write(json.dumps({"fm": fm, "args": sys.argv[1:]}) + "\\n")
        if os.path.exists(os.path.join(here, "scope.fail")):
            print("Failed to start transient scope unit: Access denied", file=sys.stderr)
            sys.exit(1)
        argv = sys.argv[sys.argv.index("--") + 1 :]
        os.execv(argv[0], argv)
        """,
    )
