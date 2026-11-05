# Reference

`python3 skills/skill-clash/scripts/skill_clash.py <command> [flags]`

Exit codes: `0` no problem, `1` a clash, over budget, undecided axes in a loadout, or `bench` precision under 90%, `2` an error (unknown skill, bad flag, a file that would be overwritten).

Flags every command takes:

| flag | meaning |
|---|---|
| `--json` | print one JSON value on stdout; messages go to stderr (`report --json [PATH]` writes to PATH, stdout when left out) |
| `--dirs DIR ...` | extra skill roots, added to the defaults |
| `--no-defaults` | scan only `--dirs` |
| `-h`, `--help` | usage with examples |

Default roots: `~/.claude/skills` (symlinks resolved, identical copies counted once) and the `skills/` folder of every plugin enabled in `~/.claude/settings.json` (`enabledPlugins`, install paths from `~/.claude/plugins/installed_plugins.json`). Plugin skills are named `plugin:skill`, as Claude lists them. `~/.agents/skills` is not scanned by default.

Size: English words by whitespace, Japanese characters / 2, tokens ≈ words × 1.3.

## Commands

### scan

```text
options:

examples:
  skill_clash.py scan
```

### budget

```text
options:
  --max MAX             word budget (default 6000)

examples:
  skill_clash.py budget impeccable interface-design
  skill_clash.py budget a b --max 4000 --json
```

### overlap

```text
options:
  --min MIN
  --top TOP

examples:
  skill_clash.py overlap
  skill_clash.py overlap --min 0.3 --top 5 --json
```

### conflict

```text
options:
  --set SET [SET ...]   the skills you will load together
  --all                 every scanned skill
  --lexicon LEXICON     another lexicon.json

examples:
  skill_clash.py conflict --set design-taste-frontend impeccable
  skill_clash.py conflict --all --json
```

### plan

```text
options:
  --task TASK
  --max MAX             word budget (default 6000)
  --lexicon LEXICON     another lexicon.json

examples:
  skill_clash.py plan --task "build a landing page for a cafe"
  skill_clash.py plan --task "高級感のある LP" --json
```

### report

```text
options:
  --combo COMBO         comma-separated skills to table together (repeatable)
  --task TASK
  --min MIN
  --max MAX             word budget (default 6000)
  --lexicon LEXICON     another lexicon.json
  --json [PATH]         write the report JSON to PATH (stdout when PATH is
                        left out)
  --html PATH           write one static HTML page (JSON embedded)

examples:
  skill_clash.py report --html .skill-clash/report.html
  skill_clash.py report --json > report.json
```

### loadout

```text
options:
  --set SET [SET ...]   the skills you will load together
  --builder BUILDER
  --checker CHECKER
  --win AXIS=SKILL      which skill wins a clashing axis (repeatable)
  --max MAX             word budget (default 6000)
  --lexicon LEXICON     another lexicon.json
  --out OUT
  --rules               also write .claude/rules/skills-loadout.md
                        (@LOADOUT.md) unless it exists
  --force               replace a LOADOUT.md that has other text
  --dry-run             print, write nothing

examples:
  skill_clash.py loadout --set a b c --win gradient=a --dry-run
  skill_clash.py loadout --set a b --out LOADOUT.md --rules --force
```

### apply

```text
options:
  --max MAX             word budget (default 6000)
  --lexicon LEXICON     another lexicon.json
  --out OUT
  --rules               also write .claude/rules/skills-loadout.md
                        (@LOADOUT.md) unless it exists
  --force               replace a LOADOUT.md that has other text
  --dry-run             print, write nothing

examples:
  skill_clash.py apply '#set=a,b&b=a&c=b' --dry-run
  skill_clash.py apply '#set=a,b&b=a&c=b&win=serif:b' --rules
```

### triggers

```text
options:

examples:
  skill_clash.py triggers
  skill_clash.py triggers --json
```

### place

```text
options:
  --out PATH            write the markdown draft here
  --force
  --min MIN
  --max MAX             word budget (default 6000)
  --lexicon LEXICON     another lexicon.json

examples:
  skill_clash.py place
  skill_clash.py place --out .skill-clash/place.md --json
```

### bench

```text
options:
  --gold PATH
  --draw STANCE NONE    draw a new random gold set
  --seed SEED
  --force
  --lexicon LEXICON     another lexicon.json

examples:
  skill_clash.py bench
  skill_clash.py bench --draw 40 20 --seed 7 --gold /tmp/new.jsonl
```

### selftest

```text
options:

examples:
  skill_clash.py selftest
  skill_clash.py selftest --json
```

## JSON report (`report --json`)

| key | content |
|---|---|
| `skills` | list of `{name, path, description, words, tokens, kind}`; `kind` is `builder`, `checker` or `other` (a review verb such as review / audit / critique / check / lint / detect / 点検 / 見直す before any build verb means `checker`) |
| `overlap` | list of `{a, b, jaccard, shared}` for every pair at or above `--min` |
| `stance` | `{skill: {axis: {stance, line, evidence}}}`; `stance` is `recommends`, `avoids`, `mixed` or `null`; `line` is 1-based in `path` |
| `axes` | axis names in lexicon order |
| `budget_limit` | the `--max` word budget |

## place (`place --json`)

`{skills: [{name, path, words, place, rules}], skillOverrides: {name: "name-only" | "off"}, routes: [{kind, builder, checker}]}`. `place` is `trunk`, `scene`, `name-only` or `drop`; precedence is drop > trunk > name-only > scene; `rules` lists every rule that matched.

## bench (`tests/gold/*.jsonl`)

One JSON object per line: `id`, `skill`, `path`, `axis`, `lines`, `text` (the lines naming the axis), `pred_at_draw`, `gold` (`recommends`, `avoids`, `mixed`, `none` or `uncertain`), `note`. Precision counts cells where the tool gives a stance; recall counts cells where the label gives one; a cell is right only when the two match exactly. `uncertain` cells are left out. Intervals are Wilson 95%.

## lexicon.json

- `axes`: `{name: {include: [regex], exclude: [regex]}}`, case-insensitive (`(?-i:...)` for case-sensitive parts). Excludes are blanked out before matching.
- `negative`, `positive`: cue regexes. Negatives are matched first and mask positives, so "don't use" never counts as "use".
- `ja_en`: `[[japanese regex, "english words"]]`, used by `plan` and the HTML page so Japanese requests match English descriptions.

## LOADOUT.md

Fixed Japanese format, shared byte for byte by `loadout_md()` in Python and `loadoutMd()` in the page: 作る用 (builder), 点検用 (checker), 読まない (do not load), 決めた向き (one line per clashing axis: the winner, or 未決 = undecided), 読む語数 (words to read). The page's URL hash for `apply` is `set=a,b,c&b=<builder>&c=<checker or ->&win=<axis>:<skill or ->;...`.
