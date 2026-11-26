"""The Projects page (projectpage.py): the list with its presets and pages,
a project's settings, a setting's values, what each tap asks of firstmate,
what is shown while it is pending, and that every view is a page the touch
bar accepts (bar_support's checks of the protocol)."""

import unittest

import agents_support  # noqa: F401  (puts the checkout and vendor/ on sys.path)
from bar_support import FakeClient, parse_page

from screenpad_agents import projectpage as pages
from screenpad_agents.common import PENDING_HOLD
from screenpad_agents.projectmodel import Change, Project, Read


def project(name="api", delivery="full", merge=True, preset=None, **more):
    fields = {"annotated": True, "where": "desktop-first", "model": "opus", "effort": "default"}
    return Project(name, delivery, merge, preset, **dict(fields, **more))


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class PageTests(unittest.TestCase):
    def view(self, *projects, clock=None):
        view = pages.Projects(clock or Clock())
        view.set_read(Read(projects or [project(), project("site", "pr", False)]))
        return view

    def accepted(self, view):
        """The page as the touch bar takes it, and its widgets by id."""
        msg = view.page()
        page = parse_page(FakeClient(), {k: v for k, v in msg.items() if k != "op"})
        return msg, {w.id: w for w in page.widgets}

    def look(self, view, widget):
        return self.accepted(view)[1][widget].look

    def ids(self, view, label):
        return [w for w, x in self.accepted(view)[1].items() if x.look.get("label") == label]

    def tap(self, view, widget):
        return view.touch(widget)

    def test_the_list_has_a_row_per_project_with_its_settings_and_presets(self):
        view = self.view(project(preset="iterate"), project("site", "pr", False))
        msg, widgets = self.accepted(view)
        self.assertEqual(
            (msg["page"], msg["title"], msg["text"], msg["tone"]), ("projects", "Projects", "2 projects", "neutral")
        )
        self.assertEqual((msg["columns"], msg["rows"]), (6, 4))
        names = [w for w in widgets.values() if w.look.get("label") in ("api", "site")]
        self.assertEqual(
            [w.look["text"] for w in names],
            [
                "validated · auto-merge · desktop first · opus",
                "plain PR · you merge · desktop first · opus",
            ],
        )
        # Iterate is lit for the project whose preset it is; it needs no tap.
        api_presets = [w for w in widgets.values() if w.row == 0 and w.look.get("label") in ("Iterate", "Refine")]
        self.assertEqual(
            [(w.look["label"], w.look["tone"], w.touch) for w in api_presets],
            [("Iterate", "accept", "none"), ("Refine", "neutral", "tap")],
        )
        self.assertEqual(len(self.ids(view, "Settings")), 2)

    def test_a_preset_tap_asks_firstmate_for_the_bundle(self):
        view = self.view()
        refine = next(w for w, x in self.accepted(view)[1].items() if x.row == 0 and x.look.get("label") == "Refine")
        _, change = self.tap(view, refine)
        self.assertEqual(change, Change("api", "preset", "refine"))
        # The caller sends it and the page shows it pending, amber, until a read has it.
        view.ask(change)
        msg, widgets = self.accepted(view)
        self.assertEqual((msg["tone"], msg["badge"], msg["text"]), ("warning", "1", "2 projects · 1 asked"))
        self.assertEqual(widgets[refine].look["tone"], "warning")
        row = next(w for w in widgets.values() if w.look.get("label") == "api")
        self.assertEqual((row.look["text"], row.look["tone"]), ("asked firstmate: Refine", "warning"))
        # A second tap on it asks nothing more.
        self.assertEqual(self.tap(view, refine), (False, None))

    def test_a_read_that_has_the_change_ends_the_pending_state(self):
        view = self.view()
        view.ask(Change("api", "preset", "refine"))
        view.set_read(Read([project(preset="refine", merge=False), project("site", "pr", False)]))
        self.assertFalse(view.has_pending())
        msg, widgets = self.accepted(view)
        self.assertEqual((msg["tone"], "badge" in msg), ("neutral", False))
        refine = next(w for w in widgets.values() if w.row == 0 and w.look.get("label") == "Refine")
        self.assertEqual(refine.look["tone"], "accept")

    def test_a_change_firstmate_never_made_stops_showing_after_a_while(self):
        clock = Clock()
        view = self.view(clock=clock)
        view.ask(Change("api", "model", "sonnet"))
        clock.now += PENDING_HOLD - 1
        view.set_read(Read([project(), project("site", "pr", False)]))
        self.assertTrue(view.has_pending())
        clock.now += 2
        view.set_read(Read([project(), project("site", "pr", False)]))
        self.assertFalse(view.has_pending())

    def test_an_unreadable_registry_keeps_what_was_pending(self):
        view = self.view()
        view.ask(Change("api", "model", "sonnet"))
        view.set_read(Read(error="cannot read data/projects.md: No such file or directory"))
        self.assertTrue(view.has_pending())
        msg, widgets = self.accepted(view)
        self.assertEqual(msg["text"], "projects unreadable")
        self.assertEqual([w.look["label"] for w in widgets.values()], ["Projects unreadable"])

    def test_more_than_four_projects_take_pages_of_three(self):
        view = self.view(*[project("p%d" % i) for i in range(8)])
        widgets = self.accepted(view)[1]
        shown = [w.look["label"] for w in widgets.values() if w.look.get("label", "").startswith("p")]
        self.assertEqual(shown, ["p0", "p1", "p2"])
        self.assertEqual(widgets["pj.span"].look["label"], "1-3 of 8")
        self.assertEqual((widgets["pj.prev"].touch, widgets["pj.next"].touch), ("none", "tap"))
        self.tap(view, "pj.next")
        self.tap(view, "pj.next")
        widgets = self.accepted(view)[1]
        self.assertEqual(
            [
                w.look["label"]
                for w in widgets.values()
                if w.look.get("label", "").startswith("p") and w.look["label"][1:].isdigit()
            ],
            ["p6", "p7"],
        )
        self.assertEqual((widgets["pj.span"].look["label"], widgets["pj.next"].touch), ("7-8 of 8", "none"))
        self.tap(view, "pj.prev")
        self.assertEqual(self.accepted(view)[1]["pj.span"].look["label"], "4-6 of 8")
        # A project fewer and the page is still in range.
        view.set_read(Read([project("p%d" % i) for i in range(4)]))
        self.assertNotIn("pj.span", self.accepted(view)[1])

    def test_four_projects_need_no_pager(self):
        view = self.view(*[project("p%d" % i) for i in range(4)])
        self.assertNotIn("pj.next", self.accepted(view)[1])
        self.assertEqual(len(self.ids(view, "Settings")), 4)

    def test_a_project_s_settings_are_one_tap_from_its_row(self):
        view = self.view(project(model="sonnet", effort="high", where="laptop"))
        row = next(w for w, x in self.accepted(view)[1].items() if x.look.get("label") == "Settings")
        self.assertEqual(self.tap(view, row), (True, None))
        msg, widgets = self.accepted(view)
        self.assertEqual((msg["rows"], widgets["pj.back"].look["label"]), (3, "Back"))
        shown = {w.look["label"]: w.look["text"] for w in widgets.values() if w.row > 0}
        self.assertEqual(
            shown,
            {
                "Validation": "Full validation",
                "Auto-merge": "On",
                "Annotated review": "On",
                "Runs on": "Laptop only",
                "Worker model": "Sonnet",
                "Worker effort": "High",
            },
        )
        self.assertEqual(widgets["pj.title"].look["label"], "api")
        self.assertEqual(widgets["pj.title"].look["text"], "validated · auto-merge · laptop only · sonnet high")
        # Back returns to the list.
        self.tap(view, "pj.back")
        self.assertEqual(len(self.ids(view, "Settings")), 1)

    def open_project(self, view, name="api"):
        row = next(w for w, x in self.accepted(view)[1].items() if x.look.get("label") == name)
        self.tap(view, row)

    def test_a_toggle_asks_for_the_other_value_at_once(self):
        view = self.view()
        self.open_project(view)
        _, change = self.tap(view, "pj.auto_.off")
        self.assertEqual(change, Change("api", "auto_merge", False))
        view.ask(change)
        # While it is pending, its tap asks for the first value back.
        widgets = self.accepted(view)[1]
        self.assertEqual(widgets["pj.auto_.on"].look["text"], "On → Off, asked")
        self.assertEqual(self.tap(view, "pj.auto_.on")[1], Change("api", "auto_merge", True))
        _, annotate = self.tap(view, "pj.annot.off")
        self.assertEqual(annotate, Change("api", "annotated", False))

    def test_a_setting_s_values_are_large_buttons_and_one_tap_asks_for_one(self):
        view = self.view(project(model="sonnet"))
        self.open_project(view)
        self.assertEqual(self.tap(view, "pj.model"), (True, None))
        widgets = self.accepted(view)[1]
        values = {w.look["label"]: (w.look["tone"], w.touch) for w in widgets.values() if w.row > 0}
        self.assertEqual(
            values, {"Opus": ("neutral", "tap"), "Sonnet": ("accept", "none"), "Haiku": ("neutral", "tap")}
        )
        self.assertEqual(widgets["pj.title"].look["label"], "api · Worker model")
        _, change = self.tap(view, "pj.v.haiku")
        self.assertEqual(change, Change("api", "model", "haiku"))
        # Asking returns to the project's settings, where the change shows pending.
        view.ask(change)
        widgets = self.accepted(view)[1]
        self.assertEqual(widgets["pj.model"].look["text"], "Sonnet → Haiku, asked")
        self.assertEqual(widgets["pj.model"].look["tone"], "warning")

    def test_the_other_values_the_page_offers(self):
        view = self.view()
        self.open_project(view)
        for opener, values in (
            ("pj.validation", ["full", "pr", "local"]),
            ("pj.where", ["desktop-first", "laptop-first", "desktop", "laptop"]),
            ("pj.effort", ["default", "low", "medium", "high", "xhigh", "max"]),
        ):
            self.tap(view, opener)
            widgets = self.accepted(view)[1]
            self.assertEqual(sorted(w for w in widgets if w.startswith("pj.v.")), sorted("pj.v." + v for v in values))
            self.tap(view, "pj.back")

    def test_a_failed_note_is_shown_and_not_pending(self):
        view = self.view()
        self.open_project(view)
        change = Change("api", "auto_merge", False)
        view.ask(change)
        view.failed(change, "fm-inbox.sh note failed: exit 1")
        self.assertFalse(view.has_pending())
        title = self.accepted(view)[1]["pj.title"].look
        self.assertEqual(title["text"], "firstmate was not told: fm-inbox.sh note failed: exit 1")

    def test_a_tap_on_a_widget_the_page_no_longer_shows_does_nothing(self):
        view = self.view()
        self.assertEqual(self.tap(view, "pj.auto_.off"), (False, None))  # a settings view's, not drawn
        self.open_project(view)
        self.assertEqual(self.tap(view, "pj.next"), (False, None))
        # A project that left the registry closes its view.
        view.set_read(Read([project("site", "pr", False)]))
        self.assertEqual(self.ids(view, "Back"), [])
        self.assertEqual(len(self.ids(view, "Settings")), 1)

    def test_every_view_fits_the_protocol_with_the_longest_names_and_values(self):
        long = "x" * 60
        view = self.view(project(long, model=long, effort=long, where=long), *[project("p%d" % i) for i in range(8)])
        self.accepted(view)
        self.tap(view, "pj.next")
        self.accepted(view)
        view.offset = 0
        self.open_project(view, "x" * 31 + "…")
        for opener in ("pj.validation", "pj.model", "pj.where", "pj.effort"):
            self.tap(view, opener)
            widgets = self.accepted(view)[1]
            for w in widgets.values():
                self.assertLessEqual(len(w.look.get("label", "")), 32)
            self.tap(view, "pj.back")

    def test_before_the_first_read_and_with_no_projects(self):
        view = pages.Projects()
        self.assertEqual(self.accepted(view)[0]["text"], "reading firstmate…")
        view.set_read(Read([]))
        self.assertEqual([w.look["label"] for w in self.accepted(view)[1].values()], ["No projects"])
        self.assertEqual(view.messages()[0]["page"], "projects")


if __name__ == "__main__":
    unittest.main()
