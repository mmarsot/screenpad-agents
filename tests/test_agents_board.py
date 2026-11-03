"""Captain's Call opening firstmate's decisions board: finding it through
fm-bearings-board.sh path and Lavish's session listing, opening its URL with
the opener in a scope of its own (stand-ins for both here, so nothing opens
on the screen and no unit is made), asking
firstmate for it with one fm-inbox.sh note (a stand-in too, writing into no
firstmate home), and the tap in the loop: the board opened, or the card
saying none is open, whose Open decisions board asks firstmate once."""

import os
import signal
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

from agents_support import FakeFirstmate, FakeHerdr, Rig, fake_bearings, read_calls, task
from desktop_support import fake_lavish, fake_opener, fake_scope, lavish_listing

from screenpad_agents.common import BOARD_REQUEST_HOLD
from screenpad_agents.firstmate import BOARD_REQUEST, SCOPE, Firstmate, FirstmateError, listed_url

URL = "http://127.0.0.1:4387/session/b2403039846e8e74"
NO_BOARD = "No decisions board open"
NO_BOARD_TEXT = "firstmate builds it: Open decisions board asks it for /bearings lavish."
REQUESTED_CARD = (
    "Decisions board requested",
    "firstmate was asked for /bearings lavish. Lavish opens the board once it is built; then a tap here opens it.",
    ["OK"],
)


class BoardTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = os.path.realpath(tmp.name)
        self.code = os.path.join(self.dir, "fm")
        fake_bearings(self.code)
        self.home = os.path.join(self.dir, "home")
        os.makedirs(os.path.join(self.home, ".lavish"))
        self.board = os.path.join(self.home, ".lavish", "bearings-board.html")
        self.lavish = fake_lavish(self.dir)
        self.opener = fake_opener(self.dir)
        self.scope = fake_scope(self.dir)
        bin_ = os.path.join(self.code, "bin")
        self.fm = Firstmate(
            self.home,
            os.path.join(bin_, "fm-bearings-snapshot.sh"),
            os.path.join(bin_, "fm-control.sh"),
            board=os.path.join(bin_, "fm-bearings-board.sh"),
            inbox=os.path.join(bin_, "fm-inbox.sh"),
            lavish=[self.lavish],
            opener=[self.opener, "open"],
            scope=[self.scope, *SCOPE[1:]],
        )

    def listing(self, *rows, raw=None):
        with open(os.path.join(self.dir, "listing.txt"), "w") as f:
            f.write(lavish_listing(*rows) if raw is None else raw)

    def opened(self):
        return read_calls(os.path.join(self.dir, "opened.jsonl"))

    def scoped(self):
        return read_calls(os.path.join(self.dir, "scoped.jsonl"))

    def test_opens_the_board_lavish_lists_open(self):
        self.listing(("/elsewhere/other.html", "open", "http://127.0.0.1:4387/session/1"), (self.board, "open", URL))
        with mock.patch.dict(os.environ, {"FM_HOME": "/home/me/firstmate", "FM_BACKEND": "herdr"}):
            self.assertEqual(self.fm.open_board(), (URL, None))
        self.assertEqual(self.opened(), [["open", URL]])
        # The opener ran in a transient scope of its own: a browser it starts
        # is outside the app's unit and its MemoryMax.
        scoped = ["--user", "--scope", "--collect", "--quiet", "--", self.opener, "open", URL]
        self.assertEqual(self.scoped(), [{"fm": [], "args": scoped}])
        # The board's path comes from firstmate, on the configured home only;
        # Lavish, systemd-run and the opener get no FM_* at all.
        board = read_calls(os.path.join(self.code, "bin", "board.jsonl"))
        self.assertEqual(board, [{"FM_HOME": self.home, "fm": ["FM_HOME"], "args": ["path"]}])
        self.assertEqual(read_calls(os.path.join(self.dir, "lavish.jsonl")), [{"fm": [], "args": []}])

    def test_the_opener_runs_through_systemd_run_in_a_scope_of_its_own(self):
        # The command line the app runs, opener and scope by default.
        fm = Firstmate(self.home, "r", "c")
        self.assertEqual(fm.scope, ["systemd-run", "--user", "--scope", "--collect", "--quiet", "--"])
        self.assertEqual(fm.opener, ["gio", "open"])
        self.listing((self.board, "open", URL))
        launched = []

        def run(argv, **kw):  # finds the board for real, launches nothing
            if argv[0] != "/usr/bin/systemd-run":
                return subprocess.run(argv, **kw)
            launched.append(argv)
            return subprocess.CompletedProcess(argv, 0, None, None)

        fm = Firstmate(self.home, "r", "c", run=run, board=self.fm.board, lavish=[self.lavish])
        with mock.patch("shutil.which", side_effect=lambda name: "/usr/bin/" + name):
            self.assertEqual(fm.open_board(), (URL, None))
        scoped = ["/usr/bin/systemd-run", "--user", "--scope", "--collect", "--quiet", "--", "gio", "open", URL]
        self.assertEqual(launched, [scoped])

    def test_without_systemd_run_the_opener_runs_directly_and_says_so(self):
        self.listing((self.board, "open", URL))
        missing = os.path.join(self.dir, "missing", "systemd-run")
        self.fm.scope = [missing, *SCOPE[1:]]
        url, note = self.fm.open_board()
        self.assertEqual(url, URL)
        self.assertEqual(
            note,
            "%s not found: %s open ran in the app's own cgroup, where a browser it starts counts against it"
            % (missing, self.opener),
        )
        self.assertEqual((self.opened(), self.scoped()), ([["open", URL]], []))

    def test_a_scope_that_cannot_be_made_opens_nothing(self):
        self.listing((self.board, "open", URL))
        open(os.path.join(self.dir, "scope.fail"), "w").close()
        with self.assertRaisesRegex(FirstmateError, "opening the board failed: exit 1"):
            self.fm.open_board()
        self.assertEqual(len(self.scoped()), 1)
        self.assertEqual(self.opened(), [])

    def test_a_browser_the_opener_starts_does_not_hold_the_open(self):
        # gio open returns at once, but a browser it starts lives on with its
        # output: the open must not wait for that browser (OPEN_TIMEOUT 15 s).
        self.listing((self.board, "open", URL))
        open(os.path.join(self.dir, "opener.linger"), "w").close()
        start = time.monotonic()
        self.assertEqual(self.fm.open_board(), (URL, None))
        with open(os.path.join(self.dir, "linger.pid")) as f:
            pid = int(f.read())
        self.addCleanup(os.kill, pid, signal.SIGKILL)
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(self.opened(), [["open", URL]])

    def test_the_board_is_found_by_its_real_path(self):
        os.makedirs(os.path.join(self.dir, "real"))
        os.rmdir(os.path.join(self.home, ".lavish"))
        os.symlink(os.path.join(self.dir, "real"), os.path.join(self.home, ".lavish"))
        self.listing((os.path.join(self.dir, "real", "bearings-board.html"), "open", URL))
        self.assertEqual(self.fm.board_url(), URL)

    def test_the_board_is_found_when_lavish_lists_it_unresolved(self):
        os.makedirs(os.path.join(self.dir, "real"))
        os.rmdir(os.path.join(self.home, ".lavish"))
        os.symlink(os.path.join(self.dir, "real"), os.path.join(self.home, ".lavish"))
        for listed in (self.board, self.home + "/./.lavish//bearings-board.html"):
            with self.subTest(listed=listed):
                self.listing((listed, "open", URL))
                self.assertEqual(self.fm.board_url(), URL)

    def test_no_board_open_opens_nothing(self):
        for rows in (
            (),
            ((self.board, "user-ended", URL),),
            ((self.board + ".bak", "open", URL),),
            (("/elsewhere" + self.board, "open", URL),),
        ):
            with self.subTest(rows=rows):
                self.listing(*rows)
                self.assertEqual(self.fm.open_board(), (None, None))
        self.assertEqual(self.opened(), [])

    def test_only_a_local_url_is_opened(self):
        for url in ("https://example.com/session/1", "file:///etc/passwd", "http://127.0.0.1:4387/a b", "-x"):
            with self.subTest(url=url):
                self.listing((self.board, "open", url))
                with self.assertRaisesRegex(FirstmateError, "not a local URL"):
                    self.fm.open_board()
        self.assertEqual((self.opened(), self.scoped()), ([], []))
        for url in ("http://localhost:4387/session/ab", "http://[::1]:80/"):
            self.assertEqual(listed_url('  %s,open,"%s",0,none\n' % (self.board, url), self.board), url)

    def test_failures_say_why(self):
        self.listing(raw="fail")
        with self.assertRaisesRegex(FirstmateError, "lavish-axi failed: lavish-axi: server unreachable"):
            self.fm.open_board()
        self.listing((self.board, "open", URL))
        open(os.path.join(self.dir, "opener.fail"), "w").close()
        with self.assertRaisesRegex(FirstmateError, "opening the board failed: exit 2"):
            self.fm.open_board()
        os.remove(os.path.join(self.code, "bin", "fm-bearings-board.sh"))
        with self.assertRaisesRegex(FirstmateError, "firstmate has no bin/fm-bearings-board.sh"):
            self.fm.open_board()
        self.assertIsNone(Firstmate(self.home, "r", "c").board)
        with self.assertRaisesRegex(FirstmateError, "firstmate has no"):
            Firstmate(self.home, "r", "c").board_url()

    def test_the_board_is_asked_for_with_one_inbox_note(self):
        with mock.patch.dict(os.environ, {"FM_HOME": "/home/me/firstmate", "FM_BACKEND": "herdr"}):
            self.assertEqual(self.fm.request_board("screenpad-board-1-ab"), "created 1793706159-abc123")
        # One note on the configured home only, under its request id, its
        # text after --, and nothing else: no board built, no Lavish, no opener.
        calls = read_calls(os.path.join(self.code, "bin", "inbox.jsonl"))
        args = ["note", "--json", "--request-id", "screenpad-board-1-ab", "--", BOARD_REQUEST]
        self.assertEqual(calls, [{"FM_HOME": self.home, "fm": ["FM_HOME"], "args": args}])
        self.assertIn("/bearings lavish", BOARD_REQUEST)
        self.assertEqual(read_calls(os.path.join(self.code, "bin", "board.jsonl")), [])
        self.assertEqual((read_calls(os.path.join(self.dir, "lavish.jsonl")), self.opened()), ([], []))

    def test_a_refused_request_says_why_and_a_retry_replays_it(self):
        fail = os.path.join(self.code, "bin", "inbox.fail")
        open(fail, "w").close()
        with self.assertRaisesRegex(FirstmateError, "fm-inbox.sh note failed: fm-inbox: saved, but firstmate was not"):
            self.fm.request_board("screenpad-board-1-ab")
        # The same request id again is fm-inbox.sh's replay, not a new note.
        os.remove(fail)
        self.assertEqual(self.fm.request_board("screenpad-board-1-ab"), "replay 1793706159-abc123")
        # Once firstmate has drained it (the note in handled/, announced but
        # not acknowledged) or acknowledged it, a replay wakes nothing: it is
        # told apart (None), so the app asks again under a new id.
        for listing in ("inbox.handled", "inbox.acked"):
            with open(os.path.join(self.code, "bin", listing), "w") as f:
                f.write("screenpad-board-1-ab\n")
            self.assertIsNone(self.fm.request_board("screenpad-board-1-ab"))
            os.remove(os.path.join(self.code, "bin", listing))
        self.assertEqual(self.fm.request_board("screenpad-board-1-ab"), "replay 1793706159-abc123")
        os.remove(os.path.join(self.code, "bin", "fm-inbox.sh"))
        with self.assertRaisesRegex(FirstmateError, "firstmate has no bin/fm-inbox.sh"):
            self.fm.request_board("screenpad-board-1-ab")
        with self.assertRaisesRegex(FirstmateError, "firstmate has no bin/fm-inbox.sh"):
            Firstmate(self.home, "r", "c").request_board("screenpad-board-1-ab")

    def test_a_note_answer_that_is_not_one_is_refused(self):
        for out in ("", "queued 1793706159-abc123\n", '{"schema": "other"}\n', "[]\n"):
            done = subprocess.CompletedProcess([], 0, out, "")
            fm = Firstmate(self.home, "r", "c", run=lambda *a, done=done, **k: done, inbox=self.fm.inbox)
            with self.assertRaisesRegex(FirstmateError, "fm-inbox.sh note printed no fm-inbox-note.v1"):
                fm.request_board("screenpad-board-1-ab")

    def test_a_board_path_that_is_not_one_is_refused(self):
        for out in ("", "relative/board.html\n", "/a\n/b\n"):
            done = subprocess.CompletedProcess([], 0, out, "")
            fm = Firstmate(self.home, "r", "c", run=mock.Mock(return_value=done), board=self.fm.board)
            with self.subTest(out=out), self.assertRaisesRegex(FirstmateError, "printed no board path"):
                fm.board_url()


