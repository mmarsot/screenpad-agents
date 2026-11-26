"""The Runs page of a remote machine: [[runs.remote]] in the config, the same
read-only no-mistakes commands run over ssh (a stand-in for subprocess.run
runs the shell line locally: no test reaches a real machine), the machine's
projects and tasks found through its firstmate, every run labelled with its
machine, "unreachable" in place of a machine's runs when ssh fails (without
holding up this machine's own), and Watch for a remote run opening a
terminal window here that runs the viewer there."""

import base64
import contextlib
import io
import os
import shlex
import subprocess
import tempfile
import threading
import time
import unittest

from agents_support import (
    SESSION,
    FakeHerdr,
    Rig,
    bearings_model,
    config,
    fake_bearings,
    fake_herdr,
    write_json,
)
from runs_support import FakeNoMistakes, FakeSsh, detail, detail_state, fake_no_mistakes, run, run_id, run_row, scan

from screenpad_agents import cli, runcard, runlist
from screenpad_agents.config import Remote
from screenpad_agents.config import Runs as RunsSettings
from screenpad_agents.fleet import Fleet
from screenpad_agents.herdr import Agent
from screenpad_agents.nomistakes import NoMistakesError, NotARepo, Unreachable
from screenpad_agents.remotewatch import RUNNER, RemoteWatch, build
from screenpad_agents.runmodel import Copy, Project
from screenpad_agents.runs import Runs, Scan, widget_id
from screenpad_agents.ssh import RemoteNoMistakes, Ssh

API, COPY = "/repos/api", "/pool/1/api"
REMOTE_RUN = 5


