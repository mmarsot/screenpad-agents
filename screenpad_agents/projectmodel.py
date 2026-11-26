"""The Projects page's data: firstmate's projects and their settings.

Owned by firstmate, read here and never written (docs/projects.md): the
registry, <home>/data/projects.md, gives each project its delivery mode and
auto-merge permission by its tags, and <home>/data/project-settings.toml the
other settings per project. Both are read as text, read-only, and tolerantly:
an unknown tag, table, key or value is ignored, and a key that is absent
means its default.

  - [no-mistakes] full no-mistakes validation, [direct-PR] a plain pull
    request, [local-only] no pull request; +yolo permits auto-merge;
  - preset, annotated_review, where, model and effort come from the settings
    file, per project, under [projects.<name>].

A change the captain asks for is a Change (project, setting, value) that the
app only sends to firstmate as a note; the page shows it pending until a
read of the files reflects it (reflects). Pure but for read(), which opens
the two files.
"""

import os
import re
import tomllib
from dataclasses import dataclass

REGISTRY = os.path.join("data", "projects.md")
SETTINGS = os.path.join("data", "project-settings.toml")

# A project's name in the registry, which is a directory name and a key of
# the settings file: nothing else is sent to firstmate in a note.
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
ROW = re.compile(r"-\s+(?P<name>\S+)(?:\s+\[(?P<tags>[^\]]*)\])?(?:\s+-\s+(?P<about>.*))?")
DELIVERY_TAGS = {"no-mistakes": "full", "direct-PR": "pr", "local-only": "local"}
YOLO = "+yolo"

# The presets, the bundle each is (docs/projects.md), and the words of the
# settings: key -> (label, [(value, label)]). A value read from the file
# that is none of these shows as it is and matches no button.
PRESETS = (("iterate", "Iterate"), ("refine", "Refine"))
VALIDATION = (("full", "Full validation"), ("pr", "Plain PR"), ("local", "Local only"))
ONOFF = ((True, "On"), (False, "Off"))
WHERE = (
    ("desktop-first", "Desktop first"),
    ("laptop-first", "Laptop first"),
    ("desktop", "Desktop only"),
    ("laptop", "Laptop only"),
)
MODELS = (("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku"))
EFFORTS = tuple((e, e.capitalize()) for e in ("default", "low", "medium", "high", "xhigh", "max"))
CHOICES: dict[str, tuple[str, tuple]] = {
    "preset": ("Preset", PRESETS),
    "validation": ("Validation", VALIDATION),
    "auto_merge": ("Auto-merge", ONOFF),
    "annotated": ("Annotated review", ONOFF),
    "where": ("Runs on", WHERE),
    "model": ("Worker model", MODELS),
    "effort": ("Worker effort", EFFORTS),
}
# What each setting reads as in the note that asks for it.
WORDS: dict[str, tuple[str, dict]] = {
    "preset": ("preset", {"iterate": "Iterate", "refine": "Refine"}),
    "validation": ("validation", {"full": "full no-mistakes", "pr": "plain PR", "local": "local only"}),
    "auto_merge": ("auto-merge", {True: "on", False: "off"}),
    "annotated": ("annotated review", {True: "on", False: "off"}),
    "where": ("where it runs", {v: label.lower() for v, label in WHERE}),
    "model": ("worker model", {v: v for v, _ in MODELS}),
    "effort": ("worker effort", {v: v for v, _ in EFFORTS}),
}
DEFAULTS = {"annotated": True, "where": "desktop-first", "model": "opus", "effort": "default"}


