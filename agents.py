#!/usr/bin/python3 -I
"""Runs the screenpad-agents command from the screenpad_agents package.

Installed as ~/.local/lib/screenpad-agents/agents.py next to the package,
with ~/.local/bin/screenpad-agents a symlink to it; run from the checkout as
./agents.py. Isolated mode (-I) puts neither the script's directory nor the
user's site-packages on sys.path, so this adds the directory the script
really lives in, and its vendor/ directory, which holds the client library
screenpad_app (install.sh or 'make vendor' puts it there), and only those.
"""

import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "vendor")]
sys.dont_write_bytecode = True

try:
    import screenpad_app  # noqa: F401  # checked here so a missing library says what to do
except ImportError:
    sys.exit(
        "screenpad-agents: the client library screenpad_app is not in %s; "
        "run ./install.sh (or 'make vendor' in a checkout)" % os.path.join(HERE, "vendor")
    )

from screenpad_agents.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
