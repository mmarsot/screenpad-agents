"""no-mistakes: the pipeline runs of a repository, read and never driven.

The Runs page reads no-mistakes through its own agent interface, which
prints TOON (a compact, indented key: value text with tables), and only
through these read-only commands:

  no-mistakes axi                                    (run in a repo copy)
      the repository no-mistakes knows the copy as ("repo:") and its
      newest runs, runs[N]{id,branch,status,head,pr}
  no-mistakes axi status                             (run in a repo copy)
      the copy's current branch, and under "run:" that branch's active
      or newest run
  no-mistakes axi status --run <id>
      one run: its status, whether it is parked at a gate
      ("awaiting_agent"), its steps{step,status,findings,duration_ms},
      outcome and error
  no-mistakes axi rounds --run <id> --step <step> --json
      a step's review rounds, whose findings have an id and a severity

Nothing here starts, answers, aborts, retries or syncs a run, or touches the
daemon: NoMistakes has no method that would, and it runs no argument list
but these four shapes (read_only, test_only_read_only_commands_run).
"""

import json
import os
import re
import subprocess

from .common import NO_MISTAKES_TIMEOUT

# A run id as no-mistakes prints it (a ULID), and a step name.
RUN_ID = re.compile(r"[0-9A-Za-z]{10,64}")
STEP = re.compile(r"[a-z][a-z0-9_-]{0,63}")
# A run's statuses that end it; any other is a run still going.
FINISHED = ("completed", "failed", "cancelled", "checks_passed", "passed")
# What no-mistakes says in a directory it cannot watch.
NOT_A_REPO = ("not in a git repository", "not initialized")
# A TOON line: key, an optional [N] and {fields}, then its value if any.
HEADER = re.compile(r"(?P<key>[A-Za-z_][\w.-]*)(?:\[(?P<n>\d+)\](?:\{(?P<fields>[^}]*)\})?)?:(?: (?P<rest>.*))?$")


# A quoted TOON value: a JSON string.
QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"')


class NoMistakesError(Exception):
    pass


class NotARepo(NoMistakesError):
    """The directory is no repository no-mistakes watches."""


class Run:
    """One run as a repository's list gives it."""

    __slots__ = ("branch", "head", "id", "pr", "status")

    def __init__(self, id, branch, status, head=None, pr=None):
        self.id, self.branch, self.status, self.head, self.pr = id, branch, status, head, pr

    @property
    def active(self):
        return self.status not in FINISHED

    def __eq__(self, other):
        return isinstance(other, Run) and self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __repr__(self):
        return "Run(%r, %r, %r)" % (self.id, self.branch, self.status)

    def _key(self):
        return (self.id, self.branch, self.status, self.head, self.pr)


class Step:
    __slots__ = ("duration_ms", "findings", "name", "status")

    def __init__(self, name, status, findings=0, duration_ms=0):
        self.name, self.status, self.findings, self.duration_ms = name, status, findings, duration_ms

    def __eq__(self, other):
        return isinstance(other, Step) and self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def _key(self):
        return (self.name, self.status, self.findings, self.duration_ms)

    @property
    def waiting(self):
        """Parked for a decision: awaiting approval, or a fix's review."""
        return self.status.startswith("awaiting") or self.status == "fix_review"


class Detail:
    """One run in detail (axi status --run): its steps, whether it waits on
    a decision, how it ended; findings is filled in for the open card only,
    from the steps' rounds: (step, id, severity)."""

    __slots__ = ("branch", "error", "findings", "id", "outcome", "parked", "pr", "status", "steps", "summary")

    def __init__(self, id, branch, status, steps=(), parked=False, summary=None, outcome=None, error=None, pr=None):
        self.id, self.branch, self.status, self.steps = id, branch, status, list(steps)
        self.parked, self.summary, self.outcome, self.error, self.pr = parked, summary, outcome, error, pr
        self.findings: list = []

    def __eq__(self, other):
        return isinstance(other, Detail) and self._key() == other._key()

    def __hash__(self):
        return hash(self.id)

    def _key(self):
        keys = (self.id, self.branch, self.status, tuple(self.steps), self.parked, self.summary)
        return keys + (self.outcome, self.error, self.pr, tuple(self.findings))

    @property
    def waiting(self):
        """Waiting on a decision: parked at a gate, or a step awaiting one."""
        return self.status not in FINISHED and (self.parked or any(s.waiting for s in self.steps))

    def step(self):
        """The step the run is at (or ended on): the first one neither
        done nor still to come, None when there is none."""
        return next((s for s in self.steps if s.status not in ("completed", "skipped", "pending")), None)


