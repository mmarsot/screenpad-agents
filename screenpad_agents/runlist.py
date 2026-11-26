"""The Runs page's two lists: the projects, and one project's runs.

Pure, and called by runs.py with its Runs: the grid of project cells (a
project's name, its machine's label when there are remote machines, and how
many runs are going on now; a tap opens the project), and a project's view
(Back, its title, then every one of its runs, the active ones first and the
newest first within each; a tap opens the run's card, runcard.py). Both are
grids six columns wide in cells two columns wide, three to a row, like the
Projects page's list, and both take pages: the projects after the rows a
remote machine that could not be read takes, with Previous, the span and Next
in the row under them; a project's runs under its header, whose last two
cells are Previous and Next. A page's order is the scan's own, so a turn
never reshuffles it. Both always have MAX_ROWS rows, so a cell is the same
size whatever the number of items on the page: the positions a page does not
fill are empty, nothing drawn and nothing to touch. A widget's id names what a tap on it means (Runs keeps
the maps of the page last built), and a tap on an id no longer drawn does
nothing.
"""

import hashlib

from screenpad_app import clip
from screenpad_app.common import MAX_BADGE, MAX_LABEL, MAX_ROWS, MAX_TEXT

from .common import BACK_ICON, icon
from .runmodel import widget_id

COLUMNS, MIN_ROWS = 6, 2
PER_ROW, CELL = 3, 2
DOWN_ROWS = MAX_ROWS - 2  # the rows that say a machine could not be read
UP = "runs.up"
RUNS_TITLE = "runs.title"


def project_id(project):
    return widget_id("proj.", hashlib.sha256(project.key.encode()).hexdigest()[:16])


def says(runs, project, views):
    """(text, tone, badge) of a project: its error, or the warning of more
    than one active run for one agent, copy or branch, or its machine, how
    many runs are active and how many need the captain."""
    active = [v for v in views if v.run.active]
    doubled = [v for v in active if v.duplicate]
    if project.error:
        return clip(project.error, MAX_TEXT), "warning", None
    if doubled:
        text = "%d active runs for %s: at most one each" % (len(doubled), doubled[0].name())
        return clip(text, MAX_TEXT), "reject", clip(str(len(doubled)), MAX_BADGE)
    attention = sum(v.attention for v in views)
    parts = ["%d active" % len(active) if active else "no active run"]
    parts += ["%d need%s you" % (attention, "s" if attention == 1 else "")] if attention else []
    parts += [] if views else ["no runs yet"]
    parts = [runs.label(project)] + parts if runs.machines else parts
    return " · ".join(parts), "warning" if attention else "neutral", None


def cell(id, col, row, cols=1, **look):
    return dict(look, id=id, col=col, row=row, cols=cols)


def span(offset, per, total, what=""):
    return "%d-%d of %d%s" % (offset + 1, min(offset + per, total), total, what)


# --- the projects -------------------------------------------------------------


