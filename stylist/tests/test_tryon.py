"""Offline/replay tests for stylist.tryon (Phase 6) — stdlib unittest, no network.

Run from the repo root:
    python3 -m unittest discover -s stylist/tests -v
"""

import os
import sys
import threading
import unittest
from io import BytesIO

# Make `import stylist...` work regardless of the current working directory.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PIL import Image  # noqa: E402

import importlib  # noqa: E402

# `stylist.tryon` (the attribute) is the PUBLIC callable since Phase 7 exported it on
# the package; grab the real submodule object for its helpers (run_critic/build_mask/…).
T = importlib.import_module("stylist.tryon")  # noqa: E402
from stylist.schemas import CriticReport, TryOnResult  # noqa: E402

_FIX = os.path.join(_ROOT, "stylist", "tests", "fixtures")
BASE = os.path.join(_FIX, "tryon_base.png")
TEE = os.path.join(_FIX, "tryon_tee.png")
HAT = os.path.join(_FIX, "tryon_hat.png")

_LIVE = os.environ.get("STYLIST_LIVE") == "1"


class TestTryOnSyncReturn(unittest.TestCase):
    """The synchronous return is fast and NEVER waits on the critic."""

    def setUp(self):
        import tempfile
        self._dir = tempfile.TemporaryDirectory()
        self.out = self._dir.name

    def tearDown(self):
        self._dir.cleanup()

    def test_returns_fast_pending(self):
        # No critic_cassette -> no critic thread spawned -> deterministic pending/None.
        res = T.tryon(BASE, [TEE], cassette="tryon_tee", out_dir=self.out)
        self.assertIsInstance(res, TryOnResult)
        self.assertEqual(res.status, "pending")
        self.assertIsNone(res.critic_report)
        self.assertEqual(res.retry_count, 0)
        self.assertEqual(res.rendered_option_ids, [TEE])
        self.assertTrue(os.path.exists(res.image_url))
        # The rendered file is a valid PNG.
        with Image.open(res.image_url) as im:
            self.assertEqual(im.format, "PNG")
        # No critic thread because no cassette / not live.
        self.assertFalse(hasattr(res, "_critic_thread"))

    def test_combo_single_pass(self):
        res = T.tryon(BASE, [TEE, HAT], combo=True, cassette="tryon_combo", out_dir=self.out)
        self.assertEqual(res.status, "pending")
        self.assertEqual(res.rendered_option_ids, [TEE, HAT])
        self.assertTrue(os.path.exists(res.image_url))

    def test_catalog_id_map_resolution(self):
        # id -> image-path map; category inferred from the id ("TEE-..." -> tshirt).
        catalog = {"TEE-OLIVE-001": TEE}
        res = T.tryon(BASE, ["TEE-OLIVE-001"], catalog=catalog, cassette="tryon_tee", out_dir=self.out)
        self.assertEqual(res.status, "pending")
        self.assertEqual(res.rendered_option_ids, ["TEE-OLIVE-001"])
        self.assertTrue(os.path.exists(res.image_url))

    def test_empty_option_ids_raises(self):
        with self.assertRaises(ValueError):
            T.tryon(BASE, [], out_dir=self.out)


class TestRunCritic(unittest.TestCase):
    """run_critic replays a CriticReport from a json cassette."""

    def test_pass(self):
        rep = T.run_critic(BASE, TEE, {"tshirt": "olive crew"}, cassette="tryon_critic_pass")
        self.assertIsInstance(rep, CriticReport)
        self.assertEqual(rep.verdict, "pass")
        self.assertEqual(rep.fix_instruction, "")

    def test_retry(self):
        rep = T.run_critic(BASE, TEE, {"tshirt": "olive crew"}, cassette="tryon_critic_retry")
        self.assertEqual(rep.verdict, "retry")
        self.assertTrue(rep.fix_instruction)  # a concrete fix is provided


