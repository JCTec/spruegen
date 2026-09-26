"""Bitácora de coladas (casts.jsonl): qué árbol se usó y cómo salió, para calibrar alcance/capacidad."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .schemas import InputError, Proposal

RESULTS = ("good", "porosity", "misrun", "cold_shut", "shrinkage", "other")


def add(prop: Proposal, result: str, note: str, log_file: Path) -> dict:
    if result not in RESULTS:
        raise InputError(f"--result debe ser uno de: {', '.join(RESULTS)}")
    p = prop.profile
    rec = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ring": Path(prop.input["path"]).name,
        "sha256": prop.input["sha256"],
        "volume_mm3": prop.input["volume_mm3"],
        "metal": p.metal,
        "process": p.process,
        "tree": prop.tree.get("used", "single"),
        "feeders": len(prop.feeders),
        "feeder_d_mm": [round(f.d_mm, 2) for f in prop.feeders],
        "vents": len(prop.vents),
        "coverage": prop.analysis["coverage"] if prop.analysis else None,
        "params": {
            "feed_reach_mm": p.tree.feed_reach_mm,
            "feeder_capacity_mm3": p.tree.feeder_capacity_mm3,
            "neck_ratio": p.tree.neck_ratio,
        },
        "result": result,
        "note": note,
    }
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def read(log_file: Path) -> list[dict]:
    if not log_file.exists():
        return []
    return [json.loads(line) for line in log_file.read_text().splitlines() if line.strip()]


def summary_text(log_file: Path) -> str:
    recs = read(log_file)
    if not recs:
        return f"sin registros en {log_file}"
    groups: dict[tuple, Counter] = defaultdict(Counter)
    for r in recs:
        groups[(r["metal"], r["process"], r["feeders"])][r["result"]] += 1
    lines = [f"{len(recs)} coladas en {log_file}", ""]
    lines.append(f"{'metal':8s} {'proceso':12s} {'feeders':>7s}  resultados")
    for (metal, proc, nf), cnt in sorted(groups.items()):
        tot = sum(cnt.values())
        good = cnt.get("good", 0)
        res = ", ".join(f"{k} {v}" for k, v in cnt.most_common())
        lines.append(f"{metal:8s} {proc:12s} {nf:>7d}  {good}/{tot} buenas — {res}")
    bad = [r for r in recs if r["result"] in ("porosity", "shrinkage", "misrun") and r.get("coverage") is not None]
    if bad:
        lines += ["", "sugerencia: con porosidad/rechupe o llenado incompleto, baja feed_reach_mm o "
                  "feeder_capacity_mm3 en tu profile (más feeders) y vuelve a correr propose."]
    return "\n".join(lines)
