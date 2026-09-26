"""CLI: inspect / analyze / propose / apply / validate / render / batch / demo / profile / materials / log.

Thin layer over `spruegen.pipeline`: parse flags, call, print. No geometry here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from spruegen import materials
from spruegen.config import presets
from spruegen.pipeline import (  # noqa: F401  (re-exported for backwards compatibility)
    apply_cli,
    load_profile,
    load_ring,
    run_analyze,
    run_apply,
    run_batch,
    run_inspect,
    run_propose,
    run_validate,
)
from spruegen.report import castlog
from spruegen.schemas import FeatureError, InputError, PolicyError, SpruegenError, load_proposal

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Árbol de colada para anillos (lost-wax): feeders por la cara interna + stem Ø10x35, listo para resina.",
)
profile_app = typer.Typer(no_args_is_help=True, help="Presets de metal / proceso.")
materials_app = typer.Typer(no_args_is_help=True, help="Base de aleaciones con citas (fuente única de datos metalúrgicos).")
log_app = typer.Typer(no_args_is_help=True, help="Bitácora de coladas para calibrar los parámetros.")
app.add_typer(profile_app, name="profile")
app.add_typer(log_app, name="log")
app.add_typer(materials_app, name="materials")


def _echo_json(obj) -> None:
    typer.echo(json.dumps(obj, indent=2, ensure_ascii=False, default=float))


def _fail(msg: str, code: int) -> None:
    typer.echo(f"ERROR: {msg}", err=True)
    raise typer.Exit(code)



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
        from spruegen.report import render as render_mod
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
    from spruegen.report import showcase

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
        from spruegen.gui import server
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


@materials_app.command("list")
def materials_list():
    """Aleaciones disponibles: id, familia, rango de fusión, densidad."""
    db = materials.load()
    for a in sorted(db.alloys.values(), key=lambda x: (x.family, x.id)):
        rho = a.density_g_cm3
        sol, liq = a.solidus_c, a.liquidus_c
        rng = f"{sol.mid:.0f}–{liq.mid:.0f} °C" if sol and liq else "–"
        typer.echo(f"{a.id:28s} {a.family:9s} {rng:14s} {(f'{rho.mid:.2f} g/cm³' if rho else '–'):12s} {a.name}")


@materials_app.command("show")
def materials_show(alloy_id: str, section: str = typer.Option("medium", "--section", help="thin | medium | heavy")):
    """Propiedades de una aleación, cada una con su fuente."""
    try:
        a = materials.load().get(alloy_id)
    except SpruegenError as e:
        _fail(str(e), 2)
    db = materials.load()
    typer.echo(f"{a.name}  [{a.id}]  familia={a.family}  revestimiento={a.investment}")
    typer.echo("composición (wt%): " + ", ".join(f"{k} {v:g}" for k, v in a.composition_wt_pct.items()))
    rows = [("densidad", a.density_g_cm3, " g/cm³", 2), ("solidus", a.solidus_c, " °C", 0),
            ("liquidus", a.liquidus_c, " °C", 0), (f"colada ({section})", a.pour_c(section), " °C", 0),
            (f"cilindro ({section})", a.flask_c(section), " °C", 0),
            ("contracción vol.", a.prop("shrinkage_vol_pct"), " %", 2),
            ("contracción lineal", a.prop("shrinkage_linear_pct"), " %", 2),
            ("calor latente", a.prop("latent_heat_kj_kg"), " kJ/kg", 0)]
    for label, v, unit, nd in rows:
        if v is None:
            continue
        src = "derivado: " + (v.method or "") if v.derived else (db.source(v.source).cite() if db.source(v.source) else v.source)
        typer.echo(f"  {label:20s} {v.fmt(unit, nd):18s} ← {src}" + (f" [{v.locator}]" if v.locator and not v.derived else ""))
    for n in a.notes():
        typer.echo(f"  · {n.get('text')}  ({n.get('source')})")


@materials_app.command("rules")
def materials_rules():
    """Reglas de sprueing publicadas (con cita) que usa la hoja de colada."""
    db = materials.load()
    for r in db.rules.values():
        typer.echo(f"{r.id:24s} {r.statement}  ({r.source})")


@materials_app.command("check")
def materials_check(path: Optional[Path] = typer.Argument(None, help="alloys.json propio (default: el incluido)")):
    """Valida la base: toda cifra debe citar una fuente existente."""
    try:
        db = materials.load(str(path) if path else None)
    except SpruegenError as e:
        _fail(str(e), 2)
    problems = materials.check(db)
    for p in problems:
        typer.echo(f"ERROR: {p}", err=True)
    typer.echo(f"{len(db.alloys)} aleaciones, {len(db.sources)} fuentes, {len(db.rules)} reglas — "
               + ("OK" if not problems else f"{len(problems)} problema(s)"))
    if problems:
        raise typer.Exit(1)


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
