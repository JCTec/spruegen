# Fixtures

Los anillos de prueba se generan por código (no se versionan STLs):

```
python tests/fixtures/rings.py        # torus, carved_band, head_ring, dumbbell -> *.stl
```

| anillo | qué prueba |
|---|---|
| `torus_ring()` | torus ID 19 mm, shank 2 mm: criterio de done, 1 feeder, spider/Y |
| `carved_band()` | interior liso, exterior delgado + sector tallado grueso: attach en el sector grueso, por dentro |
| `head_ring()` | torus con cabeza maciza: detección de cabeza |
| `dumbbell_ring()` | dos masas unidas por un shank fino: dos hot spots aislados -> 2 feeders |
| `open_torus()` | no watertight: la reparación falla ruidosamente |
| `tilted()` | eje arbitrario |

Los anillos de la galería (`plain_band`, `wide_band`, `lattice_band`, `signet`, `solitaire`) viven en
`spruegen/showcase.py` y se reusan acá. Si existe `../input.stl`, `tests/test_build.py` también lo corre.
