"""The usage limits: each agent provider's quota left, from quota-axi.

`quota-axi --json` prints one document (schemaVersion 5): `providers[]`, each
with its `windows[]` (a `label`, `percentRemaining`, `resetsAt`, `pace.status`)
or, when it could not be read, a `state` with the `error` or `status`. Pure:
parse turns that into one Provider each, with a Window for every window it
read ("5-hour session", "Weekly"), and "no data" with the reason for one it
could not (never a made-up number). `[usage] providers` names the providers
that count: the others are left out here, so no page or badge shows them.
Usage turns the providers into the tile, a gauge with the tightest percent
left as its badge and its tone; on the bar a tile with an icon shows only
those, so with nothing read it shows its words instead, and the home page's
list has the words either way. usagepage.py draws the Limits page from the
same providers; usagewatch.py runs quota-axi, at most once a minute, off the
loop.
"""

import json
import re
from datetime import datetime, timedelta

from screenpad_app import clip
from screenpad_app.common import MAX_BADGE, MAX_TILE_LABEL, MAX_TILE_TEXT

from .common import GAUGE_ICON, USAGE_TILE, icon

# A tile's tone follows the tightest provider: under LOW percent left it is
# amber, under CRITICAL red.
LOW, CRITICAL = 25, 10
HOURS = re.compile(r"(\d+)h")
# What quota-axi calls its windows, in the words the page uses: the order a
# provider's windows are shown in (the session first), then the name.
SESSION, WEEKLY = "5-hour session", "Weekly"


class UsageError(Exception):
    pass


class Window:
    """One quota window: its plain name, percent left, when it resets (a
    datetime, or None), and quota-axi's reading of the pace (or None)."""

    __slots__ = ("name", "order", "pace", "percent", "resets")

    def __init__(self, name, percent, resets=None, pace=None, order=2):
        self.name, self.percent, self.resets, self.pace, self.order = name, percent, resets, pace, order

    def _key(self):
        return tuple(getattr(self, s) for s in self.__slots__)

    def __eq__(self, other):
        return isinstance(other, Window) and self._key() == other._key()

    def __hash__(self):
        return hash((self.name, self.percent))

    def __repr__(self):
        return "Window(%r, %r)" % (self.name, self.percent)


class Provider:
    """A provider and its quota: its windows (none: no data, then reason says
    why). percent and resets are those of its tightest window."""

    __slots__ = ("name", "reason", "windows")

    def __init__(self, name, windows=(), reason=None):
        self.name, self.windows, self.reason = name, list(windows), reason

    @property
    def tightest(self):
        return min(self.windows, key=lambda w: w.percent, default=None)

    @property
    def percent(self):
        return self.tightest.percent if self.windows else None

    @property
    def resets(self):
        return self.tightest.resets if self.windows else None

    def __eq__(self, other):
        return isinstance(other, Provider) and (self.name, self.windows, self.reason) == (
            other.name,
            other.windows,
            other.reason,
        )

    def __hash__(self):
        return hash((self.name, self.percent))

    def __repr__(self):
        return "Provider(%r, %r)" % (self.name, self.percent)


def plain(reason):
    """A reason in words: quota-axi's `credentials_invalid` as `credentials invalid`."""
    return str(reason).replace("_", " ").strip() or "unknown"


def window_name(raw):
    """(plain name, order) of a window quota-axi gave: the session and the
    week first, the others by their length or its own label."""
    ident, kind, label = (str(raw.get(k) or "") for k in ("id", "kind", "label"))
    if ident == "five_hour":
        return SESSION, 0
    if kind == "session":
        return "Session", 0
    if ident in ("seven_day", "weekly") or kind == "weekly":
        return WEEKLY, 1
    if kind == "monthly" or ident == "monthly":
        return "Monthly", 2
    if ident == "seven_day_opus":
        return "Weekly (Opus)", 2
    hours = raw.get("windowSeconds")
    hours = hours / 3600 if isinstance(hours, int | float) and hours > 0 else None
    found = HOURS.search(ident) or HOURS.search(label)
    hours = hours or (int(found[1]) if found else None)
    if hours:
        return ("%d-day window" % round(hours / 24) if hours >= 48 else "%d-hour window" % round(hours)), 2
    return (label or ident or "Window").capitalize(), 2


def _number(value):
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def parse(text, only=None):
    """The providers quota-axi's JSON names, those it read first (in its
    order), then those it could not. only (a list of names) keeps just
    those, in that order, a listed one quota-axi does not name having
    "no data". UsageError when the text holds no providers."""
    try:
        listed = json.loads(text).get("providers")
    except (ValueError, AttributeError):
        listed = None
    if not isinstance(listed, list):
        raise UsageError("quota-axi printed no quota")
    found = {}
    for raw in listed:
        name = raw.get("provider") if isinstance(raw, dict) else None
        if not isinstance(name, str) or not name or name in found:
            continue
        if raw.get("notSetUp") and only is None:
            continue  # a provider nobody set up
        found[name] = _provider(name, raw)
    if only is not None:
        return [found.get(n) or Provider(n, reason="not reported by quota-axi") for n in dict.fromkeys(only)]
    values = list(found.values())
    return [p for p in values if p.windows] + [p for p in values if not p.windows]


