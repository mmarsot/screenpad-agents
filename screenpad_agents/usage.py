"""The usage-limits tile: each agent provider's quota left, from quota-axi.

`quota-axi` prints, in TOON, a table `quota[N]{provider,scope,
effectivePercentRemaining,...,resetsAt}:` of the windows it could read and
a table `attention[N]{provider,scope,kind,detail,remedy}:` of the providers
it could not (a credential refused, a sign-in needed, an error). Pure: parse
turns that text into one Provider each, the tightest window of one that
could be read, "no data" with the reason for one that could not (never a
made-up number), and Usage turns them into the tile. The tile has no icon:
on the bar a tile with an icon shows only it, and the words are the point.
usagewatch.py runs quota-axi, at most once a minute, off the loop.
"""

import csv
import re
from datetime import datetime, timedelta

from screenpad_app import clip
from screenpad_app.common import MAX_TILE_LABEL, MAX_TILE_TEXT

from .common import USAGE_TILE

HEADER = re.compile(r"(?P<name>[A-Za-z_][\w-]*)\[(?P<n>\d+)\]\{(?P<columns>[^}]*)\}:")
# A tile's tone follows the tightest provider: under LOW percent left it is
# amber, under CRITICAL red.
LOW, CRITICAL = 25, 10


class UsageError(Exception):
    pass


class Provider:
    """A provider and its quota: percent left (None: no data) with when the
    window resets (a datetime, or None), or why there is no data."""

    __slots__ = ("name", "percent", "reason", "resets")

    def __init__(self, name, percent=None, resets=None, reason=None):
        self.name, self.percent, self.resets, self.reason = name, percent, resets, reason

    def __eq__(self, other):
        return isinstance(other, Provider) and tuple(getattr(self, s) for s in self.__slots__) == tuple(
            getattr(other, s) for s in self.__slots__
        )

    def __hash__(self):
        return hash((self.name, self.percent))

    def __repr__(self):
        return "Provider(%r, %r)" % (self.name, self.percent)


def tables(text):
    """The tables of a TOON document: {name: [{column: value}]}. Only the
    tabular form quota-axi prints is read; any other line is skipped."""
    out = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        head = HEADER.fullmatch(lines[i]) if lines[i] and not lines[i][0].isspace() else None
        i += 1
        if head is None:
            continue
        columns = [c.strip() for c in head["columns"].split(",")]
        rows: list[dict] = []
        while i < len(lines) and lines[i][:1].isspace() and len(rows) < int(head["n"]):
            values = next(csv.reader([lines[i].strip()]), [])
            rows.append(dict(zip(columns, values, strict=False)))
            i += 1
        out[head["name"]] = rows
    return out


def parse(text):
    """The providers quota-axi's text names: those it read, the tightest
    first, then those it could not. UsageError when there is no table."""
    found = tables(text)
    if "quota" not in found and "attention" not in found:
        raise UsageError("quota-axi printed no quota")
    best: dict = {}
    for row in found.get("quota", []):
        name = row.get("provider")
        if not name:
            continue
        try:
            percent = float(row.get("effectivePercentRemaining", ""))
        except ValueError:
            best.setdefault(name, None)
            continue
        if best.get(name) is None or percent < best[name][0]:
            best[name] = (percent, _time(row.get("resetsAt")))
    read = sorted(
        (Provider(n, v[0], v[1]) for n, v in best.items() if v is not None), key=lambda p: (p.percent, p.name)
    )
    missing: list[Provider] = []
    for row in found.get("attention", []):
        name = row.get("provider")
        if name and best.get(name) is None and name not in {p.name for p in missing}:
            missing.append(Provider(name, reason=row.get("detail") or row.get("kind") or "unknown"))
    for name, v in best.items():
        if v is None and name not in {p.name for p in missing}:
            missing.append(Provider(name, reason="no percent given"))
    return read + missing


def _time(text):
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None
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

    def tone(self):
        left = [p.percent for p in self.providers or [] if p.percent is not None]
        if not left or self.error:
            return "neutral"
        return "reject" if min(left) <= CRITICAL else "warning" if min(left) <= LOW else "accept"

    def tile(self):
        msg = {"op": "set", "tile": USAGE_TILE, "label": "Limits", "tone": self.tone()}
        if self.providers is None:
            msg["text"] = "quota-axi unavailable" if self.error else "reading quota…"
        elif not self.providers:
            msg["text"] = "no provider set up"
        else:
            label, text = words(self.providers, self.now().astimezone())
            msg["label"] = label
            msg["text"] = clip((text + " (old)" if self.error else text) or "quota left", MAX_TILE_TEXT)
        return msg
