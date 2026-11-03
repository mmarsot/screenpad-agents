"""no-mistakes as the Runs page reads it: the client against a fake CLI (only
read-only commands, in the right directory), its TOON reader, and the scan
of projects and copies, with firstmate's clones and task worktrees."""

import os
import subprocess
import tempfile
import unittest

from agents_support import write_json
from runs_support import (
    FakeNoMistakes,
    detail,
    detail_state,
    fake_no_mistakes,
    read_nm_calls,
    run,
    run_id,
    run_row,
)

from screenpad_agents.config import Runs as RunsSettings
from screenpad_agents.nomistakes import NoMistakes, NoMistakesError, NotARepo, read_only, toon
from screenpad_agents.runwatch import RunsWatch

# no-mistakes 1.106's own output, trimmed: axi in a worktree, and a run in detail.
HOME = """\
bin: ~/.no-mistakes/bin/no-mistakes
description: "Validate your code changes through the no-mistakes pipeline, before they reach the target."
repo: /home/u/firstmate/projects/screenpad-linux
current_branch: unknown
daemon: running
count: 2 of 24 total
runs[2]{id,branch,status,head,pr}:
  "01M6GNTQTCC9X19MXGM8EE4BA9",fm/screenpad-generic-slots,running,a4d609fe,"https://github.com/o/r/pull/22"
  "01M6GDNJNN7MQM1V5R9GEM3N8S",fm/screenpad-fn-f6-toggle,cancelled,"02a83b82","https://github.com/o/r/pull/15"
help[2]: "Run `no-mistakes axi run --intent \\"<goal>\\"` to validate","Commit follow-up work, on top"
"""
STATUS = """\
current_branch: fm/screenpad-generic-slots
run:
  id: "01M6GNTQTCC9X19MXGM8EE4BA9"
  branch: fm/screenpad-generic-slots
  status: running
  awaiting_agent: parked 2m
  head: a4d609fe
  verification_plan: none
  pr: "https://github.com/o/r/pull/22"
  findings: 2 warning
  steps[3]{step,status,findings,duration_ms}:
    intent,completed,0,14
    review,awaiting_approval,2,484273
    ci,pending,0,0
  active_steps[1]{step,status,active_for,round_active_for,last_activity,agent_pid,round}:
    review,awaiting_approval,8m4s,8m4s,"2m9s ago: log: waiting, for you","",1
outcome: failed
error: "step push failed: \\"refusing\\", see logs"
"""


class ToonTests(unittest.TestCase):
    def test_no_mistakes_own_output(self):
        home = toon(HOME)
        self.assertEqual(home["repo"], "/home/u/firstmate/projects/screenpad-linux")
        self.assertEqual(home["runs"][0]["id"], "01M6GNTQTCC9X19MXGM8EE4BA9")
        self.assertEqual(home["runs"][1]["head"], "02a83b82")
        self.assertEqual(home["runs"][1]["pr"], "https://github.com/o/r/pull/15")
        self.assertEqual(home["help"][0], 'Run `no-mistakes axi run --intent "<goal>"` to validate')
        status = toon(STATUS)
        self.assertEqual(
            status["run"]["steps"][1],
            {"step": "review", "status": "awaiting_approval"}
            | {
                "findings": "2",
                "duration_ms": "484273",
            },
        )
        self.assertEqual(status["run"]["active_steps"][0]["last_activity"], "2m9s ago: log: waiting, for you")
        self.assertEqual(status["error"], 'step push failed: "refusing", see logs')
        self.assertEqual(toon(""), {})
        self.assertEqual(toon("a[0]:\nb: []\n"), {"a": [], "b": "[]"})
        with self.assertRaises(ValueError):
            toon('a: "unterminated\n')


class ClientTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.bin = os.path.join(self.dir, "bin")
        os.mkdir(self.bin)
        self.nm = NoMistakes([fake_no_mistakes(self.bin)])
        self.repo = os.path.join(self.dir, "repo")
        self.copy = os.path.join(self.dir, "copy")
        for d in (self.repo, self.copy, os.path.join(self.dir, "plain"), os.path.join(self.dir, "fresh")):
            os.mkdir(d)
        self.state = {
            "dirs": {
                self.repo: {"repo": self.repo, "branch": "main", "run": None},
                self.copy: {"repo": self.repo, "branch": "fm/fix", "run": run_id(2)},
                os.path.join(self.dir, "fresh"): "not-init",
            },
            "runs": {self.repo: [run_row(2, "fm/fix", "running", "https://x/pull/7"), run_row(1, "fm/old", "failed")]},
            "details": {
                run_id(2): detail_state(
                    "fm/fix",
                    steps=[("intent", "completed", 0, 14), ("review", "awaiting_approval", 2, 900)],
                    parked="parked 1m",
                ),
                run_id(1): detail_state(
                    "fm/old",
                    "failed",
                    [("push", "failed", 0, 527)],
                    findings="6 info",
                    outcome="failed",
                    error="push, failed",
                ),
            },
            "rounds": {run_id(2): {"review": [{"id": "missing-check", "severity": "warning"}, {"id": "typo"}]}},
        }
        write_json(os.path.join(self.bin, "nm.json"), self.state)

    def test_reads_a_repos_runs_and_a_copys_branch_in_that_directory(self):
        repo, runs = self.nm.listing(self.copy)
        self.assertEqual(repo, self.repo)
        self.assertEqual(runs, [run(2, "fm/fix", "running", "https://x/pull/7"), run(1, "fm/old", "failed")])
        self.assertEqual([r.active for r in runs], [True, False])
        self.assertEqual(self.nm.current(self.copy), ("fm/fix", run_id(2)))
        self.assertEqual(self.nm.current(self.repo), ("main", None))
        calls = read_nm_calls(self.bin)
        self.assertEqual(
            calls,
            [
                {"args": ["axi"], "cwd": self.copy},
                {"args": ["axi", "status"], "cwd": self.copy},
                {"args": ["axi", "status"], "cwd": self.repo},
            ],
        )

    def test_a_run_in_detail_and_its_findings(self):
        d = self.nm.detail(run_id(2))
        self.assertEqual((d.branch, d.status, d.parked, d.waiting), ("fm/fix", "running", True, True))
        self.assertEqual(
            [(s.name, s.status, s.findings, s.duration_ms) for s in d.steps],
            [
                ("intent", "completed", 0, 14),
                ("review", "awaiting_approval", 2, 900),
            ],
        )
        self.assertEqual(d.step().name, "review")
        self.assertEqual(self.nm.findings(run_id(2), "review"), [("missing-check", "warning"), ("typo", "?")])
        self.assertEqual(self.nm.findings(run_id(2), "test"), [])
        old = self.nm.detail(run_id(1))
        self.assertEqual(
            (old.summary, old.outcome, old.error, old.waiting), ("6 info", "failed", "push, failed", False)
        )
        with self.assertRaisesRegex(NoMistakesError, "not found"):
            self.nm.detail(run_id(9))
        args = [c["args"] for c in read_nm_calls(self.bin)]
        self.assertEqual(args[0], ["axi", "status", "--run", run_id(2)])
        self.assertEqual(args[1], ["axi", "rounds", "--run", run_id(2), "--step", "review", "--json"])

    def test_only_read_only_commands_run(self):
        for bad in ("--yes", "x;y", "", None, "../run"):
            with self.subTest(bad=bad), self.assertRaises(NoMistakesError):
                self.nm.detail(bad)
        with self.assertRaises(NoMistakesError):
            self.nm.findings(run_id(2), "review --yes")
        acting = [["axi", "run"], ["axi", "respond"], ["axi", "abort"], ["axi", "retry"], ["axi", "sync"]]
        acting += [["axi", "status", "--yes"], ["axi", "status", "--run", "x", "--yes"], ["daemon", "stop"], ["rerun"]]
        for words in acting:
            with self.subTest(words=words), self.assertRaisesRegex(NoMistakesError, "not a read-only"):
                self.nm._call(words)
        self.nm.listing(self.repo)
        self.nm.current(self.repo)
        self.nm.detail(run_id(2))
        self.nm.findings(run_id(2), "review")
        calls = read_nm_calls(self.bin)
        self.assertEqual(len(calls), 4)
        for c in calls:
            self.assertTrue(read_only(c["args"]), c)

    def test_directories_it_cannot_watch(self):
        for d in (os.path.join(self.dir, "plain"), os.path.join(self.dir, "fresh"), os.path.join(self.dir, "gone")):
            with self.subTest(d=d), self.assertRaises(NotARepo):
                self.nm.listing(d)

    def test_failures_say_why(self):
        write_json(os.path.join(self.bin, "nm.json"), "hang")
        slow = NoMistakes(self.nm.command, timeout=0.5)
        with self.assertRaisesRegex(NoMistakesError, "no answer in 0.5 s"):
            slow.listing(self.repo)
        with self.assertRaisesRegex(NoMistakesError, "/nonexistent/no-mistakes"):
            NoMistakes(["/nonexistent/no-mistakes"]).listing(self.repo)

        def garbled(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, "repo: relative\n", "")

        with self.assertRaisesRegex(NoMistakesError, "named no repository"):
            NoMistakes(["nm"], run=garbled).listing(self.repo)


