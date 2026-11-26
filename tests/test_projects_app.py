"""The Projects page in the app's loop (extras.py, projectwatch.py) against
the stand-in touch bar: the page drawn from firstmate's registry, taps staged
as a draft that sends nothing, Validate sending one note through firstmate's
capture surface for every change and showing them pending until the files
reflect them, Discard, a note that fails, reading only while the touch bar is
connected, and that the app never writes firstmate's files."""

import os
import threading
import time
import unittest
from unittest import mock

from agents_support import NOTE, FakeFirstmate, FakeHerdr, Rig, task

from screenpad_agents import projectmodel as model
from screenpad_agents.projectwatch import ProjectsWatch

REFINE = "ScreenPad Projects page: set api preset to Refine"


class ProjectsLoopTests(unittest.TestCase):
    def setUp(self):
        self.herdr = FakeHerdr([("w1:p1", "claude", "working")])
        self.firstmate = FakeFirstmate(calls=0, tasks={"lab:w1:p1": task("fix-api")})
        for name in ("PENDING_POLL", "PROJECTS_POLL"):
            patcher = mock.patch("screenpad_agents.projectwatch." + name, 0.05)
            patcher.start()
            self.addCleanup(patcher.stop)

    def rig(self):
        rig = Rig(self, self.herdr, self.firstmate)
        rig.until(
            lambda: "projects" in rig.apps.pages and rig.apps.pages["projects"].widgets[0].look.get("label") == "api"
        )
        return rig

    def widgets(self, rig):
        return {w.id: w for w in rig.apps.pages["projects"].widgets}

    def tap(self, rig, widget):
        rig.apps.press(rig.client(), "projects", widget, "tap")

    def label(self, rig, label):
        return next(w for w, x in self.widgets(rig).items() if x.look.get("label") == label)

    def refine(self, rig):
        return self.label(rig, "Refine")

    def open_project(self, rig, name):
        self.tap(rig, self.label(rig, name))
        rig.until(lambda: "pj.back" in self.widgets(rig))

    def back(self, rig):
        self.tap(rig, "pj.back")
        rig.until(lambda: "pj.back" not in self.widgets(rig))

    def stage(self, rig, name, preset, badge):
        """Open a project from the list, tap a preset, come back to the list."""
        self.open_project(rig, name)
        self.tap(rig, self.label(rig, preset))
        rig.until(lambda: rig.apps.pages["projects"].look.get("badge") == badge)
        self.back(rig)

    def files(self, rig):
        data = os.path.join(rig.app.config.home, "data")
        return {n: os.stat(os.path.join(data, n)).st_mtime_ns for n in sorted(os.listdir(data))}

    def write(self, rig, name, text):
        with open(os.path.join(rig.app.config.home, "data", name), "w") as f:
            f.write(text)

    def test_the_page_lists_the_registry_s_active_projects(self):
        rig = self.rig()
        page = rig.apps.pages["projects"]
        self.assertEqual(
            (page.look["title"], page.look["text"], page.columns, page.rows), ("Projects", "2 projects", 6, 4)
        )
        labels = [w.look.get("label") for w in page.widgets]
        self.assertEqual(
            labels,
            ["api", "site", "Discard", "Validate"],
        )
        self.assertEqual([self.widgets(rig)[self.label(rig, n)].touch for n in ("api", "site")], ["tap", "tap"])
        self.assertEqual(rig.logged, [])

    def test_taps_stage_a_draft_and_validate_sends_one_note_for_every_change(self):
        rig = self.rig()
        before = self.files(rig)
        self.stage(rig, "api", "Refine", "1")
        # Staged, not sent: nothing reaches firstmate until Validate.
        rig.turn(10)
        self.assertEqual(self.firstmate.notes, [])
        self.stage(rig, "site", "Iterate", "2")
        self.assertEqual(rig.apps.pages["projects"].look["text"], "2 projects · 2 to validate")
        self.tap(rig, "pj.validate")
        rig.until(lambda: len(self.firstmate.notes) == 1)
        request_id, text = self.firstmate.notes[0]
        self.assertEqual(text, REFINE + "; set site preset to Iterate")
        self.assertRegex(request_id, r"\Ascreenpad-project-[0-9]+-[0-9a-f]{8}\Z")
        rig.until(lambda: rig.apps.pages["projects"].look["text"] == "2 projects · 2 asked")
        self.assertIn("asked firstmate: " + text, rig.logged)
        # Validate again sends nothing: the draft is empty.
        self.tap(rig, "pj.validate")
        rig.turn(10)
        self.assertEqual(len(self.firstmate.notes), 1)
        # firstmate applies the first: it stops being pending, the other stays.
        self.write(rig, "projects.md", model_registry(yolo=False))
        self.write(rig, "project-settings.toml", '[projects.api]\npreset = "refine"\n')
        rig.until(lambda: rig.apps.pages["projects"].look["text"] == "2 projects · 1 asked")
        self.open_project(rig, "api")
        self.assertEqual(self.widgets(rig)[self.refine(rig)].look["tone"], "accept")
        # The app wrote neither file: only the test did.
        self.assertEqual(sorted(self.files(rig)), ["project-settings.toml", "projects.md"])
        self.assertTrue(before["projects.md"] < self.files(rig)["projects.md"])

    def test_discard_sends_nothing(self):
        rig = self.rig()
        self.stage(rig, "api", "Refine", "1")
        self.tap(rig, "pj.discard")
        rig.until(lambda: "badge" not in rig.apps.pages["projects"].look)
        self.tap(rig, "pj.validate")
        rig.turn(10)
        self.assertEqual(self.firstmate.notes, [])

    def test_a_single_setting_is_staged_from_the_project_s_view(self):
        rig = self.rig()
        self.open_project(rig, "api")
        self.tap(rig, "pj.auto_.off")
        rig.until(lambda: getattr(self.widgets(rig).get("pj.auto_.on"), "look", {}).get("text") == "On → Off, draft")
        self.assertEqual(self.firstmate.notes, [])
        self.tap(rig, "pj.validate")
        rig.until(lambda: self.firstmate.notes)
        self.assertEqual(self.firstmate.notes[0][1], "ScreenPad Projects page: set api auto-merge to off")
        rig.until(lambda: getattr(self.widgets(rig).get("pj.auto_.off"), "look", {}).get("text") == "On → Off, asked")

    def test_a_note_that_fails_is_logged_shown_and_the_draft_is_kept(self):
        self.firstmate.request_error = "fm-inbox.sh note failed: exit 1"
        rig = self.rig()
        self.stage(rig, "api", "Refine", "1")
        self.tap(rig, "pj.validate")
        rig.until(lambda: any(line.startswith("firstmate was not told") for line in rig.logged))
        # Back to a draft, not pending: the captain can validate again.
        rig.until(lambda: rig.apps.pages["projects"].look["text"] == "2 projects · 1 to validate")
        self.firstmate.request_error = None
        self.tap(rig, "pj.validate")
        rig.until(lambda: len(self.firstmate.notes) == 2)
        self.assertEqual(self.firstmate.notes[1][1], REFINE)
        self.assertNotEqual(self.firstmate.notes[0][0], self.firstmate.notes[1][0])

    def test_an_unreadable_registry_is_shown_and_logged_once(self):
        rig = Rig(self, self.herdr, self.firstmate)
        os.remove(os.path.join(rig.app.config.home, "data", "projects.md"))

        def text():
            page = rig.apps.pages.get("projects")
            return page and page.look["text"]

        rig.until(lambda: text() == "projects unreadable")
        rig.turn(10)
        self.assertEqual(len([line for line in rig.logged if "projects.md" in line]), 1)

    def test_without_firstmate_there_is_no_projects_page(self):
        rig = Rig(self, self.herdr, None)
        rig.until(lambda: rig.widgets() == ["agent.w1.p1"])
        self.assertNotIn("projects", rig.apps.pages)


