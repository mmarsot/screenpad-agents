"""The Projects page (projectpage.py): the list, a grid of project cells in
pages of nine whose tap opens the project, a project's settings with its
presets, a setting's values, choices staged in a draft and sent only by
Validate (every drafted change of every project, in one go), what is shown
while a change is a draft and while it is pending, and that every view is a
page the touch bar accepts (bar_support's checks of the protocol)."""

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

    def widgets(self, view):
        return self.accepted(view)[1]

    def ids(self, view, label, row=None):
        return [w for w, x in self.widgets(view).items() if x.look.get("label") == label and row in (None, x.row)]

    def tap(self, view, widget):
        return view.touch(widget)

    def preset(self, view, label):
        return self.ids(view, label)[0]

    def stage(self, view, label, name="api"):
        """Open a project, tap one of its presets, and come back to the list."""
        self.open_project(view, name)
        self.tap(view, self.preset(view, label))
        self.tap(view, "pj.back")

    def open_project(self, view, name="api"):
        self.tap(view, next(w for w, x in self.widgets(view).items() if x.look.get("label") == name))

    # --- the list -------------------------------------------------------------

    def test_the_list_is_a_grid_of_project_cells_with_their_settings(self):
        view = self.view(project(preset="iterate"), project("site", "pr", False))
        msg, widgets = self.accepted(view)
        self.assertEqual(
            (msg["page"], msg["title"], msg["text"], msg["tone"]), ("projects", "Projects", "2 projects", "neutral")
        )
        self.assertEqual((msg["columns"], msg["rows"]), (6, 4))
        names = [w for w in widgets.values() if w.look.get("label") in ("api", "site")]
        self.assertEqual([(w.col, w.row, w.cols, w.touch) for w in names], [(0, 0, 2, "tap"), (2, 0, 2, "tap")])
        self.assertEqual(
            [w.look["text"] for w in names],
            ["validated · auto-merge · desktop first · opus", "plain PR · you merge · desktop first · opus"],
        )
        # No preset or Settings buttons on the list: the cell itself opens the project.
        labels = {w.look.get("label") for w in widgets.values()}
        self.assertFalse(labels & {"Iterate", "Refine", "Settings"})
        # Nothing drafted: Validate and Discard are there and dead.
        self.assertEqual(
            (widgets["pj.validate"].look["text"], widgets["pj.validate"].touch), ("nothing to send", "none")
        )
        self.assertEqual(widgets["pj.discard"].touch, "none")

    def test_projects_take_pages_of_nine_in_three_rows_of_three(self):
        view = self.view(*[project("p%d" % i) for i in range(12)])
        widgets = self.widgets(view)

        def shown():
            return {w.look["label"]: (w.col, w.row) for w in self.widgets(view).values() if w.row < 3 and w.cols == 2}

        self.assertEqual(shown(), {"p%d" % i: (2 * (i % 3), i // 3) for i in range(9)})
        self.assertEqual(widgets["pj.span"].look["label"], "1-9 of 12")
        self.assertEqual((widgets["pj.prev"].touch, widgets["pj.next"].touch), ("none", "tap"))
        self.assertEqual(widgets["pj.validate"].row, 3)  # Validate is on every page
        self.tap(view, "pj.next")
        self.assertEqual(shown(), {"p9": (0, 0), "p10": (2, 0), "p11": (4, 0)})
        widgets = self.widgets(view)
        self.assertEqual((widgets["pj.span"].look["label"], widgets["pj.next"].touch), ("10-12 of 12", "none"))
        self.tap(view, "pj.prev")
        self.assertEqual(self.widgets(view)["pj.span"].look["label"], "1-9 of 12")
        # Fewer projects and the page is still in range; nine need no pager.
        self.tap(view, "pj.next")
        view.set_read(Read([project("p%d" % i) for i in range(9)]))
        self.assertNotIn("pj.span", self.widgets(view))
        self.assertEqual(len(shown()), 9)

    # --- the draft: nothing is sent until Validate -------------------------------

    def test_a_preset_tap_stages_it_and_sends_nothing(self):
        view = self.view()
        self.open_project(view)
        refine = self.preset(view, "Refine")
        self.assertEqual(self.tap(view, refine), (True, None))
        msg, widgets = self.accepted(view)
        self.assertEqual((msg["tone"], msg["badge"], msg["text"]), ("warning", "1", "2 projects · 1 to validate"))
        self.assertEqual(widgets[refine].look["tone"], "warning")
        self.tap(view, "pj.back")
        msg, widgets = self.accepted(view)
        row = next(w for w in widgets.values() if w.look.get("label") == "api")
        self.assertEqual((row.look["text"], row.look["tone"]), ("draft: Refine", "warning"))
        self.assertEqual(
            (widgets["pj.validate"].look["text"], widgets["pj.validate"].touch), ("send 1 change to firstmate", "tap")
        )
        self.assertFalse(view.has_pending())  # staged, not asked

    def test_validate_gives_every_drafted_change_of_every_project_in_order(self):
        view = self.view()
        self.stage(view, "Refine")
        self.stage(view, "Iterate", "site")
        self.open_project(view, "site")
        self.tap(view, "pj.annot.off")
        self.tap(view, "pj.model")
        self.tap(view, "pj.v.sonnet")
        changed, sent = self.tap(view, "pj.validate")
        self.assertTrue(changed)
        self.assertEqual(
            sent,
            [
                Change("api", "preset", "refine"),
                Change("site", "preset", "iterate"),
                Change("site", "annotated", False),
                Change("site", "model", "sonnet"),
            ],
        )
        # Now they are pending, the draft is empty, and Validate is dead again.
        msg, widgets = self.accepted(view)
        self.assertTrue(view.has_pending())
        self.assertEqual((msg["badge"], msg["text"]), ("4", "2 projects · 4 asked"))
        self.assertEqual(
            (widgets["pj.validate"].look["text"], widgets["pj.validate"].touch), ("nothing to send", "none")
        )
        self.assertEqual(self.tap(view, "pj.validate"), (False, None))

    def test_discard_drops_the_draft(self):
        view = self.view()
        self.stage(view, "Refine")
        self.assertEqual(self.tap(view, "pj.discard"), (True, None))
        msg, widgets = self.accepted(view)
        self.assertEqual((msg["tone"], "badge" in msg), ("neutral", False))
        self.assertEqual(widgets["pj.validate"].touch, "none")
        self.assertEqual(self.tap(view, "pj.validate"), (False, None))
        self.assertEqual(view.changes(), [])

    def test_a_drafted_preset_implies_its_bundle_and_a_single_setting_can_override_it(self):
        view = self.view()
        self.open_project(view)
        self.tap(view, self.preset(view, "Refine"))
        cells = {w.look["label"]: w.look["text"] for w in self.widgets(view).values() if w.row in (1, 2)}
        self.assertEqual(cells["Auto-merge"], "On → Off, draft")
        self.assertEqual(cells["Validation"], "Full validation")  # the bundle's, the file's
        # Auto-merge back on overrides the bundle: both are sent, the preset first.
        self.tap(view, "pj.auto_.on")
        self.assertEqual(view.changes(), [Change("api", "preset", "refine"), Change("api", "auto_merge", True)])
        self.assertEqual(
            self.tap(view, "pj.validate")[1], [Change("api", "preset", "refine"), Change("api", "auto_merge", True)]
        )

    def test_staging_what_the_file_has_takes_the_change_back_out(self):
        view = self.view(project(model="sonnet"))
        self.open_project(view)
        self.tap(view, "pj.model")
        self.tap(view, "pj.v.haiku")
        self.assertEqual(view.changes(), [Change("api", "model", "haiku")])
        self.tap(view, "pj.model")
        self.tap(view, "pj.v.sonnet")
        self.assertEqual(view.changes(), [])
        self.tap(view, "pj.auto_.off")
        self.assertEqual(view.changes(), [Change("api", "auto_merge", False)])
        self.tap(view, "pj.auto_.on")
        self.assertEqual(view.changes(), [])

    def test_a_read_that_has_a_drafted_change_drops_it_and_a_gone_project_drops_its_draft(self):
        view = self.view()
        self.stage(view, "Refine")
        self.stage(view, "Refine", "site")
        view.set_read(Read([project(preset="refine", merge=False), project("site", "pr", False)]))
        self.assertEqual(view.changes(), [Change("site", "preset", "refine")])
        view.set_read(Read([project(preset="refine", merge=False)]))
        self.assertEqual(view.changes(), [])

    # --- what is pending ------------------------------------------------------

    def test_a_read_that_has_the_change_ends_the_pending_state(self):
        view = self.view()
        self.stage(view, "Refine")
        self.tap(view, "pj.validate")
        msg, widgets = self.accepted(view)
        row = next(w for w in widgets.values() if w.look.get("label") == "api")
        self.assertEqual(row.look["text"], "asked firstmate: Refine")
        self.open_project(view)
        refine = self.preset(view, "Refine")
        self.assertEqual(self.widgets(view)[refine].look["tone"], "warning")
        view.set_read(Read([project(preset="refine", merge=False), project("site", "pr", False)]))
        self.assertFalse(view.has_pending())
        msg, widgets = self.accepted(view)
        self.assertEqual((msg["tone"], "badge" in msg), ("neutral", False))
        self.assertEqual(widgets[refine].look["tone"], "accept")

    def test_a_change_firstmate_never_made_stops_showing_after_a_while(self):
        clock = Clock()
        view = self.view(clock=clock)
        self.open_project(view)
        self.tap(view, "pj.model")
        self.tap(view, "pj.v.sonnet")
        self.tap(view, "pj.validate")
        clock.now += PENDING_HOLD - 1
        view.set_read(Read([project(), project("site", "pr", False)]))
        self.assertTrue(view.has_pending())
        clock.now += 2
        view.set_read(Read([project(), project("site", "pr", False)]))
        self.assertFalse(view.has_pending())

    def test_a_pending_value_is_not_staged_again(self):
        view = self.view()
        self.open_project(view)
        self.tap(view, "pj.auto_.off")
        self.tap(view, "pj.validate")
        self.assertEqual(self.widgets(view)["pj.auto_.off"].look["text"], "On → Off, asked")
        self.assertEqual(self.widgets(view)["pj.auto_.off"].touch, "none")  # nothing to ask again
        self.tap(view, "pj.model")
        self.tap(view, "pj.v.haiku")
        self.assertEqual(view.changes(), [Change("api", "model", "haiku")])  # others still can be

    def test_a_failed_note_restores_the_draft_and_says_why(self):
        view = self.view()
        self.open_project(view)
        self.tap(view, "pj.auto_.off")
        changes = self.tap(view, "pj.validate")[1]
        view.failed(changes, "fm-inbox.sh note failed: exit 1")
        self.assertFalse(view.has_pending())
        self.assertEqual(view.changes(), changes)
        widgets = self.widgets(view)
        self.assertEqual(widgets["pj.title"].look["text"], "firstmate was not told: fm-inbox.sh note failed: exit 1")
        self.assertEqual(widgets["pj.validate"].look["text"], "send 1 change to firstmate")

    def test_an_unreadable_registry_keeps_the_draft_and_what_was_pending(self):
        view = self.view()
        self.stage(view, "Refine")
        view.set_read(Read(error="cannot read data/projects.md: No such file or directory"))
        self.assertEqual(view.changes(), [])  # no projects to name them by: shown again with the files
        msg, widgets = self.accepted(view)
        self.assertEqual(msg["text"], "projects unreadable")
        self.assertEqual([w.look["label"] for w in widgets.values()], ["Projects unreadable"])
        view.set_read(Read([project(), project("site", "pr", False)]))
        self.assertEqual(view.changes(), [Change("api", "preset", "refine")])

    # --- a project's settings -------------------------------------------------

    def test_a_project_s_settings_are_one_tap_from_its_cell(self):
        view = self.view(project(model="sonnet", effort="high", where="laptop"))
        self.assertEqual(self.tap(view, self.ids(view, "api")[0]), (True, None))
        msg, widgets = self.accepted(view)
        self.assertEqual((msg["rows"], widgets["pj.back"].look["label"]), (4, "Back"))
        shown = {w.look["label"]: w.look["text"] for w in widgets.values() if w.row in (1, 2)}
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
        self.assertEqual(widgets["pj.title"].look["text"], "validated · auto-merge · laptop only · sonnet high")
        # Validate and Discard are here too, with the draft in words.
        self.assertEqual(
            (widgets["pj.draft"].look["label"], widgets["pj.draft"].look["text"]),
            ("No changes", "tap a value to stage it"),
        )
        self.tap(view, "pj.annot.off")
        widgets = self.widgets(view)
        self.assertEqual(widgets["pj.annot.on"].look["text"], "On → Off, draft")
        self.assertEqual(
            (widgets["pj.draft"].look["label"], widgets["pj.draft"].look["text"]), ("1 to validate", "api Off")
        )
        self.assertEqual(widgets["pj.validate"].touch, "tap")
        self.tap(view, "pj.back")
        self.assertEqual(len(self.ids(view, "api")), 1)
        self.assertEqual(self.ids(view, "Back"), [])  # the list again

    def test_a_setting_s_values_are_large_buttons_and_one_tap_stages_one(self):
        view = self.view(project(model="sonnet"))
        self.open_project(view)
        self.assertEqual(self.tap(view, "pj.model"), (True, None))
        msg, widgets = self.accepted(view)
        values = {w.look["label"]: (w.look["tone"], w.touch) for w in widgets.values() if w.row > 0}
        self.assertEqual(
            values, {"Opus": ("neutral", "tap"), "Sonnet": ("accept", "none"), "Haiku": ("neutral", "tap")}
        )
        self.assertEqual((msg["rows"], widgets["pj.title"].look["label"]), (3, "api · Worker model"))
        self.assertEqual(self.tap(view, "pj.v.haiku"), (True, None))  # staged, and back to the settings
        widgets = self.widgets(view)
        self.assertEqual(
            (widgets["pj.model"].look["text"], widgets["pj.model"].look["tone"]), ("Sonnet → Haiku, draft", "warning")
        )
        self.tap(view, "pj.model")
        values = {w.look["label"]: w.look["tone"] for w in self.widgets(view).values() if w.row > 0}
        self.assertEqual(values, {"Opus": "neutral", "Sonnet": "neutral", "Haiku": "warning"})

    def test_the_other_values_the_page_offers(self):
        view = self.view()
        self.open_project(view)
        for opener, values in (
            ("pj.validation", ["full", "pr", "local"]),
            ("pj.where", ["desktop-first", "laptop-first", "desktop", "laptop"]),
            ("pj.effort", ["default", "low", "medium", "high", "xhigh", "max"]),
        ):
            self.tap(view, opener)
            widgets = self.widgets(view)
            self.assertEqual(sorted(w for w in widgets if w.startswith("pj.v.")), sorted("pj.v." + v for v in values))
            self.tap(view, "pj.back")

    def test_a_tap_on_a_widget_the_page_no_longer_shows_does_nothing(self):
        view = self.view()
        self.assertEqual(self.tap(view, "pj.auto_.off"), (False, None))  # a settings view's, not drawn
        self.open_project(view)
        self.assertEqual(self.tap(view, "pj.next"), (False, None))
        # A project that left the registry closes its view.
        view.set_read(Read([project("site", "pr", False)]))
        self.assertEqual(self.ids(view, "Back"), [])
        self.assertEqual(len(self.ids(view, "site")), 1)

    def test_every_view_fits_the_protocol_with_the_longest_names_and_values(self):
        long = "x" * 60
        view = self.view(project(long, model=long, effort=long, where=long), *[project("p%d" % i) for i in range(11)])
        self.accepted(view)
        self.tap(view, "pj.next")
        self.accepted(view)
        view.offset = 0
        self.open_project(view, "x" * 31 + "…")
        self.tap(view, self.preset(view, "Refine"))
        self.accepted(view)
        for opener in ("pj.validation", "pj.model", "pj.where", "pj.effort"):
            self.tap(view, opener)
            for w in self.widgets(view).values():
                self.assertLessEqual(len(w.look.get("label", "")), 32)
            self.tap(view, "pj.back")

    def test_before_the_first_read_and_with_no_projects(self):
        view = pages.Projects()
        self.assertEqual(self.accepted(view)[0]["text"], "reading firstmate…")
        view.set_read(Read([]))
        self.assertEqual([w.look["label"] for w in self.widgets(view).values()], ["No projects"])
        self.assertEqual(view.messages()[0]["page"], "projects")


if __name__ == "__main__":
    unittest.main()
