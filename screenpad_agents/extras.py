"""The Projects page and the usage tile, as the app's loop uses them.

One object for the two optional parts that read their own sources in
threads of their own, so app.py only hands them what happened:

  - the Projects page (projectpage.py, projectwatch.py), with [firstmate]:
    the page, its thread, and what a tap on it means: a change is staged
    in the draft, and Validate asks firstmate for all of them in one note;
  - the usage tile and the Limits page (usage.py, usagepage.py,
    usagewatch.py), with [usage]: the tile and the page, their thread, and
    Details, which opens the terminal viewer.
"""

from . import usagepage
from .common import LIMITS_PAGE, PROJECTS_PAGE, USAGE_TILE
from .projectmodel import note_text
from .projectpage import Projects
from .projectwatch import ProjectsWatch
from .usage import Usage
from .usagewatch import UsageWatch


class Extras:
    def __init__(self, config, firstmate, post, log, tell, clock, usage_run=None, usage_launcher=None):
        self.log, self.tell = log, tell
        self.projects = self.projects_watch = self.usage = self.usage_watch = None
        if firstmate is not None and config.home:
            self.projects = Projects(clock)
            self.projects_watch = ProjectsWatch(config.home, firstmate, post, clock)
        if config.usage is not None:
            self.usage = Usage()
            runs = {"run": usage_run} if usage_run is not None else {}
            launches = {"launcher": usage_launcher} if usage_launcher is not None else {}
            self.usage_watch = UsageWatch(config.usage, post, clock, **runs, **launches, home=config.home)

    def tiles(self):
        return [USAGE_TILE] if self.usage else []

    def workers(self):
        found = (("projects", self.projects_watch), ("usage", self.usage_watch))
        return [(name, watch.worker) for name, watch in found if watch is not None]

    def showing(self, connected):
        for watch in (self.projects_watch, self.usage_watch):
            if watch is not None:
                watch.showing(connected)

    def pages(self):
        """How many pages these give the apps page (the protocol limits an app's)."""
        return (1 if self.projects else 0) + (1 if self.usage else 0)

    def messages(self):
        limits = [self.usage.tile(), usagepage.page(self.usage)] if self.usage else []
        return (self.projects.messages() if self.projects else []) + limits

    def stop(self):
        for watch in (self.projects_watch, self.usage_watch):
            if watch is not None:
                watch.stop()

    # --- what the threads say ------------------------------------------------

    def result(self, what, *rest):
        """Take one of the threads' results in: None when it is not one of
        these, else whether what the bar shows changed."""
        projects, watch = self.projects, self.projects_watch
        if projects is None or watch is None:
            projects = watch = None
        if what == "projects" and projects and watch:
            projects.set_read(rest[0])
            watch.pending(projects.has_pending())
            self.tell("projects", rest[0].error or rest[0].settings_error)
            return True
        if what == "project-note" and projects and watch:
            changes, error = rest
            if error:
                self.log("firstmate was not told: %s: %s" % (note_text(changes), error))
                projects.failed(changes, error)
                watch.pending(projects.has_pending())
            else:
                self.log("asked firstmate: %s" % note_text(changes))
            return True
        if what == "usage" and self.usage:
            providers, error = rest
            self.tell("quota-axi", error)
            return self.usage.set(providers, error)
        if what == "usage-view":
            self.log("the usage report did not open: %s" % rest[0] if rest[0] else "opened the usage report")
            return False
        return None

    # --- touches ---------------------------------------------------------------

    def touch(self, page, widget):
        """A tap on a page: whether the page changed. A tap on the Projects
        page changes its view, or asks firstmate for a change of a project's
        settings; Details on the Limits page opens the viewer."""
        if page == LIMITS_PAGE:
            if widget == usagepage.DETAILS and self.usage_watch is not None:
                self.usage_watch.open_view()
            return False
        if page != PROJECTS_PAGE or self.projects is None or self.projects_watch is None:
            return False
        changed, changes = self.projects.touch(widget)
        if changes:
            self.projects_watch.pending(True)
            self.projects_watch.send(changes)
        return changed

    def tap_tile(self, tile):
        """A tap on a tile: the usage tile opens the viewer, as Details does."""
        if tile == USAGE_TILE and self.usage_watch is not None:
            self.usage_watch.open_view()