class NoMistakes:
    """no-mistakes' CLI: command is the program (and any wrapper words)."""

    def __init__(self, command, run=subprocess.run, timeout=NO_MISTAKES_TIMEOUT):
        self.command, self._run, self.timeout = list(command), run, timeout

    def listing(self, directory):
        """(the repository no-mistakes knows directory as, its newest runs);
        NotARepo when it watches none there."""
        model = self._call(["axi"], directory)
        repo = model.get("repo")
        if not isinstance(repo, str) or not os.path.isabs(repo):
            raise NoMistakesError("no-mistakes axi named no repository")
        runs = []
        for row in _rows(model, "runs"):
            run = _run(row)
            if run is not None:
                runs.append(run)
        return repo, runs

    def current(self, directory):
        """(the copy's current branch or None, the id of that branch's
        active or newest run or None)."""
        model = self._call(["axi", "status"], directory)
        branch = _text(model.get("current_branch"))
        run = model.get("run")
        run_id = _text(run.get("id")) if isinstance(run, dict) else None
        return (None if branch == "unknown" else branch), (run_id if run_id and RUN_ID.fullmatch(run_id) else None)

    def detail(self, run_id):
        """One run in detail; NoMistakesError when no-mistakes has none."""
        _check(run_id, RUN_ID, "run id")
        model = self._call(["axi", "status", "--run", run_id])
        run = model.get("run") or model.get("other_branch_run")
        if not isinstance(run, dict) or _text(run.get("id")) != run_id:
            raise NoMistakesError("no-mistakes axi status has no run %s" % run_id)
        steps = [
            Step(row.get("step", "?"), row.get("status", "?"), _int(row.get("findings")), _int(row.get("duration_ms")))
            for row in _rows(run, "steps")
        ]
        summary = _text(run.get("findings"))
        detail = Detail(run_id, _text(run.get("branch")) or "?", _text(run.get("status")) or "unknown", steps)
        detail.parked = bool(_text(run.get("awaiting_agent")))
        detail.summary = None if summary == "none" else summary
        detail.outcome, detail.error = _text(model.get("outcome")), _text(model.get("error"))
        detail.pr = _text(run.get("pr"))
        return detail

    def findings(self, run_id, step):
        """The findings of step's last round: [(id, severity)]."""
        _check(run_id, RUN_ID, "run id")
        _check(step, STEP, "step")
        argv = self.command + ["axi", "rounds", "--run", run_id, "--step", step, "--json"]
        done = self._exec(argv, None)
        if done.returncode != 0:
            why = (done.stderr or done.stdout or "").strip().splitlines()
            raise NoMistakesError("no-mistakes axi rounds: %s" % (why[-1] if why else "exit %d" % done.returncode))
        try:
            doc = json.loads(done.stdout or "")
        except ValueError:
            raise NoMistakesError("no-mistakes axi rounds printed no JSON")
        rounds = doc.get("rounds") if isinstance(doc, dict) else None
        last = rounds[-1] if isinstance(rounds, list) and rounds and isinstance(rounds[-1], dict) else {}
        out = []
        for f in last.get("findings") or []:
            if isinstance(f, dict) and isinstance(f.get("id"), str):
                out.append((f["id"], f.get("severity") if isinstance(f.get("severity"), str) else "?"))
        return out

    def _call(self, words, cwd=None):
        """Run one of the read-only axi commands (in cwd); its TOON parsed."""
        done = self._exec(self.command + words, cwd)
        try:
            model = toon(done.stdout or "")
        except ValueError:
            raise NoMistakesError("no-mistakes %s printed no TOON" % " ".join(words))
        if done.returncode != 0 or ("error" in model and "run" not in model and "other_branch_run" not in model):
            why = _text(model.get("error")) or (done.stderr or "").strip() or "exit %d" % done.returncode
            why = why.splitlines()[-1] if why.splitlines() else why
            if any(n in why for n in NOT_A_REPO):
                raise NotARepo(why)
            raise NoMistakesError("no-mistakes %s: %s" % (" ".join(words), why))
        return model

    def _exec(self, argv, cwd):
        words = argv[len(self.command) :]
        if not read_only(words):
            raise NoMistakesError("not a read-only no-mistakes command: %s" % " ".join(words))
        try:
            return self._run(
                argv, capture_output=True, text=True, timeout=self.timeout, stdin=subprocess.DEVNULL, cwd=cwd
            )
        except OSError as e:
            if cwd is not None and not os.path.isdir(cwd):
                raise NotARepo("%s is not a directory" % cwd)
            raise NoMistakesError("%s: %s" % (self.command[0], e.strerror))
        except subprocess.TimeoutExpired:
            raise NoMistakesError("no-mistakes %s gave no answer in %g s" % (" ".join(words[:2]), self.timeout))


