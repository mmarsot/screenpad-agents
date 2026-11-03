"""The Runs page and tile as the touch bar shows them, checked against the
app protocol by the stand-in touch bar: one row per project, the joins to
agents and tasks, the warning for more than one active run, the runs
needing you, and a run's card."""

import unittest

from agents_support import SESSION
from bar_support import Apps, FakeClient
from runs_support import detail, run, run_id, scan

from screenpad_agents import runcard
from screenpad_agents.common import ICONS
from screenpad_agents.firstmate import Bearings, Task
from screenpad_agents.fleet import Fleet
from screenpad_agents.herdr import Agent
from screenpad_agents.runs import Runs, widget_id

LIGHTHOUSE = ICONS + "/lighthouse.svg"

API, WEB = "/repos/api", "/repos/web"


def fleet(agents=(), tasks=None, worktrees=None):
    f = Fleet(SESSION, True)
    f.set_agents([Agent(*a) for a in agents])
    f.set_bearings(Bearings(0, False, tasks or {}, worktrees or {}))
    return f


def rid(n):
    return widget_id("run.", run_id(n))


class RunsPageTests(unittest.TestCase):
    def accepted(self, board, f):
        """The stand-in touch bar's Apps after the board's messages."""
        apps, client = Apps(), FakeClient()
        apps.connect(client)
        apps.set_placed(["runs"])
        apps.handle(client, {"op": "hello", "app": "agents", "tiles": ["runs"], "protocol": 2})
        for msg in board.messages(f):
            apps.handle(client, msg)
        self.assertEqual([m for m in client.sent if m["op"] == "error"], [])
        return apps

    def cells(self, board, f):
        page = self.accepted(board, f).pages["runs"]
        return {w.id: w for w in page.widgets}

    def board(self, *args, **kwargs):
        b = Runs()
        b.set_scan(scan(*args, **kwargs))
        return b

    def test_one_row_per_project_active_runs_first_then_the_newest_of_each_branch(self):
        b = self.board(
            [
                (API, [run(5, "fm/new", "completed"), run(4, "fm/fix", "running"), run(3, "fm/new", "failed")]),
                (WEB, []),
            ],
            details=[detail(4, "fm/fix")],
        )
        f = fleet()
        apps = self.accepted(b, f)
        page = apps.pages["runs"]
        self.assertEqual((page.look["title"], page.look["text"], page.columns, page.rows), ("Runs", "1 active", 5, 2))
        self.assertEqual(page.look["icon"], LIGHTHOUSE)
        cells = {w.id: w for w in page.widgets}
        api = [w for w in page.widgets if w.row == 0]
        self.assertEqual([w.look.get("label") for w in api], ["api", "fm/fix", "fm/new"])
        self.assertEqual(cells[rid(4)].look["text"], "running · review")
        self.assertEqual(cells[rid(4)].look["tone"], "accept")
        self.assertEqual((cells[rid(5)].look["text"], cells[rid(5)].look["tone"]), ("passed", "neutral"))
        self.assertNotIn(rid(3), cells)  # superseded by the newer run of fm/new
        web = [w for w in page.widgets if w.row == 1]
        self.assertEqual([(w.look["label"], w.look["text"]) for w in web], [("web", "no active run · no runs yet")])
        tile = {"tone": "accept", "icon": LIGHTHOUSE, "label": "Runs", "text": "1 active"}
        self.assertEqual(apps.provided()["runs"], tile)
        self.assertEqual(b.run_of(rid(4)), run_id(4))

    def test_a_run_is_joined_to_its_agent_by_cwd_and_its_task_by_worktree(self):
        b = self.board(
            [(API, [run(2, "fm/fix", "running", "https://g/o/r/pull/12"), run(1, "fm/docs", "running")])],
            copies=[("/pool/1/api", "fm/fix", 2), ("/pool/2/api", "fm/docs", 1)],
            details=[detail(2, "fm/fix"), detail(1, "fm/docs")],
        )
        f = fleet(
            [("w1:p1", "claude", "working", "/pool/1/api"), ("w2:p1", "claude", "working", "/elsewhere")],
            tasks={"lab:w1:p1": Task("fix-api"), "lab:w2:p1": Task("api-docs")},
            worktrees={"api-docs": "/pool/2/api"},
        )
        views = {v.run.id: v for v in b.views(f)[API]}
        # By the agent's cwd, its task by its endpoint; by the task's worktree, its agent by its endpoint.
        self.assertEqual((views[run_id(2)].pane, views[run_id(2)].task), ("w1:p1", "fix-api"))
        self.assertEqual((views[run_id(1)].pane, views[run_id(1)].task), ("w2:p1", "api-docs"))
        cells = self.cells(b, f)
        self.assertEqual(cells[rid(2)].look["label"], "fix-api")
        self.assertEqual(cells[rid(2)].look["text"], "running · review · PR #12")
        self.assertFalse(any(v.duplicate for v in views.values()))
        # A copy whose axi status names no current branch joins by its run's.
        b.set_scan(scan([(API, [run(2, "fm/fix", "running")])], copies=[("/pool/1/api", None, 2)]))
        self.assertEqual(b.views(f)[API][0].pane, "w1:p1")
        # A run on a branch no copy has is shown without agent or task.
        b.set_scan(scan([(API, [run(3, "fm/lost", "running")])], details=[detail(3, "fm/lost")]))
        self.assertEqual((b.views(f)[API][0].pane, b.views(f)[API][0].task), (None, None))

    def test_more_than_one_active_run_for_one_branch_or_agent_is_the_warning(self):
        same_branch = self.board(
            [(API, [run(2, "fm/fix", "running"), run(1, "fm/fix", "running")])],
            copies=[("/pool/1/api", "fm/fix", 2)],
            details=[detail(2, "fm/fix"), detail(1, "fm/fix", at="test")],
        )
        f = fleet([("w1:p1", "claude", "working", "/pool/1/api")], tasks={"lab:w1:p1": Task("fix-api")})
        cells = self.cells(same_branch, f)
        head = cells[widget_id("proj.", __import__("hashlib").sha256(API.encode()).hexdigest()[:16])]
        self.assertEqual((head.look["tone"], head.look["badge"]), ("reject", "2"))
        self.assertEqual(head.look["text"], "2 active runs for fix-api: at most one each")
        self.assertEqual(cells[rid(1)].look["badge"], "2+")
        msgs = same_branch.messages(f)
        self.assertEqual((msgs[0]["tone"], msgs[0]["text"]), ("reject", "2 active · 2 on one agent"))
        self.assertEqual(msgs[1]["tone"], "reject")
        # Two branches in two copies, both the one agent's: its cwd, and its task's worktree.
        one_agent = self.board(
            [(API, [run(2, "fm/fix", "running"), run(1, "fm/other", "running")])],
            copies=[("/pool/1/api", "fm/fix", 2), ("/pool/2/api", "fm/other", 1)],
            details=[detail(2, "fm/fix"), detail(1, "fm/other")],
        )
        g = fleet(
            [("w1:p1", "claude", "working", "/pool/1/api")],
            tasks={"lab:w1:p1": Task("fix-api")},
            worktrees={"fix-api": "/pool/2/api"},
        )
        self.assertEqual([v.duplicate for v in one_agent.views(g)[API]], [True, True])
        # Two agents with a run each is no warning.
        two = fleet([("w1:p1", "claude", "working", "/pool/1/api"), ("w2:p1", "codex", "working", "/pool/2/api")])
        self.assertEqual([v.duplicate for v in one_agent.views(two)[API]], [False, False])

    def test_runs_needing_you_waiting_on_a_decision_or_failed(self):
        b = self.board(
            [
                (
                    API,
                    [
                        run(4, "fm/gate", "running"),
                        run(3, "fm/broke", "failed"),
                        run(2, "fm/fixed", "completed"),
                        run(1, "fm/fixed", "failed"),
                    ],
                )
            ],
            details=[detail(4, "fm/gate", at="review", step_status="awaiting_approval", findings=2)],
        )
        f = fleet()
        cells = self.cells(b, f)
        self.assertEqual(cells[rid(4)].look["text"], "waiting on you · review")
        self.assertEqual(cells[rid(4)].look["tone"], "warning")
        self.assertEqual((cells[rid(3)].look["text"], cells[rid(3)].look["tone"]), ("failed", "reject"))
        self.assertEqual(b.counts(b.views(f)), (1, 2, 0))  # the old failure of fm/fixed is not counted
        apps = self.accepted(b, f)
        self.assertEqual(apps.provided()["runs"]["text"], "1 active · 2 need you")
        self.assertEqual(apps.provided()["runs"]["badge"], "2")
        self.assertEqual(apps.pages["runs"].look["badge"], "2")
        # Parked at a gate counts too, whatever its steps say.
        b.set_scan(scan([(API, [run(4, "fm/gate", "running")])], details=[detail(4, "fm/gate", parked=True)]))
        self.assertEqual(b.counts(b.views(f)), (1, 1, 0))

    def test_too_many_runs_or_projects(self):
        runs = [run(n, "fm/b%d" % n, "running") for n in range(6)]
        b = self.board([(API, runs)], details=[detail(n, "fm/b%d" % n) for n in range(6)])
        cells = self.cells(b, fleet())
        row = sorted((w for w in cells.values() if w.row == 0), key=lambda w: w.col)
        self.assertEqual([w.look["label"] for w in row[1:]], ["fm/b0", "fm/b1", "fm/b2", "+3 active"])
        projects = [("/repos/p%d" % n, []) for n in range(5)] + [("/repos/busy", [run(9, "fm/x", "running")])]
        b = self.board(projects, details=[detail(9, "fm/x")])
        page = self.accepted(b, fleet()).pages["runs"]
        self.assertEqual(page.rows, 4)
        heads = [w.look["label"] for w in page.widgets if w.col == 0]
        self.assertEqual(heads, ["busy", "p0", "p1", "+3 more projects"])

    def test_nothing_read_yet_or_no_mistakes_failing(self):
        b = Runs()
        self.assertEqual(self.cells(b, fleet())["runs.note"].look["label"], "Reading no-mistakes…")
        b.set_scan(None, "no-mistakes: No such file or directory")
        apps = self.accepted(b, fleet())
        self.assertEqual(apps.pages["runs"].widgets[0].look["label"], "no-mistakes unavailable")
        self.assertEqual(apps.provided()["runs"]["text"], "no-mistakes unavailable")
        self.assertNotIn("icon", apps.provided()["runs"])  # its words show on the bar instead
        b.set_scan(scan([]))
        self.assertEqual(self.cells(b, fleet())["runs.note"].look["label"], "No projects")

    def test_a_runs_card(self):
        b = self.board(
            [(API, [run(2, "fm/fix", "running", "https://g/o/r/pull/12")])],
            copies=[("/pool/1/api", "fm/fix", 2)],
            details=[detail(2, "fm/fix", at="review", step_status="awaiting_approval", findings=2)],
        )
        f = fleet([("w1:p1", "claude", "working", "/pool/1/api")], tasks={"lab:w1:p1": Task("fix-api")})
        self.assertIsNotNone(b.open_card(run_id(2)))
        d = detail(2, "fm/fix", at="review", step_status="awaiting_approval", findings=2)
        d.findings = [("review", "missing-check", "warning"), ("review", "typo", "info")]
        b.set_detail(run_id(2), d)
        cells = self.cells(b, f)
        lines = cells[runcard.LINES].look["lines"]
        self.assertEqual(lines[0], "fm/fix · running · https://g/o/r/pull/12")
        self.assertEqual(lines[1], "intent     completed                1 s")
        self.assertEqual(lines[3], "review     awaiting_approval        4 s  2 findings")
        self.assertIn("waiting on a decision: answer it in the agent's pane", lines)
        self.assertIn("findings: missing-check (warning), typo (info)", lines)
        self.assertEqual(
            (cells[runcard.FOCUS].touch, cells[runcard.FOCUS].look["icon"]), ("tap", ICONS + "/spyglass.svg")
        )
        self.assertEqual(cells[runcard.BACK].look["icon"], ICONS + "/back.svg")
        self.assertEqual(cells[runcard.AGENT].look["label"], "fix-api")
        self.assertEqual(
            cells[runcard.STATE].look["text"], "waiting on you · review · PR #12 · answer it in its agent's pane"
        )
        self.assertEqual(b.card_pane(f), "w1:p1")
        self.assertEqual(b.run_of(rid(2)), None)  # the grid is not shown
        # Without an agent, Focus says so, in place of its icon, and takes no touch.
        focus = self.cells(b, fleet())[runcard.FOCUS]
        self.assertEqual(
            (focus.touch, focus.look["text"], focus.look.get("icon")), ("none", "no agent in Herdr has its copy", None)
        )
        # A long error is wrapped; the card closes when the run leaves the list.
        d.error = "x" * 400
        self.assertTrue(self.cells(b, f)[runcard.LINES].look["lines"][-1].endswith("…"))
        b.set_scan(scan([(API, [])]))
        self.assertIsNone(b.card)

    def test_durations(self):
        self.assertEqual(
            [runcard.duration(ms) for ms in (17, 4000, 484273, 3723000)], ["17 ms", "4 s", "8m 04s", "1h 02m"]
        )


if __name__ == "__main__":
    unittest.main()
