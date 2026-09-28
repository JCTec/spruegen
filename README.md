# spruegen

**Sprue trees for lost-wax ring casting, generated deterministically and backed by a cited alloy database.**

Give spruegen the STL of one ring. It gives back a printable, watertight sprue tree:

- **Feeders attach only to the inner face** of the shank. Lattice, filigree and engraving on the outside stay untouched, and this is checked to 0.05 mm.
- **A downstem sized to your rubber sprue base** (Ø10 × 35 mm by default, editable), or **no downstem**: the feeders end in a short stub you wax onto your own tree (`--stem off`, or *Stub only* in the app). Whatever size you choose is what validation checks.
- **The number and placement of feeders come from a feeding analysis.** It uses a thermal-modulus field (the Chvorinov proxy), directional-solidification paths, capacity limits and symmetry, not guesswork. You can also choose the layout yourself: single, spider or Y.
- **Optional vent rods** go where the metal arrives last.
- **A casting sheet for your alloy.** It gives grams of metal, pour and flask temperature windows for the ring's wall thickness, the investment type, and rule checks. Every number cites the paper or datasheet it came from.

There's no CFD and no LLM at runtime. The same input always gives the same tree.

![spruegen GUI](docs/gui.png)

> **Status:** v0.4 — working CLI + local web GUI, used in a real Ag925 vacuum-casting shop. The feeding parameters are starting values that you should calibrate against your own casts (`spruegen log`).

## Install

macOS / Linux with [Homebrew](https://brew.sh):

```bash
brew install jctec/spruegen/spruegen
```

From source:

```bash
git clone https://github.com/JCTec/spruegen && cd spruegen
python3 -m venv .venv                       # Python 3.11+
.venv/bin/pip install -e ".[gui,dev]"       # manifold3d / shapely / rtree ship as binary wheels
.venv/bin/pytest -q
```

## Use it

**App** (local, nothing leaves your machine):

```bash
spruegen gui            # opens http://127.0.0.1:8765
```

Load the STL, pick a metal and tree type, then Analyze (optional), Generate and Export. Export is only enabled when every validation check passes.

**CLI:**

```bash
spruegen analyze  ring.stl -o analysis/              # how many feeders, where, and where metal arrives last
spruegen propose  ring.stl -p au18k -o workdir/      # plan + previews; never writes out.stl
spruegen apply    workdir/proposal.json -o out.stl   # boolean union + validation; writes only if all checks pass
spruegen validate out.stl --proposal workdir/proposal.json
spruegen materials show au18y --section thin         # cited alloy data
```

| Command | What it does |
|---|---|
| `inspect` | finger axis, radii, wall thickness, attach candidates (JSON) |
| `analyze` | thermal-modulus map, feeding zones, suggested feeder count, last-to-fill spots |
| `propose` | `proposal.json` (including the `casting` sheet) and `preview_ring/sprues/vents.stl` |
| `apply` / `validate` | union, then checks: watertight, one body, stem size, finger hole clear, outer face unchanged, locks |
| `render` / `demo` / `batch` | images and HTML cards, example gallery, one job per STL in a folder |
| `profile list/show/new` | presets (alloy + process + shop rules) |
| `materials list/show/rules/check` | the alloy database |
| `log add/summary` | casting log to calibrate feeding parameters |

## Presets and alloys

Presets hold shop rules. The metallurgy lives in the alloy database, and presets inherit from each other:

```json
{ "extends": "au14k", "metal": "Au18k", "alloy": "au18y" }
```

The bundled presets are `ag925`, `ag925_centrifugal`, `au14k`, `au18k`, `au18k_white_pd`, `bronze`, `brass` and `pt950`. The database holds 23 alloys: sterling and Argentium, 10–18K yellow, red and white golds, Pt950 (Ru and Co), Pd950, silicon and tin bronzes, and brasses. It has 52 sources, 27 published sprueing rules, and a citation on every value. See [docs/MATERIALS.md](docs/MATERIALS.md).

## How it decides

1. **Axis and faces.** It finds the finger axis with PCA and a best-fit circle, confirmed by a tunnel test. It then fans rays out from the axis: the first hit is the inner face, the second is the outer face, and the difference is the wall thickness.
2. **Where an attach *can* go.** The wall must be at least the minimum thickness, the feeder's whole footprint must sit on a solid patch (this rules out lattice), and at least 0.3 mm of outer skin must remain.
3. **Where an attach *should* go.** It voxelises the ring and uses the distance transform as a thermal modulus. A cell counts as fed if the widest path from the feeder to it never narrows below `neck_ratio` × the cell's modulus and stays within reach. A greedy set cover with reverse delete picks the feeders, subject to a minimum set by capacity and a preference for symmetry. Heads and settings are detected and handled.
4. **Routing.** Each layout (direct, spider or Y) respects the feeder length and angle windows. A Y trunk keeps the gating area of its arms. Candidates that fail a check fall back to nearby alternates, and nothing ever attaches to the outside.

The architecture and roadmap are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). The Spanish v0.2 manual is [docs/README.es.md](docs/README.es.md).

## Contributing

Code, alloy data with citations, and reports from real casts are all welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

- **Code:** [MIT](LICENSE).
- **Alloy dataset:** [CC BY 4.0](spruegen/materials/data/LICENSE.md). If you reuse it, credit the spruegen alloy database and keep the per-value source citations.

Casting involves molten metal at up to 2000 °C. spruegen gives geometric and literature-based guidance, not a guarantee. Always follow your equipment's and your alloy supplier's instructions.
