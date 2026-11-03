#!/bin/sh
# Install or remove the ScreenPad agent app for your user. Run as your user,
# not root: everything goes under your home, nothing needs sudo.
#   ./install.sh            install or update the program and its user unit;
#                           it never enables or starts the unit (docs/agents.md
#                           says how to configure and turn it on)
#   ./install.sh uninstall  stop and disable the unit, and remove what install
#                           put in place; your agents.toml is kept
# The client library screenpad_app is installed next to the program with pip,
# from the git URL in pyproject.toml; SCREENPAD_APP names another source for
# it (a local screenpad-linux checkout, or a wheel), which the tests use.
set -eu

here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
PYTHON=/usr/bin/python3
# The program: agents.py with its package, its icons in icons/, and the
# library in vendor/.
LIB=$HOME/.local/lib/screenpad-agents
# A relative symlink to LIB/agents.py; the unit runs it.
BIN=$HOME/.local/bin/screenpad-agents
UNIT=${XDG_DATA_HOME:-$HOME/.local/share}/systemd/user/screenpad-agents.service
CONFIG=${XDG_CONFIG_HOME:-$HOME/.config}/screenpad/agents.toml

die() {
    echo "install.sh: $*" >&2
    exit 1
}

[ "$(id -u)" -ne 0 ] || die "run as your user, not root (it installs under your home)"

library() {
    if [ -n "${SCREENPAD_APP:-}" ]; then
        echo "$SCREENPAD_APP"
        return
    fi
    "$PYTHON" -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["dependencies"][0])' \
        "$here/pyproject.toml"
}

# The new copy is built next to LIB and then takes its place, so a failed
# step leaves the previous install as it was, and no module of an earlier
# version lingers.
install_all() {
    [ -x "$PYTHON" ] || die "$PYTHON not found; the agent app needs Python 3.11 or newer there"
    "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 11))' || die "$PYTHON is older than 3.11"
    "$PYTHON" -m pip --version >/dev/null 2>&1 || die "pip is missing for $PYTHON (on Ubuntu: sudo apt install python3-pip)"
    new=$LIB.new
    rm -rf "$new"
    install -D -m 0755 "$here/agents.py" "$new/agents.py"
    for f in "$here"/screenpad_agents/*.py; do
        install -D -m 0644 "$f" "$new/screenpad_agents/$(basename "$f")"
    done
    for f in "$here"/icons/*.svg; do
        install -D -m 0644 "$f" "$new/icons/$(basename "$f")"
    done
    "$PYTHON" -m pip install --quiet --disable-pip-version-check --no-deps --target "$new/vendor" "$(library)" ||
        { rm -rf "$new"; die "could not install the client library screenpad_app"; }
    rm -rf "$LIB"
    mv "$new" "$LIB"
    install -d -m 0755 "$(dirname "$BIN")"
    ln -sfn ../lib/screenpad-agents/agents.py "$BIN"
    install -D -m 0644 "$here/systemd/screenpad-agents.service" "$UNIT"
    systemctl --user daemon-reload || echo "Could not reload your systemd user manager; log out and in once."
    echo "Installed $BIN and the unit screenpad-agents.service, not enabled."
    if [ -e "$CONFIG" ]; then
        echo "If it is running, restart it to run the new version: systemctl --user restart screenpad-agents"
    else
        echo "It runs only once you write $CONFIG; docs/agents.md says how, and how to turn it on."
    fi
    case ":$PATH:" in
    *":$(dirname "$BIN"):"*) ;;
    *) echo "$(dirname "$BIN") is not on your PATH; add it to run screenpad-agents by name." ;;
    esac
}

uninstall_all() {
    if [ -e "$UNIT" ]; then
        systemctl --user disable --now screenpad-agents.service || true
    fi
    [ ! -L "$BIN" ] || rm -f "$BIN"
    rm -f "$UNIT"
    rm -rf "$LIB" "$LIB.new"
    systemctl --user daemon-reload || true
    echo "Removed. Your config $CONFIG is kept; delete it by hand if you no longer want it."
}

case "${1:-install}" in
install) install_all ;;
uninstall) uninstall_all ;;
*) die "usage: $0 [install|uninstall]" ;;
esac
