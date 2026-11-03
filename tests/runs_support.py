"""What the Runs page's tests share: a fake no-mistakes CLI (a script in a
temporary directory, so the real client runs it), an in-memory fake of the
client for the loop, and builders of runs, details and scans.

The fake CLI knows only the read-only commands the app may run; any other
(axi run, respond, abort, daemon ...) is recorded and exits 2, so a test
sees it. Nothing here talks to a real no-mistakes, repository or daemon.
"""

import json
import os
import threading

from agents_support import write_json, write_script

from screenpad_agents.nomistakes import Detail, NoMistakesError, NotARepo, Run, Step
from screenpad_agents.runs import Copy, Project, Scan

ID = "01M6GNTQTCC9X19MXGM8EE4B%02d"


def run_id(n):
    return ID % n


def run_row(n, branch, status="completed", pr=None):
    """One run as the fake's state lists it."""
    return {"id": run_id(n), "branch": branch, "status": status, "head": "a4d609fe", "pr": pr}


def detail_state(branch, status="running", steps=(), parked=None, findings="none", outcome=None, error=None):
    """One run's detail as the fake's state holds it: steps are
    (step, status, findings, duration_ms)."""
    return {
        "branch": branch,
        "status": status,
        "steps": [list(s) for s in steps],
        "parked": parked,
        "findings": findings,
        "outcome": outcome,
        "error": error,
    }


def fake_no_mistakes(directory):
    """A no-mistakes stand-in reading nm.json next to it:

      dirs:    {directory: {"repo", "branch", "run"} or "not-init"}
      runs:    {repo: [run_row ...]}
      details: {run id: detail_state}
      rounds:  {run id: {step: [{"id", "severity"}]}}

    It prints TOON shaped like no-mistakes 1.106's for axi (in a dir),
    axi status (in a dir, or --run <id>) and axi rounds --json, records
    each call's arguments and cwd in nm-calls.jsonl, and exits 2 on any
    other command."""
    write_json(os.path.join(directory, "nm.json"), {"dirs": {}, "runs": {}, "details": {}, "rounds": {}})
    return write_script(
        os.path.join(directory, "no-mistakes"),
        """
        import json, os, sys
        here = os.path.dirname(os.path.abspath(__file__))
        args = sys.argv[1:]
        with open(os.path.join(here, "nm-calls.jsonl"), "a") as f:
            f.write(json.dumps({"args": args, "cwd": os.getcwd()}) + "\\n")
        with open(os.path.join(here, "nm.json")) as f:
            state = json.load(f)
        if state == "hang":
            import time
            time.sleep(30)
        def q(v):
            if v is None:
                return '""'
            quote = any(c in str(v) for c in ',"') or str(v)[:1].isdigit()
            return json.dumps(v) if quote else str(v)
        def here_dir():
            d = state["dirs"].get(os.getcwd())
            if d is None:
                print("error: not in a git repository")
                sys.exit(1)
            if d == "not-init":
                print("error: repo not initialized (run 'no-mistakes init' first)")
                print("help[1]: Run `no-mistakes init` to set up the gate in this repository")
                sys.exit(1)
            return d
        def table(runs, indent=""):
            print("%scount: %d of %d total" % (indent, len(runs), len(runs)))
            print("%sruns[%d]{id,branch,status,head,pr}:" % (indent, len(runs)))
            for r in runs:
                print(indent + "  " + ",".join(q(r.get(k)) for k in ("id", "branch", "status", "head", "pr")))
        def run_block(key, rid):
            d = state["details"][rid]
            print(key + ":")
            print('  id: "%s"' % rid)
            print("  branch: " + d["branch"])
            print("  status: " + d["status"])
            if d.get("parked"):
                print("  awaiting_agent: " + d["parked"])
            print("  head: a4d609fe")
            print("  findings: " + d.get("findings", "none"))
            print("  steps[%d]{step,status,findings,duration_ms}:" % len(d["steps"]))
            for s in d["steps"]:
                print("    " + ",".join(str(x) for x in s))
            if d.get("outcome"):
                print("outcome: " + d["outcome"])
            if d.get("error"):
                print("error: " + json.dumps(d["error"]))
        if args == ["axi"]:
            d = here_dir()
            print("bin: ~/.no-mistakes/bin/no-mistakes")
            print('description: "Validate your code changes"')
            print("repo: " + d["repo"])
            print("current_branch: unknown")
            print("daemon: running")
            table(state["runs"].get(d["repo"], []))
            print('help[1]: "Run `no-mistakes axi run --intent ...` to validate your changes"')
        elif args == ["axi", "status"]:
            d = here_dir()
            print("current_branch: " + (d.get("branch") or "unknown"))
            if d.get("run"):
                run_block("run", d["run"])
            else:
                print("runs_on_current_branch: 0")
                table(state["runs"].get(d["repo"], []))
        elif args[:3] == ["axi", "status", "--run"] and len(args) == 4:
            if args[3] not in state["details"]:
                print('error: "run \\\\"%s\\\\" not found"' % args[3])
                sys.exit(1)
            print("current_branch: main")
            run_block("other_branch_run", args[3])
        elif args[:3] == ["axi", "rounds", "--run"] and args[4:5] == ["--step"] and args[6:] == ["--json"]:
            found = state["rounds"].get(args[3], {}).get(args[5], [])
            rounds = [{"round": 1, "findings": found}] if found else []
            print(json.dumps({"schema_version": 1, "run_id": args[3], "step": args[5], "rounds": rounds}))
        else:
            print("fake no-mistakes: refused %s" % args, file=sys.stderr)
            sys.exit(2)
        """,
    )


