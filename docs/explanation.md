# Why skill-clash exists

## Skills are being loaded too many at a time

A skill is a block of instructions Claude reads when its description matches the task. Design work matches many of them: a landing page fits a frontend skill, a typography skill, a motion skill and a review skill at once. Load three to five and the instructions pass 10,000 words.

Those instructions were written by different people for different tastes, so they disagree. One popular design skill recommends a warm cream `#FDFBF7` ground with large serif headlines. Anthropic's official `frontend-design` lists exactly that look as the first of the defaults that make a page read as AI-generated. A model handed both does not report the conflict; it settles somewhere in between, and the page leans toward none of them. That in-between is the "average" look people complain about.

## What the research says

- **IFScale** ([arXiv:2507.11538](https://arxiv.org/abs/2507.11538)) measures instruction following as the number of simultaneous instructions grows from 10 to 500. Accuracy falls steadily for every model tested, frontier models included. More skills means more instructions, so a smaller share of each one is followed.
- **ConInstruct** ([arXiv:2511.14342](https://arxiv.org/abs/2511.14342)) gives models instructions that contradict each other. Models often detect the conflict but rarely say so; they silently pick a side. You cannot rely on Claude to tell you two skills disagree.
- Tool and skill selection also gets worse as the list of candidates grows, which is why descriptions should say when to use a skill up front and rarely used skills can be listed by name only.

## What the tool does about it

1. **Fewer skills.** `plan` proposes one skill to build with and one to review with. `budget` warns above 6,000 words.
2. **Visible conflicts.** `conflict` gives each skill one stance per design axis, with the sentence and line number, so a person can check it in seconds.
3. **A decision, not a blend.** `loadout` writes `LOADOUT.md`: the builder, the checker, the skills not to read, and which side wins each clash. Claude reads it before the skills and leans one way instead of averaging.
4. **The same path for Claude.** `apply`, `--rules` and the `loadout-guard` hook make Claude go through the same file a person would.
5. **A tidy list.** `place` suggests which skills should always be on, which should be listed by name only, and which can be turned off, so the list Claude chooses from stays short.

## Limits

- Stances come from sentence cues, not from understanding. See "Accuracy" in the README for measured precision and recall, and always open the evidence line.
- Only `SKILL.md` is read; rules kept in reference files are not seen.
- The axes are design axes (colour, type, layout, motion). Other kinds of conflict need new entries in `lexicon.json`.