class ScanTests(unittest.TestCase):
    """The scan of runwatch.py over a FakeNoMistakes, with a throwaway
    firstmate home whose projects/ holds the clones."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = os.path.join(tmp.name, "fmhome")
        self.clone = os.path.join(self.home, "projects", "api")
        self.other = os.path.join(self.home, "projects", "web")
        for d in (self.clone, self.other, os.path.join(self.home, "projects", ".hidden")):
            os.makedirs(d)
        self.task = os.path.join(tmp.name, "pool", "1", "api")
        self.extra = os.path.join(tmp.name, "extra")
        self.nm = FakeNoMistakes()
        self.nm.dirs = {
            self.clone: (self.clone, "main", None),
            self.task: (self.clone, "fm/fix", run_id(2)),
            self.extra: (self.extra, "main", None),
        }
        self.nm.runs = {self.clone: [run(2, "fm/fix", "running"), run(1, "fm/old")], self.extra: []}
        self.nm.details = {run_id(2): detail(2, "fm/fix")}

    def watch(self, repos=(), firstmate=True):
        return RunsWatch(RunsSettings(list(repos), firstmate), self.nm, self.home, None)

    def test_firstmate_clones_and_task_copies_are_one_project(self):
        scan = self.watch([self.extra]).scan((self.task,), ("/w/elsewhere",))
        self.assertEqual([p.repo for p in scan.projects], [self.extra, self.clone])
        self.assertEqual([c.path for c in scan.copies], [os.path.realpath(self.task)])
        self.assertEqual(list(scan.details), [run_id(2)])  # the active run only
        self.assertTrue(scan.active())
        listed = [c[1] for c in self.nm.calls if c[0] == "listing"]
        self.assertEqual(listed, [self.extra, self.clone, self.other, self.task])
        self.assertNotIn(os.path.join(self.home, "projects", ".hidden"), listed)

    def test_without_firstmate_only_the_repos_configured(self):
        scan = self.watch([self.extra], firstmate=False).scan((self.task,), ())
        self.assertEqual([p.repo for p in scan.projects], [self.extra])
        self.assertNotIn(self.clone, [c[1] for c in self.nm.calls])

    def test_a_configured_repo_it_cannot_read_is_shown_with_why(self):
        scan = self.watch([self.other], firstmate=False).scan()
        self.assertEqual([(p.repo, p.error) for p in scan.projects], [(self.other, "not in a git repository")])
        self.nm.error = "no-mistakes: No such file or directory"
        with self.assertRaisesRegex(NoMistakesError, "No such file"):
            self.watch([self.other]).scan()


if __name__ == "__main__":
    unittest.main()
