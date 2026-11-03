"""Captain's Call's Request in the loop (boardrequest.py): firstmate asked
with one inbox note, the card saying at once that the board is opening, and
the wait for it: the board open (the card's Open opens it), firstmate's
reply, no board in time or a failed note (the card's Retry asks again), the
Captain's Call count read again, and the checks only while the app waits."""

import threading
import unittest

from agents_support import NOTE, FakeFirstmate, FakeHerdr, Rig, task

from screenpad_agents import callcard
from screenpad_agents.common import BOARD_REPLY_GRACE, BOARD_REQUEST_HOLD, BOARD_WAIT

OPENING = ("Opening board…", callcard.OPENING_TEXT, ["OK"])
OPENED = ("Board open", callcard.OPENED_TEXT, ["Open"])
LATE = ("No board yet", callcard.LATE_TEXT, ["Retry"])
NOT_REQUESTED = "Request failed"


class BoardWaitTests(unittest.TestCase):
    def setUp(self):
        self.herdr = FakeHerdr([("w1:p1", "claude", "blocked")])
        self.firstmate = FakeFirstmate(calls=2, tasks={"lab:w1:p1": task("fix-api")})
        self.firstmate.board = None

    def rig(self):
        rig = Rig(self, self.herdr, self.firstmate)
        rig.app.board.poll = 0.02
        rig.apps.asks.set_available(True)
        rig.until(lambda: rig.widgets() == ["calls", "agent.w1.p1"])
        rig.until(lambda: rig.apps.provided().get("calls", {}).get("badge") == "2")
        return rig

    def asked(self, rig):
        return [(a.title, a.text, [o["label"] for o in a.options]) for a in rig.apps.asks.queue]

    def calls_text(self, rig):
        return rig.apps.pages["agents"].widgets[0].look.get("text")

    def request(self, rig):
        """Tap Captain's Call, then Request on the card saying no board is open."""
        rig.apps.press(rig.client(), "agents", "calls", "tap")
        rig.until(lambda: [a.title for a in rig.apps.asks.queue] == ["No board open"])
        rig.apps.asks.choose(rig.apps.asks.queue[0], 0)

    def test_request_says_at_once_that_the_board_is_opening(self):
        rig = self.rig()
        # firstmate's note takes a while: the card and the widget say the
        # board is opening before it is saved.
        release, answer = threading.Event(), self.firstmate.request_board
        self.firstmate.request_board = lambda rid: release.wait(5) and answer(rid)  # type: ignore[method-assign]
        reads = self.firstmate.reads
        self.request(rig)
        rig.until(lambda: self.asked(rig) == [OPENING])
        rig.until(lambda: self.calls_text(rig) == "2 waiting · opening board")
        self.assertEqual(rig.apps.provided()["calls"]["text"], "2 waiting · opening board")
        self.assertEqual(self.firstmate.requests, 0)
        release.set()
        rig.until(lambda: self.firstmate.requests == 1)
        rig.until(lambda: "asked firstmate for the decisions board: created " + NOTE in rig.logged)
        # The count is read again right after the request.
        rig.until(lambda: self.firstmate.reads >= reads + 2)
        # While it waits, a tap still looks for the board and says it is
        # opening, and nothing asks firstmate again.
        calls = self.firstmate.board_calls
        rig.apps.event("calls", "up", inside=True)
        rig.until(lambda: self.firstmate.board_calls == calls + 1)
        rig.turn(10)
        self.assertEqual(self.asked(rig), [OPENING])
        rig.app.request_board()  # a Request chosen on an older card
        rig.turn(10)
        self.assertEqual((self.firstmate.requests, self.asked(rig)), (1, [OPENING]))
        self.assertEqual((self.herdr.sent, self.firstmate.interrupted, self.firstmate.opened), ([], [], []))

    def test_the_board_open_ends_the_wait_and_open_opens_it(self):
        rig = self.rig()
        self.assertEqual(self.firstmate.checks, 0)
        self.request(rig)
        rig.until(lambda: self.firstmate.checks >= 2)
        reads = self.firstmate.reads
        self.firstmate.board = FakeFirstmate.BOARD
        rig.until(lambda: self.asked(rig) == [OPENED])
        self.assertIn("firstmate opened the decisions board: " + FakeFirstmate.BOARD, rig.logged)
        rig.until(lambda: self.calls_text(rig) == "2 waiting")
        # The count is read again once the board is open, and the checks stop.
        rig.until(lambda: self.firstmate.reads > reads)
        checks = self.firstmate.checks
        rig.turn(20)
        self.assertLessEqual(self.firstmate.checks, checks + 1)
        self.assertEqual(self.firstmate.opened, [])
        rig.apps.asks.choose(rig.apps.asks.queue[0], 0)
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
        self.firstmate.board_error = None
        self.firstmate.board = FakeFirstmate.BOARD
        rig.app.board.poll = 60.0  # no check before the tap
        rig.apps.event("calls", "up", inside=True)
        rig.until(lambda: self.firstmate.opened == [FakeFirstmate.BOARD])
        rig.until(lambda: not rig.app.board.waiting() and self.calls_text(rig) == "2 waiting")

    def test_firstmate_s_reply_is_shown_and_ends_the_wait_soon(self):
        rig = self.rig()
        self.request(rig)
        reply = "Nothing waits for you: the call was a stale PR row, refreshed now."
        self.firstmate.receipts[NOTE] = (True, reply)
        rig.until(lambda: self.asked(rig) == [("Opening board…", "firstmate: " + reply, ["OK"])])
        self.assertIn("firstmate replied to the board request: " + reply, rig.logged)
        self.assertTrue(rig.app.board.waiting())
        # With no board BOARD_REPLY_GRACE after the reply, the card says so.
        rig.app.board.replied -= BOARD_REPLY_GRACE
        rig.until(lambda: self.asked(rig) == [("No board yet", "firstmate: " + reply, ["Retry"])])
        rig.until(lambda: self.calls_text(rig) == "2 waiting")

    def test_no_board_in_time_says_so_and_retry_asks_again(self):
        rig = self.rig()
        self.request(rig)
        rig.until(lambda: self.firstmate.checks >= 1)
        rig.app.board.since -= BOARD_WAIT
        rig.until(lambda: self.asked(rig) == [LATE])
        self.assertIn("no decisions board came after asking firstmate", rig.logged)
        rig.until(lambda: self.calls_text(rig) == "2 waiting")
        checks = self.firstmate.checks
        rig.turn(20)
        self.assertLessEqual(self.firstmate.checks, checks + 1)
        # Retry asks again under the same id: fm-inbox.sh replays a note
        # firstmate has not handled yet rather than queueing a second.
        rig.apps.asks.choose(rig.apps.asks.queue[0], 0)
        rig.until(lambda: self.asked(rig) == [OPENING])
        rig.until(lambda: self.firstmate.requests == 2)
        ids = self.firstmate.request_ids
        self.assertEqual(ids[0], ids[1])

    def test_a_check_that_fails_is_logged_once_and_the_wait_goes_on(self):
        rig = self.rig()
        self.firstmate.receipt_error = "fm-inbox.sh receipts failed: exit 1"
        self.request(rig)
        rig.until(lambda: self.firstmate.checks >= 3)
        logged = [line for line in rig.logged if line.startswith("checking for the decisions board")]
        self.assertEqual(logged, ["checking for the decisions board: fm-inbox.sh receipts failed: exit 1"])
        self.firstmate.board = FakeFirstmate.BOARD
        rig.until(lambda: self.asked(rig) == [OPENED])

    def test_a_failed_request_is_shown_and_retry_replays_it(self):
        rig = self.rig()
        self.firstmate.request_error = "fm-inbox.sh note failed: exit 1"
        self.request(rig)
        failed = (NOT_REQUESTED, "fm-inbox.sh note failed: exit 1", ["Retry"])
        rig.until(lambda: self.asked(rig) == [failed])
        self.assertIn("the request for the decisions board failed: fm-inbox.sh note failed: exit 1", rig.logged)
        rig.until(lambda: self.calls_text(rig) == "2 waiting")
        self.assertEqual(self.firstmate.checks, 0)
        self.firstmate.request_error = None
        rig.apps.asks.choose(rig.apps.asks.queue[0], 0)
        rig.until(lambda: self.asked(rig) == [OPENING])
        # The retry repeats the same request, so fm-inbox.sh replays a note
        # it saved before failing instead of queueing a second one.
        rig.until(lambda: self.firstmate.requests == 2)
        ids = self.firstmate.request_ids
        self.assertEqual(ids[0], ids[1])

    def test_an_acknowledged_replay_is_asked_again_under_a_new_id(self):
        rig = self.rig()
        self.firstmate.request_error = "fm-inbox.sh note failed: exit 3"
        self.request(rig)
        rig.until(lambda: [a.title for a in rig.apps.asks.queue] == [NOT_REQUESTED])
        # firstmate handled that note meanwhile: the retry's replay wakes
        # nothing, so the same job asks once more, under a new id.
        first = self.firstmate.request_ids[0]
        self.firstmate.acknowledged.add(first)
        self.firstmate.request_error = None
        rig.apps.asks.choose(rig.apps.asks.queue[0], 0)
        rig.until(lambda: len(self.firstmate.request_ids) == 3)
        ids = self.firstmate.request_ids
        self.assertEqual(ids[:2], [first, first])
        self.assertNotEqual(ids[2], first)
        rig.until(lambda: rig.app.board.id == ids[2] and rig.app.board.note == NOTE)
        self.assertEqual(self.asked(rig), [OPENING])

    def test_a_failed_request_older_than_the_hold_is_asked_anew(self):
        rig = self.rig()
        self.firstmate.request_error = "fm-inbox.sh note failed: exit 3"
        self.request(rig)
        rig.until(lambda: [a.title for a in rig.apps.asks.queue] == [NOT_REQUESTED])
        # firstmate may have handled that note since: replaying its id would
        # wake nothing, so past the hold the retry is a new request.
        rig.app.board.made -= BOARD_REQUEST_HOLD
        self.firstmate.request_error = None
        rig.apps.asks.choose(rig.apps.asks.queue[0], 0)
        rig.until(lambda: self.firstmate.requests == 2)
        ids = self.firstmate.request_ids
        self.assertNotEqual(ids[0], ids[1])

    def test_a_restart_starts_with_no_wait(self):
        rig = self.rig()
        self.request(rig)
        rig.until(lambda: rig.app.board.note == NOTE)
        rig.app.close()
        rig.close_server()
        # A new app knows of no request: no wait, no checks, and a tap that
        # finds no board offers Request again.
        again = self.rig()
        checks = self.firstmate.checks
        again.turn(20)
        self.assertEqual((again.app.board.waiting(), self.firstmate.checks), (False, checks))
        self.assertEqual(self.calls_text(again), "2 waiting")
        again.apps.press(again.client(), "agents", "calls", "tap")
        again.until(lambda: [a.title for a in again.apps.asks.queue] == ["No board open"])


if __name__ == "__main__":
    unittest.main()
