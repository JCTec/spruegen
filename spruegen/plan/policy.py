"""Reglas del profile: locks, overrides, dimensiones de feeder. El ruteo geométrico vive en tree.py.

Layout v1 (frame del job, Z arriba, mm):
  - stem Ø stem_d x stem_h, vertical, base en z=0, tapa en z=stem_h, centrado en x=y=0.
  - el eje del dedo del anillo queda coaxial con el stem (anillo "acostado" sobre el stem):
    el hueco del dedo mira hacia el stem, así el feeder sale de la cara interna, baja por la
    boca del hueco y llega al nudo en la tapa del stem sin tocar nunca la cara externa.
  - el attach queda en -Y.
  - feeder_angle_deg = ángulo entre el feeder y el eje del stem.
"""

from __future__ import annotations

import math

import numpy as np
import trimesh

from spruegen.schemas import Job, PolicyError, Profile, Stem

LOCKABLE = set(Profile.model_fields) - {"lock"}
PEN_RANGE = (0.4, 0.8)
SKIN_MARGIN_MM = 0.3  # piel mínima de la cara externa que el feeder nunca toca
CLEARANCE_MM = 0.1


def effective_locks(profile: Profile, job: Job) -> list[str]:
    return sorted(set(profile.lock) | set(job.lock))


def apply_overrides(profile: Profile, job: Job) -> tuple[Profile, list[str]]:
    """Aplica job.overrides; prohibido tocar claves bloqueadas."""
    locks = effective_locks(profile, job)
    unknown = set(job.overrides) - LOCKABLE
    if unknown:
        raise PolicyError(f"overrides desconocidos en job.json: {sorted(unknown)}")
    blocked = sorted(k for k in job.overrides if k in locks and job.overrides[k] != getattr(profile, k))
    if blocked:
        raise PolicyError(
            f"job.json intenta cambiar claves bloqueadas: {blocked}. "
            "Quita el lock (en el profile y en el job) si de verdad quieres cambiarlas."
        )
    if not job.overrides:
        return profile, []
    data = profile.model_dump()
    data.update(job.overrides)
    return Profile.model_validate(data), [f"override explícito: {k}={v}" for k, v in job.overrides.items()]


def lock_values(profile: Profile, locks: list[str]) -> dict:
    return {k: getattr(profile, k) for k in locks if k in LOCKABLE}


def check_locks(locked: dict, stem: Stem, profile: Profile) -> list[str]:
    """Devuelve lista de violaciones (vacía = locks respetados)."""
    actual = {
        "stem_d_mm": stem.d_mm,
        "stem_h_mm": stem.h_mm,
        "attach_mode": profile.attach_mode,
        "keepout": profile.keepout,
    }
    bad = []
    for k, v in locked.items():
        a = actual.get(k, getattr(profile, k, None))
        if isinstance(v, float) or isinstance(a, float):
            same = a is not None and abs(float(a) - float(v)) < 1e-9
        elif isinstance(v, list):
            same = set(v) <= set(a or [])
        else:
            same = a == v
        if not same:
            bad.append(f"{k}: bloqueado={v!r}, plan={a!r}")
    return bad


def feeder_diameter(thickness: float, p: Profile) -> float:
    return float(np.clip(thickness * p.feeder_d_factor, p.feeder_d_min_mm, p.feeder_d_max_mm))


def solve_feeder(r_in: float, R: float, p: Profile):
    """Busca (rho, alpha, L): nudo a distancia rho del eje sobre la tapa del stem.

    horizontal = r_in - rho, L = horizontal / sin(alpha). Minimiza |L - default|.
    """
    stem_r = p.stem_d_mm / 2
    rho_max = max(0.0, stem_r - R)
    a_lo, a_hi = (math.radians(a) for a in p.feeder_angle_deg)
    L_lo, L_hi = p.feeder_len_mm
    a_mid = (a_lo + a_hi) / 2
    best = None
    for rho in np.linspace(0.0, rho_max, 41):
        hz = r_in - rho
        if hz <= 0:
            continue
        a = math.asin(min(1.0, hz / p.feeder_len_default_mm))
        a = min(max(a, a_lo), a_hi)
        L = hz / math.sin(a)
        if not (L_lo - 1e-9 <= L <= L_hi + 1e-9):
            continue
        cost = abs(L - p.feeder_len_default_mm) + 0.05 * abs(a - a_mid)
        if best is None or cost < best[0]:
            best = (cost, float(rho), float(a), float(L))
    return best