@dataclass(frozen=True)
class Project:
    """One project with its settings as the files give them now: delivery
    (full, pr, local, or None when the registry names none), auto_merge,
    the stored preset (None: none), annotated review, where it runs, the
    worker's model and effort."""

    name: str
    delivery: str | None
    auto_merge: bool
    preset: str | None
    annotated: bool
    where: str
    model: str
    effort: str

    def effective_preset(self):
        """The stored preset while the project's settings still are its
        bundle, else None: a preset the captain has since changed by hand
        is no longer the project's."""
        if self.preset == "iterate" and self.delivery == "full" and self.auto_merge:
            return "iterate"
        if self.preset == "refine" and self.delivery == "full" and not self.auto_merge and self.annotated:
            return "refine"
        return None

    def value(self, key):
        return self.effective_preset() if key == "preset" else getattr(self, "delivery" if key == "validation" else key)


@dataclass(frozen=True)
class Change:
    """A setting the captain asked firstmate to change: project, key (one of
    CHOICES) and value."""

    project: str
    key: str
    value: object

    def text(self):
        what, words = WORDS[self.key]
        return "ScreenPad Projects page: set %s %s to %s" % (self.project, what, words[self.value])


def reflects(project, change):
    """Whether project, as read now, has the setting change asks for."""
    return project.value(change.key) == change.value


class Read:
    """One read of the files: the projects (the registry's, archived ones
    left out), why the registry could not be read (error: then there are
    none), and why the settings file could not (the defaults then apply)."""

    def __init__(self, projects=(), error=None, settings_error=None):
        self.projects, self.error, self.settings_error = list(projects), error, settings_error

    def find(self, name):
        return next((p for p in self.projects if p.name == name), None)


def read(home):
    """The Read of firstmate's files under home."""
    try:
        with open(os.path.join(home, REGISTRY), encoding="utf-8", errors="replace") as f:
            rows = parse_registry(f.read())
    except OSError as e:
        return Read(error="cannot read %s: %s" % (REGISTRY, e.strerror))
    settings, problem = {}, None
    try:
        with open(os.path.join(home, SETTINGS), "rb") as f:
            settings = parse_settings(f.read().decode("utf-8", "replace"))
    except FileNotFoundError:
        pass
    except OSError as e:
        problem = "cannot read %s: %s" % (SETTINGS, e.strerror)
    except tomllib.TOMLDecodeError as e:
        problem = "%s: %s" % (SETTINGS, e)
    return Read([project(name, tags, settings.get(name, {})) for name, tags in rows], settings_error=problem)


def parse_registry(text):
    """[(name, tags)] of the active projects in the registry's text: a line
    `- <name> [<tags>] - <about>`; others, and archived projects (about
    starts with ARCHIVED), are skipped."""
    rows = []
    for line in text.splitlines():
        m = ROW.fullmatch(line.strip())
        if m is None or not NAME.fullmatch(m["name"]) or (m["about"] or "").startswith("ARCHIVED"):
            continue
        rows.append((m["name"], set((m["tags"] or "").split())))
    return rows


def parse_settings(text):
    """{project: {key: value}} of the valid settings in the file's text
    (under [projects.<name>]); a key or value that is not one is left out."""
    table = tomllib.loads(text).get("projects")
    out = {}
    for name, entry in (table if isinstance(table, dict) else {}).items():
        if not isinstance(entry, dict):
            continue
        found = {k: entry[k] for k in ("preset", "where", "model", "effort") if isinstance(entry.get(k), str)}
        found = {k: v for k, v in found.items() if v}
        if isinstance(entry.get("annotated_review"), bool):
            found["annotated"] = entry["annotated_review"]
        out[name] = found
    return out


def project(name, tags, settings):
    delivery = next((DELIVERY_TAGS[t] for t in sorted(tags) if t in DELIVERY_TAGS), None)
    merged = dict(DEFAULTS, **settings)
    return Project(
        name,
        delivery,
        YOLO in tags,
        merged.get("preset"),
        merged["annotated"],
        merged["where"],
        merged["model"],
        merged["effort"],
    )


def label(key, value):
    """A value's words on the page (the value as it is when it is not one
    of the setting's)."""
    return dict(CHOICES[key][1]).get(value, str(value))
