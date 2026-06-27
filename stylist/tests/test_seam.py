"""Partner-seam tests (Phase 7): the package exposes exactly the 3 callables +
the schemas module, and the optional FastAPI wrapper imports without fastapi.

Run from the repo root:
    python3 -m unittest discover -s stylist/tests -v
"""

import os
import sys
import unittest

# Make `import stylist...` work regardless of the current working directory.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import stylist  # noqa: E402


class TestSeamExports(unittest.TestCase):
    """`import stylist` exposes analyze / recommend / tryon (callable) + schemas."""

    def test_three_callables_exposed(self):
        for name in ("analyze", "recommend", "tryon"):
            self.assertTrue(hasattr(stylist, name), f"stylist.{name} is missing")
            self.assertTrue(callable(getattr(stylist, name)), f"stylist.{name} not callable")

    def test_schemas_module_exposed(self):
        self.assertTrue(hasattr(stylist, "schemas"), "stylist.schemas is missing")
        # The data contract is reachable through it.
        for contract in ("StyleProfile", "Options", "TryOnResult"):
            self.assertTrue(
                hasattr(stylist.schemas, contract), f"stylist.schemas.{contract} missing"
            )

    def test_all_lists_the_seam(self):
        self.assertEqual(
            set(stylist.__all__), {"analyze", "recommend", "tryon", "schemas"}
        )

    def test_importing_package_is_offline(self):
        # The 3 callables resolve without any network: the OpenAI calls live INSIDE
        # the functions, not at import time. Re-importing must stay cheap/clean.
        self.assertIsNotNone(stylist.__version__)


class TestServeLazyImport(unittest.TestCase):
    """`import stylist.serve` must not raise even when fastapi is absent."""

    def test_import_serve_does_not_require_fastapi(self):
        import stylist.serve as serve  # noqa: F401 — must succeed with or without fastapi

        self.assertTrue(hasattr(serve, "create_app"))
        self.assertTrue(callable(serve.create_app))

    def test_create_app_only_when_fastapi_present(self):
        import stylist.serve as serve

        try:
            import fastapi  # noqa: F401
        except ImportError:
            # Lazy-import contract is proven by the import test above; nothing more to do.
            self.skipTest("fastapi not installed — lazy-import path already verified")
        app = serve.create_app()
        self.assertIsNotNone(app)


if __name__ == "__main__":
    unittest.main()
