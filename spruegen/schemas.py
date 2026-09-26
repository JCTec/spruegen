"""Pydantic v2 schemas: profile (reglas de taller), job (este anillo), proposal (plan no aplicado)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from spruegen.errors import FeatureError, InputError, PolicyError, SpruegenError  # noqa: F401  (re-export)

DEFAULT_LOCKS = ["stem_d_mm", "stem_h_mm", "attach_mode", "keepout"]
KEEPOUTS = {"finger_hole", "outer_surface", "lattice_thin"}

Vec3 = list[float]




class TreeConfig(BaseModel):
    """Cómo se reparte el metal: cuántos feeders, dónde y con qué forma de árbol."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["single", "spider", "y", "auto"] = "auto"
    feeders: int | None = Field(None, ge=1, le=6)  # forzar cantidad (spider / y)
    max_feeders: int = Field(4, ge=1, le=6)
    neck_ratio: float = Field(0.8, gt=0, le=1.5)  # cuello mínimo / módulo de la zona alimentada
    feed_reach_mm: float = Field(40.0, gt=0)  # distancia geodésica que alcanza un feeder
    feeder_capacity_mm3: float = Field(900.0, gt=0)  # volumen que alimenta un feeder (~9.4 g de Ag925)
    min_gain_frac: float = Field(0.05, ge=0, le=1)  # un feeder extra debe alimentar >= 5% más
    prefer_symmetry: bool = True
    angle_tolerance_deg: float = Field(20.0, ge=0, le=60)
    uniform: bool = True  # mismo Ø para todos los feeders (el del attach más delgado)
    y_merge_deg: float = Field(90.0, ge=0, le=180)  # en auto: attaches más cercanos que esto comparten tronco (Y)
    arm_angle_deg: float = Field(45.0, gt=10, lt=80)  # ángulo nominal de los brazos de la Y (desde vertical)
    arm_len_mm: tuple[float, float] = (3.0, 14.0)
    y_branch_radius_frac: float = Field(0.45, gt=0, lt=1)
    trunk_min_len_mm: float = Field(3.0, gt=0)
    trunk_d_max_mm: float = Field(4.5, gt=0)
    hub: Literal["none", "cone"] = "none"
    voxel_mm: float | None = None  # None = automático