def _provider(name, raw):
    windows = []
    for w in raw.get("windows") or []:
        percent = _number(w.get("percentRemaining")) if isinstance(w, dict) else None
        if percent is None:
            continue
        label, order = window_name(w)
        pace = w.get("pace") if isinstance(w.get("pace"), dict) else {}
        windows.append(
            Window(label, max(0.0, min(100.0, percent)), _time(w.get("resetsAt")), pace.get("status"), order)
        )
    windows.sort(key=lambda w: w.order)
    state = raw.get("state") if isinstance(raw.get("state"), dict) else {}
    return Provider(name, windows, None if windows else plain(state.get("error") or state.get("status") or "no data"))


def _time(text):
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone() if text else None
    except (ValueError, AttributeError):
        return None


def when(moment, now, tz=None):
    """A reset time in a few characters, in tz (the local zone when None):
    the clock time when it is within a day, else the day and month."""
    moment = moment.astimezone(tz)
    if timedelta(0) <= moment - now.astimezone(tz) < timedelta(days=1):
        return moment.strftime("%H:%M")
    return "%d %s" % (moment.day, moment.strftime("%b"))


def words(providers, now, tz=None):
    """The tile's two lines for providers: (label, text). The label holds
    each provider that was read with its percent left and, when it fits
    MAX_TILE_LABEL, the reset ("codex 87% ↻26 Dec"); the text the providers
    with no data and why ("claude no data: credentials_invalid" for one,
    "no data: claude, copilot" for several), then, when the label had no
    room for them, the resets, as far as MAX_TILE_TEXT allows."""
    read = [p for p in providers if p.percent is not None]
    missing = [p for p in providers if p.percent is None]
    plain = " · ".join("%s %d%%" % (p.name, round(p.percent)) for p in read)
    dated = " · ".join(
        "%s %d%%%s" % (p.name, round(p.percent), " ↻" + when(p.resets, now, tz) if p.resets else "") for p in read
    )
    label = dated if len(dated) <= MAX_TILE_LABEL else plain
    text = ""
    if len(missing) == 1:
        text = "%s no data" % missing[0].name + (": " + missing[0].reason if missing[0].reason else "")
    elif missing:
        text = "no data: " + ", ".join(p.name for p in missing)
    resets = "↻ " + " · ".join("%s %s" % (p.name, when(p.resets, now, tz)) for p in read if p.resets)
    if label == plain and resets != "↻ ":
        text = (text + " · " if text else "") + resets if len(text) + len(resets) + 3 <= MAX_TILE_TEXT else text
    return clip(label or "Limits", MAX_TILE_LABEL), clip(text, MAX_TILE_TEXT)


class Usage:
    """What the tile last knew: the providers (None before the first
    read), or why the last read failed."""

    def __init__(self, now=datetime.now):
        self.providers, self.error, self.now = None, None, now

    def set(self, providers, error=None):
        """Take a read in; True if the tile changed. A failed read keeps
        the providers last read and says it failed."""
        before = (self.providers, self.error)
        if error:
            self.error = error
        else:
            self.providers, self.error = providers, None
        return before != (self.providers, self.error)

    def left(self):
        """The tightest percent left of any provider read, None when none was."""
        left = [p.percent for p in self.providers or [] if p.percent is not None]
        return min(left) if left else None

    def tone(self):
        left = self.left()
        if left is None or self.error:
            return "neutral"
        return "reject" if left <= CRITICAL else "warning" if left <= LOW else "accept"

    def summary(self):
        """The tile's words on the home page's list: the providers' percents
        left, or why there are none."""
        if self.providers is None:
            return "quota-axi unavailable" if self.error else "reading quota…"
        if not self.providers:
            return "no provider set up"
        label, text = words(self.providers, self.now().astimezone())
        return label if self.left() is not None else text

    def tile(self):
        msg = {"op": "set", "tile": USAGE_TILE, "label": "Limits", "tone": self.tone()}
        left = self.left()
        if left is not None:
            msg["icon"], msg["badge"] = icon(GAUGE_ICON), clip("%d%%" % round(left), MAX_BADGE)
        if self.providers is None:
            msg["text"] = "quota-axi unavailable" if self.error else "reading quota…"
        elif not self.providers:
            msg["text"] = "no provider set up"
        else:
            label, text = words(self.providers, self.now().astimezone())
            msg["label"] = label
            msg["text"] = clip((text + " (old)" if self.error else text) or "quota left", MAX_TILE_TEXT)
        return msg
