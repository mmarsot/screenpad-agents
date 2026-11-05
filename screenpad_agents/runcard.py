"""A run's card: its steps, its findings, and Focus to its agent.

Tapping a run on the Runs page opens its card in place of the grid: the run's
branch, status and PR, each step with its status, duration and findings
count, the findings' ids and severities when the run has any, and how it
ended; then Back, and Focus, which focuses the pane of the agent the run is
joined to (the same Herdr focus as an agent's card), and, once the run has a
pull request (no-mistakes' "pr", a pull request's URL on the forge:
nomistakes.pr_url), Open PR, which opens it in the browser on the main
screen (runwatch.py, desktop.py) and says whether it did. With [runs]
watch_command, Watch opens a live view of the run (the command, started
detached, runs.py's Runs.watch). A run whose pull request is ready for the
captain (runs.View.review) also has Review, Approve and Request changes,
those of Captain's Call (reviewcall.py), in the cards' bottom row, which
then holds buttons only. It answers no gate and starts, stops or retries
nothing: a run waiting on a decision is answered in its agent's pane. Pure:
runwatch.py reads the run while the card is open.
"""

from screenpad_app import clip
from screenpad_app.common import MAX_LABEL, MAX_LINE_CHARS, MAX_LINES, MAX_TEXT

from . import reviewcall
from .callpage import LABEL_CHARS, TEXT_CHARS, fit
from .common import BACK_ICON, FOCUS_ICON, PR_ICON, icon

COLUMNS, ROWS = 5, 4
LINES, BACK, FOCUS, AGENT, STATE = "runs.lines", "runs.back", "runs.focus", "runs.agent", "runs.state"
PR, WATCH = "runs.pr", "runs.watch"
# A button's box in the bottom row is a fifth of the bar: about 12 characters
# of label and 57 of text (callpage.py measures a quarter: 16 and 72).
CARD_LABEL, CARD_TEXT = 12, 57
# What the review buttons say in a box that small.
SHORT = {"Request changes": "Changes", "Changes requested": "Requested"}
# Findings named on the card at most; the rest are counted.
MAX_FINDINGS = 6


