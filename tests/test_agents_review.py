"""A change ready for review on Captain's Call: which calls get Review,
Approve and Request changes, the notes Approve and Request changes send
(their text and request id, through a stand-in fm-inbox.sh that writes into
no firstmate home), the review command Review starts (a stand-in in a stand-in
systemd-run scope, so nothing opens on the screen), the buttons hidden
without [firstmate] review_command, and the taps in the loop: one note per
verdict however often it is pressed, its state, and firstmate handling it."""

import os
import tempfile
import unittest
from unittest import mock

from agents_support import NOTE, FakeFirstmate, FakeHerdr, Rig, fake_bearings, read_calls, task, write_script
from desktop_support import fake_scope

from screenpad_agents.common import ConfigError
from screenpad_agents.config import load
from screenpad_agents.firstmate import SCOPE, Bearings, Call, Firstmate, FirstmateError, Review, parse
from screenpad_agents.reviewcall import request_id, token

HEAD = "3f9c2ab"
READY = "ready for review at %s: wire the review buttons" % HEAD
REVIEW = Review("fix-api", HEAD)
CALL = Call("decision", "fix-api", READY, REVIEW)
OTHER = Call("decision", "screenpad-grid-layout", "until 2026-11-17: deferred")


def model(*decisions):
    return {
        "schema": "fm-bearings.v1",
        "decisions_open": [dict({"verb": "needs-decision"}, **d) for d in decisions],
    }


class SourceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = os.path.realpath(tmp.name)
        self.code = os.path.join(self.dir, "fm")
        fake_bearings(self.code)
        self.home = os.path.join(self.dir, "home")
        os.makedirs(self.home)
        self.scope = fake_scope(self.dir)
        self.launcher = write_script(
            os.path.join(self.dir, "launcher"),
            """
            import json, os, sys
            here = os.path.dirname(os.path.abspath(__file__))
            with open(os.path.join(here, "launched.jsonl"), "a") as f:
                fm = sorted(k for k in os.environ if k.startswith("FM_"))
                f.write(json.dumps({"args": sys.argv[1:], "fm": fm}) + "\\n")
            if os.path.exists(os.path.join(here, "launcher.fail")):
                print("no such task", file=sys.stderr)
                sys.exit(2)
            """,
        )
        self.fm = Firstmate(
            self.home,
            "r",
            "c",
            inbox=os.path.join(self.code, "bin", "fm-inbox.sh"),
            scope=[self.scope, *SCOPE[1:]],
            review=[self.launcher, "--task={task}", "main"],
        )

    def notes(self):
        return read_calls(os.path.join(self.code, "bin", "inbox.jsonl"))

    def test_only_a_code_review_decision_is_a_change_ready_for_review(self):
        bearings = parse(
            model(
                {"id": "fix-api", "key": "code-review", "summary": READY},
                {"id": "fix-ui", "key": "code-review", "summary": "ready for review, no head named"},
                {"id": "screenpad-grid-layout", "key": "screenpad-grid-layout", "verb": "captain-hold"},
                {"id": "not a task id", "key": "code-review", "summary": READY},
                {"key": "code-review", "summary": READY},
            )
        )
        self.assertEqual(
            [(c.title, c.review) for c in bearings.waiting],
            [
                ("fix-api", REVIEW),
                ("fix-ui", Review("fix-ui")),
                ("screenpad-grid-layout", None),
                ("not a task id", None),
                ("code-review", None),
            ],
        )

    def test_the_notes_say_what_the_captain_decided(self):
        with mock.patch.dict(os.environ, {"FM_HOME": "/home/me/firstmate", "FM_BACKEND": "herdr"}):
            self.assertEqual(self.fm.review_note("rid-1", "approve", REVIEW), ("created", NOTE))
        self.assertEqual(self.fm.review_note("rid-2", "changes", REVIEW), ("created", NOTE))
        texts = [(c["args"][3], c["args"][-1]) for c in self.notes()]
        self.assertEqual(
            texts,
            [
                ("rid-1", "Captain approves the change for task fix-api (ready head %s)." % HEAD),
                ("rid-2", "Captain requests changes on task fix-api; review comments follow from the review window."),
            ],
        )
        # One configured home, no other FM_* variable, and only notes.
        self.assertEqual({(c["FM_HOME"], tuple(c["fm"])) for c in self.notes()}, {(self.home, ("FM_HOME",))})
        self.assertEqual(
            {tuple(c["args"][:4]) for c in self.notes()},
            {("note", "--json", "--request-id", r) for r in ("rid-1", "rid-2")},
        )

    def test_the_same_decision_has_the_same_request_id(self):
        ids = {
            request_id(REVIEW, "approve"),
            request_id(REVIEW, "changes"),
            request_id(Review("fix-api", "aaaaaaa"), "approve"),
            request_id(Review("fix-ui", HEAD), "approve"),
        }
        self.assertEqual(len(ids), 4)
        self.assertEqual(request_id(Review("fix-api", HEAD), "approve"), request_id(REVIEW, "approve"))
        self.assertTrue(all(len(i) <= 128 and i.startswith("screenpad-review-") for i in ids))
        # A second press replays the first note (fm-inbox.sh wakes nothing); one firstmate handled says so.
        self.fm.review_note(request_id(REVIEW, "approve"), "approve", REVIEW)
        self.assertEqual(self.fm.review_note(request_id(REVIEW, "approve"), "approve", REVIEW), ("replay", NOTE))
        with open(os.path.join(self.code, "bin", "inbox.handled"), "w") as f:
            f.write(request_id(REVIEW, "approve") + "\n")
        self.assertIsNone(self.fm.review_note(request_id(REVIEW, "approve"), "approve", REVIEW))

    def test_a_note_for_something_else_is_refused(self):
        refused = (
            (Review("../x", HEAD), "approve"),
            (Review("-rf"), "approve"),
            (REVIEW, "merge"),
            # No head: nothing tells this round of review from the last.
            (Review("fix-ui"), "approve"),
            (Review("fix-ui"), "changes"),
        )
        for review, verdict in refused:
            with self.subTest(review=review, verdict=verdict), self.assertRaisesRegex(FirstmateError, "not a"):
                self.fm.review_note("rid", verdict, review)
        self.assertEqual(self.notes(), [])

    def test_the_review_command_gets_the_task_and_runs_in_a_scope_of_its_own(self):
        with mock.patch.dict(os.environ, {"FM_HOME": "/home/me/firstmate", "FM_BACKEND": "herdr"}):
            self.fm.open_review("fix-api")
        scoped = read_calls(os.path.join(self.dir, "scoped.jsonl"))
        self.assertEqual(scoped[0]["args"], [*SCOPE[1:], self.launcher, "--task=fix-api", "main"])
        self.assertEqual(scoped[0]["fm"], [])
        # It ran (the stand-in scope waits for it only up to its grace), with no firstmate variable.
        import time

        end = time.monotonic() + 3
        while not read_calls(os.path.join(self.dir, "launched.jsonl")) and time.monotonic() < end:
            time.sleep(0.02)
        self.assertEqual(
            read_calls(os.path.join(self.dir, "launched.jsonl")), [{"args": ["--task=fix-api", "main"], "fm": []}]
        )

    def test_a_review_that_does_not_start_says_why(self):
        open(os.path.join(self.dir, "launcher.fail"), "w").close()
        with self.assertRaisesRegex(FirstmateError, "the review command failed: exit 2"):
            self.fm.open_review("fix-api")
        with self.assertRaisesRegex(FirstmateError, "not a firstmate task id"):
            self.fm.open_review("../etc")
        self.assertEqual(read_calls(os.path.join(self.dir, "scoped.jsonl"))[0]["args"][-2:], ["--task=fix-api", "main"])
        os.remove(os.path.join(self.dir, "launcher.fail"))
        open(os.path.join(self.dir, "scope.fail"), "w").close()
        with self.assertRaisesRegex(FirstmateError, "failed: exit 1"):
            self.fm.open_review("fix-api")
        with self.assertRaisesRegex(FirstmateError, "no review_command"):
            Firstmate(self.home, "r", "c").open_review("fix-api")


class ConfigTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = os.path.realpath(tmp.name)
        self.code, self.home = os.path.join(self.dir, "fm"), os.path.join(self.dir, "home")
        fake_bearings(self.code)
        os.makedirs(self.home)

    def load(self, extra):
        path = os.path.join(self.dir, "agents.toml")
        with open(path, "w") as f:
            f.write(
                '[herdr]\nsession = "lab"\n[firstmate]\nhome = "%s"\ncode = "%s"\n%s' % (self.home, self.code, extra)
            )
        return load(path)

    def test_the_review_command_is_a_program_with_a_task_word(self):
        self.assertEqual(self.load('review_command = "/opt/review {task}"\n').review, ["/opt/review {task}"])
        self.assertEqual(
            self.load('review_command = ["/opt/review", "--task", "{task}"]\n').review,
            ["/opt/review", "--task", "{task}"],
        )
        for bad in ('"/opt/review"', "[]", "7", '["/opt/review", "x"]'):
            with self.subTest(bad=bad), self.assertRaisesRegex(ConfigError, "review_command must"):
                self.load("review_command = %s\n" % bad)

    def test_without_it_there_is_no_review_command(self):
        from screenpad_agents.cli import clients

        c = self.load("")
        self.assertIsNone(c.review)
        self.assertIsNone(clients(c)[1].review)
        self.assertEqual(clients(self.load('review_command = "/opt/r {task}"\n'))[1].review, ["/opt/r {task}"])


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.herdr = FakeHerdr([("w1:p1", "claude", "blocked")])
        self.firstmate = FakeFirstmate(calls=2, tasks={"lab:w1:p1": task("fix-api")})
        self.firstmate.bearings = Bearings(2, False, {"lab:w1:p1": task("fix-api")}, waiting=[OTHER, CALL])

    def rig(self, review=("/opt/review", "{task}")):
        self.firstmate.review = list(review) if review else None
        rig = Rig(self, self.herdr, self.firstmate)
        rig.until(lambda: rig.apps.provided().get("calls", {}).get("badge") == "2")
        return rig

    def page(self, rig):
        return {w.id: (w.look.get("label"), w.look.get("text")) for w in rig.apps.pages["calls"].widgets}

    def buttons(self, rig):
        """The review buttons now: id -> label."""
        return {i: v[0] for i, v in self.page(rig).items() if i.startswith("call.rv.")}

    def press(self, rig, prefix):
        widget = next(i for i in self.buttons(rig) if i.startswith(prefix))
        rig.apps.press(rig.client(), "calls", widget, "tap")

    def test_the_first_change_ready_for_review_gets_three_buttons(self):
        rig = self.rig()
        page = self.page(rig)
        self.assertEqual(sorted(self.buttons(rig).values()), ["Approve", "Request changes", "Review"])
        # The call is shown with its words, the other call waits on the board.
        self.assertEqual(page["call.item.0"][0], "fix-api")
        self.assertNotIn("screenpad-grid-layout", [v[0] for v in page.values()])
        self.assertIn("1 more on the board", page["call.count"][1])
        self.assertEqual(self.placed(rig), {"open": (2, 1, 1, 1), "approve": (3, 1, 1, 1), "changes": (2, 2, 2, 1)})

    def test_without_a_review_command_only_approve_is_shown(self):
        rig = self.rig(review=None)
        self.assertEqual(list(self.buttons(rig).values()), ["Approve"])
        self.press(rig, "call.rv.approve.idle")
        rig.until(lambda: self.firstmate.review_notes)
        self.assertEqual(self.firstmate.reviews_opened, [])

    def placed(self, rig):
        return {
            w.id.split(".")[2]: (w.col, w.row, w.cols, w.rows)
            for w in rig.apps.pages["calls"].widgets
            if w.id.startswith("call.rv.")
        }

    def test_a_change_with_no_head_named_can_be_reviewed_but_not_answered(self):
        self.firstmate.bearings = Bearings(
            2, False, {}, waiting=[Call("decision", "fix-ui", "ready for review", Review("fix-ui")), OTHER]
        )
        rig = self.rig()
        self.assertEqual(list(self.buttons(rig).values()), ["Review"])
        self.assertEqual(self.placed(rig), {"open": (2, 1, 2, 2)})
        self.press(rig, "call.rv.open.idle")
        rig.until(lambda: self.firstmate.reviews_opened == ["fix-ui"])
        for verdict in ("approve", "changes"):
            rig.apps.press(rig.client(), "calls", "call.rv.%s.idle.%s" % (verdict, token(Review("fix-ui"))), "tap")
        rig.turn(10)
        self.assertEqual((self.firstmate.review_notes, self.firstmate.reviews_opened), ([], ["fix-ui"]))

    def test_without_a_review_command_a_change_with_no_head_named_is_a_plain_call(self):
        self.firstmate.bearings = Bearings(
            2, False, {}, waiting=[Call("decision", "fix-ui", "ready for review", Review("fix-ui")), OTHER]
        )
        rig = self.rig(review=None)
        self.assertEqual(self.buttons(rig), {})
        self.assertEqual(self.page(rig)["call.item.0"][0], "fix-ui")

    def test_calls_that_are_not_ready_for_review_stay_as_they_are(self):
        self.firstmate.bearings = Bearings(
            2, False, {}, waiting=[OTHER, Call("contribution", "insusty", "merge: ready")]
        )
        rig = self.rig()
        page = self.page(rig)
        self.assertEqual(self.buttons(rig), {})
        self.assertEqual([page[i][0] for i in ("call.item.0", "call.item.1")], ["screenpad-grid-layout", "insusty"])
        self.assertEqual([i for i in page if i.startswith("call.board.")], ["call.board.idle"])
        self.assertNotIn("1 more", page["call.count"][1])

    def test_approve_tells_firstmate_once_however_often_it_is_pressed(self):
        rig = self.rig()
        old = "call.rv.approve.idle." + token(REVIEW)
        self.assertIn(old, self.buttons(rig))
        rig.apps.press(rig.client(), "calls", old, "tap")
        rig.until(lambda: any(".approve.sent." in i for i in self.buttons(rig)))
        for _ in range(3):  # the button it was, and the ones shown now
            rig.apps.press(rig.client(), "calls", old, "tap")
            self.press(rig, "call.rv.approve")
            self.press(rig, "call.rv.changes")
        rig.turn(10)
        self.assertEqual(self.firstmate.review_notes, [(request_id(REVIEW, "approve"), "approve", "fix-api", HEAD)])
        self.assertEqual(sorted(self.buttons(rig).values()), ["Approved", "Request changes", "Review"])
        self.assertEqual(self.page(rig)[next(i for i in self.buttons(rig) if ".approve." in i)][1], "sent to firstmate")
        # Nothing was opened, merged or sent to an agent.
        self.assertEqual((self.firstmate.reviews_opened, self.firstmate.interrupted, self.herdr.sent), ([], [], []))

    def test_request_changes_opens_the_review_and_tells_firstmate(self):
        rig = self.rig()
        self.press(rig, "call.rv.changes.idle")
        rig.until(lambda: self.firstmate.review_notes and self.firstmate.reviews_opened)
        self.assertEqual(self.firstmate.reviews_opened, ["fix-api"])
        self.assertEqual(self.firstmate.review_notes, [(request_id(REVIEW, "changes"), "changes", "fix-api", HEAD)])
        rig.until(lambda: any(".changes.sent." in i for i in self.buttons(rig)))
        self.assertEqual(sorted(self.buttons(rig).values()), ["Approve", "Changes requested", "Review"])
        # Approve is no longer offered after it; Review still opens the review again.
        self.press(rig, "call.rv.approve")
        self.press(rig, "call.rv.open")
        rig.until(lambda: len(self.firstmate.reviews_opened) == 2)
        rig.turn(10)
        self.assertEqual(len(self.firstmate.review_notes), 1)

    def test_review_opens_the_change_and_sends_nothing(self):
        rig = self.rig()
        self.press(rig, "call.rv.open.idle")
        rig.until(lambda: any(".open.opened." in i for i in self.buttons(rig)))
        self.assertEqual((self.firstmate.reviews_opened, self.firstmate.review_notes), (["fix-api"], []))
        self.assertEqual(
            self.page(rig)[next(i for i in self.buttons(rig) if ".open." in i)][1], "opened on the main screen"
        )

    def test_a_review_that_did_not_open_says_why(self):
        rig = self.rig()
        self.firstmate.review_error = "the review command failed: exit 2"
        self.press(rig, "call.rv.open.idle")
        rig.until(lambda: any(".open.failed." in i for i in self.buttons(rig)))
        self.assertIn(
            "not opened: the review command failed: exit 2",
            self.page(rig)[next(i for i in self.buttons(rig) if ".open." in i)][1],
        )

    def test_a_failed_note_can_be_pressed_again_and_replays_under_the_same_id(self):
        rig = self.rig()
        self.firstmate.review_error = "fm-inbox.sh note failed: exit 3"
        self.press(rig, "call.rv.approve.idle")
        rig.until(lambda: any(".approve.failed." in i for i in self.buttons(rig)))
        self.assertIn(
            "not sent: fm-inbox.sh note failed: exit 3",
            self.page(rig)[next(i for i in self.buttons(rig) if ".approve." in i)][1],
        )
        self.firstmate.review_error = None
        self.press(rig, "call.rv.approve.failed")
        rig.until(lambda: any(".approve.sent." in i for i in self.buttons(rig)))
        ids = {n[0] for n in self.firstmate.review_notes}
        self.assertEqual((len(self.firstmate.review_notes), ids), (2, {request_id(REVIEW, "approve")}))

    def test_a_note_firstmate_handled_already_shows_as_handled(self):
        rig = self.rig()
        self.firstmate.review_note = lambda *a: None  # type: ignore[method-assign]
        self.press(rig, "call.rv.approve.idle")
        rig.until(lambda: any(".approve.handled." in i for i in self.buttons(rig)))
        self.assertEqual(
            self.page(rig)[next(i for i in self.buttons(rig) if ".approve." in i)][1], "handled by firstmate"
        )

    def test_firstmate_handling_the_note_is_read_with_its_own_reads(self):
        rig = self.rig()
        self.press(rig, "call.rv.approve.idle")
        rig.until(lambda: any(".approve.sent." in i for i in self.buttons(rig)))
        # Nothing polls for it: no receipts are read until firstmate is read again.
        checks = self.firstmate.checks
        rig.turn(20)
        self.assertEqual(self.firstmate.checks, checks)
        self.firstmate.receipts[NOTE] = (True, "approved, merging")
        rig.app.refresh_calls()
        rig.until(lambda: any(".approve.handled." in i for i in self.buttons(rig)))
        self.assertEqual(
            self.page(rig)[next(i for i in self.buttons(rig) if ".approve." in i)][1], "handled by firstmate"
        )
        # Once firstmate no longer lists the call, so does the page.
        self.firstmate.bearings = Bearings(1, False, {}, waiting=[OTHER])
        rig.app.refresh_calls()
        rig.until(lambda: not self.buttons(rig))
        self.assertEqual(self.page(rig)["call.item.0"][0], "screenpad-grid-layout")


