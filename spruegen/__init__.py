"""spruegen: árbol de colada (feeders por la cara interna + stem Ø10x35) para anillos STL (lost-wax)."""

import warnings as _warnings

# astillas de área cero en mallas de CAD: trimesh avisa en baricéntricas, sin efecto en los resultados
_warnings.filterwarnings("ignore", category=RuntimeWarning, module=r"trimesh\.triangles")

__version__ = "0.3.0"
