"""Presets de metal/proceso incluidos + profiles del usuario (profiles/*.json)."""

from __future__ import annotations

import json
from pathlib import Path

from spruegen.schemas import InputError, Profile, load_profile

PRESET_DIR = Path(__file__).parent / "presets"
DEFAULT = "ag925"


def _user_dir() -> Path:
    return Path.cwd() / "profiles"


def available() -> dict[str, Profile]:
    out = {}
    for d in (PRESET_DIR, _user_dir()):
        if d.is_dir():
            for f in sorted(d.glob("*.json")):
                try:
                    out[f.stem] = load_profile(f)
                except InputError:
                    continue
    return out


def resolve(ref) -> Path:
    if ref is None:
        return PRESET_DIR / f"{DEFAULT}.json"
    p = Path(ref)
    if p.suffix == ".json" or p.exists():
        if not p.exists():
            raise InputError(f"no existe el profile: {p}")
        return p
    for d in (_user_dir(), PRESET_DIR):
        cand = d / f"{ref}.json"
        if cand.exists():
            return cand
    names = ", ".join(sorted(f.stem for f in PRESET_DIR.glob("*.json")))
    raise InputError(f"profile desconocido: {ref!r}. Presets: {names} (o una ruta .json)")


def load(ref) -> Profile:
    return load_profile(resolve(ref))


def describe(ref) -> str:
    p = resolve(ref)
    return f"preset:{p.stem}" if p.parent == PRESET_DIR else str(p.resolve())


def new(name: str, from_: str, out_dir: Path) -> Path:
    src = load(from_)
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"{name}.json"
    if dst.exists():
        raise InputError(f"ya existe {dst}")
    data = src.model_dump()
    data["notes"] = f"copiado de {from_}; edita y calibra con `spruegen log`"
    dst.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return dst
