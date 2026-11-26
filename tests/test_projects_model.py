"""The Projects page's data (projectmodel.py): firstmate's registry and
settings file read tolerantly and read-only, the settings' defaults, the
preset a project still is, and the note a change is asked for with."""

import os
import tempfile
import unittest

from agents_support import PROJECTS

import screenpad_agents.projectmodel as model
from screenpad_agents.projectmodel import Change, Project, reflects

SETTINGS = """\
[projects.api]
preset = "refine"
annotated_review = false
where = "laptop-first"
model = "sonnet"
effort = "high"

[projects.ghost]
model = "opus"
"""


class RegistryTests(unittest.TestCase):
    def test_the_tags_give_the_delivery_and_the_auto_merge(self):
        rows = dict(model.parse_registry(PROJECTS))
        self.assertEqual(sorted(rows), ["api", "site"])  # the archived one is left out
        api = model.project("api", rows["api"], {})
        self.assertEqual((api.delivery, api.auto_merge), ("full", True))
        site = model.project("site", rows["site"], {})
        self.assertEqual((site.delivery, site.auto_merge), ("pr", False))
        local = model.project("x", {"local-only"}, {})
        self.assertEqual((local.delivery, local.auto_merge), ("local", False))

    def test_an_unknown_annotation_or_line_is_tolerated(self):
        text = "\n".join(
            [
                "# the projects",
                "",
                "- a [no-mistakes +yolo +future-flag some-tag] - one",
                "- b - no tags at all",
                "- c [local-only]",
                "- ../evil [no-mistakes] - a name that is no project's",
                "not a project line",
                "- d [direct-PR] - ARCHIVED 2026-11-03: gone",
            ]
        )
        rows = model.parse_registry(text)
        self.assertEqual([n for n, _ in rows], ["a", "b", "c"])
        a, b, c = (model.project(n, t, {}) for n, t in rows)
        self.assertEqual((a.delivery, a.auto_merge), ("full", True))
        self.assertEqual((b.delivery, b.auto_merge), (None, False))  # delivery unknown
        self.assertEqual(c.delivery, "local")


class SettingsTests(unittest.TestCase):
    def test_absent_keys_mean_the_defaults(self):
        p = model.project("api", {"no-mistakes"}, {})
        self.assertEqual(
            (p.preset, p.annotated, p.where, p.model, p.effort), (None, True, "desktop-first", "opus", "default")
        )

    def test_the_settings_file_gives_the_other_settings_per_project(self):
        found = model.parse_settings(SETTINGS)
        self.assertEqual(
            found["api"],
            {"preset": "refine", "annotated": False, "where": "laptop-first", "model": "sonnet", "effort": "high"},
        )
        p = model.project("api", {"no-mistakes"}, found["api"])
        self.assertEqual((p.annotated, p.where, p.model, p.effort), (False, "laptop-first", "sonnet", "high"))

    def test_a_value_of_the_wrong_kind_is_ignored(self):
        text = '[projects.api]\nannotated_review = "yes"\nmodel = 3\neffort = ""\nunknown = 1\n[projects]\nx = 1\n'
        self.assertEqual(model.parse_settings(text), {"api": {}})
        self.assertEqual(model.parse_settings("[other]\nx = 1\n"), {})

    def test_a_preset_is_the_project_s_only_while_its_bundle_holds(self):
        def p(preset, delivery="full", merge=True, annotated=True):
            return Project("api", delivery, merge, preset, annotated, "desktop-first", "opus", "default")

        self.assertEqual(p("iterate").effective_preset(), "iterate")
        self.assertEqual(p("refine", merge=False).effective_preset(), "refine")
        # Changed by hand since: no longer the project's.
        self.assertIsNone(p("iterate", merge=False).effective_preset())
        self.assertIsNone(p("iterate", delivery="pr").effective_preset())
        self.assertIsNone(p("refine", merge=False, annotated=False).effective_preset())
        self.assertIsNone(p("refine", merge=True).effective_preset())
        self.assertIsNone(p(None).effective_preset())  # none was ever set
        self.assertIsNone(p("custom").effective_preset())


