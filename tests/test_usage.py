"""The usage limits: quota-axi's JSON read into providers (usage.py), the
providers that count (`[usage] providers`), the tile's words, the Limits
page (usagepage.py) checked against the app protocol by the stand-in touch
bar, quota-axi run at most once a minute and only while the touch bar is
connected, never a made-up number for a provider it could not read, and
Details opening the viewer in a terminal (usagewatch.py)."""

import json
import os
import shlex
import subprocess
import tempfile
import threading
import time
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest import mock

from agents_support import FakeFirstmate, FakeHerdr, Rig, config
from bar_support import Apps, FakeClient
from runs_support import FakeNoMistakes

from screenpad_agents import usage, usagepage
from screenpad_agents.config import TERMINAL
from screenpad_agents.config import Runs as RunsSettings
from screenpad_agents.config import Usage as UsageSettings
from screenpad_agents.usagewatch import KEY, VIEWER, UsageWatch


def quota(*providers):
    """What `quota-axi --json` prints (schemaVersion 5) for providers."""
    return json.dumps({"generatedAt": "2026-11-26T10:30:00.000Z", "schemaVersion": 5, "providers": list(providers)})


def window(ident, label, percent, resets, kind="unknown", pace="on_pace", **more):
    return dict(
        {"id": ident, "label": label, "kind": kind, "resetsAt": resets, "percentRemaining": percent},
        pace={"status": pace},
        **more,
    )


# Claude Code here authenticates with a token quota-axi cannot use: no windows, the reason.
CLAUDE_DOWN = {
    "provider": "claude",
    "windows": [],
    "state": {"status": "auth_required", "stale": False, "error": "credentials_invalid"},
}
# What it reads once Claude can be read: the five-hour session and the week.
CLAUDE_UP = {
    "provider": "claude",
    "windows": [
        window("seven_day", "week", 18, "2026-12-01T00:00:00.000Z", "weekly", "ahead"),
        window("five_hour", "session", 42.4, "2026-11-26T14:30:00.000Z", "session", windowSeconds=18000),
    ],
    "state": {"status": "fresh", "stale": False},
}
# A free plan has one 30-day window: not a subscription.
CODEX = {
    "provider": "codex",
    "plan": "free",
    "windows": [window("window:720h", "720h window", 100, "2026-12-26T11:19:12.000Z")],
    "state": {"status": "fresh", "stale": False},
}
CURSOR = {
    "provider": "cursor",
    "windows": [],
    "state": {"status": "auth_required", "error": "Cursor sign-in required"},
    "notSetUp": True,
}
COPILOT = {
    "provider": "copilot",
    "windows": [],
    "state": {"status": "auth_required", "error": "GitHub Copilot sign-in required"},
}
API = "/repos/api"
TODAY = quota(CLAUDE_DOWN, CODEX, CURSOR, COPILOT)
NOW = datetime(2026, 11, 26, 10, 30, tzinfo=UTC)
UTC = UTC


