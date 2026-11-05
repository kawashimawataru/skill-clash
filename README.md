# skill-clash

Find the fights between your Claude Code skills before you load them together.

Load three design skills at once and you hand Claude more than 10,000 words of instructions that disagree with each other. skill-clash reads every installed `SKILL.md` and tells you, before anything is loaded:

- which **one** skill to build with and which **one** to review with, for a one-line task;
- where the skills you picked **contradict** each other (cream backgrounds, serif headlines, bento grids, gradients, ...), with the sentence and line number;
- whether the set is **over the word budget**;
- where every installed skill **belongs**: always on, on demand, name only, or off.

It writes the decision to a short `LOADOUT.md` that Claude reads before the skills. One Python 3 file, standard library only, no network.

## Install

```sh
npx skills add kawashimawataru/skill-clash
```

Or clone and link it: `ln -s "$PWD/skills/skill-clash" ~/.claude/skills/skill-clash`.

## Example

```text
$ python3 scripts/skill_clash.py conflict --set design-taste-frontend interface-design \
    landing-page-design frontend-design marp-slide
  axis                      |  1  |  2  |  3  |  4  |  5
  --------------------------+-----+-----+-----+-----+----
  gradient                  |  ✗  |  ✗  |  ✗  |  ✗  |  ✓
  scroll reveal             |  ✗  |     |  ✓  |  ✗  |
  ...
[scroll reveal]
  ✓ landing-page-design L434: - [ ] Every transition uses the B7 base curve, scroll reveals use IntersectionObserver
  ✗ design-taste-frontend L266: - A card, row or tile that animates on scroll; a reveal, fade-in or parallax; random blinking.

2 axes with ✓ and ✗ in the same row            (exit code 1)
```

## Tutorial: the first five minutes

Paths below are relative to `skills/skill-clash/` (or `~/.claude/skills/skill-clash/` once installed).

1. See what Claude is carrying: `python3 scripts/skill_clash.py scan`. The last line is the total word count.
2. Ask for a pair: `python3 scripts/skill_clash.py plan --task "build a landing page for a cafe"`. Japanese works too (`--task "高級感のある LP"`).
3. Check the pair, or any set you meant to load: `python3 scripts/skill_clash.py conflict --set <a> <b>`. Open each evidence line it prints.
4. Settle each clash and write the file: `python3 scripts/skill_clash.py loadout --set <a> <b> --win "gradient=<a>" --dry-run`, then again without `--dry-run`.
5. Tell Claude to read `LOADOUT.md` first. Done.

## How-to

### Pick skills on a page

```sh
python3 scripts/skill_clash.py report --html .skill-clash/report.html
```
One static page (nothing fetched) in five steps: what the tool is, a one-line request, the proposed builder and checker, the clashes to decide, and the `LOADOUT.md` to copy or save. The page also shows an `apply '<hash>'` command that writes the same file from the terminal. The page text is Japanese.

### Use the CLI

Every subcommand takes `--json` (JSON on stdout, messages on stderr) and `--help` with examples. Exit codes: 0 no problem, 1 a clash or over budget, 2 an error. There is no colour output, so `NO_COLOR` needs nothing. All flags are in [docs/reference.md](docs/reference.md).

### Make Claude go through the same file

- **apply**: paste the page's `python3 .../skill_clash.py apply '<hash>'` to Claude, or run it. `--dry-run` prints without writing; an existing `LOADOUT.md` with other text is replaced only with `--force`.
- **rules**: `loadout --rules` or `apply --rules` also writes `.claude/rules/skills-loadout.md` containing `@../../LOADOUT.md`, so Claude Code loads it every session. An existing rules file is never overwritten.
- **hook**: register `hooks/loadout-guard.py` as a `PreToolUse` hook with matcher `Skill`. When Claude is about to load a skill listed under 読まない (do not load) in `LOADOUT.md`, it adds a note; with `LOADOUT_GUARD=deny` it blocks instead.

