# spruegen materials dataset: report

Files: `alloys.json` (schema_version 1: 52 sources, 23 alloys, 27 rules). Accessed 2026-09-26.

## Coverage (alloy × property)

Legend: P = peer-reviewed paper, Santa Fe paper or book · S = manufacturer or foundry datasheet · H = handbook-type secondary source (Wikipedia citing CRC/TPRC) · D = derived, with `method` stated · `-` = not found, left out.

| alloy | rho | sol | liq | pour | flask | vol% | lin% | k | cp | L |
|---|---|---|---|---|---|---|---|---|---|---|
| ag925 | S | P | P | S | S | S | - | H | S | D |
| ag935_argentium | S | S | S | S | S | - | - | - | - | - |
| ag960_argentium | S | S | S | - | - | - | - | - | - | - |
| ag999 | S | S | S | S | S | - | - | H | D | P |
| au14y | P | P | P | S | S | P | D | - | - | P |
| au18y | P | P | P | S | S | P | D | - | - | P |
| au18r | P | P | P | S | S | P | D | - | - | P |
| au18w_ni | P | P | P | S | S | P | D | - | - | P |
| au18w_pd | S | S | S | S | S | P | D | - | - | - |
| au14w_ni | S | S | S | S | S | - | - | - | - | - |
| au14w_pd | S | S | S | S | S | - | - | - | - | - |
| au10y | S | S | S | S | S | - | - | - | - | - |
| pt950ru | P | P | P | P | P | - | - | - | D | P |
| pt950co | P | P | P | P | P | - | - | - | - | P |
| pd950 | S | S | S | S | S | - | - | - | D | D |
| cu_c87500_si_brass | S | S | S | S | S | P* | S | S | S | - |
| cu_c87600_si_bronze | S | S | S | S | S | P* | S | S | S | - |
| cu_c90500_tin_bronze | S | S | S | S | S | P* | S | S | S | - |
| cu_c92200_tin_bronze | S | S | S | S | S | P* | S | S | S | - |
| cu_c83600_red_brass | S | S | S | S | S | P* | S | S | S | - |
| cu_c85700_yellow_brass | S | S | S | - | S | - | S | S | S | - |
| cu_c26000_cartridge_brass | S | S | S | - | S | - | - | S | S | - |
| cu_c23000_nugold | S | S | S | - | S | - | - | S | S | - |

\* Copper-alloy vol% is Campbell's value for **pure Cu** (5.30%). It is tagged `note: "pure Cu reference"`, so treat it as a proxy, not an alloy measurement.

### Schema conventions to know about
- `pour_c` has an overall `min`/`max`. Where the source splits by thickness, there is also `by_piece` {thin, medium, heavy}.
- `flask_c` usually has `heavy`, `thin` and sometimes `medium`, plus `method` (vacuum or centrifugal) where the source splits by method. Three alloys only have a single range, stored as `general` with no heavy/thin split: ag999, pd950 and one alt of ag935. The loader needs to handle this.
- Composition carries a `composition_source`. Where it is `derived`, it was calculated from a Legor master-alloy recipe × karat fraction or from spec midpoints, and the method is given.
- Values converted from °F, lb/in³, Btu/ft·h·°F or in/ft keep the original source id, and the locator quotes the original units.
- Primary values sit in `value`/`min`/`max`. Disagreeing sources are in `alt[]`.

## Conflicts between sources (primary value first)

| Alloy / property | Primary | Alternatives | Comment |
|---|---|---|---|
| Ag925 solidus | 780 °C (Fischer-Bühner 2022) | 802 (Eid), 810 (Umicore) | 780 is near the Ag-Cu eutectic (non-equilibrium). The spread matters for feeding-time estimates. |
| Ag925 liquidus | 900 (FB 2022) | 893 (Umicore), 899 (Eid) | Minor. |
| Argentium 935 melting range | 803–903 (Rio/Bell 2010) | 766–877 (H&S 2009) | H&S data is probably for the older "Argentium Sterling" formulation. |
| Argentium 935 pour | 960–1000 (Rio) | 980–1020 (H&S 2010), 950–980 (H&S 2009) | |
| 14K yellow sol/liq | 823/862 (Progold 2018, alloy O) | 870/910 (Umicore) | 14K yellow varies widely with Zn/Ag content. Glines pour 882–963 is low relative to the Umicore liquidus. |
| 18K Pd-white sol/liq | 905/960 (Legor NF509) | 1009/1079 (Progold M), 1064/1074 (Umicore) | Strongly depends on Pd%. Take the actual alloy's sheet. |
| 14K Pd-white sol/liq | 1090/1170 (Legor NF508) | 1079/1094 (Umicore) | |
| 18K yellow pour | 960–1030 (Legor A183N, by thickness) | 1050 (Ott 1985 "normally used"), 918–979 (Glines) | |
| Pt950Ru liquidus | 1795 (Maerz/PGI; Umicore agrees) | ~1818 derived from Klotz 2014 "+50 K for 5% Ru" | |
| Pt950Co liquidus | 1765 (Maerz/PGI) | ~1668 derived from Klotz 2014 "−100 K for 5% Co" | A large gap. Klotz is a CALPHAD phase-diagram paper; Maerz is a trade sheet. Worth a DSC check. |
| Pt950Ru flask | 760–870 heavy (Maerz 2007) / 950 filigree (Klotz & Drago 2011) | Rio Pt-Ir 704–860 / 1010 | |
| Pd950 | TruPd 1350–1380 °C melt, pour 1550–1600 (H&S 2006) | PdRu-type liquidus 1560–1570, +80 °C superheat (Klotz/Held 2019) | Different alloy families: Ga-containing vs Ru-based. Model them as separate alloys if both are needed. |
| Sprue angle | 45° (Stuller) | ~80° (H&S, vacuum), 90° (Progold, Klotz Pt sim, Maerz Pt) | The 45° folklore is for centrifugal/gravity trees. Recent vacuum and Pt simulation work favours near-perpendicular. |
| Feeder size | > section thickness (Stuller); ≥1.25× (H&S) | ingate area 1:1 (Progold); 70–150% area (Bell); ≥2/3 area (Yoshida) | spruegen should default to diameter ≥ 1.25 × max section thickness. |
| C90500 light-casting pour | not stored | St Paul prints "2000–3000 °F" | Evidently a typo. Only the heavy range (1038–1149 °C) is stored. |
| C92200 sol/liq | 826/988 | St Paul page labels them swapped | Corrected by magnitude. |

