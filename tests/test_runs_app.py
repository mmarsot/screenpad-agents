"""The Runs page in the loop, against the stand-in touch bar's socket server:
its page and tile, a tap opening a run's card and its Focus focusing the
run's agent, the runs tile, how often no-mistakes is read (only while the
touch bar is connected, faster while a run is active), its failures, and
`show`. no-mistakes, Herdr and firstmate are fakes."""

import os
import subprocess
import tempfile
import time
import unittest

from agents_support import REPO, FakeFirstmate, FakeHerdr, Rig, config, fake_bearings, fake_herdr, write_json
from runs_support import FakeNoMistakes, detail, detail_state, fake_no_mistakes, run, run_id, run_row

from screenpad_agents import runcard
from screenpad_agents.config import Runs as RunsSettings
from screenpad_agents.firstmate import Bearings, Task
from screenpad_agents.herdr import Agent
from screenpad_agents.runs import widget_id

API, COPY = "/repos/api", "/pool/1/api"


class RunsLoopTests(unittest.TestCase):
    def setUp(self):
        self.herdr = FakeHerdr([Agent("w1:p1", "claude", "working", COPY)])
        self.firstmate = FakeFirstmate()
        self.firstmate.bearings = Bearings(0, False, {"lab:w1:p1": Task("fix-api")}, {"fix-api": COPY})
        self.nm = FakeNoMistakes()
        self.nm.dirs = {API: (API, "main", None), COPY: (API, "fm/fix", run_id(2))}
        self.nm.runs = {API: [run(2, "fm/fix", "running"), run(1, "fm/old", "completed")]}
        self.nm.details = {run_id(2): detail(2, "fm/fix", at="review", step_status="awaiting_approval", findings=1)}
        self.nm.rounds = {(run_id(2), "review"): [("missing-check", "warning")]}

    def rig(self, poll=0.05, idle=60.0, wait=True):
        cfg = config(herdr_poll=0.05)
        cfg.runs = RunsSettings([API], True, poll=poll, idle=idle)
        rig = Rig(self, self.herdr, self.firstmate, cfg=cfg, nomistakes=self.nm)
        if wait:
            rig.until(lambda: self.run_label(rig) == "fix-api")
        return rig

    @staticmethod
    def run_label(rig, n=2):
        page = rig.apps.pages.get("runs")
        found = [w for w in page.widgets if w.id == widget_id("run.", run_id(n))] if page else []
        return found[0].look.get("label") if found else None

    def test_the_page_and_tile_joined_to_the_agent_and_its_task(self):
        rig = self.rig()
        self.assertEqual(rig.handled[0]["tiles"], ["agents", "calls", "runs"])
        tile = rig.apps.provided()["runs"]
        self.assertEqual((tile["text"], tile["badge"], tile["tone"]), ("1 active · 1 needs you", "1", "warning"))
        self.assertIn(("current", COPY), self.nm.calls)  # the task's worktree and the agent's cwd
        self.assertEqual(rig.logged, [])

    def test_a_tap_opens_the_runs_card_and_focus_focuses_its_agent(self):
        rig = self.rig()
        client = rig.client()
        wid = widget_id("run.", run_id(2))
        rig.apps.press(client, "runs", wid, "long")
        rig.turn(3)
        self.assertNotIn(runcard.LINES, [w.id for w in rig.apps.pages["runs"].widgets])
        rig.apps.press(client, "runs", wid, "tap")

        def lines():
            ws = {w.id: w for w in rig.apps.pages["runs"].widgets}
            return ws[runcard.LINES].look["lines"] if runcard.LINES in ws else []

        rig.until(lambda: "findings: missing-check (warning)" in lines())
        self.assertIn(("findings", run_id(2), "review"), self.nm.calls)
        rig.apps.press(client, "runs", runcard.FOCUS, "tap")
        rig.until(lambda: self.herdr.focused == ["w1:p1"])
        rig.apps.press(client, "runs", runcard.BACK, "tap")
        rig.until(lambda: self.run_label(rig) == "fix-api")
        self.assertEqual(self.herdr.sent, [])
        self.assertEqual({c[0] for c in self.nm.calls}, {"listing", "current", "detail", "findings"})

    def test_the_runs_tile_focuses_the_agent_of_a_run_needing_you(self):
        rig = self.rig()
        rig.apps.event("runs", "up", inside=False)
        rig.turn(3)
        self.assertEqual(self.herdr.focused, [])
        rig.apps.event("runs", "up", inside=True)
        rig.until(lambda: self.herdr.focused == ["w1:p1"])

    def test_read_faster_while_a_run_is_active_and_not_while_disconnected(self):
        rig = self.rig(poll=0.05, idle=60.0)
        rig.until(lambda: self.nm.count("listing") >= 6)  # API and the task's copy, three times
        self.nm.runs[API] = [run(2, "fm/fix", "completed")]
        rig.until(lambda: rig.apps.provided()["runs"].get("text") == "none active")
        seen = self.nm.count("listing")
        end = time.monotonic() + 0.4
        while time.monotonic() < end:
            rig.turn()
        self.assertEqual(self.nm.count("listing"), seen)  # idle: next read in 60 s

    def test_nothing_is_read_while_the_touch_bar_is_not_connected(self):
        rig = self.rig(wait=False)
        rig.close_server()
        rig.until(lambda: not rig.app.link.connected)
        seen = self.nm.count("listing")
        end = time.monotonic() + 0.4
        while time.monotonic() < end:
            rig.turn()
        self.assertLessEqual(self.nm.count("listing") - seen, 2)  # at most the read under way

    def test_no_mistakes_failing_is_shown_and_logged_once(self):
        self.nm.error = "no-mistakes: No such file or directory"
        rig = self.rig(poll=0.05, idle=0.05, wait=False)  # a failed read waits idle seconds
        rig.until(lambda: rig.apps.provided().get("runs", {}).get("text") == "no-mistakes unavailable")
        rig.until(lambda: self.nm.count("listing") >= 3)
        self.assertEqual(rig.logged, ["no-mistakes: No such file or directory"])
        self.nm.error = None
        rig.until(lambda: self.run_label(rig) == "fix-api")
        self.assertEqual(rig.logged[-1], "no-mistakes answers again")