```json
{"hooks": {"PreToolUse": [{"matcher": "Skill", "hooks": [{"type": "command",
  "command": "python3 ~/.claude/skills/skill-clash/hooks/loadout-guard.py"}]}]}}
```

### Tidy every skill (place)

```sh
python3 scripts/skill_clash.py place --out .skill-clash/place.md
```
Each skill gets one place and the rule that put it there:

| place | rule | suggested setting |
|---|---|---|
| trunk | the description routes to other skills ("read this before any other skill", "orchestrates", "entry point") | keep on |
| scene | says when to use it up front, overlap with others under 0.25 | keep on |
| name-only | no when-to-use in the first 160 characters, or loses a 0.25+ overlap to a skill of the same role, or a same-named version exists | `"name-only"` |
| drop | another skill's body says it replaced this one, the link is broken, or top 5% by size with no when-to-use | `"off"` |

The file ends with a `skillOverrides` fragment for `settings.json` and a draft route table (kind of work → builder → checker). Nothing is applied: you decide. On the author's machine (170 skills) it found 6 trunk, 105 scene, 58 name-only and 1 drop.

```text
| 種類 (kind)             | builder               | checker             |
|---|---|---|
| app / tool / dashboard  | interface-design      | impeccable          |
| landing page / website  | design-taste-frontend | impeccable          |
| slides / documents      | slideshow             | presentation-design |
```

## Accuracy

`conflict` gives each skill one stance per axis (✓ recommends, ✗ avoids, ~ both, blank none) from sentence cues. `bench` measures it against cells labelled by hand after reading the source lines; a cell counts as right only when the stance matches exactly.

| gold set | precision | recall |
|---|---|---|
| `tests/gold/cells.jsonl`: 60 random cells (40 with a stance, 20 with none but naming the axis); 54 labelled, 6 too unclear to label | **100%** (32/32, 95% Wilson 89.3–100%) | **88.9%** (32/36, 74.7–95.6%) |
| same set before tuning | 81.1% (30/37, 65.8–90.5%) | 83.3% (30/36, 68.1–92.1%) |
| `tests/gold/holdout.jsonl`: 23 fresh cells drawn after tuning, never tuned on; 21 labelled | **83.3%** (10/12, 55.2–95.3%) | **83.3%** (10/12, 55.2–95.3%) |

The lexicon was tuned in two rounds on the first set, so its 100% is optimistic; the held-out row is the honest estimate, and its sample is small. Typical errors: a word used as a name (`rounded` as a token key, "cream" as a caption template), a platform note read as advice, and positive advice phrased without a cue word ("a serif headline over a sans body reads as deliberate"). Run `python3 scripts/skill_clash.py bench` (and `--gold tests/gold/holdout.jsonl`); the gold files store paths from the author's machine (`~/.claude/...`), so rows whose skill is not installed are skipped until you draw your own set with `bench --draw 40 20`.

## Why

**Skills are being loaded too many at a time.** Load three to five design skills together and the instructions pass 10,000 words. They collide, and the screen that comes out leans toward none of them: an average. One popular design skill recommends a cream ground with large serif headlines; Anthropic's official `frontend-design` lists exactly that look as the first of the AI defaults to avoid. The more instructions there are, the smaller the share that is followed.

- IFScale ([arXiv:2507.11538](https://arxiv.org/abs/2507.11538)): instruction-following accuracy falls steadily as the number of simultaneous instructions grows, even for frontier models.
- ConInstruct ([arXiv:2511.14342](https://arxiv.org/abs/2511.14342)): models often notice conflicting instructions but rarely say so; they silently follow one side.

Longer version: [docs/explanation.md](docs/explanation.md).

## Credits

- Built by Wataru Kawashima with Claude Code.
- The design of the HTML page follows GOV.UK's question pages and check-answers pattern and Vercel's new-project flow.
- Skill-authoring guidance from Anthropic's Agent Skills documentation; CLI conventions from [clig.dev](https://clig.dev); documentation structure from [Diátaxis](https://diataxis.fr).

## License

MIT. See [LICENSE](LICENSE).
