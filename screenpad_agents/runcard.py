"""A run's card: its steps, its findings, and Focus to its agent.

Tapping a run on the Runs page opens its card in place of the grid: the run's
branch, status and PR, each step with its status, duration and findings
count, the findings' ids and severities when the run has any, and how it
ended; then Back, and Focus, which focuses the pane of the agent the run is
joined to (the same Herdr focus as an agent's card). It answers no gate and
starts, stops or retries nothing: a run waiting on a decision is answered in
its agent's pane. Pure: runwatch.py reads the run while the card is open.
"""

from screenpad_app import clip
from screenpad_app.common import MAX_LABEL, MAX_LINE_CHARS, MAX_LINES, MAX_TEXT

from .common import BACK_ICON, FOCUS_ICON, icon

COLUMNS, ROWS = 5, 4
LINES, BACK, FOCUS, AGENT, STATE = "runs.lines", "runs.back", "runs.focus", "runs.agent", "runs.state"
# Findings named on the card at most; the rest are counted.
MAX_FINDINGS = 6


class RunCard:
    """The card open for run_id: its last detail read with its findings
    (None until the first read), or why that read failed."""

    __slots__ = ("detail", "error", "run_id")

    def __init__(self, run_id):
        self.run_id, self.detail, self.error = run_id, None, None

    def widgets(self, view):
        """The card's widgets for view, the run as the page joins it."""
        detail = self.detail or view.detail
        lines = {"id": LINES, "col": 0, "row": 0, "cols": 4, "rows": 3, "touch": "none"}
        lines["lines"] = self.lines(view, detail)
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
        state = {"id": STATE, "col": 0, "row": 3, "cols": 5, "label": clip(view.project.name, MAX_LABEL)}
        words = [view.phrase()]
        if view.duplicate:
            words.append("more than one active run for this agent, copy or branch")
        elif view.attention and view.run.active:
            words.append("answer it in its agent's pane")
        state.update({"text": clip(" · ".join(words), MAX_TEXT), "tone": view.tone(), "touch": "none"})
        out.append(state)
        return out

    def lines(self, view, detail):
        run = view.run
        head = [run.branch, detail.status if detail is not None else run.status]
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
