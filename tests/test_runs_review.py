"""A run whose pull request is ready for the captain, and Watch, on the Runs
page: which run's card gets Review, Approve and Request changes (and which
does not), where the buttons sit in the card's bottom row, Watch and its
`[runs] watch_command` (a stand-in launcher: nothing opens on the screen),
the buttons in the loop (one note per verdict, the review opened through
the review command), and focusing a done agent whose run is ready opening
the review. no-mistakes, Herdr and firstmate are fakes."""

import os
import tempfile
import time
import unittest
from unittest import mock

from agents_support import SESSION, FakeFirstmate, FakeHerdr, Rig, config, read_calls, write_script
from bar_support import Apps, FakeClient
from desktop_support import fake_scope
from runs_support import FakeNoMistakes, run, run_id, scan

from screenpad_agents import reviewcall, runcard
from screenpad_agents.config import Runs as RunsSettings
from screenpad_agents.config import parse
from screenpad_agents.desktop import DesktopError
from screenpad_agents.firstmate import Bearings, Task
from screenpad_agents.fleet import Fleet
from screenpad_agents.herdr import Agent
from screenpad_agents.reviewrequest import Reviews
from screenpad_agents.runwatch import start_watch
from screenpad_agents.runs import Runs, widget_id

API, COPY = "/repos/api", "/pool/1/api"
URL = "https://github.com/o/r/pull/12"
HEAD = "a4d609fe"  # runs_support's runs


def fleet(review=("/opt/review", "{task}"), task="fix-api"):
    """The Agents page's model with one task in COPY and a Reviews like the app's."""
    f = Fleet(SESSION, True)
    f.set_agents([Agent("w1:p1", "claude", "idle", COPY)])
    f.set_bearings(Bearings(0, False, {"lab:w1:p1": Task(task)} if task else {}, {task: COPY} if task else {}))
    firstmate = FakeFirstmate()
    firstmate.review = list(review) if review else None
    f.reviews = Reviews(firstmate, None, None, lambda line: None)
    return f


def card(f, runs, watch=False, copies=((COPY, "fm/fix", 2),), details=()):
    """The widgets of run 2's card, by id, as the stand-in touch bar accepts them."""
    board = Runs(watch=watch)
    board.set_scan(scan([(API, runs)], copies=copies, details=details))
    board.open_card(run_id(2))
    apps, client = Apps(), FakeClient()
    apps.connect(client)
    apps.set_placed(["runs"])
    apps.handle(client, {"op": "hello", "app": "agents", "tiles": ["runs"], "protocol": 2})
    for msg in board.messages(f):
        apps.handle(client, msg)
    assert [m for m in client.sent if m["op"] == "error"] == [], client.sent
    return board, {w.id: w for w in apps.pages["runs"].widgets}


READY = [run(2, "fm/fix", "completed", URL), run(1, "fm/old", "completed")]


