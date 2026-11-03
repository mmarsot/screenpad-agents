"""Captain's Call's Request board in the loop (boardrequest.py): firstmate
asked with one inbox note, the board's button and the Captain's Call widget
saying at once that the board is opening, and the wait for it: the board
open (the button then opens it), firstmate's reply, no board in time or a
failed note (the button's Retry asks again), the Captain's Call count read
again, and the checks only while the app waits."""

import threading
import unittest

from agents_support import NOTE, FakeFirstmate, FakeHerdr, Rig, task

from screenpad_agents.callpage import BUTTONS
from screenpad_agents.common import BOARD_REPLY_GRACE, BOARD_REQUEST_HOLD, BOARD_WAIT


def shown(state, text=None):
    label, fixed, _, _ = BUTTONS[state]
    return ("call.board." + state, label, text or fixed)


OPENING, OPEN, LATE = shown("opening"), shown("open"), shown("late")


class BoardWaitTests(unittest.TestCase):
    def setUp(self):
        self.herdr = FakeHerdr([("w1:p1", "claude", "blocked")])
        self.firstmate = FakeFirstmate(calls=2, tasks={"lab:w1:p1": task("fix-api")})
        self.firstmate.board = None

    def rig(self):
        rig = Rig(self, self.herdr, self.firstmate)
        rig.app.board.poll = 0.02
        rig.until(lambda: rig.widgets() == ["calls", "agent.w1.p1"])
        rig.until(lambda: rig.apps.provided().get("calls", {}).get("badge") == "2")
        return rig

    def button(self, rig, page="calls"):
        w = next((w for w in rig.apps.pages[page].widgets if w.id.startswith("call.board.")), None)
        return w and (w.id, w.look.get("label"), w.look.get("text"))

    def calls_text(self, rig):
        return rig.apps.pages["agents"].widgets[0].look.get("text")

    def tap(self, rig, state):
        """Tap the calls page's board button as it shows state."""
        rig.until(lambda: self.button(rig)[0] == "call.board." + state)
        rig.apps.press(rig.client(), "calls", "call.board." + state, "tap")

    def request(self, rig):
        """Find no board open (the calls tile), then tap Request board."""
        rig.apps.event("calls", "up", inside=True)
        self.tap(rig, "none")

    def test_request_says_at_once_that_the_board_is_opening(self):
        rig = self.rig()
        # firstmate's note takes a while: the button and the widget say the
        # board is opening before it is saved.
        release, answer = threading.Event(), self.firstmate.request_board
        self.firstmate.request_board = lambda rid: release.wait(5) and answer(rid)  # type: ignore[method-assign]
        reads = self.firstmate.reads
        self.request(rig)
        rig.until(lambda: self.button(rig) == OPENING)
        rig.until(lambda: self.calls_text(rig) == "2 waiting · opening board")
        self.assertEqual(self.firstmate.requests, 0)
        release.set()
        rig.until(lambda: self.firstmate.requests == 1)
        rig.until(lambda: "asked firstmate for the decisions board: created " + NOTE in rig.logged)
        # The count is read again right after the request.
        rig.until(lambda: self.firstmate.reads >= reads + 2)
        # While it waits, a tap on the button or the tile looks for the board
        # and keeps saying it is opening; nothing asks firstmate again.
        calls = self.firstmate.board_calls
        rig.apps.press(rig.client(), "calls", "call.board.opening", "tap")
        rig.until(lambda: self.firstmate.board_calls == calls + 1)
        rig.apps.event("calls", "up", inside=True)
        rig.until(lambda: self.firstmate.board_calls == calls + 2)
        rig.app.request_board()  # a Request board on a page drawn before
        rig.apps.press(rig.client(), "calls", "call.board.none", "tap")
        rig.turn(10)
        self.assertEqual((self.firstmate.requests, self.button(rig)), (1, OPENING))
        self.assertEqual((self.herdr.sent, self.firstmate.interrupted, self.firstmate.opened), ([], [], []))

    def test_the_board_open_ends_the_wait_and_the_button_opens_it(self):
        rig = self.rig()
        self.assertEqual(self.firstmate.checks, 0)
        self.request(rig)
        rig.until(lambda: self.firstmate.checks >= 2)
        reads = self.firstmate.reads
        self.firstmate.board = FakeFirstmate.BOARD
        rig.until(lambda: self.button(rig) == OPEN)
        self.assertIn("firstmate opened the decisions board: " + FakeFirstmate.BOARD, rig.logged)
        rig.until(lambda: self.calls_text(rig) == "2 waiting")
        # The count is read again once the board is open, and the checks stop.
        rig.until(lambda: self.firstmate.reads > reads)
        checks = self.firstmate.checks
        rig.turn(20)
        self.assertLessEqual(self.firstmate.checks, checks + 1)
        self.assertEqual(self.firstmate.opened, [])
        self.tap(rig, "open")
        rig.until(lambda: self.firstmate.opened == [FakeFirstmate.BOARD])
        # The board was seen open: a later request asks anew, under a new id.
        self.firstmate.board = None
        self.request(rig)
        rig.until(lambda: self.firstmate.requests == 2)
        ids = self.firstmate.request_ids
        self.assertNotEqual(ids[0], ids[1])
        for rid in ids:
            self.assertRegex(rid, r"\A[A-Za-z0-9._:-]{1,128}\Z")

    def test_a_tap_that_finds_the_board_ends_the_wait(self):
        rig = self.rig()
        self.request(rig)
        rig.until(lambda: rig.app.board.note == NOTE)
        rig.app.board.poll = 60.0  # no check before the tap
        self.firstmate.board = FakeFirstmate.BOARD
        rig.apps.event("calls", "up", inside=True)
        rig.until(lambda: self.firstmate.opened == [FakeFirstmate.BOARD])
        rig.until(lambda: not rig.app.board.waiting() and self.calls_text(rig) == "2 waiting")
        rig.until(lambda: self.button(rig) == shown("shown"))

    def test_firstmate_s_reply_is_shown_and_ends_the_wait_soon(self):
        rig = self.rig()
        self.request(rig)
        reply = "Nothing waits for you: a stale PR row."
        self.firstmate.receipts[NOTE] = (True, reply)
        rig.until(lambda: self.button(rig) == shown("opening", "firstmate: " + reply))
        self.assertIn("firstmate replied to the board request: " + reply, rig.logged)
        self.assertTrue(rig.app.board.waiting())
        # With no board BOARD_REPLY_GRACE after the reply, the button says so.
        rig.app.board.replied -= BOARD_REPLY_GRACE
        rig.until(lambda: self.button(rig) == shown("late", "firstmate: " + reply))
        rig.until(lambda: self.calls_text(rig) == "2 waiting")

    def test_no_board_in_time_says_so_and_retry_asks_again(self):
        rig = self.rig()
        self.request(rig)
        rig.until(lambda: self.firstmate.checks >= 1)
        rig.app.board.since -= BOARD_WAIT
        rig.until(lambda: self.button(rig) == LATE)
        self.assertIn("no decisions board came after asking firstmate", rig.logged)
        rig.until(lambda: self.calls_text(rig) == "2 waiting")
        checks = self.firstmate.checks
        rig.turn(20)
        self.assertLessEqual(self.firstmate.checks, checks + 1)
        # Retry asks again under the same id: fm-inbox.sh replays a note
        # firstmate has not handled yet rather than queueing a second.
        self.tap(rig, "late")
        rig.until(lambda: self.button(rig) == OPENING)
        rig.until(lambda: self.firstmate.requests == 2)
        ids = self.firstmate.request_ids
        self.assertEqual(ids[0], ids[1])

    def test_retry_with_the_board_open_since_writes_no_note(self):
        rig = self.rig()
        self.request(rig)
        rig.until(lambda: self.firstmate.checks >= 1)
        rig.app.board.since -= BOARD_WAIT
        rig.until(lambda: self.button(rig) == LATE)
        # firstmate opens the board after the wait ended: the button still
        # says Retry, and a tap on it finds the board rather than asking again.
        self.firstmate.board = FakeFirstmate.BOARD
        self.tap(rig, "late")
        rig.until(lambda: self.button(rig) == OPEN)
        rig.turn(10)
        self.assertEqual((self.firstmate.requests, rig.app.board.waiting()), (1, False))
        self.assertEqual(self.firstmate.opened, [])

    def test_a_look_that_fails_before_a_request_still_asks(self):
        rig = self.rig()
        rig.apps.event("calls", "up", inside=True)
        rig.until(lambda: self.button(rig)[0] == "call.board.none")
        self.firstmate.board_error = "lavish-axi failed: exit 1"
        self.tap(rig, "none")
        rig.until(lambda: self.firstmate.requests == 1)
        rig.until(lambda: rig.app.board.note == NOTE)
        self.assertEqual(self.button(rig), OPENING)

    def test_a_check_that_fails_is_logged_once_and_the_wait_goes_on(self):
        rig = self.rig()
        self.firstmate.receipt_error = "fm-inbox.sh receipts failed: exit 1"
        self.request(rig)
        rig.until(lambda: self.firstmate.checks >= 3)
        logged = [line for line in rig.logged if line.startswith("checking for the decisions board")]
        self.assertEqual(logged, ["checking for the decisions board: fm-inbox.sh receipts failed: exit 1"])
        self.firstmate.board = FakeFirstmate.BOARD
        rig.until(lambda: self.button(rig) == OPEN)

    def test_a_failed_request_is_shown_and_retry_replays_it(self):
        rig = self.rig()
        self.firstmate.request_error = "fm-inbox.sh note failed: exit 1"
        self.request(rig)
        rig.until(lambda: self.button(rig) == shown("failed", "request failed: fm-inbox.sh note failed: exit 1"))
        self.assertIn("the request for the decisions board failed: fm-inbox.sh note failed: exit 1", rig.logged)
        rig.until(lambda: self.calls_text(rig) == "2 waiting")
        self.assertEqual(self.firstmate.checks, 0)
        self.firstmate.request_error = None
        self.tap(rig, "failed")
        rig.until(lambda: self.button(rig) == OPENING)
        # The retry repeats the same request, so fm-inbox.sh replays a note
        # it saved before failing instead of queueing a second one.
        rig.until(lambda: self.firstmate.requests == 2)
        ids = self.firstmate.request_ids
        self.assertEqual(ids[0], ids[1])

    def test_an_acknowledged_replay_is_asked_again_under_a_new_id(self):
        rig = self.rig()
        self.firstmate.request_error = "fm-inbox.sh note failed: exit 3"
        self.request(rig)
        rig.until(lambda: self.button(rig)[0] == "call.board.failed")
        # firstmate handled that note meanwhile: the retry's replay wakes
        # nothing, so the same job asks once more, under a new id.
        first = self.firstmate.request_ids[0]
        self.firstmate.acknowledged.add(first)
        self.firstmate.request_error = None
        self.tap(rig, "failed")
        rig.until(lambda: len(self.firstmate.request_ids) == 3)
        ids = self.firstmate.request_ids
        self.assertEqual(ids[:2], [first, first])
        self.assertNotEqual(ids[2], first)
        rig.until(lambda: rig.app.board.id == ids[2] and rig.app.board.note == NOTE)
        self.assertEqual(self.button(rig), OPENING)

    def test_a_failed_request_older_than_the_hold_is_asked_anew(self):
        rig = self.rig()
        self.firstmate.request_error = "fm-inbox.sh note failed: exit 3"
        self.request(rig)
        rig.until(lambda: self.button(rig)[0] == "call.board.failed")
        # firstmate may have handled that note since: replaying its id would
        # wake nothing, so past the hold the retry is a new request.
        rig.app.board.made -= BOARD_REQUEST_HOLD
        self.firstmate.request_error = None
        self.tap(rig, "failed")
        rig.until(lambda: self.firstmate.requests == 2)
        ids = self.firstmate.request_ids
        self.assertNotEqual(ids[0], ids[1])

    def test_the_view_on_the_agents_page_requests_and_waits_too(self):
        rig = self.rig()
        rig.apps.press(rig.client(), "agents", "calls", "tap")
        rig.until(lambda: self.button(rig, "agents") == shown("none"))
        rig.apps.press(rig.client(), "agents", "call.board.none", "tap")
        rig.until(lambda: self.button(rig, "agents") == OPENING)
        rig.until(lambda: self.firstmate.requests == 1)
        self.firstmate.board = FakeFirstmate.BOARD
        rig.until(lambda: self.button(rig, "agents") == OPEN)
        self.assertEqual(self.button(rig), OPEN)

    def test_a_restart_starts_with_no_wait(self):
        rig = self.rig()
        self.request(rig)
        rig.until(lambda: rig.app.board.note == NOTE)
        rig.app.close()
        rig.close_server()
        # A new app knows of no request: no wait, no checks, and the button
        # offers to open the board, then Request board when none is open.
        again = self.rig()
        checks = self.firstmate.checks
        again.turn(20)
        self.assertEqual((again.app.board.waiting(), self.firstmate.checks), (False, checks))
        self.assertEqual(self.calls_text(again), "2 waiting")
        self.assertEqual(self.button(again), shown("idle"))
        again.apps.event("calls", "up", inside=True)
        again.until(lambda: self.button(again) == shown("none"))


if __name__ == "__main__":
    unittest.main()