class ParseTests(unittest.TestCase):
    def test_every_provider_quota_axi_can_read_and_those_it_could_not_with_why(self):
        codex, claude, copilot = usage.parse(TODAY)  # the unreadable ones last; one nobody set up is left out
        self.assertEqual((codex.name, codex.percent), ("codex", 100.0))
        self.assertEqual(codex.resets, datetime(2026, 12, 26, 11, 19, 12, tzinfo=UTC))
        self.assertEqual([w.name for w in codex.windows], ["30-day window"])
        self.assertEqual(
            [(p.name, p.percent, p.windows, p.reason) for p in (claude, copilot)],
            [
                ("claude", None, [], "credentials invalid"),
                ("copilot", None, [], "GitHub Copilot sign-in required"),
            ],
        )

    def test_a_reset_time_with_no_offset_is_read_in_the_local_zone(self):
        # ISO 8601 without an offset is local time; it must compare with the aware clock.
        local = dict(CLAUDE_UP, windows=[window("five_hour", "session", 42.4, "2026-11-26T14:30:00", "session")])
        (claude,) = usage.parse(quota(local))
        self.assertIsNotNone(claude.resets.tzinfo)
        self.assertEqual(claude.resets, datetime(2026, 11, 26, 14, 30).astimezone())
        now = datetime(2026, 11, 26, 12, 0).astimezone()
        self.assertEqual(usagepage.reset_in(claude.resets, now), "in 2h30")

    def test_only_the_listed_providers_count_in_the_order_listed(self):
        self.assertEqual([p.name for p in usage.parse(TODAY, ["claude"])], ["claude"])
        self.assertEqual([p.name for p in usage.parse(TODAY, ["codex", "claude"])], ["codex", "claude"])
        # A listed provider quota-axi does not name has no data; one it says nobody set up counts when listed.
        missing, cursor = usage.parse(TODAY, ["kimi", "cursor"])
        self.assertEqual((missing.name, missing.percent, missing.reason), ("kimi", None, "not reported by quota-axi"))
        self.assertEqual((cursor.name, cursor.reason), ("cursor", "Cursor sign-in required"))
        # A hidden provider never gives the tightest percent.
        both = usage.parse(quota(CLAUDE_UP, CODEX))
        shown = usage.Usage(now=lambda: NOW)
        shown.set(usage.parse(quota(CLAUDE_UP, CODEX), ["claude"]))
        self.assertEqual((shown.left(), min(p.percent for p in both)), (18.0, 18.0))
        shown.set(usage.parse(quota(CLAUDE_DOWN, CODEX), ["claude"]))
        self.assertIsNone(shown.left())  # a hidden codex at 100% is no number

    def test_a_provider_s_windows_are_named_plainly_session_first_and_the_tightest_counts(self):
        (claude,) = usage.parse(quota(CLAUDE_UP))
        self.assertEqual(
            [(w.name, w.percent, w.pace) for w in claude.windows],
            [("5-hour session", 42.4, "on_pace"), ("Weekly", 18.0, "ahead")],
        )
        self.assertEqual((claude.percent, claude.resets), (18.0, datetime(2026, 12, 1, tzinfo=UTC)))  # the week
        names = {
            ("five_hour", "session", "x"): "5-hour session",
            ("seven_day", "week", "weekly"): "Weekly",
            ("seven_day_opus", "opus week", "model"): "Weekly (Opus)",
            ("window:5h", "5h window", "unknown"): "5-hour window",
            ("window:720h", "720h window", "unknown"): "30-day window",
            ("month_total", "month", "monthly"): "Monthly",
            ("other", "things", "unknown"): "Things",
        }
        for (ident, label, kind), name in names.items():
            self.assertEqual(usage.window_name({"id": ident, "label": label, "kind": kind})[0], name)

    def test_a_window_with_no_percent_is_not_a_number_and_a_percent_is_kept_in_range(self):
        odd = {
            "provider": "x",
            "windows": [{"id": "a", "percentRemaining": "n/a"}, {"id": "b", "percentRemaining": 140}, {"id": "c"}],
        }
        (x,) = usage.parse(quota(odd))
        self.assertEqual([w.percent for w in x.windows], [100.0])
        (y,) = usage.parse(quota({"provider": "y", "windows": [{"id": "a"}]}))
        self.assertEqual((y.percent, y.reason), (None, "no data"))

    def test_text_that_holds_no_providers_is_an_error(self):
        for text in ("", "quota-axi: boom\n", "[]", "{}", '{"providers": 3}', "bin: quota-axi\nquota[0]{provider}:\n"):
            with self.assertRaises(usage.UsageError):
                usage.parse(text)
        self.assertEqual(usage.parse(quota()), [])


