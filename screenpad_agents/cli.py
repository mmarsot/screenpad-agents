"""The screenpad-agents command: run, and show."""

import argparse
import json
import signal
import sys

from .app import App
from .common import AgentsError, config_path, socket_path
from .config import load
from .firstmate import Firstmate, FirstmateError
from .fleet import Fleet
from .herdr import Herdr, HerdrError
from .nomistakes import NoMistakes, NoMistakesError
from .runwatch import RunsWatch


def clients(config):
    herdr = Herdr(config.herdr, config.session)
    firstmate = None
    if config.home:
        paths = config.runs is not None and config.runs.firstmate
        firstmate = Firstmate(
            config.home,
            config.bearings,
            config.control,
            board=config.board,
            inbox=config.inbox,
            lavish=config.lavish,
            paths=paths,
        )
    return herdr, firstmate


def cmd_run(args):
    config = load(args.config)
    herdr, firstmate = clients(config)
    nomistakes = NoMistakes(config.runs.command) if config.runs is not None else None
    app = App(config, herdr, firstmate, socket_path(), nomistakes=nomistakes)
    signal.signal(signal.SIGTERM, lambda *_: app.stop())
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    return 0


def cmd_show(args):
    """Read Herdr and firstmate once and print what the touch bar would show."""
    config = load(args.config)
    herdr, firstmate = clients(config)
    fleet = Fleet(config.session, firstmate is not None)
    try:
        fleet.set_agents(herdr.agents())
    except HerdrError as e:
        fleet.set_agents(None, str(e))
    if firstmate is not None:
        try:
            fleet.set_bearings(firstmate.read())
        except FirstmateError as e:
            fleet.set_bearings(None, str(e))
    watch = None
    if config.runs is not None:
        watch = RunsWatch(config.runs, NoMistakes(config.runs.command), config.home, None)
        try:
            watch.board.set_scan(watch.scan(*watch.places(fleet)))
        except NoMistakesError as e:
            watch.board.set_scan(None, str(e))
    if args.json:
        print(json.dumps(fleet.messages() + (watch.board.messages(fleet) if watch else []), indent=2))
        return 0
    print("Herdr session %s: %s" % (config.session, fleet.summary()))
    if fleet.herdr_error:
        print("  " + fleet.herdr_error)
    for agent in fleet.agents or []:
        task = fleet.task(agent)
        print("  %-8s %-8s %-10s %s" % (agent.pane, agent.kind, agent.state, task.id if task else "-"))
    if firstmate is not None:
        tile = fleet.calls_tile()
        print("Captain's Call: %s" % tile["text"])
        if fleet.firstmate_error:
            print("  " + fleet.firstmate_error)
    if watch is not None:
        show_runs(watch.board, fleet)
    return 1 if fleet.herdr_error else 0


def show_runs(board, fleet):
    views = board.views(fleet)
    print("no-mistakes runs: %s" % board.summary(views))
    if board.error:
        print("  " + board.error)
    for p in board.scan.projects if board.scan else []:
        print("  %s (%s)%s" % (p.name, p.repo, ": " + p.error if p.error else ""))
        for v in views[p.repo]:
            marks = "".join(m for m, on in (("!", v.duplicate), ("*", v.attention)) if on)
            print("    %-2s %-26s %-36s %-24s %s" % (marks, v.run.id, v.run.branch, v.phrase(), v.pane or "-"))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="screenpad-agents",
        description="The agent app for the ScreenPad touch bar: Herdr's agents and firstmate's Captain's Calls.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, helptext in (
        ("run", "connect to the touch bar and keep its agents page and tiles up to date"),
        ("show", "read Herdr and firstmate once and print what the touch bar would show"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--config", default=None, help="the config file (default: ~/.config/screenpad/agents.toml)")
        if name == "show":
            p.add_argument("--json", action="store_true", help="print the socket messages instead")
    args = parser.parse_args(argv)
    try:
        args.config = args.config or config_path()
        return {"run": cmd_run, "show": cmd_show}[args.command](args)
    except AgentsError as e:
        print("screenpad-agents: %s" % e, file=sys.stderr)
        return 2
