# Materials database

`spruegen/materials/data/alloys.json` is the **single source of truth** for metallurgical numbers. Code never hard-codes an alloy property: it calls `spruegen.materials.load()`. For the coverage table, the conflicts between sources and the known gaps, see [`PROVENANCE.md`](../spruegen/materials/data/PROVENANCE.md).

```bash
spruegen materials list                    # 23 alloys: family, melting range, density
spruegen materials show ag925 --section thin
spruegen materials rules                   # 27 published sprueing rules
spruegen materials check my_alloys.json    # validate a custom file
```

## Principles

1. **No number without a source.** Every numeric value has a `source` (an id in `sources`) and a `locator` (table, page or quoted line). Values you compute yourself use `"source": "derived"` and must include `"method"`. CI enforces this in `tests/test_materials.py`.
2. **Keep disagreements visible.** When sources differ, the primary value (peer-reviewed or Santa Fe Symposium papers first, then handbooks, then vendor datasheets) goes in `value` / `min` / `max`. The others go in `alt[]`. Never average them silently.
3. **Leave a value out rather than guess.** A missing property shows up as missing in the casting sheet, which is better than a made-up number.
4. **Datasheets are vendor-specific.** They're allowed, with `type: "datasheet"`, because they are often the only source for pour and flask temperatures. Always check against the datasheet for your own alloy.

## Schema (v1)

```jsonc
{
  "schema_version": 1,
  "sources": {
    "fb2022": { "title": "...", "authors": "...", "year": 2022, "venue": "Santa Fe Symposium",
                "url": "...", "type": "paper|handbook|datasheet|standard|book", "accessed": "2026-09-26" }
  },
  "alloys": {
    "ag925": {
      "name": "Sterling silver 925 (Ag-Cu)", "family": "silver", "fineness": 925,
      "investment": "gypsum",                       // or "phosphate" (Pt, Pd, high-melting alloys)
      "composition_wt_pct": {"Ag": 92.5, "Cu": 7.5},
      "properties": {
        "density_g_cm3": {"value": 10.4, "source": "umicore2021", "locator": "...", "alt": [ ... ]},
        "solidus_c":     {"value": 780,  "source": "fb2022", "locator": "Table 3"},
        "liquidus_c":    {"value": 900,  "source": "fb2022", "locator": "Table 3"},
        "pour_c":  {"min": 935, "max": 985, "source": "...",            // overall window
                    "by_piece": {"thin": [..], "medium": [..], "heavy": [..]}},   // optional
        "flask_c": {"heavy": {"min":..,"max":..}, "thin": {..}, "medium": {..},  // or "general"
                    "source": "...", "method": "vacuum|centrifugal"},
        "shrinkage_vol_pct": {...}, "shrinkage_linear_pct": {...},
        "thermal_conductivity_w_mk": {...}, "specific_heat_j_kgk": {...}, "latent_heat_kj_kg": {...}
      },
      "notes": [{"text": "Wide freezing range (~120 K) ...", "source": "fb2022"}]
    }
  },
  "rules": [
    {"id": "feeder_125pct", "statement": "...", "value": {"min_ratio": 1.25}, "source": "hs_jeff", "locator": "..."}
  ]
}
```

## How spruegen uses it

- **Presets** name an alloy (`"alloy": "au18y"`). The label in `metal` is for display only.
- **Casting sheet**: `proposal.json → casting`, and `/api/{sid}/generate → casting` in the GUI. It contains:
  - section class, from the median wall thickness (< 0.5 thin, ≤ 1.2 medium, otherwise heavy; the Legor/Rio Grande split);
  - pour and flask windows for that class, each with its source;
  - metal mass for the ring, the tree and the total. The tree figure sums the part volumes without subtracting overlaps, so it runs slightly high;
  - rule checks, each carrying a stable `code`:
    - `feeder_thinner_than_section`: feeder Ø smaller than the thickness it feeds (Stuller)
    - `phosphate_investment`: the alloy needs phosphate-bonded investment
    - `pour_above_gypsum_limit`: pour temperature above ~1200 °C, where gypsum breaks down and releases SO₂
  - the bibliography of the sources actually used.
- **Not used yet:** feeding reach, capacity and neck ratio remain shop-calibrated. No mould constant for gypsum investment has been published (rule `mould_constant_gypsum`), so absolute solidification times can't be computed. See the roadmap in [ARCHITECTURE.md](ARCHITECTURE.md).

## Adding or correcting an alloy

1. Add the source to `sources` first. Use a stable id such as `author_year` or `vendor_product`, and include the URL and access date.
2. Add or edit the alloy. Every number needs `source` and `locator`. If you convert units, keep the original in the locator, for example `"Cast Temp 1715-1805F (converted)"`.
3. If your value disagrees with the existing one, add it to `alt[]` and explain in the PR which one should be primary and why.
4. Run `spruegen materials check` and `pytest tests/test_materials.py`.
5. Open a PR with the **data** template. Reviewers will check the citation against the source.

## License of the data

The dataset (`alloys.json`, `PROVENANCE.md`) is a compilation of published facts with citations. It is licensed **CC BY-NC-SA 4.0** (see [`spruegen/materials/data/LICENSE.md`](../spruegen/materials/data/LICENSE.md)). If you reuse it, cite this project and keep the per-value source citations.
