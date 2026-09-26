"""Spanish engine messages -> English for the GUI.

The CLI/engine speaks Spanish; the GUI is in English. Common messages are matched by pattern;
anything not listed is shown as-is.
"""

from __future__ import annotations

import re

_SIDE = {
    "attach restringido al lado opuesto": "attach kept to the opposite side",
    "solo lleva feeder si es un hot spot aislado": "it only gets a feeder if it's an isolated hot spot",
}

# (pattern, template or callable) — templates use {1}, {2}... for groups
_RULES: list[tuple[str, object]] = [
    # --- reasons
    (r"cobertura: (\d+) feeder\(s\) alimentan (\d+)% \(cuello ≥ ([\d.]+)×módulo, alcance ≤ ([\d.]+) mm\)",
     "coverage: {1} feeder(s) feed {2}% of the ring (neck ≥ {3}× modulus, reach ≤ {4} mm)"),
    (r"capacidad: volumen (\S+) mm³ / (\S+) mm³ por feeder → mínimo (\d+)",
     "capacity: volume {1} mm³ / {2} mm³ per feeder → at least {3}"),
    (r"cantidad forzada por el profile/CLI: (\d+)", "feeder count set manually: {1}"),
    (r"la cabeza es un hot spot aislado: lleva su propio feeder por la cara interna",
     "the head is an isolated hot spot: it gets its own feeder on the inner face"),
    (r"reparto simétrico .*", "symmetric layout (covers about the same and balances the flow)"),
    (r"candidato #(\d+): los anteriores dejaban < 0\.3 mm de piel externa o rozaban el anillo",
     "spot #{1}: better-ranked spots left < 0.3 mm of outer skin or touched the ring"),
    (r"(spider|y): (\d+) feeders repartidos \(pedidos (\d+)\)", "{1}: {2} feeder(s) placed ({3} requested)"),
    (r"manual_attach del job, proyectado a la cara interna \(espesor ([\d.]+) mm\)",
     "manual attach point, projected onto the inner face ({1} mm thick)"),
    # --- warnings
    (r"espesor en el attach \(([\d.]+) mm\) justo en el mínimo \(([\d.]+) mm\)",
     "attach thickness {1} mm is right at the minimum ({2} mm)"),
    (r"espesor en el attach ([\d.]+) mm, justo en el mínimo", "attach thickness {1} mm is right at the minimum"),
    (r"cabeza/setting detectada hacia (\[.*?\]) \(frame del STL\): (.*)",
     lambda m: f"head/setting detected toward {m[1]} (STL axes): {_SIDE.get(m[2], m[2])}"),
    (r"zona aislada de ([\d.]+) mm³ cerca de theta=(-?\d+)° \(módulo ([\d.]+) mm\).*",
     "isolated zone of {1} mm³ near {2}° (modulus {3} mm): may come out porous; thicken the bridge "
     "or add a manual feeder"),
    (r"feeder Ø([\d.]+) mm más ancho que la banda \(([\d.]+) mm\).*",
     "feeder Ø{1} mm is wider than the band ({2} mm): the fillet will show on the inner edges"),
    (r"feeder #(\d+) de ([\d.]+) mm \(> 12 mm\)", "feeder #{1} is {2} mm long (> 12 mm)"),
    (r"feeder de ([\d.]+) mm \(> 12 mm\)", "feeder is {1} mm long (> 12 mm)"),
    (r"se descartó el attach cerca de theta=(-?\d+)° \((.*)\); quedan (\d+) feeders",
     lambda m: f"dropped the spot near {m[1]}° ({translate(m[2])}); {m[3]} feeder(s) left"),
    (r"el feeder queda a (-?[\d.]+) mm de la cara externa \(mín\. ([\d.]+) mm\).*",
     "the feeder would come within {1} mm of the outer surface (min {2} mm): the shank is thin there"),
    (r"(spider|y): solo (\d+) de (\d+) feeders caben con attach interno seguro en este anillo",
     "{1}: only {2} of {3} feeders fit with a safe inner attach on this ring"),
    (r"spider asimétrico: .*\(huecos (.*)\)",
     "uneven spider: this shank only allows safe attach points in some areas (gaps {1})"),
    (r"feeder #(\d+): penetración reducida a ([\d.]+) mm \(cáscara delgada\)",
     "feeder #{1}: penetration reduced to {2} mm (thin shell)"),
    (r"no se pudo poner varilla cerca de theta=(-?\d+)° .*",
     "couldn't place a vent near {1}° (thin edge or too close to a feeder)"),
    (r"varillas recortadas: no caben en ring_space_mm", "some vents removed: they don't fit in the flask space"),
    (r"tronco de la Y limitado a Ø([\d.]+) mm .*", "Y trunk limited to Ø{1} mm (less area than its arms)"),
    (r"tronco Ø([\d.]+) mm con menos área que sus brazos.*", "trunk Ø{1} mm has less area than its arms"),
    (r"feeders directos con largos dispares \(([\d.]+)–([\d.]+) mm\)", "feeder lengths differ ({1}–{2} mm)"),
    (r"el anillo mide ([\d.]+) mm de ancho > button_d_mm ([\d.]+) mm",
     "the ring is {1} mm wide > sprue base Ø {2} mm"),
    (r"el STL( de entrada)? tenía normales/winding raros.*", "the STL had inverted/odd normals (repaired)"),
    (r"auto: (.*); se prueba spider", lambda m: f"auto: {translate(m[1])}; trying spider"),
    (r"spider: (.*); se usa un solo feeder", lambda m: f"spider: {translate(m[1])}; using a single feeder"),
    (r"túnel del dedo (\d+)% abierto.*", "finger hole only {1}% open (something crosses it)"),
    (r"manual_attach: se usa un solo feeder.*", "manual attach: a single feeder is used"),
    (r"override explícito: (.*)", "explicit override: {1}"),
    (r"stem con override explícito: (.*)", "stem changed explicitly: {1}"),
    (r"sin --proposal .*", "without a proposal only watertight and stem are checked"),
    # --- errors
    (r"posible STL en pulgadas: el anillo mide ([\d.]+) unidades de ancho\..*",
     "Possible STL in inches: the ring is {1} units wide. spruegen assumes millimetres — re-export in mm "
     "(or scale ×25.4)."),
    (r"el STL mide ([\d.]+) unidades: demasiado grande.*",
     "The STL is {1} units wide — too big for a ring in mm (exported in microns or another scale?)."),
    (r"el STL no es watertight y la reparación automática no alcanza \((\d+) caras, bordes abiertos\).*",
     "The STL isn't watertight and automatic repair can't close it ({1} faces, open edges). Repair it in "
     "your CAD or Meshmixer — spruegen doesn't invent surfaces."),
    (r"el STL contiene (\d+) cuerpos separados.*",
     "The STL contains {1} separate bodies. Only a single-body ring is supported — join the parts in your CAD."),
    (r"no se detecta el hueco del dedo \(túnel abierto (\d+)%\).*",
     "Can't find the finger hole (only {1}% open). Is this a ring?"),
    (r"no hay attach interno ≥ ([\d.]+) mm de espesor \(espesor máx\. medido ([\d.]+) mm\).*",
     "No inner attach spot at least {1} mm thick (thickest measured: {2} mm). Thicken the shank on the "
     "inside, or lower the minimum in Advanced."),
    (r"ninguno de los (\d+) candidatos internos admite un feeder seguro.*",
     "None of the {1} inner spots allow a safe feeder (the shank is too thin around them)."),
    (r"no se pudo rutear el árbol.*", "Couldn't route the sprue tree on this ring with these settings."),
    (r"no se encontraron attaches internos para modo (\w+)", "No inner attach spots found for {1} mode."),
    (r"no existe el STL: (.*)", "File not found: {1}"),
    (r"no se pudo leer el STL (.*?): .*", "Couldn't read the STL {1}."),
    (r"el STL (.*) no contiene triángulos", "The STL {1} has no triangles."),
    (r"la malla final no es watertight", "The final mesh isn't watertight."),
    (r"la malla final tiene (\d+) cuerpos.*", "The final mesh has {1} separate pieces — something isn't attached."),
    (r"volumen final .* no se pegó nada", "Nothing got attached to the ring."),
    (r"el sprue tapa el hueco del dedo: (\d+)% .*", "The sprue blocks {1}% of the finger hole."),
    (r"(feeder #\d+: )?attach más cerca de la cara externa.*", "A feeder attaches closer to the outer surface."),
    (r"la cara externa del anillo cambió \(hasta (\S+) mm\).*",
     "The outer surface changed (up to {1} mm) — a sprue touches it."),
    (r"stem mide Ø([\d.]+) mm \(esperado (.*)\)", "Stem measures Ø{1} mm (expected {2})."),
    (r"stem mide ([\d.]+) mm de alto \(esperado (.*)\)", "Stem is {1} mm tall (expected {2})."),
    (r"la pieza mide ([\d.]+) mm sobre el stem > ring_space_mm (\S+)",
     "The piece is {1} mm above the stem — more than the flask space ({2} mm)."),
    (r"la pieza \(anillo \+ árbol\) mide ([\d.]+) mm sobre el stem > ring_space_mm (\S+) mm",
     "The piece is {1} mm above the stem — more than the flask space ({2} mm)."),
    (r"locks violados: (.*)", "Locked settings were changed: {1}"),
    (r"falló el boolean \(manifold\): (.*)", "The boolean union failed: {1}"),
    (r"la unión no (quedó watertight|sobrevive la exportación a STL).*", "The union didn't come out watertight."),
    (r"el STL de entrada cambió desde el propose.*", "The input STL changed since it was loaded — reload it."),
]
_COMPILED = [(re.compile(p), t) for p, t in _RULES]


def translate(msg: str) -> str:
    for rx, tpl in _COMPILED:
        m = rx.fullmatch(msg.strip())
        if not m:
            continue
        if callable(tpl):
            return tpl(m)
        out = tpl
        for i, g in enumerate(m.groups(), start=1):
            out = out.replace("{" + str(i) + "}", g or "")
        return out
    return msg


def translate_all(msgs) -> list[str]:
    return [translate(m) for m in msgs or []]
