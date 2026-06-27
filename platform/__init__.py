"""platform — the persistence + app-state layer that wraps the pure ``stylist`` brain.

The ``stylist`` package is stateless inference (analyze / recommend / tryon over
plain ``@dataclass`` schemas). This ``platform`` package adds the only state it needs:
a crawled, pre-enriched product catalog — two sqlite tables, ``stores`` and
``products`` — persisted in a single stdlib ``sqlite3`` file. No ORM, no Postgres,
no third-party deps, no user accounts.

Submodules are imported directly (e.g. ``from platform import db``); nothing heavy is
imported eagerly here so that ``import platform`` stays cheap and side-effect free.

NAME-SHADOW NOTE (important): this package name shadows the Python stdlib ``platform``
module. Because the repo root sits ahead of the stdlib on ``sys.path``, a plain
``import platform`` resolves to THIS package — yet various stdlib modules do
``import platform; platform.system()`` at import time (e.g. ``uuid``). To keep both
worlds working, this package transparently delegates any attribute it does not define
(``system``, ``uname``, ``python_version``, …) to the genuine stdlib ``platform``
module via a PEP 562 module ``__getattr__``. So:

    from platform import db        # -> our submodule (normal package import)
    import platform; platform.system()   # -> delegated to the real stdlib platform

The delegation is lazy (only on attribute miss) and the real stdlib module is loaded
once, by file, with the repo root excluded from the search path to avoid recursion.
"""

from __future__ import annotations

__all__: list[str] = []
__version__ = "0.1.0"

# Cache for the genuine stdlib ``platform`` module (loaded on first delegated miss).
_stdlib_platform = None


def _load_stdlib_platform():
    """Load and cache the real stdlib ``platform`` module, bypassing this package.

    Finds ``platform`` on ``sys.path`` with this package's parent directory (the repo
    root) removed, so the finder resolves the stdlib module rather than us.
    """
    global _stdlib_platform
    if _stdlib_platform is not None:
        return _stdlib_platform
    import importlib.machinery
    import importlib.util
    import os
    import sys

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    search = [p for p in sys.path if os.path.abspath(p or ".") != repo_root]
    spec = importlib.machinery.PathFinder.find_spec("platform", search)
    if spec is None or spec.loader is None:  # pragma: no cover - stdlib always present
        raise ImportError("could not locate the stdlib 'platform' module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _stdlib_platform = module
    return module


def __getattr__(name: str):
    """PEP 562 fallback: delegate unknown attributes to the stdlib ``platform`` module.

    Submodules (``db``, ``tests``) are handled by the import machinery, not here, so a
    missing-name miss for them harmlessly raises ``AttributeError`` and the importer
    falls through to a real submodule import.
    """
    return getattr(_load_stdlib_platform(), name)
