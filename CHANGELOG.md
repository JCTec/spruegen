# Changelog

## 0.4.0 — 2026-09-27

### License
- The code is now MIT (was PolyForm Noncommercial 1.0.0) and the alloy dataset is CC BY 4.0 (was CC BY-NC-SA 4.0). Commercial use is allowed.
- Installable with Homebrew: `brew install jctec/spruegen/spruegen`.

### Stem
- The downstem is editable: `--stem 12x40` on `propose`/`batch`, or the Ø and length fields in the app. The chosen size is what locks and validation check; the fixed "standard Ø10 × 35" warning is gone.
- The downstem is optional: `--stem off` (or *Stub only* in the app) ends the feeders in a short stub (`stub_d_mm` × `stub_h_mm`, Ø6 × 5 by default) to wax onto your own tree. It's planned as a small stem, so routing and every check still apply.
- New profile keys `stem_kind`, `stub_d_mm`, `stub_h_mm`; `stem_kind` is locked by default, so `job.json` can't switch it.

### App
- Disabled fields now look disabled, and static files are revalidated on every load so edits show up after a refresh.

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
