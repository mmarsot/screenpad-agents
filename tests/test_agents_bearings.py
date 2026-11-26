"""Bearings (the bearings tile, boardrequest.py's rebuild): one tap opens
the decisions board when it is open and fresh, and otherwise asks firstmate,
with a note of its own, to rebuild it and opens it as soon as the rebuilt
board is open; the tile says it is asking while it waits. The firstmate
side (the board file's age and the note's text) runs the real client
against the fake checkout; the loop runs the app against the stand-in bar."""

import os
import tempfile
import time
import unittest
from unittest import mock

from agents_support import NOTE, FakeFirstmate, FakeHerdr, Rig, fake_bearings, read_calls, task

from screenpad_agents.common import BOARD_FRESH
from screenpad_agents.firstmate import REBUILD_REQUEST, Firstmate, FirstmateError


class FirstmateSideTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = os.path.realpath(tmp.name)
        self.code = os.path.join(self.dir, "fm")
        fake_bearings(self.code)
        self.home = os.path.join(self.dir, "home")
        os.makedirs(os.path.join(self.home, ".lavish"))
        self.board = os.path.join(self.home, ".lavish", "bearings-board.html")
        bin_ = os.path.join(self.code, "bin")
        self.fm = Firstmate(
            self.home,
            os.path.join(bin_, "fm-bearings-snapshot.sh"),
            os.path.join(bin_, "fm-control.sh"),
            board=os.path.join(bin_, "fm-bearings-board.sh"),
            inbox=os.path.join(bin_, "fm-inbox.sh"),
        )

    def test_the_board_s_age_is_its_file_s_modification_time_and_nothing_more(self):
        with open(self.board, "w") as f:
            f.write("<html>not read</html>")
        old = time.time() - 3600
        os.utime(self.board, (old, old))
        self.assertAlmostEqual(self.fm.board_age(), 3600, delta=5)
        os.utime(self.board)
        self.assertLess(self.fm.board_age(), 5)

    def test_a_board_never_built_says_so(self):
        with self.assertRaisesRegex(FirstmateError, "the decisions board's file: No such file or directory"):
            self.fm.board_age()
        with self.assertRaisesRegex(FirstmateError, "firstmate has no"):
            Firstmate(self.home, "r", "c").board_age()

    def test_the_rebuild_is_asked_with_its_own_note(self):
        self.assertEqual(self.fm.request_board("screenpad-board-1-ab", REBUILD_REQUEST), ("created", NOTE))
        calls = read_calls(os.path.join(self.code, "bin", "inbox.jsonl"))
        args = ["note", "--json", "--request-id", "screenpad-board-1-ab", "--", "ScreenPad: rebuild the bearings board"]
        self.assertEqual([c["args"] for c in calls], [args])
        self.assertEqual(REBUILD_REQUEST, "ScreenPad: rebuild the bearings board")