class FocusTests(unittest.TestCase):
    """Focusing an agent that is done and whose task is ready for review
    opens the review; a blocked agent keeps its terminal."""

    def setUp(self):
        self.herdr = FakeHerdr([("w1:p1", "claude", "idle"), ("w2:p1", "claude", "working")])
        self.tasks = {"lab:w1:p1": task("fix-api"), "lab:w2:p1": task("fix-ui")}
        self.firstmate = FakeFirstmate(calls=1, tasks=self.tasks)
        self.firstmate.bearings = Bearings(1, False, self.tasks, waiting=[CALL])

    def rig(self, review=("/opt/review", "{task}")):
        self.firstmate.review = list(review) if review else None
        rig = Rig(self, self.herdr, self.firstmate)
        rig.until(lambda: rig.apps.provided().get("calls", {}).get("badge") == "1")
        return rig

    def focus_tile(self, rig):
        rig.apps.event("agents", "up", inside=True)

    def focus_card(self, rig, pane):
        rig.apps.press(rig.client(), "agents", "agent.%s" % pane.replace(":", "."), "tap")
        rig.until(lambda: rig.widgets()[0] == "card.screen")
        rig.apps.press(rig.client(), "agents", "card.focus", "tap")

    def test_the_review_opens_in_place_of_the_terminal_of_a_done_task_ready_for_review(self):
        rig = self.rig()
        self.focus_card(rig, "w1:p1")
        rig.until(lambda: self.firstmate.reviews_opened == ["fix-api"])
        rig.turn(10)
        # No terminal was focused, and nothing was sent to firstmate or an agent.
        self.assertEqual((self.herdr.focused, self.firstmate.review_notes, self.herdr.sent), ([], [], []))

    def test_a_blocked_agent_keeps_its_terminal_though_its_task_is_ready_for_review(self):
        self.herdr = FakeHerdr([("w1:p1", "claude", "blocked")])
        rig = self.rig()
        self.focus_tile(rig)
        rig.until(lambda: self.herdr.focused == ["w1:p1"])
        self.focus_card(rig, "w1:p1")
        rig.until(lambda: self.herdr.focused == ["w1:p1", "w1:p1"])
        self.assertEqual(self.firstmate.reviews_opened, [])

    def test_other_tasks_keep_their_terminal(self):
        rig = self.rig()
        self.focus_card(rig, "w2:p1")
        rig.until(lambda: self.herdr.focused == ["w2:p1"])
        self.assertEqual(self.firstmate.reviews_opened, [])

    def test_without_a_review_command_the_terminal_is_focused_as_before(self):
        rig = self.rig(review=None)
        self.focus_card(rig, "w1:p1")
        rig.until(lambda: self.herdr.focused == ["w1:p1"])
        self.assertEqual(self.firstmate.reviews_opened, [])

    def test_a_task_whose_ready_work_is_a_pull_request_keeps_its_terminal(self):
        self.firstmate.bearings = Bearings(
            1, False, self.tasks, waiting=[Call("contribution", "fix-api", "merge: PR ready, checks green")]
        )
        rig = self.rig()
        self.focus_card(rig, "w1:p1")
        rig.until(lambda: self.herdr.focused == ["w1:p1"])
        self.assertEqual(self.firstmate.reviews_opened, [])
