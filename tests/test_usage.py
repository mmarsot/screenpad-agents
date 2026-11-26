"""The usage-limits tile: quota-axi's TOON read into providers (usage.py),
the tile's words, quota-axi run at most once a minute and only while the
touch bar is connected, never a made-up number for a provider it could not
read, and the tap that opens the full report in a terminal (usagewatch.py)."""

import subprocess
import threading
import time
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import mock

from agents_support import FakeFirstmate, FakeHerdr, Rig, config

from screenpad_agents import usage
from screenpad_agents.config import TERMINAL
from screenpad_agents.config import Usage as UsageSettings
from screenpad_agents.usagewatch import KEY, UsageWatch

# What `quota-axi` printed on the captain's laptop (Claude's credentials refused).
TOON = """\
bin: ~/.local/bin/quota-axi
description: Report local agent-provider quota windows for routing-aware agents
generatedAt: "2026-11-26T10:15:33.938Z"
quota[1]{provider,scope,effectivePercentRemaining,spendPriority,runway,confidence,limitedBy,resetsAt}:
  codex,all_models,100,1,through_reset,early,"window:720h","2026-12-26T10:15:33.000Z"
exhaustion[0]:
attention[3]{provider,scope,kind,detail,remedy}:
  claude,all,auth_required,credentials_invalid,none
  copilot,all,auth_required,GitHub Copilot sign-in required,none
  opencode-go,all,error,sqlite3_unavailable,none
help[2]:
  15 providers not set up are omitted; run `quota-axi --full` to list them
  Run `quota-axi --full` for windows, pace, reserve, and account evidence
"""
BOTH = """\
quota[3]{provider,scope,effectivePercentRemaining,resetsAt}:
  claude,five_hour,42.4,"2026-11-26T14:30:00.000Z"
  claude,weekly,18,"2026-12-01T00:00:00.000Z"
  codex,all_models,null,"2026-12-26T10:15:33.000Z"
attention[1]{provider,scope,kind,detail,remedy}:
  claude,all,error,stale_but_read,none
"""
NOW = datetime(2026, 11, 26, 10, 30, tzinfo=UTC)
UTC = UTC


class ParseTests(unittest.TestCase):
    def test_a_provider_quota_axi_read_has_its_percent_and_reset(self):
        read, *missing = usage.parse(TOON)
        self.assertEqual((read.name, read.percent), ("codex", 100.0))
        self.assertEqual(read.resets, datetime(2026, 12, 26, 10, 15, 33, tzinfo=UTC))
        # The ones it could not read have no number, and say why.
        self.assertEqual(
            [(p.name, p.percent, p.reason) for p in missing],
            [
                ("claude", None, "credentials_invalid"),
                ("copilot", None, "GitHub Copilot sign-in required"),
                ("opencode-go", None, "sqlite3_unavailable"),
            ],
        )

    def test_the_tightest_window_of_a_provider_counts_and_an_unreadable_percent_is_no_data(self):
        claude, codex = usage.parse(BOTH)
        self.assertEqual((claude.name, claude.percent), ("claude", 18.0))  # weekly, not the five hours
        self.assertEqual(claude.resets, datetime(2026, 12, 1, tzinfo=UTC))
        self.assertEqual((codex.name, codex.percent, codex.reason), ("codex", None, "no percent given"))

    def test_text_that_holds_no_quota_is_an_error(self):
        for text in ("", "quota-axi: boom\n", "help[1]:\n  nothing\n"):
            with self.assertRaises(usage.UsageError):
                usage.parse(text)

    def test_a_table_with_no_provider_gives_none(self):
        self.assertEqual(usage.parse("quota[0]{provider}:\nattention[0]{provider}:\n"), [])