class RunCard:
    """The card open for run_id: its last detail read with its findings
    (None until the first read), or why that read failed; and its pull
    request's open: the URL being opened, the URL last opened, or (URL, why)
    when that open failed."""

    __slots__ = (
        "detail",
        "error",
        "failed",
        "opened",
        "opening",
        "run_id",
        "watch_error",
        "watch_started",
        "watching",
    )

    def __init__(self, run_id):
        self.run_id, self.detail, self.error = run_id, None, None
        self.opening = self.opened = self.failed = None
        # Watch: the command is being started, was started, or failed.
        self.watching, self.watch_started, self.watch_error = False, False, None

    def start_watch(self):
        """Watch chosen: False while the command is being started."""
        if self.watching:
            return False
        self.watching, self.watch_started, self.watch_error = True, False, None
        return True

    def watch_ended(self, error):
        """The watch command started, or failed with error."""
        self.watching = False
        self.watch_started, self.watch_error = error is None, error

    def open_pr(self, url):
        """Open PR chosen for url: False while an open is on its way."""
        if self.opening is not None:
            return False
        self.opening, self.opened, self.failed = url, None, None
        return True

    def pr_opened(self, url, error):
        """The open of url ended, failed with error or not."""
        if self.opening == url:
            self.opening = None
            self.opened, self.failed = (None, (url, error)) if error else (url, None)

    def widgets(self, view, review=None, watch=False):
        """The card's widgets for view, the run as the page joins it: review
        is (the change ready for review, its entry, whether a review command
        is configured) when the run leaves one, and watch whether [runs]
        watch_command is set."""
        detail = self.detail or view.detail
        lines = {"id": LINES, "col": 0, "row": 0, "cols": 4, "rows": 3, "touch": "none"}
        url = view.pr_url(detail)
        row = self.bottom(url, review, watch)
        # With no room for the state widget, its project is on the first line.
        lines["lines"] = self.lines(view, detail, project=row[0] is None)
        out = [lines, {"id": BACK, "col": 4, "row": 0, "label": "Back", "icon": icon(BACK_ICON)}]
        focus = {"id": FOCUS, "col": 4, "row": 1, "label": "Focus"}
        if view.pane:
            focus["icon"] = icon(FOCUS_ICON)
        else:
            focus.update({"text": "no agent in Herdr has its copy", "touch": "none"})
        out.append(focus)
        agent = {"id": AGENT, "col": 4, "row": 2, "label": clip(view.task or "no task", MAX_LABEL), "touch": "none"}
        agent["text"] = clip("pane %s" % view.pane if view.pane else "no agent", MAX_TEXT)
        out.append(agent)
        state, buttons = row
        if state is not None:
            words = [view.phrase()]
            if view.duplicate:
                words.append("more than one active run for this agent, copy or branch")
            elif view.attention and view.run.active:
                words.append("answer it in its agent's pane")
            state.update({"label": clip(view.project.name, MAX_LABEL), "text": clip(" · ".join(words), MAX_TEXT)})
            state.update({"tone": view.tone(), "touch": "none"})
            out.append(state)
        return out + buttons

    def bottom(self, url, review, watch):
        """The bottom row: (the state widget with its place, or None when
        the buttons take the whole row, the buttons placed from the right):
        the review's, Watch, then Open PR."""
        buttons = []
        if review is not None:
            for b in reviewcall.buttons(review[0], review[1], review[2]):
                w = {k: v for k, v in b.items() if k != "act"}
                w["label"] = fit(SHORT.get(w["label"], w["label"]), CARD_LABEL)
                w["text"] = fit(w["text"], CARD_TEXT)
                buttons.append(w)
        if watch:
            buttons.append(self.watch_button())
        if url:
            buttons.append(self.pr_button(url))
        first = COLUMNS - len(buttons)
        for col, w in enumerate(buttons, start=first):
            w.update({"col": col, "row": 3})
        state = {"id": STATE, "col": 0, "row": 3, "cols": first} if first > 0 else None
        return state, buttons

    def watch_button(self):
        """Watch: what a tap does, or that the command is starting, started,
        or why it did not."""
        button = {"id": WATCH, "label": "Watch"}
        if self.watching:
            return dict(button, text="starting the view…", touch="none")
        if self.watch_error is not None:
            return dict(button, text=fit("not opened: " + self.watch_error, CARD_TEXT), tone="reject")
        text = "opened on the main screen" if self.watch_started else "live view of the run"
        return dict(button, text=text, tone="accept")

    def pr_button(self, url):
        """Open PR, for the run's pull request at url: what a tap does, or
        that it is opening, or why it was not opened."""
        number = url.rpartition("/")[2]
        button = {"id": PR, "col": 4, "row": 3}
        if self.opening == url:
            return dict(button, label="Opening PR…", touch="none")
        if self.failed is not None and self.failed[0] == url:
            text = fit("not opened: " + self.failed[1], TEXT_CHARS)
            return dict(button, label=fit("Open PR #" + number, LABEL_CHARS), text=text, tone="reject")
        words = "PR #%s opened" if self.opened == url else "Open PR #%s"
        return dict(button, label=fit(words % number, LABEL_CHARS), icon=icon(PR_ICON))

    def lines(self, view, detail, project=False):
        run = view.run
        head = [view.project.name] if project else []
        head += [run.branch, detail.status if detail is not None else run.status]
        if run.pr:
            head.append(run.pr)
        out = [" · ".join(head)]
        if detail is None:
            out.append(self.error or "reading the run…")
            return [cut(line) for line in out]
        for s in detail.steps:
            findings = "%d finding%s" % (s.findings, "" if s.findings == 1 else "s") if s.findings else ""
            took = duration(s.duration_ms) if s.status not in ("running", "fixing", "pending") else ""
            out.append(("%-10s %-18s %9s  %s" % (s.name, s.status, took, findings)).rstrip())
        if detail.waiting:
            out.append("waiting on a decision: answer it in the agent's pane")
        named = detail.findings[:MAX_FINDINGS]
        if named:
            text = ", ".join("%s (%s)" % (fid, sev) for _, fid, sev in named)
            rest = len(detail.findings) - len(named)
            out.append("findings: " + text + (" and %d more" % rest if rest else ""))
        elif detail.summary:
            out.append("findings: " + detail.summary)
        if detail.outcome:
            out.append("outcome: " + detail.outcome)
        if detail.error:
            out += wrap("error: " + " ".join(detail.error.split()), MAX_LINE_CHARS, 3)
        if self.error:
            out.append("(stale: %s)" % self.error)
        out = [cut(line) for line in out]
        return out if len(out) <= MAX_LINES else out[: MAX_LINES - 1] + ["…"]


def duration(ms):
    """A step's duration in a few characters: 17 ms, 4 s, 8m 04s, 1h 02m."""
    if ms < 1000:
        return "%d ms" % ms
    s = ms // 1000
    if s < 60:
        return "%d s" % s
    if s < 3600:
        return "%dm %02ds" % (s // 60, s % 60)
    return "%dh %02dm" % (s // 3600, s % 3600 // 60)


def cut(line):
    """A line of the card: printable, at most MAX_LINE_CHARS, its spacing
    kept (clip would fold the columns)."""
    line = "".join(c if c.isprintable() else " " for c in line).rstrip()
    return line if len(line) <= MAX_LINE_CHARS else line[: MAX_LINE_CHARS - 1] + "…"


def wrap(text, width, most):
    """text cut into at most most lines of width, the last ending in … when
    some was left out."""
    out = [text[i : i + width] for i in range(0, len(text), width)][:most]
    if len(text) > width * most:
        out[-1] = out[-1][: width - 1] + "…"
    return out
