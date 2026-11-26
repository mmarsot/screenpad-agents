"""The Limits page: each provider's quota left, one large row per window.

Pure: it turns the providers usage.py read (the ones `[usage] providers`
keeps) into the "page" message of screenpad-linux's docs/app-api.md. A grid
six columns wide: a provider is a block of rows, its logo in the first column
across them (the provider's name too, where the cell has room), and one row
per quota window with, left to right, the window's plain name with when it
resets ("resets in 3h20", or a weekday and date), a bar of what is left
(a line of block characters, green, amber under 25 percent, red under 10) and
the percent left. A provider that could not be read has its logo and "No
data" with the reason in words: never a number. The last row is the Details
button, which opens the terminal viewer (usagewatch.py), and a line that says
what the page shows, or that the last read failed. At most MAX_ROWS rows
(the protocol's limit) fit, so what does not fit is counted on that line.
A widget's id is stable and names what a touch means; only Details takes one.
Nothing on the page that a finger can be on changes by itself.
"""

from datetime import timedelta

from screenpad_app import clip
from screenpad_app.common import MAX_BADGE, MAX_LABEL, MAX_ROWS, MAX_TILE_TEXT

from .callpage import fit
from .common import GAUGE_ICON, LIMITS_PAGE, PROVIDER_ICONS, icon
from .usage import CRITICAL, LOW

COLUMNS = 6
BAR = 22  # characters of a bar
FULL, EMPTY = "█", "░"
DETAILS, NOTE = "limits.details", "limits.note"
# Characters of a two-column cell's second line, from the Projects page's boxes.
WIDE_TEXT = 66
TOP = {"claude": "Claude", "codex": "Codex"}


def title(name):
    return TOP.get(name) or name.replace("-", " ").capitalize()


def tone(percent):
    return "reject" if percent <= CRITICAL else "warning" if percent <= LOW else "accept"


def bar(percent):
    """percent left as a line of BAR block characters."""
    filled = round(BAR * max(0.0, min(100.0, percent)) / 100)
    return FULL * filled + EMPTY * (BAR - filled)


def reset_in(moment, now, tz=None):
    """When a window resets, for "resets <this>": "in 45 min" or "in 3h20"
    within a day, else the weekday and date ("Fri 28 Nov") in tz (the local
    zone when None); "now" once it is past."""
    delta = moment - now
    if delta <= timedelta(0):
        return "now"
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return "in %d min" % max(1, minutes)
    if delta < timedelta(days=1):
        return "in %dh%02d" % divmod(minutes, 60)
    local = moment.astimezone(tz)
    return "%s %d %s" % (local.strftime("%a"), local.day, local.strftime("%b"))


def _cell(id, col, row, cols=1, rows=1, **look):
    cell = {"id": id, "col": col, "row": row}
    if cols > 1:
        cell["cols"] = cols
    if rows > 1:
        cell["rows"] = rows
    return dict(cell, **look)


def layout(providers):
    """[(provider, the windows shown)], the rows they take and how many
    providers or windows did not fit: the last row is for Details."""
    room, shown, hidden = MAX_ROWS - 1, [], 0
    for p in providers:
        want = p.windows or [None]
        if room <= 0:
            hidden += len(want)
            continue
        take = want[:room]
        hidden += len(want) - len(take)
        shown.append((p, take))
        room -= len(take)
    return shown, MAX_ROWS - 1 - room, hidden


def widgets(providers, error, now, tz=None):
    """(the widgets, the rows) of the page for providers (the last read
    ones), error being why the last read failed."""
    if providers is None:
        words = ("quota-axi unavailable", error) if error else ("Reading quota…", None)
        look = {"label": words[0], "touch": "none"}
        return [_cell(NOTE, 0, 0, COLUMNS, 2, **look, **({"text": fit(words[1], 100)} if words[1] else {}))], 2
    if not providers:
        return [_cell(NOTE, 0, 0, COLUMNS, 2, label="No provider set up", touch="none")], 2
    shown, used, hidden = layout(providers)
    rows = used + 1
    out, row = [], 0
    for p, windows in shown:
        span = len(windows)
        logo = {"icon": icon(PROVIDER_ICONS.get(p.name, GAUGE_ICON)), "touch": "none"}
        if span > 1 or rows < MAX_ROWS:
            logo["label"] = clip(title(p.name), MAX_LABEL)
        out.append(_cell("limits.logo.%s" % p.name[:16], 0, row, 1, span, **logo))
        for i, w in enumerate(windows):
            out += _window(p, w, row + i, now, tz) if w is not None else _no_data(p, row)
        row += span
    out += _foot(rows - 1, error, hidden)
    return out, max(2, rows)


def _window(p, w, row, now, tz):
    key = "%s.%s" % (p.name[:12], row)
    when = "resets %s" % reset_in(w.resets, now, tz) if w.resets else "no reset given"
    if w.pace == "ahead":
        when += " · using fast"
    look = tone(w.percent)
    return [
        _cell("limits.name." + key, 1, row, 2, label=clip(w.name, MAX_LABEL), text=fit(when, WIDE_TEXT), touch="none"),
        _cell("limits.bar." + key, 3, row, 2, lines=[bar(w.percent)], tone=look, touch="none"),
        _cell("limits.left." + key, 5, row, 1, label="%d%%" % round(w.percent), text="left", tone=look, touch="none"),
    ]


def _no_data(p, row):
    """A provider that could not be read: its reason, and no number."""
    look = {"label": "No data", "text": fit(p.reason or "unknown", WIDE_TEXT), "tone": "warning", "touch": "none"}
    return [_cell("limits.nodata.%s" % p.name[:16], 1, row, 5, **look)]


def _foot(row, error, hidden):
    said = "last read failed: %s" % error if error else "percent left in each window, read every minute"
    if hidden:
        said += " · +%d more not shown" % hidden
    return [
        _cell(
            NOTE,
            0,
            row,
            4,
            label="Usage limits",
            text=fit(said, 2 * WIDE_TEXT),
            tone="warning" if error else "neutral",
            touch="none",
        ),
        _cell(DETAILS, 4, row, 2, label="Details", text="the full report in a terminal"),
    ]


def page(usage, tz=None):
    """The Limits page's message for a Usage (usage.py)."""
    cells, rows = widgets(usage.providers, usage.error, usage.now().astimezone(), tz)
    msg = {"op": "page", "page": LIMITS_PAGE, "title": "Limits", "icon": icon(GAUGE_ICON), "tone": usage.tone()}
    msg.update({"columns": COLUMNS, "rows": rows, "widgets": cells})
    msg["text"] = clip(usage.summary(), MAX_TILE_TEXT)
    left = usage.left()
    if left is not None:
        msg["badge"] = clip("%d%%" % round(left), MAX_BADGE)
    return msg
