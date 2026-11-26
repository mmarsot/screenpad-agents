"""The Runs page and tile as the touch bar shows them, checked against the
app protocol by the stand-in touch bar: a grid of project cells, a project's
runs, the joins to agents and tasks, the warning for more than one active
run, the runs needing you, a run's card, and Open PR on a run with a pull
request."""

import hashlib
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

    def inside(self, b, repo=API):
        """The project's view of the board: its cell tapped, as the page has it."""
        self.cells(b, fleet())  # the page last built holds the cell's id
        cell = next(w for w, x in self.cells(b, fleet()).items() if x.look.get("label") == repo.rsplit("/", 1)[1])
        self.assertTrue(b.navigate(cell))
        return b

    def labels(self, b, f, projects=False, **where):
        """The labels of the page's widgets (those matching where; projects:
        only the project cells)."""
        page = self.accepted(b, f).pages["runs"]
        return [
            w.look["label"]
            for w in page.widgets
            if all(getattr(w, k) == v for k, v in where.items()) and (not projects or w.id.startswith("proj."))
        ]

    def test_a_grid_of_project_cells_then_the_project_s_runs_active_first(self):
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
        self.assertEqual((page.look["title"], page.look["text"], page.columns, page.rows), ("Runs", "1 active", 6, 4))
        self.assertEqual(page.look["icon"], LIGHTHOUSE)
        # A cell per project, two columns wide, three to a row, each a tap.
        self.assertEqual(
            [(w.look["label"], w.look["text"], w.col, w.row, w.cols, w.touch) for w in page.widgets],
            [("api", "1 active", 0, 0, 2, "tap"), ("web", "no active run · no runs yet", 2, 0, 2, "tap")],
        )
        self.assertEqual(
            self.cells(b, f)[widget_id("proj.", hashlib.sha256(API.encode()).hexdigest()[:16])].look["tone"], "neutral"
        )
        tile = {"tone": "accept", "icon": LIGHTHOUSE, "label": "Runs", "text": "1 active"}
        self.assertEqual(apps.provided()["runs"], tile)
        # A tap on api shows all its runs, the active ones first.
        self.inside(b)
        page = self.accepted(b, f).pages["runs"]
        self.assertEqual((page.columns, page.rows), (6, 4))
        top = [w for w in page.widgets if w.row == 0]
        self.assertEqual(
            [(w.id, w.look["label"], w.touch) for w in top], [("runs.up", "Back", "tap"), ("runs.title", "api", "none")]
        )
        self.assertEqual(top[1].look["text"], "1 active")
        cells = {w.id: w for w in page.widgets}
        runs = [w for w in page.widgets if w.row == 1]
        self.assertEqual([(w.id, w.col, w.cols) for w in runs], [(rid(4), 0, 2), (rid(5), 2, 2), (rid(3), 4, 2)])
        self.assertEqual([w.look["label"] for w in runs], ["fm/fix", "fm/new", "fm/new"])
        self.assertEqual((cells[rid(4)].look["text"], cells[rid(4)].look["tone"]), ("running · review", "accept"))
        self.assertEqual((cells[rid(5)].look["text"], cells[rid(5)].look["tone"]), ("passed", "neutral"))
        self.assertEqual((cells[rid(3)].look["text"], cells[rid(3)].look["tone"]), ("failed", "neutral"))  # superseded
        self.assertEqual(b.run_of(rid(4)), run_id(4))
        # Back returns to the grid; a tap on a widget no longer drawn does nothing.
        self.assertTrue(b.navigate("runs.up"))
        self.assertEqual(self.labels(b, f), ["api", "web"])
        self.assertFalse(b.navigate("runs.up"))
        self.assertFalse(b.navigate(rid(4)))

    def test_a_project_with_no_runs_says_so_and_a_card_returns_to_the_project(self):
        b = self.board([(API, [run(2, "fm/fix", "running")]), (WEB, [])], details=[detail(2, "fm/fix")])
        f = fleet()
        self.inside(b, WEB)
        self.assertEqual(self.labels(b, f), ["Back", "web", "No runs yet"])
        self.assertTrue(b.navigate("runs.up"))
        self.inside(b)
        b.open_card(run_id(2))
        self.assertIn(runcard.LINES, self.cells(b, f))
        b.close_card()
        self.assertEqual(self.labels(b, f, row=0), ["Back", "api"])  # still in the project
        # A project that leaves the scan closes its view.
        b.set_scan(scan([(WEB, [])]))
        self.assertEqual(self.labels(b, f), ["web"])

    def test_a_project_with_more_runs_than_a_page_takes_pages_of_nine(self):
        runs = [run(n, "fm/b%d" % n, "completed") for n in range(11)] + [run(20, "fm/live", "running")]
        b = self.board([(API, runs)], details=[detail(20, "fm/live")])
        f = fleet()
        self.inside(b)
        page = self.accepted(b, f).pages["runs"]
        self.assertEqual(
            (page.rows, [w.look["label"] for w in page.widgets if w.row == 0]), (4, ["Back", "api", "Prev", "Next"])
        )
        shown = [w.look["label"] for w in page.widgets if w.row > 0]
        self.assertEqual(shown, ["fm/live"] + ["fm/b%d" % n for n in range(8)])  # the active one first
        cells = {w.id: w for w in page.widgets}
        self.assertEqual(cells["runs.title"].look["text"], "1-9 of 12 runs")
        self.assertEqual((cells["runs.rprev"].touch, cells["runs.rnext"].touch), ("none", "tap"))
        self.assertTrue(b.navigate("runs.rnext"))
        page = self.accepted(b, f).pages["runs"]
        self.assertEqual([w.look["label"] for w in page.widgets if w.row > 0], ["fm/b8", "fm/b9", "fm/b10"])
        cells = {w.id: w for w in page.widgets}
        self.assertEqual((cells["runs.title"].look["text"], cells["runs.rnext"].touch), ("10-12 of 12 runs", "none"))
        self.assertFalse(b.navigate("runs.rnext"))
        self.assertTrue(b.navigate("runs.rprev"))
        self.assertEqual(self.accepted(b, f).pages["runs"].widgets[1].look["text"], "1-9 of 12 runs")
        # The project's pages are not the projects': Back finds the grid on its own page.
        self.assertEqual(b.offset, 0)

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
        cells = self.cells(self.inside(b), f)
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
        head = self.cells(same_branch, f)[widget_id("proj.", hashlib.sha256(API.encode()).hexdigest()[:16])]
        self.assertEqual((head.look["tone"], head.look["badge"]), ("reject", "2"))
        self.assertEqual(head.look["text"], "2 active runs for fix-api: at most one each")
        title = self.cells(self.inside(same_branch), f)["runs.title"]
        self.assertEqual((title.look["tone"], title.look["badge"]), ("reject", "2"))
        self.assertEqual(self.cells(same_branch, f)[rid(1)].look["badge"], "2+")
        self.assertTrue(same_branch.navigate("runs.up"))
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
        self.assertEqual(
            self.cells(b, f)[widget_id("proj.", hashlib.sha256(API.encode()).hexdigest()[:16])].look["text"],
            "1 active · 2 need you",
        )
        cells = self.cells(self.inside(b), f)
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

    def test_too_many_projects_take_pages_of_nine_in_the_scan_s_order(self):
        projects = [("/repos/p%d" % n, []) for n in range(13)] + [("/repos/busy", [run(9, "fm/x", "running")])]
        b = self.board(projects, details=[detail(9, "fm/x")])
        f = fleet()
        # More than nine take pages of nine, the pager under them.
        self.assertEqual(self.labels(b, f, projects=True), ["p%d" % n for n in range(9)])
        self.assertEqual(self.accepted(b, f).pages["runs"].rows, 4)
        cells = self.cells(b, f)
        self.assertEqual(cells["runs.span"].look["label"], "1-9 of 14")
        self.assertEqual((cells["runs.prev"].touch, cells["runs.next"].touch), ("none", "tap"))
        self.assertEqual(cells["runs.next"].row, 3)
        self.assertTrue(b.turn("runs.next"))
        self.assertEqual(self.labels(b, f, projects=True), ["p9", "p10", "p11", "p12", "busy"])
        busy = next(w for w in self.accepted(b, f).pages["runs"].widgets if w.look["label"] == "busy")
        self.assertEqual((busy.look["text"], busy.look["tone"]), ("1 active", "neutral"))
        self.assertEqual(self.cells(b, f)["runs.span"].look["label"], "10-14 of 14")
        self.assertEqual(self.cells(b, f)["runs.next"].touch, "none")
        self.assertFalse(b.turn("runs.next"))  # nothing past the last page
        # A tap on busy opens it, and Back returns to the same page.
        self.assertTrue(b.navigate(next(w for w, x in self.cells(b, f).items() if x.look.get("label") == "busy")))
        self.assertEqual(self.labels(b, f, row=0), ["Back", "busy"])
        self.assertTrue(b.navigate("runs.up"))
        self.assertEqual(self.labels(b, f, projects=True), ["p9", "p10", "p11", "p12", "busy"])

    def test_the_grid_cells_are_the_same_size_whatever_the_number_on_the_page(self):
        # One project, a partial page, a full page, a second page and twelve
        # (ten to twelve used to grow the grid to four rows of projects): the grid is always
        # four rows, a project's cell two columns by one row at its slot, and
        # the slots without a project hold nothing.
        for count in (1, 4, 9, 12):
            b = self.board([("/repos/p%d" % n, []) for n in range(count)])
            f = fleet()
            page = self.accepted(b, f).pages["runs"]
            self.assertEqual((page.columns, page.rows), (6, 4), count)
            shown = [w for w in page.widgets if w.id.startswith("proj.")]
            self.assertEqual(len(shown), min(count, 9), count)
            self.assertEqual(
                [(w.col, w.row, w.cols) for w in shown],
                [(2 * (i % 3), i // 3, 2) for i in range(len(shown))],
                count,
            )
            self.assertEqual({w.touch for w in shown}, {"tap"})
            self.assertEqual(len(page.widgets), len(shown) + (3 if count > 9 else 0), count)
        # A project's runs: the same, one run or nine.
        for count in (1, 5, 9):
            b = self.board([(API, [run(n, "fm/b%d" % n, "completed") for n in range(count)])])
            self.inside(b)
            page = self.accepted(b, fleet()).pages["runs"]
            self.assertEqual((page.columns, page.rows), (6, 4), count)
            runs = [w for w in page.widgets if w.row > 0]
            self.assertEqual(
                [(w.col, w.row, w.cols) for w in runs], [(2 * (i % 3), 1 + i // 3, 2) for i in range(count)], count
            )

    def test_with_many_machines_down_a_row_of_projects_and_the_pager_still_fit(self):
        # Three or four machines unreachable and more projects than a page: the
        # bar's four rows hold one down row, one that counts the others, a row
        # of three projects and the pager.
        machines = ["m1", "m2", "m3", "m4"]
        for down in (machines[:3], machines):
            b = Runs(False, machines)
            b.set_scan(scan([("/repos/p%d" % n, []) for n in range(7)]))
            for name in down:
                b.set_remote(name, None, "ssh: no route to host", True)
            f = fleet()
            page = self.accepted(b, f).pages["runs"]
            self.assertEqual(page.rows, 4)
            rows = {w.id: w for w in page.widgets}
            self.assertEqual((rows["runs.down.m1"].row, rows["runs.down.m1"].look["label"]), (0, "m1 unreachable"))
            more = next(w for w in page.widgets if w.row == 1)
            self.assertEqual(more.look["label"], "%d more machines not read" % (len(down) - 1))
            self.assertEqual(more.look["text"], ", ".join(down[1:]))
            self.assertEqual(self.labels(b, f, projects=True), ["p0", "p1", "p2"])
            self.assertEqual((rows["runs.span"].look["label"], rows["runs.next"].row), ("1-3 of 7", 3))
            self.assertTrue(b.turn("runs.next"))
            self.assertEqual(self.labels(b, f, projects=True), ["p3", "p4", "p5"])

    def test_a_project_starting_a_run_does_not_reshuffle_the_pages(self):
        projects = [("/repos/p%d" % n, []) for n in range(13)]
        b = self.board(projects)
        f = fleet()
        self.assertTrue((self.cells(b, f), b.turn("runs.next"))[1])
        self.assertEqual(self.labels(b, f, projects=True), ["p9", "p10", "p11", "p12"])
        projects[12] = ("/repos/p12", [run(9, "fm/x", "running")])
        b.set_scan(scan(projects))
        self.assertEqual(self.labels(b, f, projects=True), ["p9", "p10", "p11", "p12"])
        self.assertTrue((self.cells(b, f), b.turn("runs.prev"))[1])
        self.assertEqual(self.labels(b, f, projects=True), ["p%d" % n for n in range(9)])
        # Nine projects fit one page: no pager, and the offset is forgotten.
        b = self.board([("/repos/p%d" % n, []) for n in range(9)])
        self.assertNotIn("runs.next", self.cells(b, f))
        self.assertFalse(b.turn("runs.next"))

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
        self.assertIn("icon", self.accepted(b, fleet()).provided()["runs"])
        b.set_scan(None, "no-mistakes: timed out")  # failing after a good scan: the stale runs stay on the page
        tile = self.accepted(b, fleet()).provided()["runs"]
        self.assertEqual(tile["text"], "no-mistakes unavailable")
        self.assertNotIn("icon", tile)

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

    def test_open_pr_shows_once_the_run_has_a_pull_request_on_the_forge(self):
        url = "https://github.com/o/r/pull/12"
        f = fleet()
        cases = [
            # (run, its detail, the card's detail): no PR yet, at CI, passed, failed with one.
            (run(2, "fm/fix", "running"), detail(2, "fm/fix", at="push"), None),
            (run(2, "fm/fix", "running", url), detail(2, "fm/fix", at="ci"), url),
            (run(2, "fm/fix", "completed", url), None, url),
            (run(2, "fm/fix", "failed", url), None, url),
            (run(2, "fm/fix", "completed", "https://gitlab.com/o/r/pull/12"), None, None),  # not the forge
            (run(2, "fm/fix", "completed", "http://github.com/o/r/pull/12"), None, None),  # not https
        ]
        for r, d, shown in cases:
            with self.subTest(status=r.status, pr=r.pr):
                b = self.inside(self.board([(API, [r])], details=[d] if d else []))
                cell = self.cells(b, f)[rid(2)]
                self.assertEqual(cell.touch, "tap")
                self.assertNotIn("hold", cell.look["text"])
                self.assertEqual(b.pr_of(f, run_id(2)), shown)
                b.open_card(run_id(2))
                cells = self.cells(b, f)
                if shown:
                    pr = cells[runcard.PR]
                    self.assertEqual((pr.col, pr.row, pr.touch), (4, 3, "tap"))
                    self.assertEqual((pr.look["label"], pr.look["icon"]), ("Open PR #12", ICONS + "/flag.svg"))
                    self.assertEqual(cells[runcard.STATE].cols, 4)
                else:
                    self.assertNotIn(runcard.PR, cells)
                    self.assertEqual(cells[runcard.STATE].cols, 5)
        # The card's own read gives the PR before the run list does.
        b = self.board([(API, [run(2, "fm/fix", "running")])], details=[detail(2, "fm/fix", at="pr")])
        b.open_card(run_id(2))
        d = detail(2, "fm/fix", at="ci")
        d.pr = url
        b.set_detail(run_id(2), d)
        self.assertEqual(self.cells(b, f)[runcard.PR].look["label"], "Open PR #12")

    def test_open_pr_says_it_is_opening_then_whether_it_opened(self):
        url = "https://github.com/o/r/pull/12"
        b = self.board([(API, [run(2, "fm/fix", "completed", url)])])
        f = fleet()
        card = b.open_card(run_id(2))
        self.assertTrue(card.open_pr(url))
        self.assertFalse(card.open_pr(url))  # one open at a time
        pr = self.cells(b, f)[runcard.PR]
        self.assertEqual((pr.look["label"], pr.touch), ("Opening PR…", "none"))
        b.set_opened(run_id(2), url, "systemd-run not found")
        pr = self.cells(b, f)[runcard.PR]
        self.assertEqual(
            (pr.look["label"], pr.look["text"], pr.look["tone"], pr.look.get("icon")),
            ("Open PR #12", "not opened: systemd-run not found", "reject", None),
        )
        self.assertTrue(card.open_pr(url))  # a tap tries again
        b.set_opened(run_id(2), url, None)
        pr = self.cells(b, f)[runcard.PR]
        self.assertEqual((pr.look["label"], pr.touch, pr.look["icon"]), ("PR #12 opened", "tap", ICONS + "/flag.svg"))
        b.set_opened(run_id(3), url, "late")  # another run's: ignored
        self.assertEqual(self.cells(b, f)[runcard.PR].look["label"], "PR #12 opened")

    def test_durations(self):
        self.assertEqual(
            [runcard.duration(ms) for ms in (17, 4000, 484273, 3723000)], ["17 ms", "4 s", "8m 04s", "1h 02m"]
        )


if __name__ == "__main__":
    unittest.main()
