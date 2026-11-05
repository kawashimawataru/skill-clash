---
name: skill-clash
description: Finds instruction conflicts and word-budget overruns between Claude Code skills before several are loaded together, narrows them to one builder and one checker, writes the decision to LOADOUT.md, and suggests where every installed skill belongs (trunk, scene, name-only, drop). Use when two or more skills look relevant to one task (especially design, UI, landing page or slide skills), when output looks averaged or skills seem to contradict each other, or when the skill list needs tidying. 複数の skill を同時に読みたくなったとき、読む前に回し、作る用1つ＋点検用1つに絞って、指示のぶつかりと語数の超過を先に見つける。skill 全体の置き場所（幹・場面・名前だけ・外す候補）を整理するときにも使う。
---

# skill-clash

Loading several skills at once makes their instructions collide and the output drift to an average. This skill finds that before you read them.

`CLI` below means `python3 ~/.claude/skills/skill-clash/scripts/skill_clash.py` (use the folder this SKILL.md is in if it is installed elsewhere). Exit codes: 0 no problem, 1 clash or over budget, 2 error. Every command takes `--json`.

## When two or more skills fit one task

1. Pick candidates from the one-line request (Japanese is fine):
   ```
   CLI plan --task "<the request in one line>"
   ```
   Read only the `Proposal` pair: one builder, one checker. Scores come from word overlap with each description, so if a name is plainly wrong for the task, take the next candidate.
2. Check the set you are about to load:
   ```
   CLI conflict --set <skill> <skill> ...
   CLI budget <skill> <skill>
   ```
   `conflict` prints a table: rows are design axes (gradient, serif, ...), columns are skills. ✓ recommends, ✗ avoids, ~ says both, blank says nothing. `budget` exits 1 above 6,000 words; drop a skill or read only the sections you need.
3. For every axis with ✓ and ✗ in the same row, the evidence sentence and line number are printed under the table. Open that line. If the clash is real, decide which side wins and say so in one line of your report (for example "background colour follows frontend-design; the cream ground from the other skill is not used"). If it is a misread, ignore it.
4. Write the decision before reading the skills:
   ```
   CLI loadout --set <skill> <skill> ... --win "<axis>=<winning skill>" --dry-run
   CLI loadout --set <skill> <skill> ... --win "<axis>=<winning skill>"
   ```
   Read `LOADOUT.md` first, then build with the builder only. Do not blend every skill a little; lean the way the file says. Axes without `--win` are written as `未決` (undecided): ask the user or decide and report it. An existing `LOADOUT.md` with other text is only replaced with `--force`.
5. If `plan` prints `Hint:`, suggest to the user a description that leads with when to use the skill. Never edit another skill's files.

## When the user pastes a command from the page

`report --html .skill-clash/report.html` writes a one-page picker for people. Its last step shows `CLI apply '<hash>'`. Run it (add `--dry-run` first if a `LOADOUT.md` exists) and the working folder gets the same `LOADOUT.md` the page showed. `--rules` also writes `.claude/rules/skills-loadout.md` so the file is read every session. Do not open the page in the user's browser; give the path.

## When the skill list needs tidying

```
CLI place --out .skill-clash/place.md
```
Every skill gets one place, with the rule that put it there:

- **trunk**: an entry point that routes to other skills (for example design-director). Keep it always on.
- **scene**: the description says when to use it up front and does not overlap much. Leave it.
- **name-only**: no when-to-use, or loses an overlap of 0.25+ to another skill, or another version has the same name. Candidate for `"skillOverrides": {"<name>": "name-only"}`.
- **drop**: another skill's body says it was replaced, or the link is broken, or it is in the top 5% by size with no when-to-use. Candidate for `"off"`.

The file ends with a `skillOverrides` JSON fragment and a draft route table (kind of work → builder / checker). Show both to the user; never write `settings.json` yourself.

## Reading the output carefully

- Stances are heuristics from sentence cues. Measured precision is in README.md ("Accuracy"); always open the evidence line before acting on a clash.
- Only `SKILL.md` is read. Skills that keep their rules in `reference/` files show empty columns.
- Defaults scan `~/.claude/skills` and the skills of enabled plugins. `--dirs` adds roots; `--no-defaults` scans only `--dirs`.
- To add an axis, edit `lexicon.json` (`include`, optional `exclude`), then run `CLI selftest` and `CLI bench`.
- `hooks/loadout-guard.py` (PreToolUse, matcher `Skill`) warns when a skill listed under 読まない in `LOADOUT.md` is about to be loaded.