class Machine(unittest.TestCase):
    """A remote machine made of temporary directories: its firstmate home
    (projects/api, and the checkout with a fake reader that knows one task,
    fix-remote, whose worktree is its pool/1/api) and a fake no-mistakes
    that finds REMOTE_RUN running there on fm/remote-fix."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(tmp.cleanup)
        self.dir = os.path.realpath(tmp.name)
        self.home = os.path.join(self.dir, "home")
        self.repo = os.path.join(self.home, "projects", "api")
        self.copy = os.path.join(self.dir, "pool", "1", "api")
        self.code = os.path.join(self.dir, "code")
        self.bin = os.path.join(self.dir, "bin")
        for d in (self.repo, self.copy, self.bin):
            os.makedirs(d)
        fake_bearings(self.code)
        model = bearings_model(endpoints=[("fix-remote", "lab:w9:p9")])
        model["paths"] = [{"id": "fix-remote", "worktree": self.copy}]
        write_json(os.path.join(self.code, "bin", "model.json"), model)
        fake_no_mistakes(self.bin)
        self.state: dict = {
            "dirs": {
                self.repo: {"repo": self.repo, "branch": "main"},
                self.copy: {"repo": self.repo, "branch": "fm/remote-fix", "run": run_id(REMOTE_RUN)},
            },
            "runs": {self.repo: [run_row(REMOTE_RUN, "fm/remote-fix", "running")]},
            "details": {run_id(REMOTE_RUN): detail_state("fm/remote-fix", steps=[("review", "running", 0, 0)])},
            "rounds": {},
        }
        self.save()
        self.ssh = FakeSsh(self.bin)
        self.addCleanup(self.release)

    def save(self):
        write_json(os.path.join(self.bin, "nm.json"), self.state)

    def release(self):
        if self.ssh.gate is not None:
            self.ssh.gate.set()

    def remote(self, **kwargs):
        args = {"home": self.home, "code": self.code}
        args.update(kwargs)
        return Remote("desktop", "desktop", **args)

    def watcher(self, post=None, **kwargs):
        remote = self.remote(**kwargs)
        client = RemoteNoMistakes(Ssh(remote.ssh, self.ssh), remote.command)
        return RemoteWatch(remote, client, RunsSettings(poll=0.05, idle=0.05), post or (lambda *a: None))


class RemoteReadTests(Machine):
    def test_the_machines_projects_runs_and_task_copies_are_read_over_ssh(self):
        got = self.watcher().scan()
        self.assertEqual(
            [(p.repo, p.machine, p.key) for p in got.projects], [(self.repo, "desktop", "desktop:" + self.repo)]
        )
        self.assertEqual([r.id for r in got.projects[0].runs], [run_id(REMOTE_RUN)])
        self.assertEqual(got.copies, [Copy(self.copy, "fm/remote-fix", run_id(REMOTE_RUN), "desktop", "fix-remote")])
        self.assertIn(run_id(REMOTE_RUN), got.details)
        self.assertTrue(got.active())

    def test_ssh_never_prompts_and_gives_up_connecting_quickly(self):
        self.watcher().scan()
        for argv in self.ssh.calls:
            self.assertEqual(argv[0], "ssh")
            self.assertEqual(argv[argv.index("-o") + 1], "BatchMode=yes")
            self.assertIn("ConnectTimeout=4", argv)
            self.assertIn("ControlMaster=auto", argv)
            self.assertEqual(argv[-3:-1], ["--", "desktop"])

    def test_only_read_only_commands_run_on_the_machine(self):
        self.watcher().scan()
        reads = {"axi", "axi status", "axi status --run %s" % run_id(REMOTE_RUN)}
        seen = set()
        for script in self.ssh.scripts():
            words = shlex.split(script)
            if words[0] == "cd":
                words = words[words.index("&&") + 1 :]
            if words[0] == "find":
                self.assertEqual(words[1:2], ["-L"])  # listing projects: nothing else is touched
            elif words[0].startswith("FM_HOME="):
                self.assertEqual(words[2:], ["--json", "--fields", "endpoints,paths"])  # firstmate's reader
            else:
                self.assertEqual(words[0], "no-mistakes")
                seen.add(" ".join(words[1:]))
        self.assertEqual(seen, reads)
        client = self.watcher().client
        calls = len(self.ssh.calls)
        for words in (["axi", "run", "--intent", "x"], ["axi", "respond"], ["axi", "abort"], ["daemon", "stop"]):
            with self.assertRaises(NoMistakesError):
                client._exec(client.command + words, self.repo)
        self.assertEqual(len(self.ssh.calls), calls)

    def test_a_machine_that_cannot_be_reached_fails_at_once_with_why(self):
        self.ssh.down = "ssh: connect to host desktop port 22: Connection timed out"
        with self.assertRaisesRegex(Unreachable, "Connection timed out"):
            self.watcher().scan()
        self.assertEqual(len(self.ssh.calls), 1)  # not one timeout for each directory
        self.ssh.down = None
        self.ssh.timeout = True
        with self.assertRaisesRegex(Unreachable, "no answer from desktop in 12 s"):
            self.watcher().scan()

    def test_a_configured_repo_missing_there_shows_with_why(self):
        missing = os.path.join(self.dir, "nowhere")
        got = self.watcher(repos=[missing]).scan()
        errors = [(p.repo, p.error) for p in got.projects if p.error]
        self.assertEqual(errors, [(missing, "%s is not a directory" % missing)])
        self.assertEqual(len(got.projects), 2)

    def test_its_firstmate_is_asked_at_most_once_a_minute_and_failing_is_no_outage(self):
        watcher = self.watcher()
        watcher.scan()
        watcher.scan()
        readers = [s for s in self.ssh.scripts() if "fm-bearings-snapshot" in s]
        self.assertEqual(len(readers), 1)
        self.assertIn("FM_HOME=%s" % shlex.quote(self.home), readers[0])
        write_json(os.path.join(self.code, "bin", "model.json"), "fail")
        late = self.watcher()
        got = late.scan()  # the reader fails: the projects and their runs still show
        self.assertEqual(got.copies, [])
        self.assertEqual([r.id for r in got.projects[0].runs], [run_id(REMOTE_RUN)])

    def test_a_remote_without_a_firstmate_reads_its_repos_only(self):
        got = self.watcher(home=None, code=None, repos=[self.repo, self.copy]).scan()
        self.assertEqual([p.repo for p in got.projects], [self.repo])
        self.assertEqual(got.copies[0].task, None)
        self.assertFalse([s for s in self.ssh.scripts() if "fm-bearings" in s or "find" in s])

    def test_a_directory_that_is_no_repository_is_left_out(self):
        self.state["dirs"][self.copy] = "not-init"
        self.save()
        with self.assertRaises(NotARepo):
            RemoteNoMistakes(Ssh("desktop", self.ssh), ["no-mistakes"]).listing(self.copy)


def fleet():
    f = Fleet(SESSION, False)
    f.set_agents([])
    return f


class RemotePageTests(unittest.TestCase):
    def board(self, local=True, remote=True, down=None, watch=("desktop",), unreachable=True):
        board = Runs(False, ["desktop"], watch)
        if local:
            board.set_scan(scan([(API, [run(2, "fm/fix", "running")])], [(COPY, "fm/fix", 2)]))
        if remote:
            project = Project("/home/m/api", [run(5, "fm/remote-fix", "running")], machine="desktop")
            copy = Copy("/pool/1/api", "fm/remote-fix", run_id(5), "desktop", "fix-remote")
            board.set_remote("desktop", Scan([project], [copy]))
        if down:
            board.set_remote("desktop", None, down, unreachable)
        return board

    @staticmethod
    def widgets(board):
        return {w["id"]: w for w in board.page(fleet(), board.views(fleet()))["widgets"]}

    def inside(self, board, machine):
        """Tap the project cell of a machine; its runs are the page then."""
        cell = next(w for w in self.widgets(board).values() if w.get("text", "").startswith(machine))
        self.assertTrue(board.navigate(cell["id"]))

    def test_every_run_says_which_machine_it_is_on(self):
        board = self.board()
        heads = [w["text"] for w in self.widgets(board).values() if w["id"].startswith("proj.")]
        self.assertEqual(heads, ["laptop · 1 active", "desktop · 1 active"])  # two projects, both called api
        self.inside(board, "desktop")
        texts = {w["label"]: w["text"] for w in self.widgets(board).values() if "label" in w and "text" in w}
        self.assertEqual(texts["fix-remote"], "desktop · running")
        self.assertNotIn("fm/fix", texts)
        self.assertTrue(board.navigate("runs.up"))
        self.inside(board, "laptop")
        texts = {w["label"]: w["text"] for w in self.widgets(board).values() if "label" in w and "text" in w}
        self.assertEqual(texts["fm/fix"], "laptop · running")

    def test_the_same_repo_path_on_both_machines_is_two_projects(self):
        board = Runs(False, ["desktop"])
        board.set_scan(scan([(API, [run(2, "fm/a", "running")])]))
        board.set_remote("desktop", Scan([Project(API, [run(5, "fm/b", "running")], machine="desktop")]))
        views = board.views(fleet())
        self.assertEqual(sorted(views), [API, "desktop:" + API])
        self.assertEqual(board.machine_of(run_id(5)), "desktop")
        self.assertIsNone(board.machine_of(run_id(2)))

    def test_without_a_remote_nothing_says_a_machine(self):
        board = Runs()
        board.set_scan(scan([(API, [run(2, "fm/fix", "running")])]))
        self.inside(board, "1 active")
        cell = self.widgets(board)[widget_id("run.", run_id(2))]
        self.assertEqual(cell["text"], "running")
        self.assertIsNone(board.label(board.scan.projects[0]))

    def test_an_unreachable_machine_is_a_row_of_its_own_and_its_old_runs_are_gone(self):
        board = self.board(down="ssh: connect to host desktop port 22: No route to host")
        widgets = list(board.page(fleet(), board.views(fleet()))["widgets"])
        first = widgets[0]
        self.assertEqual((first["id"], first["row"], first["tone"]), ("runs.down.desktop", 0, "reject"))
        self.assertEqual(first["label"], "desktop unreachable")
        self.assertEqual(first["text"], "ssh: connect to host desktop port 22: No route to host")
        self.assertEqual({w["row"] for w in widgets[1:]}, {1})  # this machine's runs are one row down
        self.assertNotIn("fix-remote", [w.get("label") for w in widgets])
        tile = board.tile(board.views(fleet()))
        self.assertEqual((tile["text"], tile["tone"]), ("1 active · desktop unreachable", "warning"))
        board.set_remote("desktop", Scan([]))
        self.assertNotIn("runs.down.desktop", self.widgets(board))

    def test_a_machine_that_answers_but_whose_no_mistakes_fails_is_not_called_unreachable(self):
        why = "no-mistakes axi: sh: 1: no-mistakes: not found"
        board = self.board(down=why, unreachable=False)
        first = board.page(fleet(), board.views(fleet()))["widgets"][0]
        self.assertEqual(
            (first["id"], first["label"], first["text"]), ("runs.down.desktop", "desktop: no-mistakes unavailable", why)
        )
        self.assertNotIn("fix-remote", [w.get("label") for w in self.widgets(board).values()])
        tile = board.tile(board.views(fleet()))
        self.assertEqual(tile["text"], "1 active · desktop: no-mistakes unavailable")

    def test_with_nothing_read_but_the_notice_the_page_still_says_it(self):
        board = self.board(local=False, remote=False, down="ssh: nope")
        page = board.page(fleet(), board.views(fleet()))
        self.assertEqual(page["text"], "desktop unreachable")
        self.assertEqual([w["id"] for w in page["widgets"]], ["runs.down.desktop"])

    def test_a_remote_run_has_no_agent_and_no_review_here(self):
        board = self.board()
        view = next(v for vs in board.views(fleet()).values() for v in vs if v.run.id == run_id(5))
        self.assertEqual((view.task, view.pane, view.machine), ("fix-remote", None, "desktop"))
        self.assertIsNone(view.review())  # not a task of this machine's firstmate
        board.open_card(run_id(5))
        ws = {w["id"]: w for w in board.page(fleet(), board.views(fleet()))["widgets"]}
        self.assertEqual(ws[runcard.FOCUS]["text"], "runs on desktop")
        self.assertTrue(ws[runcard.LINES]["lines"][0].startswith("desktop · "))
        self.assertEqual(ws[runcard.AGENT]["label"], "fix-remote")
        self.assertIn(runcard.WATCH, ws)  # the remote has a terminal and a viewer
        no_watch = self.board(watch=())
        no_watch.open_card(run_id(5))
        self.assertNotIn(runcard.WATCH, self.widgets(no_watch))

    def test_the_machines_are_checked_against_the_one_warning_rule_separately(self):
        board = Runs(False, ["desktop"])
        board.set_scan(scan([(API, [run(2, "fm/a", "running")])], [(COPY, "fm/a", 2)]))
        same = Project(API, [run(5, "fm/a", "running")], machine="desktop")
        board.set_remote("desktop", Scan([same], [Copy(COPY, "fm/a", run_id(5), "desktop")]))
        self.assertEqual(board.counts(board.views(fleet())), (2, 0, 0))


class RemoteLoopTests(Machine):
    def setUp(self):
        super().setUp()
        self.herdr = FakeHerdr([Agent("w1:p1", "claude", "working", COPY)])
        self.nm = FakeNoMistakes()
        self.nm.dirs = {API: (API, "main", None), COPY: (API, "fm/fix", run_id(2))}
        self.nm.runs = {API: [run(2, "fm/fix", "running")]}
        self.nm.details = {run_id(2): detail(2, "fm/fix", at="review")}
        self.launched = []

    def rig(self, wait=True, remote=None, poll=0.05, idle=0.05):
        cfg = config(firstmate=False, herdr_poll=0.05)
        cfg.runs = RunsSettings([API], False, poll=poll, idle=idle, watch=("/opt/watch", "{run}"))
        cfg.runs.remotes = [remote or self.remote()]
        rig = Rig(
            self,
            self.herdr,
            None,
            cfg=cfg,
            nomistakes=self.nm,
            launcher=self.launched.append,
            ssh_run=self.ssh,
        )
        if wait:
            self.goto(rig, "laptop")
            rig.until(lambda: self.text(rig, run_id(2)) is not None)
        return rig

    def goto(self, rig, machine):
        """Show the runs of a machine's project: leave the one open, tap the other's cell."""
        ids = lambda: [w.id for w in rig.apps.pages["runs"].widgets] if rig.apps.pages.get("runs") else []  # noqa: E731
        if runlist.UP in ids():
            rig.apps.press(rig.client(), "runs", runlist.UP, "tap")
            rig.until(lambda: runlist.UP not in ids())

        def cell():
            page = rig.apps.pages.get("runs")
            widgets = page.widgets if page else []
            found = [w.id for w in widgets if w.id.startswith("proj.") and w.look.get("text", "").startswith(machine)]
            return found[0] if found else None

        rig.until(lambda: cell() is not None)
        rig.apps.press(rig.client(), "runs", cell(), "tap")
        rig.until(lambda: runlist.UP in ids())

    @staticmethod
    def look(rig, wid):
        page = rig.apps.pages.get("runs")
        found = [w for w in page.widgets if w.id == wid] if page else []
        return found[0].look if found else {}

    def text(self, rig, n):
        return self.look(rig, widget_id("run.", n)).get("text")

    def test_the_runs_of_both_machines_are_on_the_page_each_with_its_machine(self):
        rig = self.rig()
        self.assertEqual(self.text(rig, run_id(2)), "laptop · running · review")
        self.goto(rig, "desktop")
        rig.until(lambda: self.text(rig, run_id(REMOTE_RUN)) == "desktop · running · review")
        self.assertEqual(self.look(rig, widget_id("run.", run_id(REMOTE_RUN)))["label"], "fix-remote")
        self.assertEqual(rig.apps.provided()["runs"]["text"], "2 active")
        self.assertEqual(rig.logged, [])

    def test_a_desktop_whose_no_mistakes_cannot_run_is_not_said_to_be_unreachable(self):
        rig = self.rig(remote=self.remote(command=[os.path.join(self.dir, "no-such-no-mistakes")]))
        rig.apps.press(rig.client(), "runs", runlist.UP, "tap")  # the notice is on the projects page
        rig.until(lambda: self.look(rig, "runs.down.desktop").get("label") == "desktop: no-mistakes unavailable")
        self.assertIn("not found", self.look(rig, "runs.down.desktop")["text"])
        self.assertEqual(rig.apps.provided()["runs"]["text"], "1 active · desktop: no-mistakes unavailable")
        self.assertEqual(len(rig.logged), 1)
        self.assertTrue(rig.logged[0].startswith("desktop: no-mistakes unavailable: "), rig.logged)

    def test_an_unreachable_desktop_is_said_on_the_page_and_logged_once(self):
        self.ssh.down = "ssh: connect to host desktop port 22: Connection refused"
        rig = self.rig()
        rig.apps.press(rig.client(), "runs", runlist.UP, "tap")  # the notice is on the projects page
        rig.until(lambda: self.look(rig, "runs.down.desktop").get("label") == "desktop unreachable")
        self.assertEqual(
            self.look(rig, "runs.down.desktop")["text"], "ssh: connect to host desktop port 22: Connection refused"
        )
        self.assertEqual(rig.apps.provided()["runs"]["text"], "1 active · desktop unreachable")
        self.goto(rig, "laptop")
        self.assertEqual(self.text(rig, run_id(2)), "laptop · running · review")  # its own runs stay
        rig.apps.press(rig.client(), "runs", runlist.UP, "tap")
        rig.until(lambda: len(self.ssh.calls) >= 3)
        self.assertEqual(rig.logged, ["desktop unreachable: ssh: connect to host desktop port 22: Connection refused"])
        self.ssh.down = None
        self.goto(rig, "desktop")
        rig.until(lambda: self.text(rig, run_id(REMOTE_RUN)) == "desktop · running · review")
        self.assertEqual(rig.logged[-1], "desktop answers again")
        rig.apps.press(rig.client(), "runs", runlist.UP, "tap")
        rig.until(lambda: self.look(rig, "runs.down.desktop") == {})

    def test_a_slow_desktop_holds_up_nothing_here(self):
        self.ssh.gate = threading.Event()
        rig = self.rig()  # this machine's run shows while every ssh call waits
        self.assertEqual(self.text(rig, run_id(2)), "laptop · running · review")
        self.assertIsNone(self.text(rig, run_id(REMOTE_RUN)))
        client = rig.client()
        rig.apps.press(client, "runs", widget_id("run.", run_id(2)), "tap")
        rig.until(lambda: runcard.LINES in [w.id for w in rig.apps.pages["runs"].widgets])
        self.ssh.gate.set()
        rig.apps.press(client, "runs", runcard.BACK, "tap")
        rig.until(lambda: runcard.LINES not in [w.id for w in rig.apps.pages["runs"].widgets])
        self.goto(rig, "desktop")
        rig.until(lambda: self.text(rig, run_id(REMOTE_RUN)) is not None)

    def test_the_desktop_is_read_no_more_often_than_this_machine_and_not_while_disconnected(self):
        rig = self.rig(poll=0.05, idle=60.0)
        rig.until(lambda: len(self.ssh.calls) >= 6)
        self.state["runs"][self.repo] = [run_row(REMOTE_RUN, "fm/remote-fix", "completed")]
        self.save()
        self.goto(rig, "desktop")
        rig.until(lambda: self.text(rig, run_id(REMOTE_RUN)) == "desktop · passed")
        rig.until(lambda: rig.apps.provided()["runs"]["text"] == "1 active")
        rig.turn(5)
        seen = len(self.ssh.calls)
        end = time.monotonic() + 0.4
        while time.monotonic() < end:
            rig.turn()
        self.assertEqual(len(self.ssh.calls), seen)  # idle: the next read is in 60 s
        rig.close_server()
        rig.until(lambda: not rig.app.link.connected)
        rig.turn(20)
        seen = len(self.ssh.calls)
        end = time.monotonic() + 0.3
        while time.monotonic() < end:
            rig.turn()
        self.assertLessEqual(len(self.ssh.calls) - seen, 12)  # at most the read under way

    def test_a_remote_runs_card_is_read_there_and_watch_opens_a_terminal_running_the_viewer(self):
        script = os.path.join(self.dir, "viewer.py")
        with open(script, "w") as f:
            f.write("import sys\nprint(__name__, sys.argv[1:])\n")
        terminal = ["term", "--title", "Watch {run} on {name}", "-x", "bash -c {command}"]  # only {command} is filled
        rig = self.rig(remote=self.remote(terminal=terminal, script=script))
        self.goto(rig, "desktop")
        rig.until(lambda: self.text(rig, run_id(REMOTE_RUN)) is not None)
        client = rig.client()
        rig.apps.press(client, "runs", widget_id("run.", run_id(REMOTE_RUN)), "tap")
        rig.until(lambda: runcard.WATCH in [w.id for w in rig.apps.pages["runs"].widgets])
        self.assertNotIn(("detail", run_id(REMOTE_RUN)), self.nm.calls)  # this machine's client never saw it
        self.assertTrue([s for s in self.ssh.scripts() if "status --run %s" % run_id(REMOTE_RUN) in s])
        rig.apps.press(client, "runs", runcard.WATCH, "tap")
        rig.until(lambda: self.launched)
        argv = self.launched[0]
        self.assertEqual(argv[:3], ["term", "--title", "Watch {run} on {name}"])
        self.assertEqual(argv[3], "-x")
        outer = shlex.split(argv[4])
        self.assertEqual(outer[:2], ["bash", "-c"])
        line, _, tail = outer[2].partition("; echo; ")
        self.assertTrue(tail.startswith("read -rsn1"))
        words = shlex.split(line)
        self.assertEqual(words[:7], ["ssh", "-t", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", "--"])
        self.assertEqual(words[7], "desktop")
        there = shlex.split(words[8])
        self.assertEqual(there[:4], ["python3", "-I", "-c", RUNNER])
        self.assertEqual(there[5], run_id(REMOTE_RUN))
        with open(script, "rb") as f:
            self.assertEqual(base64.b64decode(there[4]), f.read())
        # What the machine runs does run the viewer, as __main__, with the run's id.
        done = subprocess.run(there, capture_output=True, text=True, timeout=30)
        self.assertEqual(done.stdout.strip(), "__main__ ['%s']" % run_id(REMOTE_RUN))
        # A local run's Watch still uses [runs] watch_command.
        rig.apps.press(client, "runs", runcard.BACK, "tap")
        rig.until(lambda: runcard.LINES not in [w.id for w in rig.apps.pages["runs"].widgets])
        self.goto(rig, "laptop")
        rig.apps.press(client, "runs", widget_id("run.", run_id(2)), "tap")
        rig.until(lambda: runcard.WATCH in [w.id for w in rig.apps.pages["runs"].widgets])
        rig.apps.press(client, "runs", runcard.WATCH, "tap")
        rig.until(lambda: len(self.launched) == 2)
        self.assertEqual(self.launched[1], ["/opt/watch", run_id(2)])

    def test_watch_says_when_the_viewer_cannot_be_read(self):
        script = os.path.join(self.dir, "viewer.py")
        with open(script, "w") as f:
            f.write("pass\n")
        rig = self.rig(remote=self.remote(terminal=["term", "{command}"], script=script))
        self.goto(rig, "desktop")
        rig.until(lambda: self.text(rig, run_id(REMOTE_RUN)) is not None)
        os.remove(script)
        client = rig.client()
        rig.apps.press(client, "runs", widget_id("run.", run_id(REMOTE_RUN)), "tap")
        rig.until(lambda: runcard.WATCH in [w.id for w in rig.apps.pages["runs"].widgets])
        rig.apps.press(client, "runs", runcard.WATCH, "tap")
        rig.until(lambda: self.look(rig, runcard.WATCH).get("text", "").startswith("not opened: cannot read"))
        self.assertEqual(self.launched, [])

    def test_a_remote_run_has_no_watch_without_a_terminal_and_viewer(self):
        rig = self.rig()
        self.goto(rig, "desktop")
        rig.until(lambda: self.text(rig, run_id(REMOTE_RUN)) is not None)
        rig.apps.press(rig.client(), "runs", widget_id("run.", run_id(REMOTE_RUN)), "tap")
        rig.until(lambda: runcard.LINES in [w.id for w in rig.apps.pages["runs"].widgets])
        self.assertEqual(self.look(rig, runcard.WATCH), {})


class ShowTests(Machine):
    def test_show_prints_the_desktops_runs_and_says_when_it_is_unreachable(self):
        herdr = fake_herdr(self.dir)
        write_json(os.path.join(self.dir, "agents.json"), [])
        local = os.path.join(self.dir, "local")
        os.mkdir(local)
        nm_bin = os.path.join(self.dir, "nmlocal")
        os.mkdir(nm_bin)
        nm = fake_no_mistakes(nm_bin)
        write_json(
            os.path.join(nm_bin, "nm.json"),
            {"dirs": {local: {"repo": local, "branch": "main"}}, "runs": {local: []}, "details": {}, "rounds": {}},
        )
        path = os.path.join(self.dir, "agents.toml")
        with open(path, "w") as f:
            f.write(
                '[herdr]\ncommand = "%s"\nsession = "lab"\n[runs]\nrepos = ["%s"]\ncommand = "%s"\n'
                '[[runs.remote]]\nname = "desktop"\nssh = "desktop"\nhome = "%s"\ncode = "%s"\n'
                % (herdr, local, nm, self.home, self.code)
            )

        def show(ssh):
            args = cli.argparse.Namespace(config=path, json=False)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cli.cmd_show(args, ssh_run=ssh)
            return buf.getvalue().splitlines()

        out = show(self.ssh)
        self.assertIn("no-mistakes runs: 1 active", out)
        self.assertIn("  desktop: api (%s)" % self.repo, out)
        self.assertTrue([line for line in out if run_id(REMOTE_RUN) in line and "desktop · running" in line])
        self.ssh.down = "ssh: connect to host desktop port 22: Connection refused"
        out = show(self.ssh)
        self.assertIn("no-mistakes runs: no active run · desktop unreachable", out)
        self.assertIn("  desktop unreachable: ssh: connect to host desktop port 22: Connection refused", out)
        self.ssh.down = None
        missing = os.path.join(self.dir, "no-such-no-mistakes")
        with open(path, "a") as f:
            f.write('command = "%s"\n' % missing)
        out = show(self.ssh)
        self.assertIn("no-mistakes runs: no active run · desktop: no-mistakes unavailable", out)
        self.assertFalse([line for line in out if "unreachable" in line])


class BuildTests(Machine):
    def test_build_makes_one_thread_state_per_remote(self):
        settings = RunsSettings(["/r"], False)
        settings.remotes = [self.remote(), Remote("laptop2", "other", repos=["/x"])]
        got = build(settings, None, run=self.ssh)
        self.assertEqual(list(got), ["desktop", "laptop2"])
        self.assertFalse(got["desktop"].can_watch)


if __name__ == "__main__":
    unittest.main()