class BearingsLoopTests(unittest.TestCase):
    def setUp(self):
        self.herdr = FakeHerdr([("w1:p1", "claude", "working")])
        self.firstmate = FakeFirstmate(calls=2, tasks={"lab:w1:p1": task("fix-api")})
        patcher = mock.patch("screenpad_agents.boardrequest.BOARD_WAIT", 1.5)
        patcher.start()
        self.addCleanup(patcher.stop)

    def rig(self):
        rig = Rig(self, self.herdr, self.firstmate)
        rig.app.board.poll = 0.02
        rig.until(lambda: rig.apps.provided().get("bearings") is not None)
        return rig

    def tile(self, rig):
        return rig.apps.provided()["bearings"]

    def tap(self, rig):
        rig.apps.event("bearings", "up", inside=True)

    def test_the_tile_is_a_compass_until_something_needs_saying(self):
        rig = self.rig()
        tile = self.tile(rig)
        self.assertEqual((tile["label"], tile["icon"].rsplit("/", 1)[-1]), ("Bearings", "compass.svg"))
        self.assertNotIn("text", tile)
        self.assertIn("bearings", rig.handled[0]["tiles"])

    def test_a_fresh_board_is_opened_at_once_and_nobody_is_asked(self):
        rig = self.rig()
        self.firstmate.board_age_seconds = BOARD_FRESH - 1
        self.tap(rig)
        rig.until(lambda: self.firstmate.opened == [FakeFirstmate.BOARD])
        rig.until(lambda: "opened the decisions board: " + FakeFirstmate.BOARD in rig.logged)
        rig.turn(10)
        self.assertEqual((self.firstmate.requests, self.firstmate.notes), (0, []))
        self.assertNotIn("text", self.tile(rig))

    def test_a_board_that_is_stale_or_not_open_makes_firstmate_rebuild_it(self):
        for board, age in ((FakeFirstmate.BOARD, BOARD_FRESH + 1), (None, 5.0)):
            with self.subTest(board=board):
                self.firstmate = FakeFirstmate(calls=2)
                self.firstmate.board, self.firstmate.board_age_seconds = board, age
                self.asks_firstmate()

    def asks_firstmate(self):
        rig = Rig(self, self.herdr, self.firstmate)
        rig.app.board.poll = 0.02
        rig.until(lambda: rig.apps.provided().get("bearings") is not None)
        self.tap(rig)
        rig.until(lambda: self.firstmate.request_texts == [REBUILD_REQUEST])
        rig.until(lambda: self.tile(rig).get("text") == "asking firstmate…")
        self.assertEqual(self.firstmate.opened, [])  # the stale board it has is not opened
        self.assertEqual(self.tile(rig)["tone"], "neutral")
        self.assertNotIn("icon", self.tile(rig))
        rig.until(lambda: "asked firstmate for the decisions board: created " + NOTE in rig.logged)

    def test_it_opens_the_board_as_soon_as_the_rebuilt_one_is_open(self):
        rig = self.rig()
        self.firstmate.board_age_seconds = 3600.0  # stale
        self.tap(rig)
        rig.until(lambda: self.firstmate.request_texts == [REBUILD_REQUEST])
        rig.until(lambda: self.firstmate.checks >= 2)
        # Taps while it waits ask nothing more and open nothing.
        self.tap(rig)
        rig.turn(10)
        self.assertEqual((self.firstmate.requests, self.firstmate.opened), (1, []))
        # firstmate rebuilds: the board's file is new.
        self.firstmate.board_age_seconds = 0.0
        rig.until(lambda: self.firstmate.opened == [FakeFirstmate.BOARD])
        rig.until(lambda: "text" not in self.tile(rig))
        self.assertIn("icon", self.tile(rig))
        self.assertEqual(self.firstmate.requests, 1)
        # The wait is over: the next tap on a fresh board opens it straight away.
        self.tap(rig)
        rig.until(lambda: len(self.firstmate.opened) == 2)
        self.assertEqual(self.firstmate.requests, 1)

    def test_firstmate_never_rebuilding_it_ends_in_a_tile_that_says_so(self):
        rig = self.rig()
        self.firstmate.board_age_seconds = 3600.0
        self.tap(rig)
        rig.until(lambda: self.tile(rig).get("text") == "asking firstmate…")
        rig.until(lambda: self.tile(rig).get("text", "").startswith("no fresh board: tap to retry"), 5)
        self.assertEqual(self.tile(rig)["tone"], "warning")
        self.assertEqual(self.firstmate.opened, [])
        self.assertTrue(any(line.startswith("no decisions board came") for line in rig.logged))
        # A tap tries again.
        self.tap(rig)
        rig.until(lambda: self.firstmate.requests == 2)

    def test_a_rebuilt_board_that_fails_to_open_ends_no_wait(self):
        rig = self.rig()
        self.firstmate.board_age_seconds = 3600.0
        self.tap(rig)
        rig.until(lambda: self.firstmate.request_texts == [REBUILD_REQUEST])
        # firstmate rebuilt it, but opening it fails: the wait goes on.
        self.firstmate.board_age_seconds, self.firstmate.open_error = 0.0, "systemd-run not found"
        checks = self.firstmate.checks
        rig.until(lambda: self.firstmate.checks >= checks + 3)
        rig.turn(10)
        self.assertEqual(self.tile(rig).get("text"), "asking firstmate…")
        self.assertFalse(any(line.startswith("firstmate opened the decisions board") for line in rig.logged))
        self.firstmate.open_error = None
        rig.until(lambda: self.firstmate.opened == [FakeFirstmate.BOARD])
        self.assertEqual(self.firstmate.requests, 1)

    def test_a_rebuild_and_a_board_request_never_share_a_request_id(self):
        rig = self.rig()
        self.firstmate.board_age_seconds = 3600.0
        self.tap(rig)
        rig.until(lambda: self.tile(rig).get("text", "").startswith("no fresh board: tap to retry"), 5)
        self.firstmate.board = None
        rig.app.request_board()
        rig.until(lambda: self.firstmate.requests == 2)
        self.assertEqual(self.firstmate.request_texts, [REBUILD_REQUEST, None])
        self.assertNotEqual(self.firstmate.request_ids[0], self.firstmate.request_ids[1])

    def test_a_failed_note_is_shown_on_the_tile(self):
        rig = self.rig()
        self.firstmate.board_age_seconds = 3600.0
        self.firstmate.request_error = "fm-inbox.sh note failed: exit 1"
        self.tap(rig)
        rig.until(lambda: self.tile(rig).get("text") == "failed: fm-inbox.sh note failed: exit 1")
        self.assertEqual(self.tile(rig)["tone"], "reject")

    def test_a_board_that_cannot_be_opened_says_why_and_asks_nobody(self):
        rig = self.rig()
        self.firstmate.open_error = "systemd-run not found"
        self.tap(rig)
        rig.until(lambda: self.tile(rig).get("text") == "failed: systemd-run not found")
        self.assertEqual(self.firstmate.requests, 0)

    def test_captain_s_call_keeps_its_own_two_steps(self):
        # The calls tile still only opens an open board, and the page's button its own words.
        rig = self.rig()
        self.firstmate.board_age_seconds = 3600.0
        rig.apps.event("calls", "up", inside=True)
        rig.until(lambda: self.firstmate.opened == [FakeFirstmate.BOARD])
        self.assertEqual((self.firstmate.requests, self.firstmate.notes), (0, []))

    def test_without_firstmate_there_is_no_bearings_tile(self):
        rig = Rig(self, self.herdr, None)
        rig.until(lambda: rig.widgets() is not None)
        self.assertNotIn("bearings", rig.handled[0]["tiles"])


if __name__ == "__main__":
    unittest.main()
