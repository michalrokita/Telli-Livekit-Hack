"""Tests for the rigged demo safety-net (Phase 8) — stdlib unittest, fully offline.

The on-stage fallback must produce a clean, critic-passed render with a non-empty rationale
on EVERY call — deterministically, never touching the network. We run it repeatedly to prove
the result (status, picks, rationale) doesn't drift.

Run from the repo root:
    python3 -m unittest discover -s stylist/tests -v
"""

import os
import sys
import tempfile
import unittest

# Make `import stylist...` work regardless of the current working directory.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PIL import Image  # noqa: E402

from stylist.demo import run_demo  # noqa: E402
from stylist.schemas import TryOnResult  # noqa: E402


class TestRunDemo(unittest.TestCase):
    def _assert_clean(self, out):
        # A clean, critic-passed render.
        self.assertIsInstance(out["tryon"], TryOnResult)
        self.assertEqual(out["status"], "pass")
        self.assertEqual(out["tryon"].status, "pass")
        self.assertTrue(os.path.exists(out["image_url"]))
        with Image.open(out["image_url"]) as im:
            self.assertEqual(im.format, "PNG")
        # A non-empty spoken rationale.
        self.assertTrue(out["rationale"].strip())
        self.assertTrue(out["spoken"].strip())
        # A combined hat+tee render.
        self.assertEqual(len(out["tryon"].rendered_option_ids), 2)

    def test_one_clean_run(self):
        with tempfile.TemporaryDirectory() as d:
            self._assert_clean(run_demo(out_dir=d))

    def test_deterministic_across_repeated_calls(self):
        """Same inputs → same picks/status/rationale, run after run (model variance excluded)."""
        picks, statuses, rationales = set(), set(), set()
        for _ in range(3):
            with tempfile.TemporaryDirectory() as d:
                out = run_demo(out_dir=d)
                self._assert_clean(out)
                picks.add(tuple(out["tryon"].rendered_option_ids))
                statuses.add(out["status"])
                rationales.add(out["rationale"])
        self.assertEqual(len(picks), 1, f"non-deterministic picks: {picks}")
        self.assertEqual(statuses, {"pass"})
        self.assertEqual(len(rationales), 1, f"non-deterministic rationale: {rationales}")

    def test_default_out_dir_still_writes_png(self):
        # out_dir=None -> tryon mints a temp dir; the render must still land on disk.
        out = run_demo()
        self._assert_clean(out)


if __name__ == "__main__":
    unittest.main()