class ChangeTests(unittest.TestCase):
    def test_every_change_reads_as_a_sentence_for_firstmate(self):
        cases = {
            ("preset", "refine"): "ScreenPad Projects page: set api preset to Refine",
            ("preset", "iterate"): "ScreenPad Projects page: set api preset to Iterate",
            ("validation", "full"): "ScreenPad Projects page: set api validation to full no-mistakes",
            ("validation", "pr"): "ScreenPad Projects page: set api validation to plain PR",
            ("validation", "local"): "ScreenPad Projects page: set api validation to local only",
            ("auto_merge", True): "ScreenPad Projects page: set api auto-merge to on",
            ("auto_merge", False): "ScreenPad Projects page: set api auto-merge to off",
            ("annotated", False): "ScreenPad Projects page: set api annotated review to off",
            ("where", "desktop-first"): "ScreenPad Projects page: set api where it runs to desktop first",
            ("where", "laptop"): "ScreenPad Projects page: set api where it runs to laptop only",
            ("model", "opus"): "ScreenPad Projects page: set api worker model to opus",
            ("effort", "xhigh"): "ScreenPad Projects page: set api worker effort to xhigh",
        }
        for (key, value), text in cases.items():
            self.assertEqual(Change("api", key, value).text(), text)
        # Every value the page offers has its words.
        for key, (_, values) in model.CHOICES.items():
            for value, _ in values:
                self.assertTrue(Change("api", key, value).text())

    def test_a_change_is_reflected_once_the_files_have_it(self):
        p = Project("api", "pr", False, "refine", True, "desktop", "sonnet", "default")
        self.assertTrue(reflects(p, Change("api", "validation", "pr")))
        self.assertFalse(reflects(p, Change("api", "validation", "full")))
        self.assertTrue(reflects(p, Change("api", "auto_merge", False)))
        self.assertTrue(reflects(p, Change("api", "model", "sonnet")))
        self.assertFalse(reflects(p, Change("api", "preset", "refine")))  # the bundle does not hold: pr
        full = Project("api", "full", False, "refine", True, "desktop", "sonnet", "default")
        self.assertTrue(reflects(full, Change("api", "preset", "refine")))
        self.assertFalse(reflects(full, Change("api", "preset", "iterate")))


class ReadTests(unittest.TestCase):
    def home(self, registry=PROJECTS, settings=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.makedirs(os.path.join(tmp.name, "data"))
        if registry is not None:
            with open(os.path.join(tmp.name, model.REGISTRY), "w") as f:
                f.write(registry)
        if settings is not None:
            with open(os.path.join(tmp.name, model.SETTINGS), "w") as f:
                f.write(settings)
        return tmp.name

    def test_the_two_files_are_read_and_nothing_is_written(self):
        home = self.home(settings=SETTINGS)
        before = {n: os.stat(os.path.join(home, "data", n)).st_mtime_ns for n in os.listdir(os.path.join(home, "data"))}
        read = model.read(home)
        self.assertEqual((read.error, read.settings_error), (None, None))
        self.assertEqual([p.name for p in read.projects], ["api", "site"])  # ghost has no row; old is archived
        self.assertEqual((read.find("api").preset, read.find("api").model), ("refine", "sonnet"))
        self.assertEqual((read.find("site").preset, read.find("site").model), (None, "opus"))
        after = {n: os.stat(os.path.join(home, "data", n)).st_mtime_ns for n in os.listdir(os.path.join(home, "data"))}
        self.assertEqual(before, after)

    def test_a_missing_settings_file_means_the_defaults(self):
        read = model.read(self.home())
        self.assertEqual((read.error, read.settings_error), (None, None))
        self.assertEqual(read.find("api").annotated, True)

    def test_a_missing_registry_says_so(self):
        read = model.read(self.home(registry=None))
        self.assertEqual(read.projects, [])
        self.assertEqual(read.error, "cannot read data/projects.md: No such file or directory")

    def test_a_broken_settings_file_keeps_the_projects_with_the_defaults(self):
        read = model.read(self.home(settings="[projects\n"))
        self.assertIn("project-settings.toml", read.settings_error)
        self.assertEqual([p.name for p in read.projects], ["api", "site"])
        self.assertEqual(read.find("api").model, "opus")


if __name__ == "__main__":
    unittest.main()
