# The usage tile

The **usage** tile (`usage`) of the [agent app](agents.md) shows how much of each coding agent's quota is left, from [`quota-axi`](https://github.com/kunchenguid/axi), the tool that reads each provider's limits. It is optional: it exists only with `[usage]` in `agents.toml`.

```toml
[usage]
command = ["/home/me/.local/bin/quota-axi"]   # quota-axi, "quota-axi" by default; or a wrapper and its arguments
poll = 60                                      # seconds between two runs, 60 to 3600, 60 by default
terminal = ["ptyxis", "--new-window", "-T", "Usage limits", "-x", "bash -c {command}"]   # the default
```

Give the tile a spot in `touchbar.toml`:

```toml
[[bar]]
label = "Limits"
tile = "usage"
```

## What it shows

On the bar the tile is a **gauge** (`gauge.svg`) with the **tightest provider's percent left** as its badge (`87%`) and its tone; a tile with an icon shows only those. The home page's list shows the words with the icon: the first line is each provider quota-axi could read with its percent left and when its window resets (`codex 87% ↻26 Dec`, a clock time when it resets within a day); the second the providers quota-axi could **not** read, with why:

```text
codex 100% ↻26 Dec
no data: claude, copilot, opencode-go
```

When no provider could be read there is nothing to put in a gauge: the tile shows these words instead, with no icon.

A single provider with no data says why: `claude no data: credentials_invalid`. The reason is quota-axi's own (`credentials_invalid`, a sign-in required, an error); there is **never a made-up number** for a provider it could not read. Several windows of one provider (a five-hour and a weekly one) count as the tightest. When the first line has no room for the resets, they go to the second, as far as it allows. The tile is green while every provider has more than 25 percent left, amber at 25 percent or less, red at 10 percent or less, and grey when none could be read. If a later run fails, the tile keeps what was read and marks it `(old)`; if the very first fails it says `quota-axi unavailable` in words, and the app logs why once.

## When it runs

`quota-axi` (TOON on its standard output, the default) runs in a thread of its own, **at most once a minute** (`poll`, never less) and **only while the touch bar is connected**: a read asks each vendor, and nothing would show it. It runs with none of the `FM_*` variables, with no input, and gives up after 60 seconds.

A tap on the tile opens the full report, `quota-axi --full`, in a new terminal window: `terminal` is the terminal's command with `{command}` where the line to run goes (a window that stays until a key is pressed), started detached in a scope of its own like [Watch](runs.md#watching-a-run) and the review command. It reads nothing for that: the window runs quota-axi itself.

Under `systemd`, `quota-axi` is a script that needs `node` on its `PATH`, and the app's unit has a short `PATH`: set `command` to the node program and the script, as `[firstmate] lavish` is (`["/path/to/node", "/path/to/quota-axi"]`); the terminal window then runs the same words.

## Troubleshooting

| Problem | Where to look |
|---|---|
| The tile says `quota-axi unavailable` | the app's log (`journalctl --user -u screenpad-agents`) says why: not found (give `command` an absolute path, with `node` first for a script), no answer in 60 seconds, a non-zero exit with its last line, or output that holds no quota |
| A provider says `no data` | quota-axi could not read it: the reason is its own (`quota-axi --full` has the account evidence) |
| The tile has no spot | the app logs `tile "usage" has no spot` at start: add `tile = "usage"` to a `[[bar]]` block |
| A tap opens nothing | the terminal command failed within 2 seconds (the app logs `the usage report did not open` and why); check `[usage] terminal` |
