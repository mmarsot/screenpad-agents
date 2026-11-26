# The usage limits: the Limits page and the usage tile

The **Limits** page (`limits`) of the [agent app](agents.md) shows how much of each coding agent's quota is left, from [`quota-axi`](https://github.com/kunchenguid/axi), the tool that reads each provider's limits: one large row per quota window, with the provider's logo, a bar, the percent left and when the window resets. The **usage** tile (`usage`) is the same numbers in the bar: a gauge with the tightest percent left. Both are optional: they exist only with `[usage]` in `agents.toml`.

```toml
[usage]
command = ["/home/me/.local/bin/quota-axi"]   # quota-axi, "quota-axi" by default; or a wrapper and its arguments
poll = 60                                      # seconds between two runs, 60 to 3600, 60 by default
providers = ["claude"]                         # the providers that count; every one quota-axi can read by default
terminal = ["ptyxis", "--new-window", "-T", "Usage limits", "-x", "bash -c {command}"]   # the default
```

Give the page a spot in `touchbar.toml`, as the Runs and Projects pages have (a tap opens the apps page on it, and the bar draws the page's gauge, its tightest percent as a badge and its tone):

```toml
[[bar]]
label = "Limits"
page = "limits"
```

The `usage` tile (`tile = "usage"`) still works for a bar that has it, but **a tile cannot turn the apps page**: the touch bar's protocol has no message for that, so a tile can only open Details. Use the page item to open the page. Without a spot the page is still in the apps page's home list.

## The providers

`providers` names the providers that count. **Providers not in the list are ignored** by the page, the tile and the tightest percent that is the badge: a provider you do not use never shows a number (a free plan that reports a window that is always 100 percent, say). Without the list, every provider quota-axi can read counts (one it says nobody set up is left out); with it they show in the order you list them, and a listed provider quota-axi does not report at all says `No data: not reported by quota-axi`. Names are quota-axi's own, lower case (`claude`, `codex`, `copilot`, ...).

## What the page shows

A grid six columns wide: a provider is a block of rows, its **logo** (and its name where the cell has room) in the first column across them, and one row per quota window:

| Cell | What it shows |
|---|---|
| the window | its plain name (**5-hour session** and **Weekly** for Claude; another window by its length, `30-day window`) and when it resets: `resets in 3h20`, `resets in 45 min`, or a weekday and date (`resets Tue 1 Dec`) once it is more than a day away; `using fast` follows when quota-axi reads the pace as ahead |
| the bar | a line of blocks, filled with what is left: green, amber at 25 percent or less, red at 10 percent or less |
| the percent | `42%` and `left`, in the bar's color |

The first window is the session, then the week, then any other. A provider that **cannot be read** has its logo and **No data** with the reason in words (`credentials invalid`, `GitHub Copilot sign-in required`): never a made-up number. The last row is **Details**, which opens a terminal window with a viewer (below), and a line that says what the page shows, or that the last read failed (`last read failed: ...`, the page then keeping what it last read) and how many windows did not fit. The protocol limits a page to four rows, so three windows fit with Details; with more, the first providers' windows show and the line counts the rest.

The logos are the app's own small SVGs in `icons/` (`claude.svg`, a sunburst, and `openai.svg`, a knot, for Codex; another provider has the gauge): monochrome marks drawn for personal use, on the same navy disc as the other [icons](agents.md#its-icons).

Nothing a finger can be on changes by itself: only **Details** takes a touch, and its text never changes; the reset times are the only words that change, on a read.

## Details

**Details** opens a terminal window with a viewer, started detached in a scope of its own like [Watch](runs.md#watching-a-run) and the review command, and not waited for beyond 2 seconds. `terminal` is the terminal's command with `{command}` where the line to run goes (a window that stays until a key is pressed). The viewer is firstmate's **`data/tools/usage-view.py`** in `[firstmate] home` when that file exists (it runs `quota-axi --json` itself and draws a bar per window, refreshing every minute); without it, or without `[firstmate]`, the window runs `quota-axi --full`. A tap on the `usage` tile does the same.

## What the tile shows

On the bar the tile is a **gauge** (`gauge.svg`) with the **tightest percent left** as its badge (`87%`) and its tone; a tile with an icon shows only those. The home page's list shows the words: the first line is each provider that was read with its percent left and when its window resets (`claude 18% ↻1 Dec`, a clock time when it resets within a day); the second the providers quota-axi could **not** read, with why:

```text
claude 18% ↻1 Dec
no data: copilot
```

When no provider could be read there is nothing to put in a gauge: the tile shows these words instead, with no icon. A single provider with no data says why: `claude no data: credentials invalid`. Several windows of one provider count as the tightest. The tile is green while every provider has more than 25 percent left, amber at 25 percent or less, red at 10 percent or less, and grey when none could be read. If a later run fails, the tile and the page keep what was read (the tile marks it `(old)`); if the very first fails they say `quota-axi unavailable`, and the app logs why once.

## When it runs

`quota-axi --json` (the JSON of its schema version 5 on its standard output) runs in a thread of its own, **at most once a minute** (`poll`, never less) and **only while the touch bar is connected**: a read asks each vendor, and nothing would show it. It runs with none of the `FM_*` variables, with no input, and gives up after 60 seconds.

Under `systemd`, `quota-axi` is a script that needs `node` on its `PATH`, and the app's unit has a short `PATH`: set `command` to the node program and the script, as `[firstmate] lavish` is (`["/path/to/node", "/path/to/quota-axi"]`); the terminal window then runs the same words.

## The apps page's four pages

The touch bar takes at most **four pages** from an app. The app gives the Agents page, Captain's Call's (`calls`), the Projects page, the Runs page and the Limits page: with all five on, **Captain's Call's own page is left out** (the app logs it once). Its view is still the Captain's Call widget on the Agents page, and the `calls` tile still opens the decisions board.

## Troubleshooting

| Problem | Where to look |
|---|---|
| The page or tile says `quota-axi unavailable` | the app's log (`journalctl --user -u screenpad-agents`) says why: not found (give `command` an absolute path, with `node` first for a script), no answer in 60 seconds, a non-zero exit with its last line, or output that holds no providers |
| A provider says `No data` | quota-axi could not read it: the reason is its own (`quota-axi --full` has the account evidence). Claude says `credentials invalid` when Claude Code authenticates with a long-lived token quota-axi cannot use: signing in to Claude Code again, in the way quota-axi reads, fixes it |
| A provider shows that I do not use | list the ones you use in `providers` |
| A listed provider says `not reported by quota-axi` | its name is not one quota-axi knows: check `quota-axi --json` for the `provider` names |
| The page is not in the bar | add `page = "limits"` to a `[[bar]]` block; the page is in the apps page's home list without it |
| There is no Captain's Call page | the touch bar's four pages are used by the others (above); open Captain's Call from the Agents page |
| Details opens nothing | the terminal command failed within 2 seconds (the app logs `the usage report did not open` and why); check `[usage] terminal` |
