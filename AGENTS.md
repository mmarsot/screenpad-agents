# Project agent guide

This project's agent knowledge lives in skills, one per code area: `.agents/skills/<name>/SKILL.md`. `.claude/skills` is a committed symlink to `.agents/skills`, so Claude Code, Codex and other agents read the same files. Each skill lists the rules, owning files, tests and pitfalls of its area and links the `docs/` pages that explain them.

**Before changing anything, load the [`contributing`](.agents/skills/contributing/SKILL.md) skill and the skill of every area the change touches.** If no skill fits, start from the [README](README.md) and [docs/development.md](docs/development.md).

## Skills

| Skill | Load before changing |
|---|---|
| `contributing` | anything: the checks (`make check`), file size, documentation, working in steps, no-mistakes review, maintaining skills |
| `agents` | the agent app: `agents.py` and `screenpad_agents/` (Herdr, firstmate's reader, the Agents page and tiles, its config and opt-in), the client library it uses, and the stand-in touch bar its tests run against |
| `install` | `install.sh`, `systemd/`, and any installed path or unit |

## Skills are part of the code

The skills are committed and reviewed with the code. Whoever changes an area's rules, invariants, owning files or tests updates the matching skill in the same change; contributors and agents may add, edit, split or prune skills on their own. `tests/test_skills.py` checks each skill's front matter, this index, the symlink, and that every relative link in the skills resolves. Keep this file to the index: area knowledge goes in its skill, explanations in `docs/`.
