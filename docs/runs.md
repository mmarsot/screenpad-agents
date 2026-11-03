# The Runs page

With a `[runs]` table in its config, the [agent app](agents.md) adds a second page to the touch bar's apps page: **Runs**, the [no-mistakes](https://github.com/kunchenguid/no-mistakes) pipeline runs of your projects and their status. It only reads them: it starts, answers, aborts, retries or syncs no run, and never touches the no-mistakes daemon. The one thing it does is open a run's pull request in your browser, when you ask.

- **one row per project**: the project's widget, then its active runs, then its recent ones (the newest run of each branch not shown yet), up to four runs a row;
- **each run joined to its agent and its firstmate task**: a run shows under the task's name when it is one, otherwise under its branch, with what it is doing (`running · review`, `waiting on you · review`, `failed · push`, `passed · PR #12`);
- **a warning** when one agent, one repo copy or one branch has more than one active run: normally there is at most one per agent. The project's widget turns red and says so, and the runs involved carry a `2+` badge;
- **a run's card** when you tap it: its steps, findings and how it ended, **Focus** to its agent's pane, and **Open PR** once the run has opened a pull request;
- **its pull request in one touch**: hold a run that has one (its cell ends in `PR #12 · hold: open`) to open its card and the pull request in your browser on the main screen;
- an optional **`runs` tile** for the bar: a lighthouse, with how many runs need you (the home page's list adds how many are active). The Runs page has the lighthouse too, in the home page's list; see [its icons](agents.md#its-icons).

![The Runs page: api with 1 active and 1 needing you, then fix-login-redirect running at ci with PR #14 in green, fm/docs-install passed with PR #12 in grey and fm/rate-limit failed with PR #11 in red, each ending in hold: open; below, web with web-dark-mode waiting on you at review in amber and fm/footer passed with PR #30](images/runs-page.png)

*The Runs page with two projects, under a bar 208 px high. Rendered by the touch bar's extension in a headless GNOME Shell 50.1, from the app's own page fed to the daemon's own code, with stand-in runs, agents and tasks.*

## Turning it on

Add to `~/.config/screenpad/agents.toml`:

```toml
[runs]
repos = ["/home/you/code/api"]   # repo directories to watch; may be empty with [firstmate]
```

With `[firstmate]` configured, `[runs]` alone is enough: the app also watches the projects firstmate knows (below). Then restart the app (`systemctl --user restart screenpad-agents`) and check what it reads with `screenpad-agents show`, which prints each project's runs after the agents.

To give the tile a spot, add a button for it in `~/.config/screenpad/touchbar.toml` (at most three buttons in all):

```toml
[[button]]
icon = "emblem-ok-symbolic"
label = "Runs"
tile = "runs"
```

| Setting | Meaning |
|---|---|
| `[runs] repos` | repo directories (absolute paths) to watch, `[]` by default. Each one shows even when no-mistakes cannot read it, with why |
| `[runs] firstmate` | `true` by default: with `[firstmate]`, also watch firstmate's registered clones and its live tasks' worktrees. `false` watches only `repos` |
| `[runs] command` | the no-mistakes program, `"no-mistakes"` by default; or a list of words, for a wrapper and its arguments. The unit runs with your session's `PATH` |
| `[runs] poll` | seconds between two reads while a run is active, 10 to 300, default 20 |
| `[runs] idle` | seconds between two reads while none is, 30 to 3600 and at least `poll`, default 120 |

Without `[runs]` there is no Runs page and no `runs` tile, and no-mistakes is never run.

## Which projects

- every directory in `[runs] repos`;
- with `[runs] firstmate`, firstmate's registered clones, the directories in `<home>/projects/`, and the worktree firstmate records for each live task (its reader's `paths`, below), so a task's run made in its own copy is found.

no-mistakes names the repository it knows each directory as (`repo:` in `no-mistakes axi`), so a clone and its worktrees are one project, named after the clone's directory. A discovered directory no-mistakes does not watch (not a git repository, or `no-mistakes init` never run there) is left out.

## The joins

A run is made on a branch; no-mistakes resolves the run of a repo copy's current branch (`no-mistakes axi status` in that copy). The app asks that in every repo copy it knows: the configured repos, the tasks' worktrees, and each Herdr agent's `cwd`. A run is then joined to:

- the **copy** that resolves a run of the same branch: the run `axi status` gives there, and any other run of that run's branch in the same project (a copy on a detached `HEAD`, which names no branch itself, still joins this way);
- the **agent** whose Herdr `cwd` is that copy, or else the agent in the pane of the task whose worktree it is (the task's endpoint, as on the Agents page);
- the **firstmate task** whose recorded worktree is that copy, or else the task of that agent.

A run on a branch no copy resolves (an old run, a removed worktree) shows without an agent or task.

## Status, and what needs you

| A run that is | Shows | Tone |
|---|---|---|
| active, at a gate (parked, or a step `awaiting_approval` or `fix_review`) | `waiting on you · <step>` | amber; it needs you |
| active otherwise (`pending`, `running`) | its step and the step's status | green |
| the newest run of its branch, failed | `failed · <step>` | red; it needs you |
| completed, cancelled, or an older failure | `passed`, `cancelled`, `failed` | grey |

The page's and the tile's badge count the runs that need you. The warning rule: two or more active runs with the same agent, the same repo copy or the same branch of one project. Their project's widget turns red, says `N active runs for <task or branch>: at most one each`, and the tile and page turn red.

## A run's card

Tapping a run opens its card in place of the grid, until **Back** or the run leaving the project's list:

- the branch, the run's status and its PR;
- each step with its status, its duration once it finished, and its findings count;
- the findings' ids and severities from the last round of each step that has findings (at most six named, the rest counted), or no-mistakes' own summary (`6 info`);
- `waiting on a decision: answer it in the agent's pane` while it waits at a gate, then the outcome and error once it ended.

**Focus** (a spyglass) focuses the pane of the run's agent in Herdr, like Focus on an agent's card; with no agent joined it is dimmed and says so in place of its spyglass. The card answers nothing: a gate is answered where the run is driven, in the agent's pane.

## Opening a run's pull request

![A run's card: fix-login-redirect's steps, each completed up to ci running, under its branch, status and pull request URL; Back, Focus and the task with its pane on the right, the project api running at ci with PR #14 in green across the bottom, and Open PR #14 with its signal flag in the bottom right corner](images/runs-card.png)

*The card of a run watching CI, opened from the Runs page. Rendered like the page above.*

Once no-mistakes has opened the run's pull request (from its `pr` step on: while it watches CI, and after the run passed or failed), the card has **Open PR #12** (a signal flag) in its bottom right corner, and the run's cell on the page ends in `· hold: open`. A tap on Open PR, or a long press (0.8 s) on the run's cell, which also opens the card, opens the pull request in your browser on the main screen, the same way [Captain's Call opens the decisions board](agents.md#opening-the-board): the desktop's URL handler in a transient scope of its own, outside the app's unit,

```sh
systemd-run --user --scope --collect --quiet -- gio open https://github.com/<owner>/<repo>/pull/<number>
```

| The button says | When | A tap |
|---|---|---|
| **Open PR #12** | the run has a pull request | opens it |
| **Opening PR…** (no touch) | the URL handler is running | |
| **PR #12 opened** | it opened | opens it again |
| **Open PR #12** (not opened: why), in red | `systemd-run` is missing or could not make the scope, or the URL handler failed | tries again |

The URL is no-mistakes' own: the run's `pr` in `no-mistakes axi status --run <id>` (the card's read), else in the run list of `no-mistakes axi`, already read for the page; nothing more is read for it, and no URL is ever made up from a branch or a number. Only a pull request's own https URL on GitHub, `https://github.com/<owner>/<repo>/pull/<number>` with nothing else (no user, port, query or fragment), is opened; a run whose `pr` is anything else has no Open PR. The journal says what came of each open (`opened PR <url>`, or `PR <url> not opened: <why>`).

## How it reads

Only these no-mistakes commands run, each read-only, and no other (`screenpad_agents/nomistakes.py` refuses any other argument list):

| Command | Where | What it gives |
|---|---|---|
| `no-mistakes axi` | in each project directory | the repository no-mistakes knows it as, and its newest runs (`runs[N]{id,branch,status,head,pr}`, the ten newest) |
| `no-mistakes axi status` | in each repo copy | the copy's current branch and that branch's run |
| `no-mistakes axi status --run <id>` | | each active run in detail: steps, gate, outcome, error; and the open card's run |
| `no-mistakes axi rounds --run <id> --step <step> --json` | | the findings of the open card's steps that have some |

The one command the Runs page runs that acts is opening a pull request, on Open PR or a long press: `systemd-run --user --scope --collect --quiet -- gio open <url>`, with the run's `pr` the commands above gave ([Opening a run's pull request](#opening-a-runs-pull-request)); `systemd-run` and `gio` get no `FM_*` variable. It runs in the Runs page's thread, between two reads.

firstmate's task worktrees come from its own reader: with `[runs] firstmate`, the reader the app already runs is asked for `--fields endpoints,paths` instead of `--fields endpoints`. Of firstmate's home the app reads nothing else but the names of the directories in `<home>/projects/`.

Each call takes about 30 ms. They run in a thread of their own, off the app's loop: every `[runs] poll` seconds while any run is active, every `[runs] idle` seconds while none is (and after a failed read), within a `poll` when a new task copy or agent appears, at once when a card opens, and **not at all while the touch bar is not connected**. A page is sent only when what it shows changed, and no widget text holds a time that changes on every read (a running step shows no duration), so a read that changed nothing repaints nothing.

## Troubleshooting

| Problem | Where to look |
|---|---|
| The Runs page or the `runs` tile says **no-mistakes unavailable** | no-mistakes could not be run in any project (the tile says so in place of its lighthouse, even while the page still shows the last runs read); `screenpad-agents show` prints why. Is `no-mistakes` on the unit's `PATH` (else set `[runs] command`)? |
| A configured repo says `repo not initialized` | no-mistakes does not watch it: `no-mistakes init` there |
| **No projects** | none of the directories configured or found is a repository no-mistakes watches |
| A run shows without its agent or task | no repo copy the app knows has the run's branch checked out, or no Herdr agent's `cwd` is that copy; `screenpad-agents show` lists each run with its pane |
| A run's card has no **Open PR** | no-mistakes has not opened its pull request yet (the run's `pr` in `no-mistakes axi status --run <id>` is empty), or that `pr` is no GitHub pull request URL: only `https://github.com/<owner>/<repo>/pull/<number>` is opened |
| **Open PR** says **not opened** | the button says why (the journal has it whole): `systemd-run` not found by the unit, it could not make the scope, or `gio open` failed (its own message is in the journal, `journalctl --user -u screenpad-agents`), as for [the decisions board](agents.md#troubleshooting) |
| A project is red | more than one run is active for one agent, copy or branch; `no-mistakes axi status` in that copy says which run is the branch's |
