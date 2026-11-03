"""screenpad-agents: the agent app for the ScreenPad touch bar.

A separate program, and only a client of the touch bar's app socket
(screenpad-linux's docs/app-api.md), through the client library screenpad_app: it imports
nothing of screenpad_touchbar. It shows every
agent Herdr reports (busy, idle, blocked; Herdr's own state is authoritative)
as a widget on the apps page and as a tile in the bar, joins them to
firstmate's tasks through the endpoints firstmate records, focuses an agent's
pane through Herdr when its widget is tapped, and shows how many Captain's
Calls are waiting; with [runs], a Runs page shows the no-mistakes runs of
each project (read only). docs/agents.md and docs/runs.md are the reference.

The modules, imported one way: common, config, herdr, keymap, screen,
firstmate, nomistakes, card, fleet, runcard, runs, runwatch, app, cli.
"""
