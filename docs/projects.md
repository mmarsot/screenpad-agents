# The Projects page

**Projects** (`projects`) is a page of the [agent app](agents.md) for the touch bar: firstmate's projects, each with the settings that decide how its work is done, switchable with a tap. It replaces the Agents page on the bar: the Agents page is still there, [one level down](agents.md#the-agents-page).

It needs `[firstmate]` in `agents.toml` (the page reads firstmate's home) and nothing else. Without `[firstmate]` there is no Projects page.

The settings are **firstmate's, not the app's**. The app reads them and asks firstmate to change them, and never writes them itself: your choices are staged on the page as a **draft**, **Validate** sends firstmate one note through its capture surface with all of them, firstmate applies it and records it, and the page shows the changes as pending until it can read them back. Nothing is sent before Validate. [What the app reads and writes](#what-the-app-reads-and-writes) is below.

## What it shows

| View | What it shows |
|---|---|
| **The list** | three projects to a page, a row each: its name and a line of its settings (`validated · auto-merge · desktop first · opus`), the two presets, **Iterate** and **Refine** (the project's own is green, a drafted one amber), and **Settings**. Under them, **Previous**, the span (`1-3 of 8`) and **Next** (with more than three projects), **Discard** and **Validate**. A tap on the name or on Settings opens the project |
| **A project's settings** | Back, the project's name and line, the presets, six settings, each in a large cell with its value, and under them the draft in words with **Discard** and **Validate** |
| **A setting's values** | large buttons, one per value, the current one green; a tap stages that value and returns to the project's settings |

Auto-merge and Annotated review switch with one tap (the cell shows the value, a tap stages the other); Validation, Runs on, Worker model and Worker effort open their values. The cells are large (a cell of the project's view is two columns wide), the text is short, and nothing on the page moves by itself: the page changes when you tap, when firstmate's files do, and when a change you asked for is there.

A project is one line of firstmate's registry that is not archived (the line's description does not start with `ARCHIVED`).

## The settings

| Setting | Values | Where it is read from |
|---|---|---|
| **Preset** | **Iterate**: validation on, auto-merge, no milestone stops. **Refine**: validation on, the captain merges, annotated review | `preset` of the settings file |
| **Validation** | **Full validation** (the whole [no-mistakes](https://github.com/kunchenguid/no-mistakes) pipeline), **Plain PR** (a pull request, no pipeline), **Local only** (no pull request) | the registry's tag: `[no-mistakes]`, `[direct-PR]`, `[local-only]` |
| **Auto-merge** | On or Off: whether firstmate may merge the project's pull request | the registry's `+yolo` tag |
| **Annotated review** | On (the default) or Off: a change ready for review is reviewed with line comments | `annotated_review` of the settings file |
| **Runs on** | **Desktop first** (the default: both machines, the desktop preferred), **Laptop first**, **Desktop only**, **Laptop only** | `where` of the settings file |
| **Worker model** | **Opus** (the default), **Sonnet**, **Haiku** | `model` of the settings file |
| **Worker effort** | **Default**, **Low**, **Medium**, **High**, **Xhigh**, **Max** | `effort` of the settings file |

There is no spend allowance and no post-merge digest setting.

A preset is a **bundle**: tapping **Refine** asks firstmate to turn validation on, auto-merge off and annotated review on, and to record `preset = "refine"`. The page lights a preset only while its bundle still holds (`preset` is recorded, and the project's validation, auto-merge and annotated review are the bundle's): once you change a single setting by hand the project has no preset, and neither button is lit. A project with no recorded preset has none either, however its tags read: the app never guesses one.

**Defaults are permissive, and only for future projects**: a key absent from the settings file means the default of the table above (annotated review on, desktop first, Opus, default effort), and a project that exists keeps the settings it has. Validation and auto-merge have no default in the app: they are the registry's tags, and a project with none of the three delivery tags shows **delivery unknown**.

## Staging, then Validate

A tap on a preset or a value **stages** it in the draft and sends nothing. The change shows amber: its cell reads `On → Off, draft`, the project's row says `draft: Refine`, the preset button turns amber, and the page's entry in the home list says `2 projects · 3 to validate` with the number of changes as a badge. Staging the value a setting already has takes it back out of the draft; **Discard** drops the whole draft. A preset staged also changes what the project's cells show (Refine turns Auto-merge to Off in the draft), and a single setting staged after it overrides the bundle.

**Validate** sends firstmate **one** note with **every** drafted change of **every** project, with its capture surface:

```sh
FM_HOME=<home> <code>/bin/fm-inbox.sh note --json --request-id <id> -- '<text>'
```

with a request id of its own for each validation (so a retry of a note that failed never queues a second), and a text that lists the changes, a preset first, projects in the registry's order, separated by semicolons:

```text
ScreenPad Projects page: set api preset to Refine; set api where it runs to laptop first; set site worker model to sonnet
```

Each change is `set <project> <setting> to <value>`, with the settings' words:

| Setting | In the note |
|---|---|
| Preset | `preset to Iterate`, `preset to Refine` |
| Validation | `validation to full no-mistakes`, `plain PR`, `local only` |
| Auto-merge | `auto-merge to on`, `off` |
| Annotated review | `annotated review to on`, `off` |
| Runs on | `where it runs to desktop first`, `laptop first`, `desktop only`, `laptop only` |
| Worker model | `worker model to opus`, `sonnet`, `haiku` |
| Worker effort | `worker effort to default`, `low`, `medium`, `high`, `xhigh`, `max` |

The project is a name from the registry (letters, digits, `.`, `_`, `-`), and the value one of the table's: nothing else goes into a note. The note wakes firstmate once. It is firstmate that decides what each change means, applies them (a preset's bundle, the registry's tags, the settings file) and records them.

Until the files say so, the changes are **pending**: a cell reads `On → Off, asked`, the project's row says `asked firstmate: Refine`, and the page's entry carries the number of changes asked as a badge. A value already asked is not staged again, and a pending change cannot be taken back from the page. A change stops being pending

- once the app reads the files and they have it (the app reads every 15 seconds while a change is pending);
- after 15 minutes, when firstmate has not applied it (the page then shows what the files say, and nothing is retried);
- at once, when the note could not be sent: the changes are the draft again, the project's view says `firstmate was not told: <why>` (a firstmate checkout without `bin/fm-inbox.sh`, or the note's own error), the app logs it, and Validate sends them again.

A draft is kept in the app only, not on disk: it is gone when the app restarts, and a draft entry the files already have (firstmate changed it meanwhile) or whose project left the registry is dropped.

## What the app reads and writes

It reads, read-only and as text, in firstmate's home (`[firstmate] home`):

- `data/projects.md`, the registry: lines of the form `- <name> [<tags>] - <description>`. The tags it knows are `no-mistakes`, `direct-PR`, `local-only` and `+yolo`; any other tag, any line that is not a project's, and any description are ignored, so a registry that grows new annotations still reads;
- `data/project-settings.toml`, the settings file described below.

It reads them every minute while the touch bar is connected, and not at all while it is not (nothing would show it). It **never writes** either file, nor anything else in firstmate's home: its only writes into firstmate are these notes, and, for [Bearings](agents.md#bearings) and [a change ready for review](agents.md#changes-ready-for-review), their own.

## The settings file

`data/project-settings.toml` in firstmate's home is private to firstmate and the captain; the app reads it and firstmate writes it. It holds one table per project, named by the registry's name, and every key is optional:

```toml
[projects.screenpad-agents]
preset = "refine"               # "iterate" or "refine": the preset last applied
annotated_review = true         # annotated review on (the default) or off
where = "desktop-first"         # "desktop-first" (the default), "laptop-first", "desktop" or "laptop"
model = "opus"                  # the worker's model, "opus" by default
effort = "default"              # the worker's effort: "default", "low", "medium", "high", "xhigh" or "max"

[projects."a.dotted.name"]      # a name with dots is quoted
model = "sonnet"
```

An absent file, table or key means the key's default. The reading is tolerant: a table for a project that is not in the registry, an unknown key, a value of the wrong kind (a string for `annotated_review`) or an empty one is ignored, and a `model` or `effort` that is not one the page offers is shown as it is and matches no button. A file that is not valid TOML is shown as an error in the app's log, and every project then has its defaults.

`preset` is what firstmate records when it applies a preset (and may use to read "no milestone stops" for **Iterate**, which no other key says). The app shows it only while it still agrees with the registry's tags (see [the settings](#the-settings)).

## Troubleshooting

| Problem | Where to look |
|---|---|
| There is no Projects page | the config has no `[firstmate]`; the app logs why a firstmate section is wrong |
| **Projects unreadable** | `data/projects.md` cannot be read in `[firstmate] home` (the page says why); the app logs it once |
| A project is missing | its registry line is not `- <name> [<tags>] - <description>`, its name has other characters than letters, digits, `.`, `_` and `-`, or its description starts with `ARCHIVED` |
| **delivery unknown** | the registry line has none of `[no-mistakes]`, `[direct-PR]`, `[local-only]` |
| A change stays amber and says *draft* | it is not sent: tap **Validate** (or **Discard**) |
| A change stays amber and says *asked* | firstmate has not applied it (it applies a note when it next drains its inbox: `FM_HOME=<home> <code>/bin/fm-inbox.sh status`); after 15 minutes the page gives up showing it |
| Neither preset is lit | the project has no recorded preset, or its settings have been changed one by one since: tap a preset to set the bundle |
| **firstmate was not told** | `fm-inbox.sh note` failed; the project's view says why, the changes are the draft again (tap Validate to send them again), and `journalctl --user -u screenpad-agents` has it whole |