def read_only(words):
    """True for the commands this client runs (the words after the
    program), and only those: axi, axi status, axi status --run <id>, and
    axi rounds --run <id> --step <step> --json."""
    if words in (["axi"], ["axi", "status"]):
        return True
    if len(words) == 4 and words[:3] == ["axi", "status", "--run"]:
        return True
    return len(words) == 7 and words[:3] == ["axi", "rounds", "--run"] and words[4] == "--step" and words[6] == "--json"


def toon(text):
    """The keys of a TOON document as a dict: scalars as text, nested
    objects as dicts, key[N]{fields}: tables as lists of dicts and
    key[N]: a,b lists as lists. ValueError when a quoted value is broken."""
    lines = [(len(raw) - len(raw.lstrip(" ")), raw.strip()) for raw in text.splitlines() if raw.strip()]
    out, _ = _block(lines, 0, lines[0][0] if lines else 0)
    return out


def _block(lines, i, indent):
    out: dict = {}
    while i < len(lines):
        ind, body = lines[i]
        if ind < indent:
            break
        i += 1
        m = HEADER.match(body) if ind == indent else None
        if m is None:
            continue
        key, rest = m["key"], m["rest"]
        if m["n"] is not None and m["fields"] is not None:
            names = _split(m["fields"])
            rows = []
            while i < len(lines) and lines[i][0] > indent:
                rows.append(dict(zip(names, _split(lines[i][1]), strict=False)))
                i += 1
            out[key] = rows
        elif m["n"] is not None:
            out[key] = _split(rest) if rest else []
        elif not rest:
            deeper = lines[i][0] if i < len(lines) and lines[i][0] > indent else None
            out[key], i = _block(lines, i, deeper) if deeper is not None else ({}, i)
        else:
            out[key] = _split(rest)[0] if rest.startswith('"') else rest
    return out, i


def _split(text):
    """The comma-separated values of a TOON row, quoted ones decoded."""
    out, i = [], 0
    while True:
        if text.startswith('"', i):
            m = QUOTED.match(text, i)
            if m is None:
                raise ValueError("an unterminated quoted value")
            value, i = json.loads(m.group()), m.end()
        else:
            j = text.find(",", i)
            j = len(text) if j < 0 else j
            value, i = text[i:j].strip(), j
        out.append(value)
        j = text.find(",", i)
        if j < 0:
            return out
        i = j + 1


def _rows(model, key):
    rows = model.get(key) if isinstance(model, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _run(row):
    run_id, branch, status = (_text(row.get(k)) for k in ("id", "branch", "status"))
    if not run_id or not RUN_ID.fullmatch(run_id) or not branch or not status:
        return None
    return Run(run_id, branch, status, _text(row.get("head")), _text(row.get("pr")))


def _check(value, pattern, what):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise NoMistakesError("not a no-mistakes %s: %r" % (what, value))


def _text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