class TileTests(unittest.TestCase):
    def tile(self, text=TODAY, error=None, only=None):
        u = usage.Usage(now=lambda: NOW)
        if text is not None:
            u.set(usage.parse(text, only))
        if error:
            u.set(None, error)
        return u.tile()

    def test_the_percent_and_reset_of_a_provider_and_those_with_no_data(self):
        tile = self.tile()
        self.assertEqual(tile["tile"], "usage")
        self.assertRegex(tile["label"], r"\Acodex 100% ↻26 Dec\Z")
        self.assertEqual(tile["text"], "no data: claude, copilot")
        # On the bar a tile with an icon shows only it, its badge and its tone: the gauge
        # with the tightest percent left; the words are for the home page's list.
        self.assertEqual((tile["icon"].rsplit("/", 1)[-1], tile["badge"]), ("gauge.svg", "100%"))
        self.assertLessEqual(len(tile["text"]), 48)

    def test_a_hidden_provider_is_in_no_word_or_badge(self):
        tile = self.tile(only=["claude"])
        self.assertEqual((tile["label"], tile["text"]), ("Limits", "claude no data: credentials invalid"))
        self.assertNotIn("%", tile["label"] + tile["text"])
        self.assertNotIn("icon", tile)  # nothing read: its words show on the bar, no gauge, no badge
        self.assertNotIn("badge", tile)
        self.assertEqual(tile["tone"], "neutral")
        self.assertNotIn("codex", str(tile))

    def test_a_reset_within_a_day_is_a_clock_time_and_both_windows_count(self):
        providers = usage.parse(quota(CLAUDE_UP, CODEX))
        label, text = usage.words(providers, NOW, UTC)
        self.assertEqual((label, text), ("claude 18% · codex 100%", "↻ claude 1 Dec · codex 26 Dec"))
        self.assertEqual(usage.when(datetime(2026, 11, 26, 14, 30, tzinfo=UTC), NOW, UTC), "14:30")
        self.assertEqual(usage.when(datetime(2026, 11, 27, 10, 30, tzinfo=UTC), NOW, UTC), "27 Nov")
        self.assertEqual(usage.when(datetime(2026, 11, 26, 9, 0, tzinfo=UTC), NOW, UTC), "26 Nov")  # past

    def test_the_tone_follows_the_tightest_provider_and_never_a_fake_number(self):
        for percent, tone in ((90, "accept"), (25, "warning"), (10, "reject")):
            codex = dict(CODEX, windows=[window("window:720h", "w", percent, "2026-12-26T10:15:33.000Z")])
            self.assertEqual(self.tile(quota(codex))["tone"], tone)

    def test_before_the_first_read_and_when_quota_axi_fails(self):
        self.assertEqual(usage.Usage().tile()["text"], "reading quota…")
        failed = usage.Usage()
        failed.set(None, "quota-axi: No such file or directory")
        self.assertEqual(failed.tile()["text"], "quota-axi unavailable")
        self.assertNotIn("icon", failed.tile())
        # A failure after a read keeps what was read, marked old.
        tile = self.tile(error="quota-axi gave no answer in 60 s")
        self.assertEqual(tile["label"].split(" ")[0], "codex")
        self.assertTrue(tile["text"].endswith(" (old)"))
        self.assertEqual(tile["badge"], "100%")  # what was read stays
        self.assertLessEqual(len(tile["text"]), 48)

    def test_set_says_whether_the_tile_changed(self):
        u = usage.Usage()
        self.assertTrue(u.set(usage.parse(TODAY)))
        self.assertFalse(u.set(usage.parse(TODAY)))
        self.assertTrue(u.set(None, "boom"))
        self.assertFalse(u.set(None, "boom"))
        self.assertTrue(u.set(usage.parse(TODAY)))


def accepted(providers, error=None):
    """The Limits page for providers (read at NOW), as the stand-in touch bar takes it."""
    u = usage.Usage(now=lambda: NOW)
    if providers is not None:
        u.set(providers)
    if error:
        u.set(None, error)
    msg = usagepage.page(u, UTC)
    apps, client = Apps(), FakeClient()
    apps.connect(client)
    apps.handle(client, {"op": "hello", "app": "agents", "tiles": [], "protocol": 2})
    apps.handle(client, msg)
    errors = [m for m in client.sent if m["op"] == "error"]
    if errors:
        raise AssertionError(errors)
    return msg, {w.id: w for w in apps.pages["limits"].widgets}


def lines_of(widget):
    return widget.look["lines"] if "lines" in widget.look else []


