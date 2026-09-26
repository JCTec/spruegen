# Changelog

## 0.3.0 — 2026-09-26

### Architecture
- The package is split into layers: `mesh/`, `detect/`, `plan/`, `construct/`, `config/`, `materials/` and `report/`. Module contents are unchanged apart from their imports.
- New `spruegen.pipeline` holds the orchestration (`run_*`) that used to live in `cli.py`. The CLI, the GUI and the demo gallery all call the pipeline. `spruegen.cli` still re-exports `run_*` for 0.2 scripts.
- Exceptions moved to `spruegen.errors` (`spruegen.schemas` re-exports them).

### Metallurgy
- New `spruegen.materials`: a cited alloy database (23 alloys, 52 sources, 27 sprueing rules). Every value has a source and locator.
- `Profile.alloy` links a preset to the database, and `proposal.json` gets a `casting` sheet: grams of metal, pour and flask windows by section class, investment type, rule checks and bibliography.
- New CLI commands: `spruegen materials list | show | rules | check`.
- Presets now inherit through `"extends"`. New presets: `pt950`, `au18k_white_pd`. `bronze` is mapped to C87600 and `brass` to C85700.

### Open source
- Licensed under PolyForm Noncommercial 1.0.0 (code) and CC BY-NC-SA 4.0 (data).
- Added CONTRIBUTING, CI workflow, issue and PR templates, and an English README (the Spanish manual moved to `docs/README.es.md`).

## 0.2.0
- Feeding analysis (thermal modulus, set cover), spider and Y trees, vents, presets, casting log, render and gallery, local GUI.

## 0.1.0
- A single inner feeder and a Ø10 × 35 mm stem, with validation.