def grid(runs, views):
    """(widgets, rows) of the projects page. Fills runs._projects (a
    project cell's key) and runs._turns."""
    runs._runs, runs._turns, runs._projects = {}, {}, {}
    projects = runs.scan.projects if runs.scan else []
    # A machine that could not be read comes first, a row of its own.
    # At most DOWN_ROWS of them, so a row of projects and the pager still fit.
    downs = list(runs.down.items())
    if len(downs) > DOWN_ROWS:
        rest = downs[DOWN_ROWS - 1 :]
        more = ("%d more machines not read" % len(rest), ", ".join(name for name, _ in rest))
        downs = downs[: DOWN_ROWS - 1] + [("_more", more)]
    cells = [down(row, name, *why) for row, (name, why) in enumerate(downs)]
    if not projects and not cells:
        return [note(runs)], MIN_ROWS
    top = len(cells)
    room = MAX_ROWS - top
    per = PER_ROW * (room - 1)  # the last row of the rows left is the pager's
    paged = len(projects) > per
    total = len(projects)
    if paged:
        runs.offset = min(runs.offset, (total - 1) // per * per) // per * per
        projects = projects[runs.offset : runs.offset + per]
    else:
        runs.offset = 0
    for i, p in enumerate(projects):
        text, tone, badge = says(runs, p, views[p.key])
        wid = project_id(p)
        runs._projects[wid] = p.key
        look = {"label": clip(p.name, MAX_LABEL), "text": text, "tone": tone}
        cells.append(
            cell(wid, CELL * (i % PER_ROW), top + i // PER_ROW, CELL, **look, **({"badge": badge} if badge else {}))
        )
    if paged:
        cells += pager(runs, top + room - 1, per, total)
    return cells, MAX_ROWS


def pager(runs, row, per, total, offset=None, prefix="runs."):
    """Previous, the span shown and Next, in the row under the projects."""
    offset = runs.offset if offset is None else offset
    last = offset + per >= total
    out = [
        cell(prefix + "prev", 0, row, CELL, label="Previous"),
        cell(prefix + "span", 2, row, CELL, label=span(offset, per, total), touch="none"),
        cell(prefix + "next", 4, row, CELL, label="Next"),
    ]
    if offset:
        runs._turns[prefix + "prev"] = -per
    else:
        out[0]["touch"] = "none"
    if last:
        out[2]["touch"] = "none"
    else:
        runs._turns[prefix + "next"] = per
    return out


def down(row, name, notice, why):
    """The row that says a remote machine could not be read, and why: its
    runs are not on the page, so it never looks like it has none."""
    wid = widget_id("runs.down.", name)
    return cell(
        wid, 0, row, COLUMNS, label=clip(notice, MAX_LABEL), text=clip(why, MAX_TEXT), tone="reject", touch="none"
    )


def note(runs):
    if runs.error:
        look = {"label": "no-mistakes unavailable", "text": clip(runs.error, MAX_TEXT)}
    elif runs.scan is None:
        look = {"label": "Reading no-mistakes…"}
    else:
        look = {"label": "No projects", "text": "no-mistakes watches none of the repos configured or found"}
    return cell("runs.note", 0, 0, COLUMNS, touch="none", **look)


# --- a project's runs ---------------------------------------------------------

RUN_ROWS = MAX_ROWS - 1
PER_PROJECT = PER_ROW * RUN_ROWS


def ordered(views):
    """A project's runs, the active ones first, each group as the scan has them."""
    return [v for v in views if v.run.active] + [v for v in views if not v.run.active]


def project_view(runs, project, views):
    """(widgets, rows) of project's page: Back, its title and its runs."""
    runs._runs, runs._turns, runs._projects = {}, {}, {}
    listed = ordered(views)
    total = len(listed)
    paged = total > PER_PROJECT
    if paged:
        runs.run_offset = min(runs.run_offset, (total - 1) // PER_PROJECT * PER_PROJECT) // PER_PROJECT * PER_PROJECT
        listed = listed[runs.run_offset : runs.run_offset + PER_PROJECT]
    else:
        runs.run_offset = 0
    text, tone, badge = says(runs, project, views)
    if paged:
        text = span(runs.run_offset, PER_PROJECT, total, " runs")
    title = cell(
        RUNS_TITLE, 1, 0, 3 if paged else 5, label=clip(project.name, MAX_LABEL), text=text, tone=tone, touch="none"
    )
    if badge:
        title["badge"] = badge
    out = [cell(UP, 0, 0, 1, label="Back", icon=icon(BACK_ICON)), title]
    if paged:
        last = runs.run_offset + PER_PROJECT >= total
        out += [
            cell("runs.rprev", 4, 0, 1, label="Prev"),
            cell("runs.rnext", 5, 0, 1, label="Next"),
        ]
        if runs.run_offset:
            runs._turns["runs.rprev"] = -PER_PROJECT
        else:
            out[-2]["touch"] = "none"
        if last:
            out[-1]["touch"] = "none"
        else:
            runs._turns["runs.rnext"] = PER_PROJECT
    if not listed:
        out.append(cell("runs.none", 0, 1, COLUMNS, label="No runs yet", touch="none"))
    for i, v in enumerate(listed):
        wid = widget_id("run.", v.run.id)
        runs._runs[wid] = v.run.id
        look = {"label": clip(v.name(), MAX_LABEL), "text": clip(v.said(), MAX_TEXT), "tone": v.tone()}
        if v.duplicate:
            look["badge"] = "2+"
        out.append(cell(wid, CELL * (i % PER_ROW), 1 + i // PER_ROW, CELL, **look))
    return out, MAX_ROWS
