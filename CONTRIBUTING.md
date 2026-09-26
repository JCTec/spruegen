# Contributing to spruegen

Thanks for helping. There are three kinds of contribution, and all of them matter.

## 1. Code

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[gui,dev]"
.venv/bin/pytest -q            # the whole suite must be green
.venv/bin/ruff check spruegen tests
```

- Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) first. Imports only point downward: `cli`/`gui` → `pipeline` → `plan`/`construct` → `detect`/`mesh` → `schemas`/`errors`.
- Keep behaviour deterministic. Use no randomness, and no network access at runtime.
- Never put a sprue on the outer face "because it's easier", and never change locked keys by heuristic.
- A geometry change needs a test on a parametric ring (`tests/fixtures/rings.py` or `spruegen/report/showcase.py`).
- Engine messages are in Spanish for now. New diagnostics should carry a stable `code` plus `params` (see `materials/casting.py`), so they can be translated without regular expressions.

## 2. Alloy data

The alloy database is only as good as its citations. See [docs/MATERIALS.md](docs/MATERIALS.md):

- Every number needs a `source` and a `locator`. Values you compute yourself use `"source": "derived"` and a `method`.
- Put disagreeing values in `alt[]`, not in place of the existing value.
- Run `spruegen materials check` and `pytest tests/test_materials.py`.
- Open the PR with the *data* template.

## 3. Casting results

Real casts are how the feeding parameters get calibrated. After casting a proposal, run:

```bash
spruegen log add workdir/proposal.json --result good|porosity|misrun|cold_shut|shrinkage --note "..."
```

Then open an issue with the *cast report* template and attach `casts.jsonl` plus a photo if you can.

## License of contributions

By contributing you agree that your code is licensed under the project's [PolyForm Noncommercial 1.0.0](LICENSE) license and your data under [CC BY-NC-SA 4.0](spruegen/materials/data/LICENSE.md). You also allow the maintainer to offer the project under additional licenses, such as a commercial license, in the future.

## Conduct

Be kind and specific, and assume good faith. Harassment isn't tolerated. The maintainer may remove comments or contributors that break this.
