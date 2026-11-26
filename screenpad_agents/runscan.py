"""One read of a machine's no-mistakes projects and copies: a runs.Scan.

runwatch.py reads this machine with it and remotewatch.py a remote one
(over ssh): the same read-only commands (nomistakes.py), whichever client
runs them. In every directory (the configured repos, firstmate's clones
and its tasks' worktrees) no-mistakes names the repository (axi), and in
every copy (those, and the Herdr agents' cwds) it resolves the current
branch's run (axi status); each active run is then read in detail
(axi status --run).
"""

import os

from . import runmodel as model
from .nomistakes import NoMistakesError, NotARepo, Unreachable


def read(client, configured=(), clones=(), worktrees=(), cwds=(), machine=None, tasks=None, real=os.path.realpath):
    """A Scan of client's projects: configured repos (shown even when
    unreadable), then clones and worktrees; copies are the configured repos,
    worktrees and cwds with a run. machine tags the projects and copies of a
    remote machine, tasks gives its worktrees' task ids by path, and real
    resolves a path (a remote machine's are not this machine's to resolve).
    NoMistakesError when no project could be read at all; Unreachable at
    once when the machine cannot be reached."""
    configured, worktrees = list(configured), list(worktrees)
    projects: dict = {}
    seen, errors = set(), []
    for d in configured + list(clones) + worktrees:
        resolved = real(d)
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            repo, listed = client.listing(d)
        except Unreachable:
            raise
        except NoMistakesError as e:
            if not isinstance(e, NotARepo):
                errors.append(str(e))
            if d in configured:
                projects.setdefault(resolved, model.Project(resolved, error=str(e), machine=machine))
            continue
        projects.setdefault(repo, model.Project(repo, listed, machine=machine))
    if errors and not any(p.error is None for p in projects.values()):
        raise NoMistakesError(errors[0])
    copies, looked = [], set()
    for d in configured + worktrees + list(cwds):
        resolved = real(d)
        if resolved in looked:
            continue
        looked.add(resolved)
        try:
            branch, run_id = client.current(d)
        except Unreachable:
            raise
        except NoMistakesError:
            continue
        if run_id is not None:
            copies.append(model.Copy(resolved, branch, run_id, machine, (tasks or {}).get(resolved)))
    details = {}
    for p in projects.values():
        for r in p.runs:
            if r.active:
                try:
                    details[r.id] = client.detail(r.id)
                except Unreachable:
                    raise
                except NoMistakesError:
                    pass
    return model.Scan(projects.values(), copies, details)