class PageTests(unittest.TestCase):
    def test_a_row_per_window_with_the_logo_the_bar_the_percent_and_the_reset(self):
        msg, w = accepted(usage.parse(quota(CLAUDE_UP, CODEX), ["claude"]))
        self.assertEqual((msg["page"], msg["title"], msg["columns"], msg["rows"]), ("limits", "Limits", 6, 3))
        self.assertEqual((msg["tone"], msg["badge"], msg["text"]), ("warning", "18%", "claude 18% ↻1 Dec"))
        # The logo is across the provider's rows, with its name; nothing of codex is there.
        logo = w["limits.logo.claude"]
        self.assertEqual((logo.col, logo.row, logo.cols, logo.rows, logo.touch), (0, 0, 1, 2, "none"))
        self.assertEqual((logo.look["icon"].rsplit("/", 1)[-1], logo.look["label"]), ("claude.svg", "Claude"))
        self.assertFalse([i for i in w if "codex" in i])
        # The session is first, the week under it: name and reset, bar, percent.
        session, week = (w["limits.%s.claude.%d" % (kind, row)] for kind, row in (("name", 0), ("name", 1)))
        self.assertEqual((session.look["label"], session.look["text"]), ("5-hour session", "resets in 4h00"))
        self.assertEqual((week.look["label"], week.look["text"]), ("Weekly", "resets Tue 1 Dec · using fast"))
        bar0, left0 = w["limits.bar.claude.0"], w["limits.left.claude.0"]
        self.assertEqual((bar0.col, bar0.cols, left0.col), (3, 2, 5))
        self.assertEqual(lines_of(bar0), [usagepage.FULL * 9 + usagepage.EMPTY * 13])  # 42 percent of 22
        self.assertEqual((left0.look["label"], left0.look["text"], left0.look["tone"]), ("42%", "left", "accept"))
        self.assertEqual(
            (w["limits.left.claude.1"].look["label"], w["limits.bar.claude.1"].look["tone"]), ("18%", "warning")
        )
        # Only Details takes a touch.
        taps = {i for i, x in w.items() if x.touch != "none"}
        self.assertEqual(taps, {"limits.details"})
        self.assertEqual((w["limits.details"].look["label"], w["limits.details"].row), ("Details", 2))

    def test_a_provider_that_cannot_be_read_has_its_logo_and_no_data_never_a_number(self):
        msg, w = accepted(usage.parse(quota(CLAUDE_DOWN, CODEX), ["claude"]))
        self.assertEqual(
            (msg["tone"], msg["text"], "badge" in msg), ("neutral", "claude no data: credentials invalid", False)
        )
        self.assertEqual(msg["rows"], 2)
        nodata = w["limits.nodata.claude"]
        self.assertEqual(
            (nodata.look["label"], nodata.look["text"], nodata.cols), ("No data", "credentials invalid", 5)
        )
        self.assertEqual(w["limits.logo.claude"].look["icon"].rsplit("/", 1)[-1], "claude.svg")
        shown = " ".join(str(x.look) for x in w.values())
        self.assertNotIn("%", shown)
        self.assertNotIn("limits.bar.claude.0", w)

    def test_two_providers_each_with_their_logo_and_what_does_not_fit_is_counted(self):
        msg, w = accepted(usage.parse(quota(CLAUDE_UP, CODEX)))
        self.assertEqual(msg["rows"], 4)  # three windows and the Details row
        self.assertEqual(w["limits.logo.codex"].look["icon"].rsplit("/", 1)[-1], "openai.svg")
        self.assertEqual(
            (
                w["limits.name.codex.2"].look["label"],
                w["limits.name.codex.2"].look["text"],
                w["limits.left.codex.2"].look["label"],
            ),
            ("30-day window", "resets Sat 26 Dec", "100%"),
        )
        self.assertNotIn("label", w["limits.logo.codex"].look)  # a cell too short for icon and label
        many = [usage.Provider("p%d" % n, [usage.Window("Weekly", 50.0, NOW)]) for n in range(5)]
        msg, w = accepted(many)
        self.assertEqual(msg["rows"], 4)
        self.assertIn("+2 more not shown", w["limits.note"].look["text"])
        self.assertIn("limits.left.p2.2", w)
        self.assertNotIn("limits.left.p3.3", w)

    def test_a_provider_with_a_generic_logo_and_a_window_that_resets_now_or_never(self):
        windows = [usage.Window("Session", 5.0, NOW - timedelta(minutes=1)), usage.Window("Weekly", 60.0)]
        _msg, w = accepted([usage.Provider("kimi", windows)])
        self.assertEqual(w["limits.logo.kimi"].look["icon"].rsplit("/", 1)[-1], "gauge.svg")
        self.assertEqual(w["limits.logo.kimi"].look["label"], "Kimi")
        self.assertEqual(w["limits.name.kimi.0"].look["text"], "resets now")
        self.assertEqual(w["limits.bar.kimi.0"].look["tone"], "reject")
        self.assertEqual(w["limits.name.kimi.1"].look["text"], "no reset given")

    def test_reset_in_is_relative_within_a_day_and_a_weekday_and_date_after(self):
        for minutes, words in (
            (0, "now"),
            (-5, "now"),
            (1, "in 1 min"),
            (45, "in 45 min"),
            (60, "in 1h00"),
            (200, "in 3h20"),
            (1439, "in 23h59"),
        ):
            self.assertEqual(usagepage.reset_in(NOW + timedelta(minutes=minutes), NOW, UTC), words)
        self.assertEqual(usagepage.reset_in(NOW + timedelta(days=1), NOW, UTC), "Fri 27 Nov")
        self.assertEqual(usagepage.reset_in(datetime(2026, 12, 1, 0, 0, tzinfo=UTC), NOW, UTC), "Tue 1 Dec")

    def test_the_bar_fills_with_the_percent_left(self):
        self.assertEqual([usagepage.bar(p).count(usagepage.FULL) for p in (0, 50, 100, 120, -5)], [0, 11, 22, 22, 0])
        self.assertEqual({len(usagepage.bar(p)) for p in (0, 33, 100)}, {usagepage.BAR})

    def test_before_the_first_read_failing_with_nothing_read_and_failing_after_a_read(self):
        msg, w = accepted(None)
        self.assertEqual(w["limits.note"].look["label"], "Reading quota…")
        self.assertEqual("badge" in msg, False)
        msg, w = accepted(None, "quota-axi: No such file or directory")
        self.assertEqual(
            (w["limits.note"].look["label"], w["limits.note"].look["text"]),
            ("quota-axi unavailable", "quota-axi: No such file or directory"),
        )
        msg, w = accepted([])
        self.assertEqual(w["limits.note"].look["label"], "No provider set up")
        # A failure after a read keeps what was read and says it failed.
        msg, w = accepted(usage.parse(quota(CLAUDE_UP)), "quota-axi gave no answer in 60 s")
        self.assertIn("last read failed: quota-axi gave no answer in 60 s", w["limits.note"].look["text"])
        self.assertEqual(w["limits.left.claude.0"].look["label"], "42%")


