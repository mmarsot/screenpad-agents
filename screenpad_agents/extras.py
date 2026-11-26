"""The Projects page and the usage tile, as the app's loop uses them.

One object for the two optional parts that read their own sources in
threads of their own, so app.py only hands them what happened:

  - the Projects page (projectpage.py, projectwatch.py), with [firstmate]:
    the page, its thread, and what a tap on it means: a change of a
    project's settings is asked of firstmate in a note;
  - the usage tile (usage.py, usagewatch.py), with [usage]: the tile, its
    thread, and the tap that opens quota-axi's full report.
"""

from .common import PROJECTS_PAGE, USAGE_TILE
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
            self.usage_watch = UsageWatch(config.usage, post, clock, **runs, **launches)

    def tiles(self):
        return [USAGE_TILE] if self.usage else []

    def workers(self):
        found = (("projects", self.projects_watch), ("usage", self.usage_watch))
        return [(name, watch.worker) for name, watch in found if watch is not None]

    def showing(self, connected):
        for watch in (self.projects_watch, self.usage_watch):
            if watch is not None:
                watch.showing(connected)

    def messages(self):
        return (self.projects.messages() if self.projects else []) + ([self.usage.tile()] if self.usage else [])

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
            change, error = rest
            if error:
                self.log("firstmate was not told: %s: %s" % (change.text(), error))
                projects.failed(change, error)
                watch.pending(projects.has_pending())
            else:
                self.log("asked firstmate: %s" % change.text())
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
        settings."""
        if page != PROJECTS_PAGE or self.projects is None or self.projects_watch is None:
            return False
        changed, change = self.projects.touch(widget)
        if change is not None:
            self.projects.ask(change)
            self.projects_watch.pending(True)
            self.projects_watch.send(change)
        return changed or change is not None

    def tap_tile(self, tile):
        """A tap on a tile: the usage tile opens quota-axi's full report."""
        if tile == USAGE_TILE and self.usage_watch is not None:
            self.usage_watch.open_view()
