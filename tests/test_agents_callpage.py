"""Captain's Call's page (callpage.py): the count, the calls waiting and the
decisions board's button laid out in large boxes with spans, each text
fitted to its box, as the "calls" page and in place of the Agents page's
grid, checked against the app protocol by the stand-in touch bar
(bar_support); and the calls as firstmate's reader names them."""

import unittest

from agents_support import SESSION, bearings_model
from bar_support import Apps, FakeClient

from screenpad_agents import callpage
from screenpad_agents.callpage import BUTTONS, LABEL_CHARS, TEXT_CHARS, WIDE_TEXT_CHARS, Board, fit
from screenpad_agents.common import ICONS
from screenpad_agents.firstmate import Bearings, Call, parse
from screenpad_agents.fleet import Fleet

CAPTAIN, BACK = ICONS + "/captain.svg", ICONS + "/back.svg"
DECISION = Call("decision", "screenpad-call-sync", "Choose how a tap opens the Captain's Call page")
CONTRIBUTION = Call("contribution", "insusty-redaction", "merge: PR ready, checks green, waiting on approval")
LONG = "the summary of a decision that runs on and on " * 6


def bearings(*calls, count=None, more=False):
    return Bearings(len(calls) if count is None else count, more, {}, waiting=calls)


def place(widgets):
    return {w["id"]: (w["col"], w["row"], w.get("cols", 1), w.get("rows", 1)) for w in widgets}


class LayoutTests(unittest.TestCase):
    def accepted(self, f):
        """What the stand-in touch bar makes of the fleet's messages."""
        apps, client = Apps(), FakeClient()
        apps.connect(client)
        apps.set_placed(f.tiles())
        apps.handle(client, {"op": "hello", "app": "agents", "tiles": f.tiles()})
        for msg in f.messages():
            apps.handle(client, msg)
        self.assertEqual([m for m in client.sent if m["op"] == "error"], [])
        return apps

    def fleet(self, b, error=None):
        f = Fleet(SESSION, True)
        f.set_agents([])
        f.set_bearings(b)
        if error:
            f.set_bearings(None, error)
        return f

    def test_the_calls_page_lays_out_the_count_the_button_and_the_calls(self):
        f = self.fleet(bearings(DECISION, CONTRIBUTION))
        page = self.accepted(f).pages["calls"]
        self.assertEqual((page.columns, page.rows), (4, 3))
        self.assertEqual(
            (page.look["title"], page.look["icon"], page.look["text"], page.look["badge"], page.look["tone"]),
            ("Captain's Call", CAPTAIN, "2 waiting", "2", "warning"),
        )
        got = {w.id: (w.col, w.row, w.cols, w.rows) for w in page.widgets}
        self.assertEqual(
            got,
            {
                "call.count": (0, 0, 3, 1),
                "call.board.idle": (3, 0, 1, 1),
                "call.item.0": (0, 1, 2, 2),
                "call.item.1": (2, 1, 2, 2),
            },
        )
        look = {w.id: w.look for w in page.widgets}
        self.assertEqual(look["call.count"]["label"], "2 waiting")
        self.assertEqual(look["call.item.0"]["label"], "screenpad-call-sync")
        self.assertEqual(look["call.item.0"]["text"], "decision: " + DECISION.text)
        self.assertEqual(look["call.item.1"]["text"], "contribution: " + CONTRIBUTION.text)
        self.assertEqual(look["call.board.idle"]["label"], "Open board")
        # Only the board's button takes a touch.
        self.assertEqual([w.id for w in page.widgets if w.touch != "none"], ["call.board.idle"])

    def test_the_agents_page_shows_the_same_view_with_back(self):
        f = self.fleet(bearings(DECISION))
        f.open_calls()
        page = self.accepted(f).pages["agents"]
        got = {w.id: (w.col, w.row, w.cols, w.rows) for w in page.widgets}
        self.assertEqual(
            got,
            {
                "call.count": (0, 0, 2, 1),
                "call.back": (2, 0, 1, 1),
                "call.board.idle": (3, 0, 1, 1),
                "call.item.0": (0, 1, 2, 2),
            },
        )
        self.assertEqual({w.id: w.look for w in page.widgets}["call.back"]["icon"], BACK)
        self.assertEqual(page.look["title"], "Agents")
        f.close_calls()
        self.assertEqual([w["id"] for w in f.page()["widgets"]], ["calls", "herdr"])

    def test_more_calls_than_the_rows_hold_are_counted(self):
        calls = [Call("decision", "task-%d" % i, "summary %d" % i) for i in range(6)]
        widgets = callpage.widgets(bearings(*calls), None, Board())
        self.assertEqual(
            place(widgets)["call.more"],
            (2, 2, 2, 1),
        )
        labels = [w["label"] for w in widgets if w["id"].startswith("call.item.") or w["id"] == "call.more"]
        self.assertEqual(labels, ["task-0", "task-1", "task-2", "+3 more"])
        # Four fit as they are; four with more left out by the reader, or a
        # count above the calls listed, give way to the count.
        four = callpage.widgets(bearings(*calls[:4]), None, Board())
        self.assertNotIn("call.more", place(four))
        more = callpage.widgets(bearings(*calls[:4], more=True), None, Board())
        self.assertEqual([w["label"] for w in more][-1], "+1+ more")
        listed = callpage.widgets(bearings(*calls[:2], count=5), None, Board())
        self.assertEqual([w["label"] for w in listed][-1], "+3 more")
        self.assertEqual(place(listed)["call.more"], (0, 2, 2, 1))
        # Three or four take a row each; one or two both rows.
        self.assertEqual({place(four)["call.item.%d" % i][3] for i in range(4)}, {1})
        two = callpage.widgets(bearings(*calls[:2]), None, Board())
        self.assertEqual([place(two)["call.item.%d" % i] for i in range(2)], [(0, 1, 2, 2), (2, 1, 2, 2)])

    def test_with_nothing_waiting_or_firstmate_unread_the_page_says_so(self):
        nothing = callpage.widgets(bearings(), None, Board())
        self.assertEqual(place(nothing)["call.none"], (0, 1, 4, 2))
        self.assertEqual(nothing[-1]["label"], "Nothing waits for you")
        self.assertEqual(nothing[0]["label"], "none waiting")
        unnamed = callpage.widgets(bearings(count=2), None, Board())
        self.assertEqual(unnamed[-1]["label"], "On the board")
        reading = callpage.widgets(None, None, Board())
        self.assertEqual([w["id"] for w in reading], ["call.count", "call.board.idle"])
        self.assertEqual(reading[0]["label"], "reading firstmate…")
        failed = callpage.widgets(None, "firstmate's reader failed: exit 1", Board())
        self.assertEqual(
            (failed[0]["label"], failed[0]["text"]), ("firstmate unreadable", "firstmate's reader failed: exit 1")
        )
        stale = callpage.widgets(bearings(DECISION), "firstmate's reader failed: exit 1", Board())
        self.assertEqual(stale[0]["label"], "1 waiting (stale)")
        for f in (self.fleet(bearings()), self.fleet(None, "boom")):
            self.accepted(f)