class VentConfig(BaseModel):
    """Varillas de rebalse/venteo en el extremo lejano del anillo (arriba al imprimir, abajo al colar)."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["off", "auto", "count"] = "off"
    count: int = Field(2, ge=1, le=6)
    d_mm: float = Field(1.2, gt=0)
    len_mm: float = Field(5.0, gt=0)
    min_sep_deg: float = Field(60.0, ge=0)
    overlap_mm: float = Field(1.2, gt=0)  # cuánto baja la varilla pegada a la pared interna
    pen_mm: float = Field(0.3, gt=0)  # cuánto se mete en el metal


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metal: str = "Ag925"  # etiqueta legible; los datos metalúrgicos vienen de `alloy`
    alloy: str | None = None  # id en spruegen/materials/data/alloys.json (fuente única de propiedades)
    process: str = "vacuum"
    units: Literal["mm"] = "mm"
    stem_d_mm: float = Field(10.0, gt=0)
    stem_h_mm: float = Field(35.0, gt=0)
    ring_space_mm: float = Field(40.0, gt=0)
    button_d_mm: float = Field(40.0, gt=0)
    feeder_len_mm: tuple[float, float] = (8.0, 12.0)
    feeder_len_default_mm: float = 10.0
    feeder_angle_deg: tuple[float, float] = (25.0, 45.0)
    feeder_d_factor: float = Field(1.2, gt=0)
    feeder_d_min_mm: float = Field(2.4, gt=0)
    feeder_d_max_mm: float = Field(3.5, gt=0)
    attach_mode: Literal["inner_shank"] = "inner_shank"
    keepout: list[str] = Field(default_factory=lambda: ["finger_hole", "outer_surface", "lattice_thin"])
    join_fillet_r_mm: float = Field(0.8, ge=0)
    boolean_overlap_mm: float = Field(0.4, ge=0)
    min_attach_thickness_mm: float = Field(1.6, gt=0)
    # extras con default (no hace falta ponerlos en el JSON)
    lock: list[str] = Field(default_factory=lambda: list(DEFAULT_LOCKS))
    stem_d_tol_mm: float = 0.2
    stem_h_tol_mm: float = 0.5
    hole_test_radius_frac: float = 0.6
    hole_block_max_frac: float = 0.5
    tree: TreeConfig = Field(default_factory=TreeConfig)
    vents: VentConfig = Field(default_factory=VentConfig)
    notes: str | None = None

    @field_validator("keepout")
    @classmethod
    def _known_keepouts(cls, v: list[str]) -> list[str]:
        unknown = set(v) - KEEPOUTS
        if unknown:
            raise ValueError(f"keepout desconocido: {sorted(unknown)}; válidos: {sorted(KEEPOUTS)}")
        return v

    @model_validator(mode="after")
    def _ranges(self) -> "Profile":
        if self.feeder_len_mm[0] > self.feeder_len_mm[1]:
            raise ValueError("feeder_len_mm debe ser [min, max]")
        if self.feeder_angle_deg[0] > self.feeder_angle_deg[1]:
            raise ValueError("feeder_angle_deg debe ser [min, max]")
        if self.feeder_d_min_mm > self.feeder_d_max_mm:
            raise ValueError("feeder_d_min_mm > feeder_d_max_mm")
        return self


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stl: str | None = None
    up_axis: Literal["z"] = "z"
    finger_axis_hint: Vec3 | None = None
    lock: list[str] = Field(default_factory=lambda: ["stem_d_mm", "stem_h_mm", "attach_mode"])
    manual_attach: Vec3 | None = None
    # cambios explícitos al profile para este job; prohibidos sobre claves bloqueadas
    overrides: dict[str, Any] = Field(default_factory=dict)

    @field_validator("finger_axis_hint", "manual_attach")
    @classmethod
    def _len3(cls, v):
        if v is not None and len(v) != 3:
            raise ValueError("debe ser [x, y, z]")
        return v


class Candidate(BaseModel):
    point: Vec3  # punto sobre la cara interna (frame del STL de entrada)
    theta_deg: float
    h_mm: float  # posición axial relativa al centro del aro
    r_inner_mm: float
    r_outer_mm: float
    thickness_mm: float


class Features(BaseModel):
    axis: Vec3
    axis_source: str
    center: Vec3
    com: Vec3
    volume_mm3: float
    bbox: list[Vec3]
    band_width_mm: float
    inner_radius_mm: float  # círculo best-fit del hueco
    inner_radius_min_mm: float
    outer_radius_max_mm: float
    inner_thickness_max_mm: float
    tunnel_open_frac: float
    scan: dict[str, Any]
    head_detected: bool
    head_theta_deg: float | None = None
    candidates: list[Candidate]
    warnings: list[str] = Field(default_factory=list)


class Attach(BaseModel):
    point_input: Vec3
    point_job: Vec3
    theta_deg: float
    h_mm: float
    r_inner_mm: float
    r_outer_mm: float
    thickness_mm: float
    manual: bool
    reason: str


class Stem(BaseModel):
    d_mm: float
    h_mm: float
    origin: Vec3  # centro de la base
    axis: Vec3


class Sphere(BaseModel):
    center: Vec3
    r_mm: float
    role: str


class Feeder(BaseModel):
    d_mm: float
    len_mm: float  # nudo en la tapa del stem -> cara interna
    angle_deg: float  # ángulo respecto al eje del stem
    node: Vec3  # punto sobre la tapa del stem (z = stem_h)
    attach: Vec3  # punto sobre la cara interna
    start: Vec3  # extremo real del cilindro (dentro del stem)
    end: Vec3  # extremo real del cilindro (dentro del metal del anillo)
    penetration_mm: float  # a lo largo del eje, más allá de la cara interna
    outward_depth_mm: float  # cuánto se mete radialmente en el shank (máx)
    stem_overlap_mm: float
    clip_r_mm: float  # feeder + filete se recortan con un cilindro coaxial de este radio (nunca más hondo)
    ring_fillet: Sphere | None = None
    node_kind: Literal["stem", "branch"] = "stem"


class Branch(BaseModel):
    """Tronco de una Y: del nudo en el stem al punto de bifurcación."""

    start: Vec3
    end: Vec3
    d_mm: float
    arms: list[int]  # índices de feeders que salen de este tronco
    area_clipped: bool = False


class Vent(BaseModel):
    base: Vec3  # eje de la varilla, extremo inferior (pegado a la pared interna)
    top: Vec3
    d_mm: float
    clip_r_mm: float
    theta_deg: float  # ángulo en el frame del STL de entrada
    attach_thickness_mm: float


class Hub(BaseModel):
    z0: float
    z1: float
    r0: float
    r1: float


class Proposal(BaseModel):
    schema_version: int = 2
    spruegen_version: str
    input: dict[str, Any]  # path, sha256, bbox, volume, faces, repair
    profile_path: str | None
    profile: Profile  # profile efectivo (tras overrides)
    job: Job
    features: Features
    attach: Attach  # attach primario (ancla del frame)
    attaches: list[Attach] = Field(default_factory=list)  # todos, en orden de feeders
    transform: list[list[float]]  # 4x4, input -> frame del job
    stem: Stem
    feeders: list[Feeder]
    branches: list[Branch] = Field(default_factory=list)
    fillets: list[Sphere]  # nudos (stem / bifurcación)
    vents: list[Vent] = Field(default_factory=list)
    hub: Hub | None = None
    tree: dict[str, Any] = Field(default_factory=dict)  # modo pedido/usado + razón
    analysis: dict[str, Any] | None = None  # resumen de `analyze`
    casting: dict[str, Any] | None = None  # hoja de colada: masa, temperaturas, reglas (spruegen.materials)
    ring_job: dict[str, Any]  # bbox, volumen, z span, r_inner en frame del job
    previews: dict[str, str]
    locks: dict[str, Any]  # effective, values
    locks_honored: bool
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _upgrade_v1(cls, data: Any) -> Any:
        """proposal v1 (un solo `feeder`) -> v2 (`feeders` + filete del anillo dentro del feeder)."""
        if isinstance(data, dict) and "feeder" in data and "feeders" not in data:
            data = dict(data)
            f = dict(data.pop("feeder"))
            fillets = list(data.get("fillets", []))
            ring = [x for x in fillets if x.get("role") == "ring_join"]
            f.setdefault("ring_fillet", ring[0] if ring else None)
            data["fillets"] = [x for x in fillets if x.get("role") != "ring_join"]
            data["feeders"] = [f]
            data.setdefault("attaches", [data.get("attach")])
            data["schema_version"] = 2
        return data

    @property
    def feeder(self) -> Feeder:
        """Feeder primario (compatibilidad v1)."""
        return self.feeders[0]


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def read_profile_data(path: str | Path, _seen: tuple = ()) -> dict:
    """JSON del profile con herencia: `"extends": "ag925"` (preset o ruta) + solo las diferencias."""
    path = Path(path)
    if path.resolve() in _seen:
        raise InputError(f"herencia circular de profiles: {path}")
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        raise InputError(f"no existe el profile: {path}")
    except json.JSONDecodeError as e:
        raise InputError(f"profile inválido ({path}): {e}")
    base_ref = data.pop("extends", None)
    if base_ref is None:
        return data
    local = path.parent / f"{base_ref}.json"
    if local.exists() and local.resolve() != path.resolve():
        base_path = local
    else:
        from spruegen.config import presets  # lazy: presets importa schemas

        base_path = presets.resolve(base_ref)
    return _deep_merge(read_profile_data(base_path, _seen + (path.resolve(),)), data)


def load_profile(path: str | Path | None) -> Profile:
    if path is None:
        return Profile()
    data = read_profile_data(path)
    try:
        return Profile.model_validate(data)
    except ValueError as e:
        raise InputError(f"profile inválido ({path}): {e}")


def load_job(path: str | Path | None) -> Job:
    if path is None:
        return Job()
    try:
        return Job.model_validate(json.loads(Path(path).read_text()))
    except FileNotFoundError:
        raise InputError(f"no existe el job: {path}")
    except (json.JSONDecodeError, ValueError) as e:
        raise InputError(f"job inválido ({path}): {e}")


def load_proposal(path: str | Path) -> Proposal:
    try:
        return Proposal.model_validate(json.loads(Path(path).read_text()))
    except FileNotFoundError:
        raise InputError(f"no existe la proposal: {path}")
    except (json.JSONDecodeError, ValueError) as e:
        raise InputError(f"proposal inválida ({path}): {e}")