class TestAsyncCritic(unittest.TestCase):
    """The background critic settles status, hot-swaps on retry, and caps at 1 re-render."""

    def setUp(self):
        import tempfile
        self._dir = tempfile.TemporaryDirectory()
        self.out = self._dir.name

    def tearDown(self):
        self._dir.cleanup()

    def _wait(self, res, done):
        # Belt and suspenders: wait on both the callback Event and the thread handle.
        self.assertTrue(done.wait(timeout=15), "critic callback never fired")
        res._critic_thread.join(timeout=15)
        self.assertFalse(res._critic_thread.is_alive())

    def test_pass_keeps_zero_retries(self):
        done = threading.Event()
        seen = {}

        def cb(r):
            seen["status"] = r.status
            seen["retry"] = r.retry_count
            done.set()

        res = T.tryon(BASE, [TEE], cassette="tryon_tee",
                      critic_cassette="tryon_critic_pass", on_critic=cb, out_dir=self.out)
        self._wait(res, done)
        self.assertEqual(res.status, "pass")
        self.assertEqual(res.retry_count, 0)
        self.assertIsNotNone(res.critic_report)
        self.assertEqual(seen["status"], "pass")
        self.assertEqual(seen["retry"], 0)

    def test_retry_does_one_rerender_then_caps(self):
        done = threading.Event()

        def cb(r):
            done.set()

        res = T.tryon(BASE, [TEE], cassette="tryon_tee",
                      critic_cassette="tryon_critic_retry", on_critic=cb, out_dir=self.out)
        self._wait(res, done)
        # Cap = 1 background re-render; never loops past it.
        self.assertEqual(res.retry_count, 1)
        self.assertIn(res.status, ("pass", "low_confidence"))
        # The retry cassette always says "retry" -> capped -> low_confidence.
        self.assertEqual(res.status, "low_confidence")
        self.assertIsNotNone(res.critic_report)
        # The hot-swapped image still exists at the same url.
        self.assertTrue(os.path.exists(res.image_url))


class TestBuildMask(unittest.TestCase):
    def test_valid_rgba_png_with_edit_and_locked_regions(self):
        png = T.build_mask(BASE, ["torso", "hat"])
        self.assertIsInstance(png, (bytes, bytearray))
        with Image.open(BytesIO(png)) as im:
            self.assertEqual(im.format, "PNG")
            self.assertIn("A", im.getbands())  # has an alpha channel
            im = im.convert("RGBA")
            w, h = im.size
            # Torso centre is transparent (alpha=0 -> EDIT region).
            self.assertEqual(im.getpixel((w // 2, int(h * 0.7)))[3], 0)
            # Head-top centre is transparent too (hat region requested).
            self.assertEqual(im.getpixel((w // 2, int(h * 0.10)))[3], 0)
            # A corner is opaque (alpha=255 -> LOCKED: face/background protected).
            self.assertEqual(im.getpixel((1, 1))[3], 255)

    def test_unknown_region_raises(self):
        with self.assertRaises(ValueError):
            T.build_mask(BASE, ["shoes"])


class TestP3Prompt(unittest.TestCase):
    def test_verbatim_blocks_and_toggled_bullets(self):
        # Verbatim anchors from spec §5.2.
        tee_only = T.build_p3_prompt(tee_desc="olive crew", hat_desc=None)
        self.assertIn("PRESERVE EXACTLY (do not change): the person's face and identity", tee_only)
        self.assertIn("CHANGE ONLY the clothing:", tee_only)
        self.assertIn("Negative: warped or different face", tee_only)
        self.assertIn("Replace their current top with: olive crew", tee_only)
        self.assertNotIn("- Add:", tee_only)  # hat bullet omitted

        combo = T.build_p3_prompt(tee_desc="olive crew", hat_desc="navy cap")
        self.assertIn("Replace their current top with: olive crew", combo)
        self.assertIn("Add: navy cap", combo)

        fixed = T.build_p3_prompt(tee_desc="olive crew", fix_instruction="restore the face exactly")
        self.assertIn("Correction (apply this fix): restore the face exactly", fixed)


@unittest.skipUnless(_LIVE, "set STYLIST_LIVE=1 (and OPENAI_API_KEY) to run the live smoke")
class TestLiveSmoke(unittest.TestCase):
    """One real gpt-image-2 render + a real critic report. Spends a little credit."""

    def test_one_real_render_and_critic(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            res = T.tryon(BASE, [TEE], out_dir=d)  # live: critic spawns automatically
            self.assertEqual(res.status, "pending")
            self.assertTrue(os.path.exists(res.image_url))
            res._critic_thread.join(timeout=300)
            self.assertIsNotNone(res.critic_report)
            self.assertIn(res.status, ("pass", "low_confidence", "error"))


if __name__ == "__main__":
    unittest.main()