class BoardTapTests(unittest.TestCase):
    def setUp(self):
        self.herdr = FakeHerdr([("w1:p1", "claude", "blocked")])
        self.firstmate = FakeFirstmate(calls=2, tasks={"lab:w1:p1": task("fix-api")})

    def rig(self):
        rig = Rig(self, self.herdr, self.firstmate)
        rig.apps.asks.set_available(True)
        rig.until(lambda: rig.widgets() == ["calls", "agent.w1.p1"])
        rig.until(lambda: rig.apps.provided().get("calls", {}).get("badge") == "2")
        return rig

    def asked(self, rig):
        return [(a.title, a.text, [o["label"] for o in a.options]) for a in rig.apps.asks.queue]

    def test_a_tap_opens_the_board_and_reads_firstmate_again(self):
        rig = self.rig()
        reads = self.firstmate.reads
        for kind in ("down", "cancel", "long"):
            rig.apps.press(rig.client(), "agents", "calls", kind)
        rig.apps.event("calls", "down")
        rig.apps.event("calls", "up", inside=False)
        rig.turn(10)
        self.assertEqual(self.firstmate.board_calls, 0)
        rig.apps.press(rig.client(), "agents", "calls", "tap")
        rig.until(lambda: self.firstmate.opened == [FakeFirstmate.BOARD])
        rig.until(lambda: self.firstmate.reads == reads + 1)
        rig.until(lambda: rig.logged == ["opened the decisions board: " + FakeFirstmate.BOARD])
        rig.apps.event("calls", "up", inside=True)
        rig.until(lambda: len(self.firstmate.opened) == 2)
        self.assertEqual(self.asked(rig), [])
        # Read-only: nothing went to an agent or to firstmate's control.
        self.assertEqual((self.herdr.sent, self.firstmate.interrupted), ([], []))

    def test_an_opener_without_a_scope_is_logged(self):
        rig = self.rig()
        self.firstmate.board_note = "systemd-run not found: gio open ran in the app's own cgroup"
        rig.apps.press(rig.client(), "agents", "calls", "tap")
        rig.until(
            lambda: rig.logged == ["opened the decisions board: " + FakeFirstmate.BOARD, self.firstmate.board_note]
        )
        self.assertEqual(self.asked(rig), [])

    def test_taps_while_it_opens_open_it_once(self):
        rig = self.rig()
        self.firstmate.release = threading.Event()
        for _ in range(3):
            rig.apps.press(rig.client(), "agents", "calls", "tap")
            rig.turn(3)
        rig.until(lambda: self.firstmate.board_calls == 1)
        self.firstmate.release.set()
        rig.until(lambda: self.firstmate.opened == [FakeFirstmate.BOARD])
        rig.turn(10)
        self.assertEqual(self.firstmate.board_calls, 1)

    def test_no_board_open_shows_a_card_and_builds_nothing(self):
        rig = self.rig()
        self.firstmate.board = None
        rig.apps.press(rig.client(), "agents", "calls", "tap")
        card = (NO_BOARD, NO_BOARD_TEXT, ["Open decisions board", "OK"])
        rig.until(lambda: self.asked(rig) == [card])
        self.assertEqual(self.firstmate.opened, [])
        self.assertEqual(rig.logged, ["no decisions board is open"])
        # A second tap replaces the card rather than queueing another.
        rig.apps.event("calls", "up", inside=True)
        rig.until(lambda: self.firstmate.board_calls == 2)
        rig.turn(10)
        self.assertEqual(self.asked(rig), [card])
        # OK closes it, and does nothing more: no note to firstmate either.
        ask = rig.apps.asks.queue[0]
        rig.apps.asks.choose(ask, 1)
        rig.turn(10)
        self.assertEqual((self.asked(rig), rig.app._asked), ([], None))
        self.assertEqual((self.herdr.sent, self.firstmate.interrupted, self.firstmate.opened), ([], [], []))
        self.assertEqual(self.firstmate.requests, 0)

    def no_board_card(self, rig):
        rig.apps.press(rig.client(), "agents", "calls", "tap")
        rig.until(lambda: [a.title for a in rig.apps.asks.queue] == [NO_BOARD])
        return rig.apps.asks.queue[0]

    def test_open_decisions_board_asks_firstmate_once(self):
        rig = self.rig()
        self.firstmate.board = None
        rig.apps.asks.choose(self.no_board_card(rig), 0)
        rig.until(lambda: self.asked(rig) == [REQUESTED_CARD])
        self.assertEqual(self.firstmate.requests, 1)
        self.assertIn("asked firstmate for the decisions board: created 1793706159-abc123", rig.logged)
        # While it is pending, a tap on Captain's Call still looks for the
        # board, and says it was requested; nothing asks firstmate again.
        calls = self.firstmate.board_calls
        rig.apps.event("calls", "up", inside=True)
        rig.until(lambda: self.firstmate.board_calls == calls + 1)
        rig.turn(10)
        self.assertEqual(self.asked(rig), [REQUESTED_CARD])
        rig.app.request_board()  # an Open decisions board chosen on an older card
        rig.turn(10)
        self.assertEqual((self.firstmate.requests, self.asked(rig)), (1, [REQUESTED_CARD]))
        self.assertEqual((self.herdr.sent, self.firstmate.interrupted, self.firstmate.opened), ([], [], []))

    def test_a_request_ends_when_the_board_opens_or_after_the_hold(self):
        rig = self.rig()
        self.firstmate.board = None
        rig.apps.asks.choose(self.no_board_card(rig), 0)
        rig.until(lambda: self.firstmate.requests == 1)
        # Past the hold, the card offers to ask again, as a new request.
        rig.app._requested -= BOARD_REQUEST_HOLD
        rig.app._request_made -= BOARD_REQUEST_HOLD
        rig.apps.asks.choose(self.no_board_card(rig), 0)
        rig.until(lambda: self.firstmate.requests == 2)
        # Once the board is seen open, a later request asks again at once.
        self.firstmate.board = FakeFirstmate.BOARD
        rig.apps.press(rig.client(), "agents", "calls", "tap")
        rig.until(lambda: rig.app._requested is None)
        self.assertEqual(self.firstmate.opened, [FakeFirstmate.BOARD])
        self.firstmate.board = None
        rig.apps.asks.choose(self.no_board_card(rig), 0)
        rig.until(lambda: self.firstmate.requests == 3)
        ids = self.firstmate.request_ids
        self.assertEqual(len(set(ids)), 3)
        for rid in ids:
            self.assertRegex(rid, r"\A[A-Za-z0-9._:-]{1,128}\Z")

    def test_a_failed_request_is_shown_and_can_be_tried_again(self):
        rig = self.rig()
        self.firstmate.board = None
        self.firstmate.request_error = "fm-inbox.sh note failed: exit 1"
        rig.apps.asks.choose(self.no_board_card(rig), 0)
        failed = ("Decisions board not requested", "fm-inbox.sh note failed: exit 1", ["OK"])
        rig.until(lambda: self.asked(rig) == [failed])
        self.assertIn("the request for the decisions board failed: fm-inbox.sh note failed: exit 1", rig.logged)
        self.firstmate.request_error = None
        rig.apps.asks.choose(self.no_board_card(rig), 0)
        rig.until(lambda: self.asked(rig) == [REQUESTED_CARD])
        # The retry repeats the same request, so fm-inbox.sh replays a note
        # it saved before failing instead of queueing a second one.
        ids = self.firstmate.request_ids
        self.assertEqual((len(ids), ids[0]), (2, ids[1]))

    def test_an_acknowledged_replay_is_asked_again_under_a_new_id(self):
        rig = self.rig()
        self.firstmate.board = None
        self.firstmate.request_error = "fm-inbox.sh note failed: exit 3"
        rig.apps.asks.choose(self.no_board_card(rig), 0)
        rig.until(lambda: [a.title for a in rig.apps.asks.queue] == ["Decisions board not requested"])
        # firstmate handled that note meanwhile: the retry's replay wakes
        # nothing, so the same job asks once more, under a new id, and only
        # that note makes the card say it was requested.
        first = self.firstmate.request_ids[0]
        self.firstmate.acknowledged.add(first)
        self.firstmate.request_error = None
        rig.apps.asks.choose(self.no_board_card(rig), 0)
        rig.until(lambda: self.asked(rig) == [REQUESTED_CARD])
        ids = self.firstmate.request_ids
        self.assertEqual(ids[:2], [first, first])
        self.assertEqual(len(ids), 3)
        self.assertNotEqual(ids[2], first)
        self.assertEqual(rig.app._request_id, ids[2])
        self.assertIn("asked firstmate for the decisions board: created 1793706159-abc123", rig.logged)

    def test_a_failed_request_older_than_the_hold_is_asked_anew(self):
        rig = self.rig()
        self.firstmate.board = None
        self.firstmate.request_error = "fm-inbox.sh note failed: exit 3"
        rig.apps.asks.choose(self.no_board_card(rig), 0)
        rig.until(lambda: [a.title for a in rig.apps.asks.queue] == ["Decisions board not requested"])
        # firstmate may have handled that note since: replaying its id would
        # wake nothing, so past the hold the retry is a new request.
        rig.app._request_made -= BOARD_REQUEST_HOLD
        self.firstmate.request_error = None
        rig.apps.asks.choose(self.no_board_card(rig), 0)
        rig.until(lambda: self.asked(rig) == [REQUESTED_CARD])
        ids = self.firstmate.request_ids
        self.assertEqual(len(ids), 2)
        self.assertNotEqual(ids[0], ids[1])

    def test_a_failure_is_shown_on_the_card(self):
        rig = self.rig()
        self.firstmate.board_error = "lavish-axi failed: server unreachable"
        rig.apps.press(rig.client(), "agents", "calls", "tap")
        rig.until(lambda: self.asked(rig) == [("Decisions board not opened", self.firstmate.board_error, ["OK"])])
        self.assertEqual(rig.logged, ["the decisions board did not open: lavish-axi failed: server unreachable"])
        self.firstmate.board_error = RuntimeError("boom")
        rig.apps.press(rig.client(), "agents", "calls", "tap")
        rig.until(lambda: self.asked(rig) == [("Decisions board not opened", "RuntimeError: boom", ["OK"])])
        self.firstmate.board_error = None
        rig.apps.press(rig.client(), "agents", "calls", "tap")
        rig.until(lambda: self.firstmate.opened == [FakeFirstmate.BOARD])

    def test_a_card_the_bar_cannot_show_is_logged(self):
        rig = self.rig()
        rig.apps.asks.set_available(False)
        self.firstmate.board = None
        rig.apps.press(rig.client(), "agents", "calls", "tap")
        rig.until(lambda: "the touch bar could not show the board's card" in rig.logged)
        self.assertIsNone(rig.app._asked)

    def test_without_firstmate_a_tap_opens_nothing(self):
        rig = Rig(self, self.herdr, None)
        rig.until(lambda: rig.widgets() == ["agent.w1.p1"])
        rig.apps.event("calls", "up", inside=True)
        rig.app.captains_call()
        rig.turn(5)
        self.assertEqual(self.firstmate.board_calls, 0)


if __name__ == "__main__":
    unittest.main()