def model_registry(yolo=True):
    return "- api [no-mistakes%s] - the API (added 2026-07-29)\n- site [direct-PR] - the site\n" % (
        " +yolo" if yolo else ""
    )


class ProjectsReadTests(unittest.TestCase):
    """The thread reads only while the touch bar is connected, and sooner
    while a change is pending."""

    def watch(self, interval=0.03):
        self.reads, self.posts = [], []
        patches = [
            mock.patch("screenpad_agents.projectwatch." + n, interval) for n in ("PENDING_POLL", "PROJECTS_POLL")
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        def reader(home):
            self.reads.append(home)
            return model.Read()

        watch = ProjectsWatch("/fm", FakeFirstmate(), lambda *item: self.posts.append(item), reader=reader)
        thread = threading.Thread(target=watch.worker, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(watch.stop)
        return watch

    def test_nothing_is_read_while_the_bar_is_not_connected(self):
        watch = self.watch()
        time.sleep(0.2)
        self.assertEqual(self.reads, [])
        watch.showing(True)
        deadline = time.monotonic() + 3
        while len(self.reads) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertGreaterEqual(len(self.reads), 3)
        self.assertEqual(self.reads[0], "/fm")
        watch.showing(False)
        time.sleep(0.1)
        count = len(self.reads)
        time.sleep(0.2)
        self.assertEqual(len(self.reads), count)

    def test_a_note_is_sent_and_reported(self):
        watch = self.watch()
        change = model.Change("api", "preset", "refine")
        watch.send([change])
        deadline = time.monotonic() + 3
        while not self.posts and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.posts, [("project-note", [change], None)])
        self.assertEqual(NOTE, "1793706159-abc123")


if __name__ == "__main__":
    unittest.main()