class ShowTests(unittest.TestCase):
    def test_show_prints_the_runs(self):
        with tempfile.TemporaryDirectory() as d:
            herdr = fake_herdr(d)
            repo, copy = os.path.join(d, "repo"), os.path.join(d, "copy")
            os.mkdir(repo)
            os.mkdir(copy)
            write_json(
                os.path.join(d, "agents.json"),
                [{"agent": "claude", "agent_status": "working", "pane_id": "w1:p1", "cwd": copy}],
            )
            code, home = os.path.join(d, "fm"), os.path.join(d, "home")
            fake_bearings(code)
            os.mkdir(home)
            nm_bin = os.path.join(d, "nmbin")
            os.mkdir(nm_bin)
            nm = fake_no_mistakes(nm_bin)
            state = {
                "dirs": {
                    repo: {"repo": repo, "branch": "main"},
                    copy: {"repo": repo, "branch": "fm/fix", "run": run_id(2)},
                },
                "runs": {repo: [run_row(2, "fm/fix", "running"), run_row(1, "fm/fix", "running")]},
                "details": {run_id(2): detail_state("fm/fix"), run_id(1): detail_state("fm/fix")},
                "rounds": {},
            }
            write_json(os.path.join(nm_bin, "nm.json"), state)
            path = os.path.join(d, "agents.toml")
            with open(path, "w") as f:
                f.write(
                    '[herdr]\ncommand = "%s"\nsession = "lab"\n[firstmate]\nhome = "%s"\ncode = "%s"\n'
                    '[runs]\nrepos = ["%s"]\ncommand = "%s"\n' % (herdr, home, code, repo, nm)
                )
            env = dict(os.environ, XDG_RUNTIME_DIR=d)
            done = subprocess.run(
                [os.path.join(REPO, "agents.py"), "show", "--config", path],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            out = done.stdout.splitlines()
            self.assertIn("no-mistakes runs: 2 active · 2 on one agent", out)
            self.assertIn("  repo (%s)" % repo, out)
            rows = [line.split() for line in out if run_id(1) in line or run_id(2) in line]
            self.assertEqual([r[0] for r in rows], ["!", "!"])
            self.assertEqual(rows[0][-1], "w1:p1")


if __name__ == "__main__":
    unittest.main()