## Most useful sources
1. **Progold, Santa Fe 2018 "Understanding Gold Alloy Features From Thermodynamic Phenomena"** (Sbornicchia et al.). Dilatometric solid/liquid densities, solidification density change (2.45–3.8%), and DSC melting enthalpy for commercial 14K/18K yellow, red and white alloys. This is the best single source for gold shrinkage and latent heat.
2. **Legor TDS series** (A183N, OR133, NF509, NF508) and Rio Grande technical charts. These give pour and flask temperatures by thickness (<0.5 / 0.5–1.2 / >1.2 mm), which maps directly onto spruegen's thin vs heavy split.
3. **United PM (Thailand) flask table.** Heavy/medium/light × centrifugal/vacuum for yellow gold, white gold, sterling and brass/bronze.
4. **Klotz/Heiss/Tiberto (JMTR 2015; Santa Fe 2014) and Klotz & Drago (PMR 2011).** Pt-5Ru and Pt-5Co pour and flask windows, melting enthalpy, sprue simulation findings (hot spot at the sprue junction, 10→5 mm main sprue, 90° gating).
5. **Maerz (PGI) 2004 and 2007.** Pt alloy melting ranges and densities, Pt950Ru superheat and flask temperatures.
6. **St Paul Foundry / Wieland Concast.** These reproduce CDA-format data for cast bronzes and brasses. copper.org itself (alloys.copper.org) returned 403 to both WebFetch and curl.
7. **Stuller, Hoover & Strong, Progold LAB and Bell/Ganoksin** for sprueing rules. **Grimwade 2002 (Santa Fe)** for the Chvorinov form and the "main sprue = reservoir" principle.

## Caveats
- **Fischer-Bühner's 2007 Santa Fe paper was not read.** "Advances in the Prevention of Investment Casting Defects Assisted by Computer Simulation" has 18K thermal properties and sprueing guidance. santafesymposium.org returned HTTP 429 on 5 attempts, and the proxy then rate-limited further fetches. The Springer paper "Optimal gating system design for investment casting of sterling silver" (Int J Adv Manuf Tech, 10.1007/s00170-012-4523-3) was also blocked by the proxy (429). Both are worth reading manually. Other Santa Fe PDFs were reachable via their static1.squarespace.com mirrors.
- **WGC Handbook on Investment Casting (Ott 1997) was not reachable** (Scribd/Yumpu block it). Ott, Raub & Rapson, Gold Bulletin 1985, is used instead.
- **No published Chvorinov mould constant B for gypsum investment was found.** Heiss 2015 states that investment thermal conductivity had to be measured to calibrate their simulation. The dataset records this as the rule `mould_constant_gypsum`. spruegen should rely on modulus *ratios* (feeder modulus ≥ 1.12× the section it feeds, derived from "feeder freezes 25% later" and n = 2) rather than absolute times.
- **Thermal conductivity and specific heat are missing for all gold alloys and Pt/Pd alloys.** Pure-metal values are not substituted, except as clearly labelled derived cp/L for Pt and Pd. Alloying cuts conductivity drastically (e.g. sterling 361 vs Ag 429; tin bronze ~75 vs Cu 401).
- **Linear shrinkage for gold is derived** as (RT→solidus density change)/3, assuming isotropic contraction. Treat it as a first estimate for pattern scaling.
- **Copper-alloy pour temperatures are sand-foundry values** (light vs heavy castings). For small investment-cast pieces use the "light" end. Copper flask temperatures come from United PM's note that brass/bronze use the white-gold settings.
- **Several numbers come from secondary sources:** Wikipedia element infoboxes, the sterling k = 361 row, and Wikipedia's Chvorinov and riser pages (which cite Degarmo and Askeland). They are typed `handbook` with venue "Wikipedia (secondary)" so they can be replaced with CRC or ASM citations later.
- **ASM Handbook vol. 15 was not consulted** (paywalled).
- **Progold alloy L** ("18K Ni-white": Au 75, Cu 14, Ag 7.5, Ni 3.5) has an unusually low Ni content. Verify against the PDF before relying on its composition.
- **Argentium 960 has no pour or flask data.** The official 960S casting PDF is image-only, and the proxy blocked the direct download. **14K Ni-white and 10K yellow have no composition.**
- **Gypsum limit:** CaSO4 decomposes between 900 and 1260 °C (Phetrattanarangsi 2017). The Legor 14K Pd-white pour window (1220–1290 °C) falls inside it, and the dataset flags this.