class TileTests(unittest.TestCase):
    def tile(self, text=TOON, error=None):
        u = usage.Usage(now=lambda: NOW)
        if text is not None:
            u.set(usage.parse(text))
        if error:
            u.set(None, error)
        return u.tile()

    def test_the_percent_and_reset_of_a_provider_and_those_with_no_data(self):
        tile = self.tile()
        self.assertEqual(tile["tile"], "usage")
        self.assertEqual(tile["label"].split(" ↻")[0], "codex 100%")
        self.assertRegex(tile["label"], r"\Acodex 100% ↻26 Dec\Z")
        self.assertEqual(tile["text"], "no data: claude, copilot, opencode-go")
        # On the bar a tile with an icon shows only it, its badge and its tone: the gauge
        # with the tightest percent left; the words are for the home page's list.
        self.assertEqual((tile["icon"].rsplit("/", 1)[-1], tile["badge"]), ("gauge.svg", "100%"))
        self.assertLessEqual(len(tile["text"]), 48)

    def test_one_provider_with_no_data_says_why(self):
        providers = usage.parse(TOON)[:2]
        text = usage.words(providers, NOW)[1]
        self.assertEqual(text, "claude no data: credentials_invalid")

    def test_a_reset_within_a_day_is_a_clock_time_and_the_tightest_comes_first(self):
        providers = usage.parse(
            "quota[2]{provider,effectivePercentRemaining,resetsAt}:\n"
            '  codex,80,"2026-11-26T12:00:00.000Z"\n  claude,20,"2026-11-26T14:30:00.000Z"\n'
        )
        self.assertEqual([p.name for p in providers], ["claude", "codex"])
        label, text = usage.words(providers, NOW, UTC)
        self.assertEqual((label, text), ("claude 20% · codex 80%", "↻ claude 14:30 · codex 12:00"))
        self.assertEqual(usage.when(providers[0].resets, NOW, UTC), "14:30")
        self.assertEqual(usage.when(datetime(2026, 11, 27, 10, 30, tzinfo=UTC), NOW, UTC), "27 Nov")
        self.assertEqual(usage.when(datetime(2026, 11, 26, 9, 0, tzinfo=UTC), NOW, UTC), "26 Nov")  # past

    def test_the_tone_follows_the_tightest_provider_and_never_a_fake_number(self):
        for percent, tone in ((90, "accept"), (25, "warning"), (10, "reject")):
            text = (
                'quota[1]{provider,effectivePercentRemaining,resetsAt}:\n  codex,%d,"2026-12-26T10:15:33.000Z"\n'
                % percent
            )
            self.assertEqual(self.tile(text)["tone"], tone)
        none = "attention[1]{provider,scope,kind,detail,remedy}:\n  claude,all,auth_required,credentials_invalid,none\n"
        tile = self.tile(none)
        self.assertEqual(
            (tile["tone"], tile["label"], tile["text"]), ("neutral", "Limits", "claude no data: credentials_invalid")
        )
        self.assertNotIn("%", tile["label"] + tile["text"])
        self.assertNotIn("icon", tile)  # nothing read: the words show on the bar, no gauge, no badge
        self.assertNotIn("badge", tile)

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
        self.assertTrue(u.set(usage.parse(TOON)))
        self.assertFalse(u.set(usage.parse(TOON)))
        self.assertTrue(u.set(None, "boom"))
        self.assertFalse(u.set(None, "boom"))
        self.assertTrue(u.set(usage.parse(TOON)))


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
            return done(TOON)

        with mock.patch.dict("os.environ", {"FM_HOME": "/x", "KEEP": "1"}):
            providers = self.watch(run).read()
        self.assertEqual([p.name for p in providers], ["codex", "claude", "copilot", "opencode-go"])
        argv, kw = calls[0]
        self.assertEqual(argv, ["quota-axi"])
        self.assertNotIn("FM_HOME", kw["env"])
        self.assertEqual(kw["env"]["KEEP"], "1")
        self.assertEqual(kw["stdin"], subprocess.DEVNULL)
        self.assertEqual(kw["timeout"], 60.0)

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
            (lambda argv, **kw: done("not toon"), "quota-axi printed no quota"),
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
            return done(TOON)

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

    def test_the_tap_opens_the_full_report_in_a_terminal_window(self):
        launched = []
        watch = self.watch(None, UsageSettings(command=["node", "/home/me/bin/quota-axi"]), launched.append)
        argv = watch.view_argv()
        self.assertEqual(argv[:5], ["ptyxis", "--new-window", "-T", "Usage limits", "-x"])
        # The terminal runs `bash -c <the line>`: the command and --full, then the key to close it.
        line = "node /home/me/bin/quota-axi --full; " + KEY
        self.assertEqual(argv[5], "bash -c " + __import__("shlex").quote(line))
        self.assertEqual(TERMINAL[-1], "bash -c {command}")
        watch._open()
        self.assertEqual(launched, [argv])
        self.assertEqual(self.posts, [("usage-view", None)])

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
    """The tile in the app's loop, against the stand-in touch bar."""

    def rig(self, run, launched):
        cfg = config()
        cfg.usage = UsageSettings()
        rig = Rig(
            self,
            FakeHerdr([("w1:p1", "claude", "idle")]),
            FakeFirstmate(),
            cfg,
            usage_run=run,
            usage_launcher=launched.append,
        )
        rig.until(lambda: rig.apps.provided().get("usage", {}).get("text") is not None)
        return rig

    def test_the_tile_shows_quota_and_a_tap_opens_the_report(self):
        launched = []
        rig = self.rig(lambda argv, **kw: done(TOON), launched)
        rig.until(lambda: rig.apps.provided()["usage"].get("text") == "no data: claude, copilot, opencode-go")
        tile = rig.apps.provided()["usage"]
        self.assertTrue(tile["label"].startswith("codex 100%"))
        self.assertEqual(rig.handled[0]["tiles"], ["agents", "calls", "bearings", "usage"])
        rig.apps.event("usage", "up", inside=True)
        rig.until(lambda: launched)
        self.assertEqual(launched[0][:2], ["ptyxis", "--new-window"])
        rig.until(lambda: "opened the usage report" in rig.logged)
        # No other source is asked, and nothing reads it again within the poll.
        self.assertEqual(len([line for line in rig.logged if "quota" in line]), 0)

    def test_a_failing_quota_axi_is_logged_once_and_shown(self):
        def run(argv, **kw):
            raise FileNotFoundError(2, "No such file or directory")

        rig = self.rig(run, [])
        rig.until(lambda: rig.apps.provided()["usage"]["text"] == "quota-axi unavailable")
        self.assertEqual(rig.logged, ["quota-axi: No such file or directory"])

    def test_without_usage_in_the_config_there_is_no_tile(self):
        rig = Rig(self, FakeHerdr([("w1:p1", "claude", "idle")]), FakeFirstmate())
        rig.until(lambda: rig.widgets() is not None)
        self.assertNotIn("usage", rig.handled[0]["tiles"])


if __name__ == "__main__":
    unittest.main()