class CardTests(unittest.TestCase):
    def bottom(self, cells):
        """(col, cols) of each widget in the bottom row, by id prefix."""
        return {i: (w.col, w.cols) for i, w in cells.items() if w.row == 3}

    def test_a_ready_pull_request_gets_the_review_buttons_watch_and_open_pr_in_the_bottom_row(self):
        board, cells = card(fleet(), READY, watch=True)
        self.assertEqual(board.card_review(fleet()).pr, URL)
        row = sorted((w.col, i, w.look["label"]) for i, w in cells.items() if w.row == 3)
        self.assertEqual(
            [(c, label) for c, _, label in row],
            [(0, "Review"), (1, "Approve"), (2, "Changes"), (3, "Watch"), (4, "Open PR #12")],
        )
        self.assertNotIn(runcard.STATE, cells)  # no room for it: its project is on the first line
        self.assertEqual(cells[runcard.LINES].look["lines"][0], "api · fm/fix · completed · %s" % URL)
        self.assertTrue(all(cells[i].touch == "tap" for _, i, _ in row))
        ids = [i for _, i, _ in row]
        token = reviewcall.token(board.card_review(fleet()))
        self.assertEqual(ids[:3], ["call.rv.%s.idle.%s" % (act, token) for act in ("open", "approve", "changes")])
        self.assertEqual((ids[3], ids[4]), (runcard.WATCH, runcard.PR))
        # Every id is one the protocol takes (the stand-in checked it), and the labels fit a fifth of the bar.
        self.assertTrue(all(len(w.look["label"]) <= runcard.CARD_LABEL for w in cells.values() if w.row == 3))

    def test_without_watch_the_state_keeps_a_cell(self):
        _, cells = card(fleet(), READY)
        self.assertEqual((cells[runcard.STATE].col, cells[runcard.STATE].cols), (0, 1))
        self.assertEqual(cells[runcard.STATE].look["text"], "passed · PR #12")
        self.assertNotIn(runcard.WATCH, cells)
        self.assertEqual(cells[runcard.LINES].look["lines"][0], "fm/fix · completed · %s" % URL)

    def test_without_a_review_command_only_approve_is_shown(self):
        _, cells = card(fleet(review=None), READY, watch=True)
        labels = sorted((w.col, w.look["label"]) for w in cells.values() if w.row == 3 and w.id != runcard.STATE)
        self.assertEqual(labels, [(2, "Approve"), (3, "Watch"), (4, "Open PR #12")])
        self.assertEqual((cells[runcard.STATE].col, cells[runcard.STATE].cols), (0, 2))

    def test_a_run_not_ready_or_without_a_task_gets_open_pr_only(self):
        cases = {
            "no task": (fleet(task=None), READY, [(COPY, "fm/fix", 2)]),
            "no copy": (fleet(), READY, []),
            "running": (fleet(), [run(2, "fm/fix", "running", URL)], [(COPY, "fm/fix", 2)]),
            "failed": (fleet(), [run(2, "fm/fix", "failed", URL)], [(COPY, "fm/fix", 2)]),
            "not the forge": (
                fleet(),
                [run(2, "fm/fix", "completed", "https://gitlab.com/o/r/pull/12")],
                [(COPY, "fm/fix", 2)],
            ),
            "no pull request": (fleet(), [run(2, "fm/fix", "completed")], [(COPY, "fm/fix", 2)]),
        }
        for name, (f, runs, copies) in cases.items():
            with self.subTest(name):
                board, cells = card(f, runs, copies=copies)
                self.assertIsNone(board.card_review(f))
                self.assertEqual([i for i in cells if i.startswith("call.rv.")], [])
                self.assertEqual(cells[runcard.STATE].cols, 4 if runcard.PR in cells else 5)

    def test_only_the_newest_run_of_a_branch_is_a_change_ready_for_review(self):
        runs = [run(3, "fm/fix", "completed", "https://github.com/o/r/pull/13"), run(2, "fm/fix", "completed", URL)]
        f = fleet()
        board, cells = card(f, runs, copies=[(COPY, "fm/fix", 3)])
        self.assertIsNone(board.card_review(f))  # run 2's card, a superseded run
        self.assertEqual([i for i in cells if i.startswith("call.rv.")], [])

    def test_a_run_without_a_head_can_be_reviewed_but_not_approved(self):
        r = run(2, "fm/fix", "completed", URL)
        r.head = None
        f = fleet()
        _, cells = card(f, [r])
        self.assertEqual(sorted(w.look["label"] for w in cells.values() if w.id.startswith("call.rv.")), ["Review"])
        _, cells = card(fleet(review=None), [r])  # no review command either: nothing to press
        self.assertEqual([i for i in cells if i.startswith("call.rv.")], [])

    def test_the_state_of_a_verdict_shows_on_the_card(self):
        f = fleet()
        board, cells = card(f, READY)
        review = board.card_review(f)
        entry = f.reviews.entries.setdefault(reviewcall.key(review), reviewcall.Entry())
        entry.verdict, entry.phase = reviewcall.APPROVE, reviewcall.SENT
        _, cells = card(f, READY)
        by_label = {w.look["label"]: w for w in cells.values() if w.id.startswith("call.rv.")}
        self.assertEqual((by_label["Approved"].touch, by_label["Approved"].look["text"]), ("none", "sent to firstmate"))
        self.assertEqual(by_label["Changes"].look["text"], "the other answer is sent")

    def test_watch_says_it_is_starting_then_whether_it_started(self):
        board, cells = card(fleet(), [run(2, "fm/fix", "running")], watch=True)
        self.assertEqual((cells[runcard.WATCH].look["label"], cells[runcard.WATCH].touch), ("Watch", "tap"))
        self.assertEqual((cells[runcard.STATE].col, cells[runcard.STATE].cols), (0, 4))
        c = board.card
        self.assertTrue(c.start_watch())
        self.assertFalse(c.start_watch())  # one start at a time
        self.assertEqual(c.watch_button()["touch"], "none")
        board.set_launched(run_id(2), "systemd-run not found")
        self.assertEqual(
            (c.watch_button()["text"], c.watch_button()["tone"]), ("not opened: systemd-run not found", "reject")
        )
        self.assertTrue(c.start_watch())
        board.set_launched(run_id(2), None)
        self.assertEqual(c.watch_button()["text"], "opened on the main screen")
        board.set_launched(run_id(3), "late")  # another run's: ignored
        self.assertEqual(c.watch_button()["text"], "opened on the main screen")


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.herdr = FakeHerdr([Agent("w1:p1", "claude", "idle", COPY)])
        self.firstmate = FakeFirstmate()
        self.firstmate.review = ["/opt/review", "{task}"]
        self.firstmate.bearings = Bearings(0, False, {"lab:w1:p1": Task("fix-api")}, {"fix-api": COPY})
        self.nm = FakeNoMistakes()
        self.nm.dirs = {API: (API, "main", None), COPY: (API, "fm/fix", run_id(2))}
        self.nm.runs = {API: [run(2, "fm/fix", "completed", URL), run(1, "fm/old", "completed")]}
        self.watched, self.watch_error = [], None

    def launch(self, argv):
        """The stand-in for the watch window: records the command, or fails."""
        self.watched.append(argv)
        if self.watch_error:
            raise DesktopError(self.watch_error)

    def rig(self, watch=("/opt/watch", "{run}"), launcher=None):
        cfg = config(herdr_poll=0.05)
        cfg.runs = RunsSettings([API], True, poll=0.05, idle=60.0, watch=watch)
        rig = Rig(self, self.herdr, self.firstmate, cfg=cfg, nomistakes=self.nm, launcher=launcher or self.launch)
        rig.until(lambda: self.widget(rig, widget_id("run.", run_id(2))).get("label") == "fix-api")
        return rig

    @staticmethod
    def widget(rig, wid):
        page = rig.apps.pages.get("runs")
        found = [w for w in page.widgets if w.id == wid] if page else []
        return found[0].look if found else {}

    def open_card(self, rig):
        rig.apps.press(rig.client(), "runs", widget_id("run.", run_id(2)), "tap")
        rig.until(lambda: any(w.id == runcard.LINES for w in rig.apps.pages["runs"].widgets))

    def press(self, rig, prefix):
        wid = next(w.id for w in rig.apps.pages["runs"].widgets if w.id.startswith(prefix))
        rig.apps.press(rig.client(), "runs", wid, "tap")

    def test_watch_starts_the_command_with_the_run_id(self):
        rig = self.rig()
        self.open_card(rig)
        rig.apps.press(rig.client(), "runs", runcard.WATCH, "tap")
        rig.until(lambda: self.widget(rig, runcard.WATCH).get("text") == "opened on the main screen")
        self.assertEqual(self.watched, [["/opt/watch", run_id(2)]])
        self.assertIn("opened the watch view", rig.logged)
        # A failure is shown and logged, and a tap tries again.
        self.watch_error = "the watch command failed: exit 1"
        rig.apps.press(rig.client(), "runs", runcard.WATCH, "tap")
        rig.until(lambda: self.widget(rig, runcard.WATCH).get("text") == "not opened: the watch command failed: exit 1")
        self.assertIn("the watch view did not open: the watch command failed: exit 1", rig.logged)
        self.assertEqual(len(self.watched), 2)
        self.assertEqual(self.herdr.sent, [])

    def test_a_watch_command_written_as_a_string_starts_its_words_with_the_run_id(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        here = os.path.realpath(tmp.name)
        fake_scope(here)  # the systemd-run found on PATH: no unit is made
        watcher = write_script(
            os.path.join(here, "watch run"),
            """
            import json, os, sys
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "watched.jsonl"), "a") as f:
                f.write(json.dumps(sys.argv[1:]) + "\\n")
            """,
        )
        settings = {"repos": [here], "watch_command": "'%s' --run={run} \"a b\"" % watcher}
        watch = parse("agents.toml", {"herdr": {"session": "lab"}, "runs": settings}).runs.watch
        with mock.patch.dict(os.environ, {"PATH": here + os.pathsep + os.environ.get("PATH", "")}):
            rig = self.rig(watch=watch, launcher=start_watch)
            self.open_card(rig)
            rig.apps.press(rig.client(), "runs", runcard.WATCH, "tap")
            rig.until(lambda: self.widget(rig, runcard.WATCH).get("text") == "opened on the main screen")
        end = time.monotonic() + 3
        while not read_calls(os.path.join(here, "watched.jsonl")) and time.monotonic() < end:
            time.sleep(0.02)
        self.assertEqual(read_calls(os.path.join(here, "watched.jsonl")), [["--run=" + run_id(2), "a b"]])

    def test_there_is_no_watch_without_a_watch_command(self):
        rig = self.rig(watch=None)
        self.open_card(rig)
        self.assertEqual(self.widget(rig, runcard.WATCH), {})
        rig.apps.press(rig.client(), "runs", runcard.WATCH, "tap")  # no such widget: nothing starts
        rig.turn(5)
        self.assertEqual(self.watched, [])

    def test_approve_tells_firstmate_once_naming_the_run_and_never_merges(self):
        rig = self.rig()
        self.open_card(rig)
        self.press(rig, "call.rv.approve.idle")
        rig.until(lambda: len(self.firstmate.review_notes) == 1)
        _, verdict, task, head = self.firstmate.review_notes[0]
        self.assertEqual((verdict, task, head), ("approve", "fix-api", HEAD))
        rig.until(
            lambda: any(self.widget(rig, w.id).get("label") == "Approved" for w in rig.apps.pages["runs"].widgets)
        )
        self.assertEqual(self.firstmate.reviews_opened, [])
        rig.turn(5)
        self.assertEqual(len(self.firstmate.review_notes), 1)
        self.assertEqual(self.herdr.sent, [])
        self.assertEqual(self.watched, [])

    def test_review_and_request_changes_open_the_review_for_the_task(self):
        rig = self.rig()
        self.open_card(rig)
        self.press(rig, "call.rv.open.idle")
        rig.until(lambda: self.firstmate.reviews_opened == ["fix-api"])
        self.press(rig, "call.rv.changes.idle")
        rig.until(lambda: len(self.firstmate.review_notes) == 1)
        self.assertEqual(self.firstmate.review_notes[0][1:3], ("changes", "fix-api"))
        self.assertEqual(self.firstmate.reviews_opened, ["fix-api", "fix-api"])

    def test_the_verdict_stays_after_firstmate_is_read_again(self):
        rig = self.rig()
        self.open_card(rig)
        self.press(rig, "call.rv.approve.idle")
        rig.until(lambda: len(self.firstmate.review_notes) == 1)
        reads = self.firstmate.reads
        rig.app.refresh_calls()
        rig.until(lambda: self.firstmate.reads > reads)
        rig.turn(5)
        labels = {self.widget(rig, w.id).get("label") for w in rig.apps.pages["runs"].widgets}
        self.assertIn("Approved", labels)  # the change is not on Captain's Call, but its card keeps its entry

    def test_the_verdict_stays_after_the_card_is_closed_and_firstmate_is_read_again(self):
        rig = self.rig()
        self.open_card(rig)
        self.press(rig, "call.rv.approve.idle")
        rig.until(lambda: len(self.firstmate.review_notes) == 1)
        rig.apps.press(rig.client(), "runs", runcard.BACK, "tap")
        rig.until(lambda: not any(w.id == runcard.LINES for w in rig.apps.pages["runs"].widgets))
        reads = self.firstmate.reads
        rig.app.refresh_calls()
        rig.until(lambda: self.firstmate.reads > reads)
        rig.turn(5)
        self.open_card(rig)
        ids = [w.id for w in rig.apps.pages["runs"].widgets]
        self.assertTrue(any(i.startswith("call.rv.changes.locked") for i in ids), ids)
        self.assertFalse(any(i.startswith("call.rv.approve.idle") for i in ids), ids)
        self.press(rig, "call.rv.changes")
        rig.turn(5)
        self.assertEqual(len(self.firstmate.review_notes), 1)

    def test_focusing_a_done_agent_whose_run_is_ready_opens_the_review(self):
        rig = self.rig()
        self.open_card(rig)
        rig.apps.press(rig.client(), "runs", runcard.FOCUS, "tap")
        rig.until(lambda: self.firstmate.reviews_opened == ["fix-api"])
        rig.turn(10)
        self.assertEqual((self.herdr.focused, self.firstmate.review_notes), ([], []))

    def test_a_blocked_agent_or_one_without_a_review_command_keeps_its_terminal(self):
        self.herdr.list = [Agent("w1:p1", "claude", "blocked", COPY)]
        rig = self.rig()
        self.open_card(rig)
        rig.apps.press(rig.client(), "runs", runcard.FOCUS, "tap")
        rig.until(lambda: self.herdr.focused == ["w1:p1"])
        self.assertEqual(self.firstmate.reviews_opened, [])
        self.herdr.list = [Agent("w1:p1", "claude", "idle", COPY)]
        self.firstmate.review = None
        rig.until(lambda: self.herdr.agents()[0].state == "idle" and rig.app.fleet.agents[0].state == "idle")
        rig.apps.press(rig.client(), "runs", runcard.FOCUS, "tap")
        rig.until(lambda: self.herdr.focused == ["w1:p1", "w1:p1"])
        self.assertEqual(self.firstmate.reviews_opened, [])


if __name__ == "__main__":
    unittest.main()