def done(stdout="", code=0, stderr=""):
    return SimpleNamespace(stdout=stdout, returncode=code, stderr=stderr)


class WatchTests(unittest.TestCase):
    def watch(self, run, settings=None, launcher=None):
        self.posts = []
        watch = UsageWatch(
            settings or UsageSettings(), lambda *item: self.posts.append(item), run=run, launcher=launcher
        )
        return watch

    def test_quota_axi_is_run_with_no_fm_variables_and_its_text_parsed(self):
        calls = []

        def run(argv, **kw):
            calls.append((argv, kw))
            return done(TODAY)

        with mock.patch.dict("os.environ", {"FM_HOME": "/x", "KEEP": "1"}):
            providers = self.watch(run).read()
        self.assertEqual([p.name for p in providers], ["codex", "claude", "copilot"])
        argv, kw = calls[0]
        self.assertEqual(argv, ["quota-axi", "--json"])
        self.assertNotIn("FM_HOME", kw["env"])
        self.assertEqual(kw["env"]["KEEP"], "1")
        self.assertEqual(kw["stdin"], subprocess.DEVNULL)
        self.assertEqual(kw["timeout"], 60.0)

    def test_only_the_configured_providers_are_read_in(self):
        watch = self.watch(lambda argv, **kw: done(TODAY), UsageSettings(providers=["claude"]))
        self.assertEqual([p.name for p in watch.read()], ["claude"])

    def test_failures_say_why(self):
        def broken(error):
            def run(argv, **kw):
                raise error

            return run

        cases = [
            (broken(FileNotFoundError(2, "No such file or directory")), "quota-axi: No such file or directory"),
            (broken(subprocess.TimeoutExpired("quota-axi", 60)), "quota-axi gave no answer in 60 s"),
            (lambda argv, **kw: done("", 1, "oops\nboom"), "quota-axi failed: boom"),
            (lambda argv, **kw: done("", 3), "quota-axi failed: exit 3"),
            (lambda argv, **kw: done("not json"), "quota-axi printed no quota"),
        ]
        for run, why in cases:
            watch = self.watch(run)
            watch._read()
            self.assertEqual(self.posts, [("usage", None, why)])

    def test_the_thread_reads_at_most_once_a_poll_and_only_while_connected(self):
        reads = []
        settings = UsageSettings(poll=60.0)
        clock = FakeClock()

        def run(argv, **kw):
            reads.append(clock.now)
            return done(TODAY)

        watch = UsageWatch(settings, lambda *item: None, clock, run=run)
        thread = threading.Thread(target=watch.worker, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(watch.stop)
        time.sleep(0.1)
        self.assertEqual(reads, [])  # not connected: nothing is read
        watch.showing(True)
        wait_for(lambda: len(reads) == 1)
        # Showing again, disconnecting and reconnecting within the poll reads nothing more.
        for connected in (False, True, False, True):
            watch.showing(connected)
            clock.now += 5
        time.sleep(0.2)
        self.assertEqual(len(reads), 1)

    def test_the_loop_s_every_turn_wakes_the_thread_only_when_the_connection_changes(self):
        watch = self.watch(None)
        for connected in (False, True, True, True, False, False):
            watch.showing(connected)
        self.assertEqual(list(watch._jobs.queue), [("showing", True), ("showing", False)])

    def test_without_firstmate_s_viewer_details_opens_the_full_report_in_a_terminal_window(self):
        launched = []
        watch = self.watch(None, UsageSettings(command=["node", "/home/me/bin/quota-axi"]), launched.append)
        argv = watch.view_argv()
        self.assertEqual(argv[:5], ["ptyxis", "--new-window", "-T", "Usage limits", "-x"])
        # The terminal runs `bash -c <the line>`: the command and --full, then the key to close it.
        line = "node /home/me/bin/quota-axi --full; " + KEY
        self.assertEqual(argv[5], "bash -c " + shlex.quote(line))
        self.assertEqual(TERMINAL[-1], "bash -c {command}")
        watch._open()
        self.assertEqual(launched, [argv])
        self.assertEqual(self.posts, [("usage-view", None)])

    def test_details_opens_firstmate_s_viewer_when_its_home_has_one(self):
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, "data", "tools"))
            watch = UsageWatch(UsageSettings(), lambda *item: None, home=home)
            self.assertIn("--full", watch.view_argv()[5])  # no viewer there yet
            viewer = os.path.join(home, VIEWER)
            with open(viewer, "w") as f:
                f.write("print('limits')\n")
            line = "python3 %s; %s" % (viewer, KEY)
            self.assertEqual(watch.view_argv()[5], "bash -c " + shlex.quote(line))
            self.assertNotIn("--full", watch.view_argv()[5])

    def test_a_window_that_does_not_open_says_why(self):
        def refuse(argv):
            raise RuntimeError("no terminal")

        watch = self.watch(None, launcher=refuse)
        watch._open()
        self.assertEqual(self.posts, [("usage-view", "RuntimeError: no terminal")])


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def wait_for(check, seconds=3.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return
        time.sleep(0.01)
    raise AssertionError("not reached in %g s" % seconds)


class UsageLoopTests(unittest.TestCase):
    """The tile and the Limits page in the app's loop, against the stand-in touch bar."""

    def rig(self, run, launched, providers=None, firstmate=True, runs=None, agents_page=True):
        cfg = config(agents_page=agents_page)
        cfg.usage = UsageSettings(providers=providers)
        if runs:
            cfg.runs = runs
        rig = Rig(
            self,
            FakeHerdr([("w1:p1", "claude", "idle")]),
            FakeFirstmate() if firstmate else None,
            cfg,
            usage_run=run,
            usage_launcher=launched.append,
            **({"nomistakes": FakeNoMistakes()} if runs else {}),
        )
        rig.until(lambda: rig.apps.provided().get("usage", {}).get("text") is not None)
        return rig

    def test_the_tile_and_the_page_show_quota_and_details_opens_the_viewer(self):
        launched = []
        rig = self.rig(lambda argv, **kw: done(TODAY), launched)
        rig.until(lambda: rig.apps.provided()["usage"].get("text") == "no data: claude, copilot")
        tile = rig.apps.provided()["usage"]
        self.assertTrue(tile["label"].startswith("codex 100%"))
        self.assertEqual(rig.handled[0]["tiles"], ["agents", "calls", "bearings", "usage"])
        rig.until(lambda: "limits" in rig.apps.pages)
        page = rig.apps.pages["limits"]
        self.assertEqual((page.look["title"], page.look["badge"]), ("Limits", "100%"))
        ids = [w.id for w in page.widgets]
        self.assertIn("limits.logo.codex", ids)
        self.assertEqual(launched, [])  # nothing opens until it is asked
        rig.apps.press(rig.client(), "limits", "limits.details", "tap")
        rig.until(lambda: launched)
        self.assertEqual(launched[0][:2], ["ptyxis", "--new-window"])
        rig.until(lambda: "opened the usage report" in rig.logged)
        # A touch on anything else of the page does nothing.
        rig.apps.press(rig.client(), "limits", "limits.note", "tap")
        rig.turn(5)
        self.assertEqual(len(launched), 1)
        # The tile's tap is the same Details.
        rig.apps.event("usage", "up", inside=True)
        rig.until(lambda: len(launched) == 2)

    def test_a_hidden_provider_is_neither_on_the_page_nor_in_the_badge(self):
        rig = self.rig(lambda argv, **kw: done(quota(CLAUDE_DOWN, CODEX)), [], providers=["claude"])
        rig.until(lambda: rig.apps.provided()["usage"].get("text") == "claude no data: credentials invalid")
        tile = rig.apps.provided()["usage"]
        self.assertNotIn("badge", tile)
        rig.until(lambda: "limits.nodata.claude" in [w.id for w in rig.apps.pages["limits"].widgets])
        page = rig.apps.pages["limits"]
        self.assertNotIn("badge", page.look)
        self.assertEqual([w.id for w in page.widgets if "codex" in w.id], [])
        self.assertNotIn("100%", str([w.look for w in page.widgets]))

    def test_a_failing_quota_axi_is_logged_once_and_shown(self):
        def run(argv, **kw):
            raise FileNotFoundError(2, "No such file or directory")

        rig = self.rig(run, [])
        rig.until(lambda: rig.apps.provided()["usage"]["text"] == "quota-axi unavailable")
        self.assertEqual(rig.logged, ["quota-axi: No such file or directory"])
        rig.until(lambda: "limits" in rig.apps.pages)
        self.assertEqual(rig.apps.pages["limits"].widgets[0].look["label"], "quota-axi unavailable")

    def test_without_usage_in_the_config_there_is_no_tile_or_page(self):
        rig = Rig(self, FakeHerdr([("w1:p1", "claude", "idle")]), FakeFirstmate())
        rig.until(lambda: rig.widgets() is not None)
        self.assertNotIn("usage", rig.handled[0]["tiles"])
        self.assertNotIn("limits", rig.apps.pages)

    def test_the_touch_bar_takes_four_pages_calls_projects_runs_and_limits_without_the_agents_page(self):
        # Without [herdr] agents_page, firstmate's app gives Captain's Call,
        # Projects, Runs and Limits: the four pages the touch bar takes.
        cfg = RunsSettings([API], True, poll=60.0, idle=60.0)
        rig = self.rig(lambda argv, **kw: done(TODAY), [], runs=cfg, agents_page=False)
        rig.until(lambda: "limits" in rig.apps.pages and "runs" in rig.apps.pages)
        self.assertEqual(sorted(rig.apps.pages), ["calls", "limits", "projects", "runs"])
        self.assertFalse([line for line in rig.logged if "refused" in line or "no calls page" in line], rig.logged)
        self.assertIn("agents", rig.apps.provided())  # the agents tile stays

    def test_with_the_agents_page_and_every_other_page_on_the_calls_page_gives_way(self):
        # Agents, Projects and Limits, and Captain's Call's own page: four.
        rig = self.rig(lambda argv, **kw: done(TODAY), [])
        rig.until(lambda: "limits" in rig.apps.pages)
        self.assertEqual(sorted(rig.apps.pages), ["agents", "calls", "limits", "projects"])
        # With the Runs page too, five: the calls page is left out, and the log says so.
        cfg = RunsSettings([API], True, poll=60.0, idle=60.0)
        rig = self.rig(lambda argv, **kw: done(TODAY), [], runs=cfg)
        rig.until(lambda: "limits" in rig.apps.pages and "runs" in rig.apps.pages)
        self.assertEqual(sorted(rig.apps.pages), ["agents", "limits", "projects", "runs"])
        self.assertFalse([line for line in rig.logged if "refused" in line], rig.logged)  # the bar took every page
        self.assertTrue([line for line in rig.logged if "no calls page" in line], rig.logged)
        self.assertIn("calls", rig.apps.provided())  # the calls tile stays


if __name__ == "__main__":
    unittest.main()
