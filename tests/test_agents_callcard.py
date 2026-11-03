"""Captain's Call's card in the bar (callcard.py): each question fitted to the
boxes the touch bar draws it in, checked against the app protocol by the
stand-in touch bar (bar_support)."""

import unittest

import agents_support  # noqa: F401  (puts the checkout and vendor/ on sys.path)
from bar_support import FakeClient, parse_ask

from screenpad_agents import callcard
from screenpad_agents.callcard import ANSWER_CHARS, TEXT_CHARS, TITLE_CHARS, fit

ERROR = "fm-bearings-board.sh failed: exit 1: could not read the bearings of the home at /home/u/firstmate " * 3


def cards():
    return {
        "no board": callcard.no_board(),
        "requested": callcard.requested(),
        "not opened": callcard.not_opened(ERROR),
        "not requested": callcard.not_requested("fm-inbox.sh note failed: exit 1"),
    }


class FitTests(unittest.TestCase):
    def test_short_text_is_kept_on_one_line(self):
        self.assertEqual(fit("  Board\n requested ", 16), "Board requested")
        self.assertEqual(fit("x" * 16, 16), "x" * 16)

    def test_long_text_is_cut_at_a_word(self):
        cut = fit("the session listing could not be read, try again later", 30)
        self.assertEqual(cut, "the session listing could not…")
        self.assertLessEqual(len(cut), 30)
        # No dangling punctuation before the ellipsis.
        self.assertEqual(fit("lavish-axi failed: server unreachable", 21), "lavish-axi failed…")

    def test_a_word_longer_than_half_the_room_is_cut_inside(self):
        path = "/home/u/firstmate/bin/fm-bearings-board.sh"
        self.assertEqual(fit("failed " + path, 20), ("failed " + path)[:19] + "…")
        self.assertEqual(len(fit("x" * 300, TEXT_CHARS)), TEXT_CHARS)


class CardTests(unittest.TestCase):
    def test_every_card_fits_its_boxes(self):
        for name, card in cards().items():
            with self.subTest(name):
                self.assertLessEqual(len(card["title"]), TITLE_CHARS)
                self.assertLessEqual(len(card["text"]), TEXT_CHARS)
                for o in card["options"]:
                    self.assertLessEqual(len(o["label"]), ANSWER_CHARS)
                # Fixed words are never cut: only an error is.
                if name != "not opened":
                    self.assertNotIn("…", card["title"] + card["text"])
                # The stand-in touch bar takes it as the protocol says.
                parse_ask(FakeClient(), {"op": "ask", "id": "board.1", **card, "timeout": 30})

    def test_a_card_with_an_answer_has_no_ok_beside_dismiss(self):
        self.assertEqual(
            callcard.no_board()["options"], [{"id": callcard.REQUEST, "label": "Request", "tone": "accept"}]
        )
        for name in ("requested", "not opened", "not requested"):
            with self.subTest(name):
                self.assertEqual(cards()[name]["options"], [{"id": callcard.OK, "label": "OK"}])

    def test_an_error_is_cut_to_the_text_box(self):
        text = callcard.not_opened(ERROR)["text"]
        self.assertTrue(text.endswith("…"))
        self.assertTrue(" ".join(ERROR.split()).startswith(text[:-1]))
        self.assertEqual(callcard.not_opened("systemd-run not found")["text"], "systemd-run not found")


if __name__ == "__main__":
    unittest.main()
