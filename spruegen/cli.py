"""CLI: inspect / analyze / propose / apply / validate / render / batch / demo / profile / log."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Optional

import numpy as np
import typer

from . import __version__, analysis, build, castlog, features, io, policy, presets, repair, tree, vents
from . import union as union_mod
from . import validate as validate_mod
from .schemas import (
    Attach,
    Candidate,
    FeatureError,
    InputError,
    Job,
    PolicyError,
    Profile,
    Proposal,
    SpruegenError,
    load_job,
    load_proposal,
)

MAX_TRY = 300
POOL_ALL = 3000

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Árbol de colada para anillos (lost-wax): feeders por la cara interna + stem Ø10x35, listo para resina.",
)
profile_app = typer.Typer(no_args_is_help=True, help="Presets de metal / proceso.")
log_app = typer.Typer(no_args_is_help=True, help="Bitácora de coladas para calibrar los parámetros.")
app.add_typer(profile_app, name="profile")
app.add_typer(log_app, name="log")


def _echo_json(obj) -> None:
    typer.echo(json.dumps(obj, indent=2, ensure_ascii=False, default=float))


def _fail(msg: str, code: int) -> None:
    typer.echo(f"ERROR: {msg}", err=True)
    raise typer.Exit(code)


def load_profile(ref) -> Profile:
    return presets.load(ref)


def load_ring(path: str | Path):
    mesh = io.load_stl(path)
    io.check_units(mesh)
    mesh, rep = repair.repair(mesh)
    return mesh, rep


def apply_cli(prof: Profile, tree_mode=None, feeders=None, vents_opt=None) -> Profile:
    """Flags del CLI -> profile (tree/vents no están bloqueados)."""
    t = prof.tree.model_copy()
    v = prof.vents.model_copy()
    if tree_mode:
        t.mode = tree_mode
    if feeders:
        t.feeders = feeders
        if t.mode == "single" and feeders > 1:
            t.mode = "spider"
    if vents_opt is not None:
        vo = str(vents_opt).lower()
        if vo in ("0", "off", "no", "none"):
            v.mode = "off"
        elif vo == "auto":
            v.mode = "auto"
        else:
            v.mode, v.count = "count", int(vo)
    data = prof.model_dump()
    data["tree"], data["vents"] = t.model_dump(), v.model_dump()
    return Profile.model_validate(data)


# ---------------------------------------------------------------- pipeline (usable desde tests)


def run_inspect(stl: str | Path, profile_path=None, axis_hint=None) -> dict:
    prof = load_profile(profile_path)
    mesh, rep = load_ring(stl)
    feats = features.detect(mesh, prof, axis_hint)
    warns = list(feats.warnings)
    if rep["normals_fixed"]:
        warns.append("el STL tenía normales/winding raros (reparados)")
    return {"features": feats.model_dump(), "repair": rep, "warnings": warns}


def run_analyze(stl, profile_path=None, outdir=None, axis_hint=None, prof: Profile | None = None):
    prof = prof or load_profile(profile_path)
    mesh, _ = load_ring(stl)
    feats = features.detect(mesh, prof, axis_hint, max_candidates=POOL_ALL, respect_head=False)
    res = analysis.analyze(mesh, feats, feats.candidates, prof)
    if outdir is not None:
        outdir = Path(outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "analysis.json").write_text(json.dumps(res.summary, indent=2, ensure_ascii=False))
        for name, zm in analysis.zone_meshes(res).items():
            io.save_stl_atomic(zm, outdir / f"{name}.stl")
        try:
            from . import render

            render.analysis_png(res, feats, outdir / "analysis.png", title=Path(stl).stem)
        except ImportError:
            pass
    return res


def _attach_model(c: Candidate, T: np.ndarray, reason: str, manual: bool) -> Attach:
    A = np.array(c.point)
    return Attach(
        point_input=c.point,
        point_job=(T[:3, :3] @ A + T[:3, 3]).tolist(),
        theta_deg=c.theta_deg,
        h_mm=c.h_mm,
        r_inner_mm=c.r_inner_mm,
        r_outer_mm=c.r_outer_mm,
        thickness_mm=c.thickness_mm,
        manual=manual,
        reason=reason,
    )


def run_propose(
    stl: str | Path | None,
    profile_path,
    job_path,
    outdir: str | Path,
    tree_mode: str | None = None,
    feeders: int | None = None,
    vents_opt: str | None = None,
) -> Proposal:
    base_profile = load_profile(profile_path)
    job = load_job(job_path)
    if stl is None:
        if not job.stl:
            raise InputError("falta el STL (argumento o campo 'stl' en job.json)")
        stl = Path(job_path).parent / job.stl if job_path else Path(job.stl)
    stl = Path(stl).resolve()
    job = job.model_copy(update={"stl": str(stl)})

    locks = policy.effective_locks(base_profile, job)
    prof, ov_warn = policy.apply_overrides(base_profile, job)
    prof = apply_cli(prof, tree_mode, feeders, vents_opt)
    locked_vals = policy.lock_values(base_profile, locks)

    mesh, rep = load_ring(stl)
    mode = prof.tree.mode
    an = None
    warns: list[str] = []
    reasons: list[str] = []

    if job.manual_attach is not None:
        # con attach manual no se exige encontrar candidatos automáticos
        try:
            feats = features.detect(mesh, prof, job.finger_axis_hint)
        except FeatureError as e:
            if "no hay attach interno" not in str(e):
                raise
            feats = _features_without_candidates(mesh, prof, job)
        cand = features.manual_candidate(mesh, feats, job.manual_attach, prof)
        grid = features.OuterGrid(mesh, feats)
        if mode != "single":
            warns.append(f"manual_attach: se usa un solo feeder (tree.mode={mode} ignorado)")
        route = tree.route(mesh, feats, [cand], [[0]], prof, grid, "single")
        reasons.append(f"manual_attach del job, proyectado a la cara interna (espesor {cand.thickness_mm:.2f} mm)")
    else:
        if mode == "auto" or prof.vents.mode == "auto":
            feats_all = features.detect(
                mesh, prof, job.finger_axis_hint, max_candidates=POOL_ALL, respect_head=False
            )
            an = analysis.analyze(mesh, feats_all, feats_all.candidates, prof)
        if mode == "auto":
            feats = feats_all
            grid = features.OuterGrid(mesh, feats)
            route = _route_auto(mesh, feats, an, prof, grid, warns)
            reasons += an.summary["reasons"]
        else:
            feats = features.detect(mesh, prof, job.finger_axis_hint, max_candidates=MAX_TRY)
            grid = features.OuterGrid(mesh, feats)
            if mode == "single":
                rank, route = tree.plan_single(mesh, feats, feats.candidates, prof, grid)
                if rank:
                    reasons.append(
                        f"candidato #{rank + 1}: los anteriores dejaban < 0.3 mm de piel externa o rozaban el anillo"
                    )
            else:
                n = prof.tree.feeders or 2
                route = tree.plan_spread(mesh, feats, feats.candidates, n, mode, prof, grid)
                reasons.append(f"{mode}: {len(route.feeders)} feeders repartidos (pedidos {n})")
        feats = feats.model_copy(update={"candidates": feats.candidates[:10]})

    T = route.T
    prim = route.attaches[0]
    base_reason = (
        f"cara interna, espesor {prim.thickness_mm:.2f} mm ≥ {prof.min_attach_thickness_mm} "
        f"(máx. {feats.inner_thickness_max_mm:.2f}), parche sólido (no lattice aislado), h={prim.h_mm:+.2f} mm"
    )
    manual = job.manual_attach is not None
    attaches = [
        _attach_model(c, T, (reasons[0] if manual else base_reason) if i == 0 else "feeder adicional", manual)
        for i, c in enumerate(route.attaches)
    ]

    vent_list, vw = vents.plan_vents(
        mesh, feats, grid, T, prof, [c.theta_deg for c in route.attaches], an.vent_targets if an else None
    )
    stem = route.stem
    top_limit = stem.h_mm + prof.ring_space_mm
    kept = [v for v in vent_list if v.top[2] <= top_limit]
    if len(kept) < len(vent_list):
        vw.append("varillas recortadas: no caben en ring_space_mm")
    vent_list = kept

    bad = policy.check_locks(locked_vals, stem, prof)
    if bad:
        raise PolicyError("el plan viola locks: " + "; ".join(bad))

    ring_job = build.ring_in_job_frame(mesh, T)
    sprues = build.build_sprues(stem, route.feeders, route.fillets, route.branches, None, route.hub)
    vent_meshes = build.build_vents(vent_list)
    outdir = Path(outdir)
    previews = build.export_previews(ring_job, sprues, outdir, vent_meshes)

    warns = list(feats.warnings) + ov_warn + route.warnings + warns + vw
    if an is not None:
        warns += an.summary["warnings"]
    if rep["normals_fixed"]:
        warns.append("el STL de entrada tenía normales/winding raros (ya reparados)")
    warns = sorted(set(warns), key=warns.index)
    prop = Proposal(
        spruegen_version=__version__,
        input={
            "path": str(stl),
            "sha256": io.sha256(stl),
            "bbox": mesh.bounds.tolist(),
            "volume_mm3": float(mesh.volume),
            "faces": int(len(mesh.faces)),
            "repair": rep,
        },
        profile_path=presets.describe(profile_path),
        profile=prof,
        job=job,
        features=feats,
        attach=attaches[0],
        attaches=attaches,
        transform=T.tolist(),
        stem=stem,
        feeders=route.feeders,
        branches=route.branches,
        fillets=route.fillets,
        vents=vent_list,
        hub=route.hub,
        tree={
            "requested": mode,
            "used": route.mode,
            "groups": route.groups,
            "feeders": len(route.feeders),
            "vents": len(vent_list),
            "reasons": reasons,
        },
        analysis=an.summary if an is not None else None,
        ring_job={
            "bbox": ring_job.bounds.tolist(),
            "volume_mm3": float(ring_job.volume),
            "z_span": ring_job.bounds[:, 2].tolist(),
            "r_inner_mm": feats.inner_radius_mm,
            "r_inner_min_mm": feats.inner_radius_min_mm,
            "piece_height_mm": float(max([ring_job.bounds[1, 2]] + [v.top[2] for v in vent_list]) - stem.h_mm),
        },
        previews=previews,
        locks={"effective": locks, "values": locked_vals},
        locks_honored=True,
        warnings=warns,
    )
    (outdir / "proposal.json").write_text(prop.model_dump_json(indent=2))
    return prop


def _route_auto(mesh, feats, an, prof, grid, warns) -> tree.Route:
    """Árbol automático: attaches del análisis; pares cercanos comparten tronco (Y). Fallbacks con aviso."""
    merge = prof.tree.y_merge_deg
    try:
        r = tree.plan_with_alternates(
            mesh, feats, an.attaches, an.alternates, lambda cur: tree.pair_groups(cur, merge), prof, grid, "auto"
        )
        r.mode = "auto:" + ("+".join("y" if len(g) == 2 else "direct" for g in r.groups))
        return r
    except PolicyError as e:
        warns.append(f"auto: {e}; se prueba spider")
    n = len(an.attaches)
    if n > 1:
        try:
            return tree.plan_spread(mesh, feats, feats.candidates, n, "spider", prof, grid)
        except PolicyError as e:
            warns.append(f"spider: {e}; se usa un solo feeder")
    _, r = tree.plan_single(mesh, feats, feats.candidates, prof, grid)
    return r


def _features_without_candidates(mesh, prof, job: Job):
    """Features para attach manual cuando el auto no encuentra candidatos (eje/centro igual sirven)."""
    relaxed = prof.model_copy(update={"min_attach_thickness_mm": 1e-3, "keepout": []})
    feats = features.detect(mesh, relaxed, job.finger_axis_hint)
    return feats.model_copy(update={"candidates": []})


def run_apply(proposal_path: str | Path, out_path: str | Path) -> dict:
    prop = load_proposal(proposal_path)
    ring_job = validate_mod.load_ring_job(prop)
    parts = [ring_job] + build.sprue_parts_from(prop)
    out = union_mod.union(parts)
    # se valida exactamente lo que se va a escribir (STL float32 recargado)
    report = validate_mod.validate(union_mod.stl_roundtrip(out), prop, ring_job)
    out_path = Path(out_path)
    if report["ok"]:
        io.save_stl_atomic(out, out_path)
        report["out"] = str(out_path.resolve())
    return report


def run_validate(out_path: str | Path, proposal_path=None, profile_path=None) -> dict:
    out = io.load_stl(out_path)
    out.merge_vertices()
    prop = load_proposal(proposal_path) if proposal_path else None
    prof = load_profile(profile_path) if profile_path else None
    return validate_mod.validate(out, prop, profile=prof)


def run_batch(folder, profile_path, outdir, do_apply: bool, tree_mode=None, feeders=None, vents_opt=None) -> list[dict]:
    folder, outdir = Path(folder), Path(outdir)
    rows = []
    for stl in sorted(folder.glob("*.stl")):
        wd = outdir / stl.stem
        row = {"ring": stl.name, "ok": False, "feeders": "", "tree": "", "vents": "", "coverage": "",
               "piece_height_mm": "", "warnings": 0, "error": ""}
        try:
            prop = run_propose(stl, profile_path, None, wd, tree_mode, feeders, vents_opt)
            row.update(feeders=len(prop.feeders), tree=prop.tree["used"], vents=len(prop.vents),
                       coverage=round(prop.analysis["coverage"], 3) if prop.analysis else "",
                       piece_height_mm=round(prop.ring_job["piece_height_mm"], 1), warnings=len(prop.warnings))
            row["ok"] = True
            if do_apply:
                rep = run_apply(wd / "proposal.json", wd / "out.stl")
                row["ok"] = rep["ok"]
                row["error"] = "; ".join(rep["errors"])
        except SpruegenError as e:
            row["error"] = str(e)
        rows.append(row)
    outdir.mkdir(parents=True, exist_ok=True)
    if rows:
        with open(outdir / "summary.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    return rows


# ---------------------------------------------------------------- comandos

TREE_HELP = "single | spider | y | auto (auto = el análisis decide cantidad y lugar)"
VENTS_HELP = "off | auto (donde el metal llega último) | N (cantidad)"


@app.command()
def inspect(
    stl: Path = typer.Argument(..., help="STL de un anillo (mm)"),
    profile: Optional[str] = typer.Option(None, "-p", "--profile", help="preset (ag925, au14k...) o ruta .json"),
):
    """Detecta eje, cara interna/externa, espesores y candidatos de attach; imprime JSON."""
    try:
        _echo_json(run_inspect(stl, profile))
    except SpruegenError as e:
        _fail(str(e), 2)


@app.command()
def analyze(
    stl: Path = typer.Argument(..., help="STL de un anillo (mm)"),
    profile: Optional[str] = typer.Option(None, "-p", "--profile"),
    out_dir: Path = typer.Option(Path("analysis"), "-o", "--out-dir"),
):
    """Mapa de espesor/módulo, zonas de alimentación, cantidad de feeders sugerida y dónde llega último el metal."""
    try:
        res = run_analyze(stl, profile, out_dir)
    except SpruegenError as e:
        _fail(str(e), 2)
    s = res.summary
    typer.echo(f"feeders sugeridos: {s['feeder_count']}  (cobertura {s['coverage']:.0%}, {s['seconds']} s)")
    for r in s["reasons"]:
        typer.echo(f"  · {r}")
    for i, f in enumerate(s["feeders"]):
        typer.echo(
            f"  feeder {i + 1}: theta={f['theta_deg']:.0f}° h={f['h_mm']:+.1f} mm espesor {f['thickness_mm']:.2f} mm, "
            f"alimenta {f['feeds_volume_frac']:.0%}" + (" (cabeza)" if f["head"] else "")
        )
    lt = ", ".join(f"{t['theta_deg']:.0f}°" for t in s["last_to_fill"][:3])
    typer.echo(f"  llega último: {lt}")
    for w in s["warnings"]:
        typer.echo(f"WARNING: {w}")
    typer.echo(f"-> {out_dir}/analysis.json, zone_*.stl" + (", analysis.png" if (out_dir / "analysis.png").exists() else ""))


@app.command()
def propose(
    stl: Optional[Path] = typer.Argument(None, help="STL del anillo (o 'stl' en job.json)"),
    profile: Optional[str] = typer.Option(None, "-p", "--profile", help="preset (ag925, au14k...) o ruta .json"),
    job: Optional[Path] = typer.Option(None, "-j", "--job", help="job.json"),
    out_dir: Path = typer.Option(Path("workdir"), "-o", "--out-dir"),
    tree_mode: Optional[str] = typer.Option(None, "--tree", help=TREE_HELP),
    feeders: Optional[int] = typer.Option(None, "--feeders", help="cantidad de feeders (spider / y / auto)"),
    vents_opt: Optional[str] = typer.Option(None, "--vents", help=VENTS_HELP),
):
    """Escribe proposal.json + previews (anillo / árbol / varillas). Nunca escribe out.stl."""
    if tree_mode and tree_mode not in ("single", "spider", "y", "auto"):
        _fail(f"--tree inválido: {tree_mode} ({TREE_HELP})", 2)
    try:
        prop = run_propose(stl, profile, job, out_dir, tree_mode, feeders, vents_opt)
    except (FeatureError, PolicyError, InputError, SpruegenError, ValueError) as e:
        _fail(str(e), 2)
    typer.echo(f"proposal: {Path(out_dir) / 'proposal.json'}")
    typer.echo(f"árbol:    {prop.tree['used']} — {len(prop.feeders)} feeder(s), {len(prop.vents)} varilla(s)")
    for r in prop.tree.get("reasons", []):
        typer.echo(f"          · {r}")
    for i, f in enumerate(prop.feeders):
        typer.echo(
            f"feeder {i + 1}: Ø{f.d_mm:.2f} mm, {f.len_mm:.1f} mm, {f.angle_deg:.0f}° del eje"
            + (" (brazo de Y)" if f.node_kind == "branch" else "")
        )
    for b in prop.branches:
        typer.echo(f"tronco:   Ø{b.d_mm:.2f} mm → brazos {[i + 1 for i in b.arms]}")
    typer.echo(f"stem:     Ø{prop.stem.d_mm} x {prop.stem.h_mm} mm")
    typer.echo("previews: " + "\n          ".join(prop.previews.values()))
    for w in prop.warnings:
        typer.echo(f"WARNING: {w}")
    typer.echo("Revisa los previews y corre: spruegen apply " + str(Path(out_dir) / "proposal.json"))


@app.command()
def apply(
    proposal: Path = typer.Argument(..., help="workdir/proposal.json"),
    out: Path = typer.Option(Path("out.stl"), "-o", "--out"),
):
    """Une anillo + árbol (manifold), valida, y recién entonces escribe out.stl."""
    try:
        rep = run_apply(proposal, out)
    except SpruegenError as e:
        _fail(str(e), 2)
    _echo_json(rep)
    if not rep["ok"]:
        _fail("validate falló; no se escribió " + str(out), 1)
    typer.echo(f"OK -> {rep['out']}")


@app.command()
def validate(
    out_stl: Path = typer.Argument(..., help="STL final"),
    proposal: Optional[Path] = typer.Option(None, "--proposal", help="proposal.json (validación completa)"),
    profile: Optional[str] = typer.Option(None, "-p", "--profile"),
):
    """Valida watertight, una sola pieza, stem, hueco libre, attaches internos, cara externa intacta, locks."""
    try:
        rep = run_validate(out_stl, proposal, profile)
    except SpruegenError as e:
        _fail(str(e), 2)
    _echo_json(rep)
    if not rep["ok"]:
        raise typer.Exit(1)


@app.command()
def render(
    target: Path = typer.Argument(..., help="proposal.json (colores por pieza) u OUT.stl"),
    out: Optional[Path] = typer.Option(None, "-o", "--out", help="PNG de salida (default: junto al input)"),
):
    """PNG con 3 vistas (anillo gris, árbol rojo, varillas azul) + tarjeta HTML si es una proposal."""
    try:
        from . import render as render_mod
    except ImportError:
        _fail("falta matplotlib: pip install 'spruegen[render]'", 2)
    try:
        paths = render_mod.render_target(target, out)
    except SpruegenError as e:
        _fail(str(e), 2)
    for p in paths:
        typer.echo(f"-> {p}")


@app.command()
def batch(
    folder: Path = typer.Argument(..., help="carpeta con STLs (un anillo por archivo)"),
    profile: Optional[str] = typer.Option(None, "-p", "--profile"),
    out_dir: Path = typer.Option(Path("batch_out"), "-o", "--out-dir"),
    do_apply: bool = typer.Option(False, "--apply", help="también correr apply (sin revisión humana)"),
    tree_mode: Optional[str] = typer.Option(None, "--tree", help=TREE_HELP),
    vents_opt: Optional[str] = typer.Option(None, "--vents", help=VENTS_HELP),
):
    """Un job por STL de la carpeta (siguen siendo un anillo por árbol). Escribe summary.csv."""
    rows = run_batch(folder, profile, out_dir, do_apply, tree_mode, None, vents_opt)
    for r in rows:
        typer.echo(f"{'OK ' if r['ok'] else 'ERR'} {r['ring']}: {r['feeders']} feeders {r['tree']} {r['error']}")
    typer.echo(f"-> {out_dir}/summary.csv")
    if any(not r["ok"] for r in rows):
        raise typer.Exit(1)


@app.command()
def demo(
    out_dir: Path = typer.Option(Path("showcase"), "-o", "--out-dir"),
    ring: Optional[Path] = typer.Option(None, "--ring", help="STL propio para agregar a la galería"),
):
    """Genera anillos de ejemplo, corre todo el pipeline y arma una galería (index.html)."""
    from . import showcase

    ok = showcase.run_demo(out_dir, extra_ring=ring, echo=typer.echo)
    typer.echo(f"-> {out_dir / 'index.html'}")
    if not ok:
        raise typer.Exit(1)


@app.command()
def gui(
    port: int = typer.Option(8765, "--port", help="puerto local (si está ocupado usa el siguiente libre)"),
    no_browser: bool = typer.Option(False, "--no-browser", help="no abrir el navegador automáticamente"),
):
    """Abre la app visual en el navegador (cargar anillo, configurar, analizar, generar, exportar)."""
    try:
        from .gui import server
    except ImportError:
        _fail("faltan dependencias de la GUI: pip install 'spruegen[gui,render]'", 2)
    server.run(port, open_browser=not no_browser, echo=typer.echo)


@profile_app.command("list")
def profile_list():
    """Presets incluidos + profiles/*.json del directorio actual."""
    for name, p in presets.available().items():
        typer.echo(f"{name:22s} {p.metal:8s} {p.process:12s} {p.notes or ''}")


@profile_app.command("show")
def profile_show(name: str):
    try:
        _echo_json(load_profile(name).model_dump())
    except SpruegenError as e:
        _fail(str(e), 2)


@profile_app.command("new")
def profile_new(
    name: str,
    from_: str = typer.Option("ag925", "--from", help="preset base"),
    out_dir: Path = typer.Option(Path("profiles"), "-o", "--out-dir"),
):
    """Copia un preset a profiles/NAME.json para editarlo."""
    try:
        path = presets.new(name, from_, out_dir)
    except SpruegenError as e:
        _fail(str(e), 2)
    typer.echo(f"-> {path}")


@log_app.command("add")
def log_add(
    proposal: Path = typer.Argument(...),
    result: str = typer.Option(..., "--result", help=" | ".join(castlog.RESULTS)),
    note: str = typer.Option("", "--note"),
    log_file: Path = typer.Option(Path("casts.jsonl"), "--log"),
):
    """Registra cómo salió la colada de una proposal (para calibrar alcance/capacidad por metal)."""
    try:
        rec = castlog.add(load_proposal(proposal), result, note, log_file)
    except SpruegenError as e:
        _fail(str(e), 2)
    typer.echo(f"registrado: {rec['ring']} → {rec['result']} ({log_file})")


@log_app.command("summary")
def log_summary(log_file: Path = typer.Option(Path("casts.jsonl"), "--log")):
    """Resultados agrupados por metal / proceso / cantidad de feeders."""
    typer.echo(castlog.summary_text(log_file))


if __name__ == "__main__":
    app()
