# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-06

### Added
- `scan`, `budget`, `overlap`, `conflict`, `plan`, `report` (markdown, `--json`, `--html`), `loadout`, `apply`, `triggers`, `selftest`.
- `place`: suggests trunk / scene / name-only / drop for every skill, with the rule behind each, a `skillOverrides` fragment and a draft route table. Never writes `settings.json`.
- `bench`: exact-stance precision and recall against a hand-labelled gold set (`tests/gold/`), with Wilson 95% intervals.
- `hooks/loadout-guard.py`: a PreToolUse hook that warns when a skill listed under 読まない in `LOADOUT.md` is loaded.
- Japanese-to-English request words (`lexicon.json` `ja_en`), shared by `plan` and the HTML page.
- `--json` on every subcommand; exit codes 0 / 1 (clash or over budget) / 2 (error); `--force` and `--dry-run` for `loadout` and `apply`.

### Changed
- Renamed from skill-conductor; the CLI is `scripts/skill_clash.py` and the work folder is `.skill-clash/`.
- Default scan is what Claude sees: `~/.claude/skills` plus the skills of enabled plugins. `--dirs` adds roots instead of replacing them.

[Unreleased]: https://github.com/kawashimawataru/skill-clash/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/kawashimawataru/skill-clash/releases/tag/v0.1.0