class FitTests(unittest.TestCase):
    def test_every_button_fits_its_box_and_fixed_words_are_never_cut(self):
        for state, (label, text, tone, what) in BUTTONS.items():
            with self.subTest(state):
                w = callpage.button(Board(state))
                self.assertEqual(
                    (w["id"], w["label"], w["text"], w["tone"]), ("call.board." + state, label, text, tone)
                )
                self.assertLessEqual(len(label), LABEL_CHARS)
                self.assertLessEqual(len(text), TEXT_CHARS)
                self.assertIn(what, (callpage.OPEN, callpage.REQUEST))
                # A reply or an error is cut to the box, at a word.
                long = callpage.button(Board(state, LONG))
                self.assertLessEqual(len(long["text"]), TEXT_CHARS)
        self.assertEqual(callpage.button(Board("late", "No: nothing waits."))["text"], "firstmate: No: nothing waits.")
        self.assertEqual(callpage.button(Board("failed", "exit 1"))["text"], "request failed: exit 1")
        self.assertEqual(
            callpage.button(Board("unopened", "systemd-run not found"))["text"], "not opened: systemd-run not found"
        )
        self.assertIn("in 3 minutes", callpage.LATE_TEXT)

    def test_a_call_s_words_are_fitted_to_its_box(self):
        call = Call("decision", "t" * 40, LONG)
        w = callpage.widgets(bearings(call), None, Board())[-1]
        self.assertEqual(len(w["label"]), 32)
        self.assertLessEqual(len(w["text"]), WIDE_TEXT_CHARS)
        self.assertTrue(w["text"].endswith("…") and ("decision: " + " ".join(LONG.split())).startswith(w["text"][:-1]))

    def test_fit_cuts_at_a_word(self):
        self.assertEqual(fit("  Board\n requested ", 16), "Board requested")
        self.assertEqual(
            fit("the session listing could not be read, try again later", 30), "the session listing could not…"
        )
        self.assertEqual(fit("lavish-axi failed: server unreachable", 21), "lavish-axi failed…")
        path = "/home/u/firstmate/bin/fm-bearings-board.sh"
        self.assertEqual(fit("failed " + path, 20), ("failed " + path)[:19] + "…")


class ActionTests(unittest.TestCase):
    def test_a_tap_means_what_the_button_shows_now(self):
        self.assertEqual(callpage.action("call.board.none", Board("none")), callpage.REQUEST)
        self.assertEqual(callpage.action("call.board.late", Board("late")), callpage.REQUEST)
        self.assertEqual(callpage.action("call.board.open", Board("open")), callpage.OPEN)
        # A button the page no longer shows, or another widget, means nothing.
        self.assertIsNone(callpage.action("call.board.none", Board("opening")))
        self.assertIsNone(callpage.action("call.count", Board("none")))
        self.assertIsNone(callpage.action(None, Board()))

    def test_a_state_change_says_whether_the_page_changed(self):
        b = Board()
        self.assertTrue(b.set("opening"))
        self.assertFalse(b.set("opening"))
        self.assertTrue(b.set("opening", "On it."))


class CallsTests(unittest.TestCase):
    def test_the_reader_s_calls_are_named_as_it_gives_them(self):
        model = bearings_model()
        model["decisions_open"] = [
            {"id": "screenpad-call-sync", "key": "k", "verb": "needs-decision", "summary": " Choose a route "},
            {"key": "parked", "verb": "captain-hold"},
            {"verb": "captain-hold"},
            "odd",
        ]
        model["contributions"]["captain"] = [
            {"task": "insusty-redaction", "kind": "merge", "reason": "PR ready", "url": "https://x/pr/1"},
            {"task": "docs", "url": "https://x/pr/2"},
            {"task": "bare"},
            {"kind": "merge"},
        ]
        b = parse(model)
        self.assertEqual(b.calls, 8)
        self.assertEqual(
            b.waiting,
            [
                Call("decision", "screenpad-call-sync", "Choose a route"),
                Call("decision", "parked", None),
                Call("contribution", "insusty-redaction", "merge: PR ready"),
                Call("contribution", "docs", "https://x/pr/2"),
                Call("contribution", "bare", None),
            ],
        )


if __name__ == "__main__":
    unittest.main()
