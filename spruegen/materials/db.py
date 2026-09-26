"""Alloy database: the single source of truth for metallurgical numbers.

Every value in ``data/alloys.json`` carries a citation (``source`` id + ``locator``) into the
``sources`` table, or ``"source": "derived"`` plus the ``method`` used. Code never hard-codes
alloy properties; it asks this module.

The JSON is intentionally permissive (sources disagree and report ranges in different shapes),
so the loader keeps the raw dicts and exposes a small typed API on top.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from spruegen.errors import InputError

DERIVED = "derived"


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    authors: str | None = None
    year: int | str | None = None
    venue: str | None = None
    url: str | None = None
    type: str | None = None

    def cite(self) -> str:
        who = f"{self.authors}, " if self.authors else ""
        yr = f" ({self.year})" if self.year else ""
        return f"{who}{self.title}{yr}" + (f" — {self.url}" if self.url else "")


@dataclass(frozen=True)
class Value:
    """A cited scalar or range. ``lo == hi`` for scalars."""

    lo: float
    hi: float
    source: str
    locator: str | None = None
    method: str | None = None

    @property
    def mid(self) -> float:
        return (self.lo + self.hi) / 2

    @property
    def derived(self) -> bool:
        return self.source == DERIVED

    def fmt(self, unit: str = "", nd: int = 0) -> str:
        if abs(self.hi - self.lo) < 1e-9:
            return f"{self.lo:.{nd}f}{unit}"
        return f"{self.lo:.{nd}f}–{self.hi:.{nd}f}{unit}"


def _value(d: Any, source: str | None = None, locator: str | None = None) -> Value | None:
    if d is None:
        return None
    if isinstance(d, (int, float)):
        return Value(float(d), float(d), source or "?", locator)
    if isinstance(d, (list, tuple)) and len(d) == 2:
        return Value(float(d[0]), float(d[1]), source or "?", locator)
    if not isinstance(d, dict):
        return None
    src = d.get("source", source) or "?"
    loc = d.get("locator", locator)
    meth = d.get("method")
    if "value" in d:
        v = d["value"]
        if isinstance(v, (list, tuple)) and len(v) == 2:
            return Value(float(v[0]), float(v[1]), src, loc, meth)
        if isinstance(v, (int, float)):
            return Value(float(v), float(v), src, loc, meth)
        return None
    if "min" in d and "max" in d:
        return Value(float(d["min"]), float(d["max"]), src, loc, meth)
    return None


@dataclass
class Alloy:
    id: str
    name: str
    family: str
    investment: str
    composition_wt_pct: dict[str, float]
    raw: dict[str, Any] = field(repr=False)

    def prop(self, key: str) -> Value | None:
        return _value(self.raw.get("properties", {}).get(key))

    @property
    def density_g_cm3(self) -> Value | None:
        return self.prop("density_g_cm3")

    @property
    def solidus_c(self) -> Value | None:
        return self.prop("solidus_c")

    @property
    def liquidus_c(self) -> Value | None:
        return self.prop("liquidus_c")

    @property
    def freezing_range_k(self) -> float | None:
        s, liq = self.solidus_c, self.liquidus_c
        return None if s is None or liq is None else liq.mid - s.mid

    def pour_c(self, section: str = "heavy") -> Value | None:
        """Pour temperature; ``section`` = 'thin' | 'medium' | 'heavy' when the source splits by piece."""
        d = self.raw.get("properties", {}).get("pour_c")
        if not d:
            return None
        by = d.get("by_piece")
        if isinstance(by, dict) and by:
            pick = _pick_piece(by, section)
            if pick is not None:
                return _value(pick, d.get("source"), d.get("locator"))
        return _value(d)

    def flask_c(self, section: str = "heavy") -> Value | None:
        d = self.raw.get("properties", {}).get("flask_c")
        if not d:
            return None
        src = d.get("thin_source", d.get("source")) if section == "thin" else d.get("source")
        for k in (section, "heavy" if section == "medium" else section, "general"):
            if k in d:
                return _value(d[k], src, d.get("locator"))
        by = d.get("by_piece")
        if isinstance(by, dict) and by:
            return _value(_pick_piece(by, section), d.get("source"), d.get("locator"))
        return None

    def notes(self) -> list[dict]:
        return list(self.raw.get("notes", []))

    def citations(self) -> set[str]:
        out: set[str] = set()

        def walk(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    if k in ("source", "thin_source") and isinstance(v, str) and v != DERIVED:
                        out.add(v)
                    else:
                        walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)

        walk(self.raw)
        return out


def _pick_piece(by: dict, section: str):
    order = {"thin": ["thin", "light", "small", "<0.5", "filigree"],
             "medium": ["medium", "0.5-1.2", "regular"],
             "heavy": ["heavy", "large", ">1.2", "thick"]}[section]
    for want in order:
        for k, v in by.items():
            if want in k.lower():
                return v
    return next(iter(by.values()))


@dataclass
class Rule:
    id: str
    statement: str
    source: str
    locator: str | None
    value: Any = None


@dataclass
class AlloyDB:
    alloys: dict[str, Alloy]
    sources: dict[str, Source]
    rules: dict[str, Rule]
    path: str

    def get(self, alloy_id: str) -> Alloy:
        try:
            return self.alloys[alloy_id]
        except KeyError:
            raise InputError(f"aleación desconocida: {alloy_id!r}. Disponibles: {', '.join(sorted(self.alloys))}")

    def source(self, sid: str) -> Source | None:
        return self.sources.get(sid)

    def rule(self, rid: str) -> Rule | None:
        return self.rules.get(rid)

    def bibliography(self, ids) -> list[Source]:
        return [self.sources[i] for i in sorted(ids) if i in self.sources]


def parse(data: dict, path: str = "<memory>") -> AlloyDB:
    sources = {
        k: Source(id=k, **{f: v.get(f) for f in ("title", "authors", "year", "venue", "url", "type")})
        for k, v in data.get("sources", {}).items()
    }
    alloys = {
        k: Alloy(
            id=k,
            name=v.get("name", k),
            family=v.get("family", "?"),
            investment=v.get("investment", "gypsum"),
            composition_wt_pct=dict(v.get("composition_wt_pct") or {}),
            raw=v,
        )
        for k, v in data.get("alloys", {}).items()
    }
    rules = {
        r["id"]: Rule(id=r["id"], statement=r["statement"], source=r.get("source", "?"),
                      locator=r.get("locator"), value=r.get("value"))
        for r in data.get("rules", [])
    }
    return AlloyDB(alloys=alloys, sources=sources, rules=rules, path=path)


def check(db: AlloyDB) -> list[str]:
    """Integrity problems: every cited source must exist in the sources table."""
    problems = []
    known = set(db.sources) | {DERIVED}
    for a in db.alloys.values():
        for s in a.citations():
            if s not in known:
                problems.append(f"{a.id}: fuente desconocida {s!r}")
    for r in db.rules.values():
        if r.source not in known:
            problems.append(f"rule {r.id}: fuente desconocida {r.source!r}")
    return problems


@lru_cache(maxsize=4)
def load(path: str | None = None) -> AlloyDB:
    """Bundled database (default) or a user file with the same schema."""
    if path is None:
        ref = resources.files("spruegen.materials") / "data" / "alloys.json"
        return parse(json.loads(ref.read_text(encoding="utf-8")), str(ref))
    p = Path(path)
    if not p.exists():
        raise InputError(f"no existe la base de aleaciones: {p}")
    return parse(json.loads(p.read_text(encoding="utf-8")), str(p))