class FakeNoMistakes:
    """The no-mistakes client for the loop: dirs maps a directory to
    (repo, branch, run id) or NotARepo; runs maps a repo to its Runs;
    details maps a run id to its Detail; rounds maps (run id, step) to its
    findings. Each call is counted in calls."""

    def __init__(self):
        self.dirs = {}
        self.runs = {}
        self.details = {}
        self.rounds = {}
        self.calls = []
        self.error = None
        self.lock = threading.Lock()

    def _dir(self, what, directory):
        with self.lock:
            self.calls.append((what, directory))
            if self.error:
                raise NoMistakesError(self.error)
            found = self.dirs.get(directory)
        if found is None:
            raise NotARepo("not in a git repository")
        return found

    def listing(self, directory):
        repo, _, _ = self._dir("listing", directory)
        with self.lock:
            return repo, list(self.runs.get(repo, []))

    def current(self, directory):
        _, branch, rid = self._dir("current", directory)
        return branch, rid

    def detail(self, rid):
        with self.lock:
            self.calls.append(("detail", rid))
            if rid not in self.details:
                raise NoMistakesError('no-mistakes axi status --run %s: run "%s" not found' % (rid, rid))
            d = self.details[rid]
            copy = Detail(d.id, d.branch, d.status, d.steps, d.parked, d.summary, d.outcome, d.error, d.pr)
            return copy

    def findings(self, rid, step):
        with self.lock:
            self.calls.append(("findings", rid, step))
            return list(self.rounds.get((rid, step), []))

    def count(self, what):
        with self.lock:
            return sum(1 for c in self.calls if c[0] == what)


STEPS = ("intent", "rebase", "review", "test", "document", "lint", "push", "pr", "ci")


def steps(at="review", status="running", findings=0):
    """A run's steps: those before at completed, at with status, the rest pending."""
    out, seen = [], False
    for name in STEPS:
        if name == at:
            out.append(Step(name, status, findings, 0 if status in ("running", "fixing") else 4000))
            seen = True
        else:
            out.append(Step(name, "pending" if seen else "completed", 0, 0 if seen else 1500))
    return out


def detail(n, branch, status="running", at="review", step_status="running", parked=False, findings=0):
    return Detail(run_id(n), branch, status, steps(at, step_status, findings), parked)


def run(n, branch, status="completed", pr=None):
    return Run(run_id(n), branch, status, "a4d609fe", pr)


def scan(projects, copies=(), details=()):
    """A Scan: projects are (repo, [Run]); copies (path, branch, run n);
    details Details."""
    return Scan(
        [Project(repo, runs) for repo, runs in projects],
        [Copy(path, branch, run_id(n)) for path, branch, n in copies],
        {d.id: d for d in details},
    )


def read_nm_calls(directory):
    try:
        with open(os.path.join(directory, "nm-calls.jsonl")) as f:
            return [json.loads(line) for line in f]
    except FileNotFoundError:
        return []
