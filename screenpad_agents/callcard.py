"""Captain's Call's card in the bar: what a tap on Captain's Call says when
it opens no decisions board, fitted to the card the touch bar draws.

The touch bar lays a question out itself (screenpad-linux's docs/app-api.md,
"How a question shows"): its title and text over two of the bar's spots,
Dismiss in the third, then each answer in a spot of its own, a box taller
than it is wide. The type is sized by the bar's own height, and the title
and the answers do not wrap: what is wider than its box is cut. Measured
with the shell's font at a bar 208 px high on the 1920 px ScreenPad, the
title box holds about 480 px of 52 px bold type (16 characters), an answer
240 px (8), and the text, 37 px and wrapping, six lines of 480 px (120
characters). So each card's title fits TITLE_CHARS and each answer
ANSWER_CHARS, and a text longer than TEXT_CHARS (an error) is cut at a word,
with an ellipsis; the log keeps it whole. Dismiss closes a card, so one with
an answer of its own has no OK beside it, and fewer narrow boxes: OK stands
in for an answer only on a card that just tells. firstmate's reply, shown
on the card, is cut the same way. A lower bar (160 px by
default) has smaller type, and the same words fit with room to spare.
"""

from .common import BOARD_WAIT

TITLE_CHARS, ANSWER_CHARS, TEXT_CHARS = 16, 8, 120

# The answers: Request (and Retry) asks firstmate for the board, Open opens
# it, OK only closes the card.
REQUEST, OPEN, OK = "request", "open", "ok"

NO_BOARD = "No board open"
NO_BOARD_TEXT = "Request asks firstmate to build the decisions board; Lavish then opens it on the main screen."
OPENING = "Opening board…"
OPENING_TEXT = "firstmate is building the decisions board, about a minute. This card says when it is open."
OPENED = "Board open"
OPENED_TEXT = "firstmate built the decisions board. Open shows it on the main screen."
LATE = "No board yet"
LATE_TEXT = "firstmate has not opened the decisions board in %d minutes. Retry asks it again." % (BOARD_WAIT // 60)
NOT_OPENED, NOT_REQUESTED = "Board not opened", "Request failed"
# What firstmate replied to the request, ahead of its words.
REPLIED = "firstmate: "


def fit(text, limit):
    """text on one line, cut to at most limit characters at a word (or mid
    word, when a word takes most of the room), ending in an ellipsis when
    something was left out."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if text[limit - 1] != " " and space >= limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:.-") + "…"


def card(title, text, answer=None):
    """A question's title, text and answers, each fitted to its box: answer
    (a dict with an id, a label and a tone) or, without one, OK."""
    options = [answer or {"id": OK, "label": "OK"}]
    return {
        "title": fit(title, TITLE_CHARS),
        "text": fit(text, TEXT_CHARS),
        "options": [dict(o, label=fit(o["label"], ANSWER_CHARS)) for o in options],
    }


def _retry():
    return {"id": REQUEST, "label": "Retry", "tone": "accept"}


def no_board():
    return card(NO_BOARD, NO_BOARD_TEXT, {"id": REQUEST, "label": "Request", "tone": "accept"})


def opening(reply=None):
    """firstmate was asked and the board is not open yet: what firstmate
    replied, once it has."""
    return card(OPENING, REPLIED + reply if reply else OPENING_TEXT)


def opened():
    return card(OPENED, OPENED_TEXT, {"id": OPEN, "label": "Open", "tone": "accept"})


def late(reply=None):
    """The wait for the board ended without it: what firstmate replied, or
    that it said nothing."""
    return card(LATE, REPLIED + reply if reply else LATE_TEXT, _retry())


def not_opened(error):
    return card(NOT_OPENED, error)


def not_requested(error):
    return card(NOT_REQUESTED, error, _retry())
