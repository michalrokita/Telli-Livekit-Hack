"""End-to-end + graceful-error tests for the stylist brain (Phase 8).

The full loop, fully OFFLINE (cassette replay, no network, no key):

    analyze(good photo) -> recommend(combo=True) -> tryon(combo) -> critic passes

plus the graceful-degradation contract the voice agent depends on (empty catalog,
bad input, async-critic failure) — every one must surface a clean, spoken-friendly
signal, never a traceback.

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

import tempfile  # noqa: E402
from io import BytesIO  # noqa: E402

from PIL import Image  # noqa: E402

import stylist  # noqa: E402
from stylist._openai import OpenAIError  # noqa: E402
from stylist.catalog import load_catalog  # noqa: E402
from stylist.schemas import Options, TryOnResult  # noqa: E402

_FIX = os.path.join(_ROOT, "stylist", "tests", "fixtures")
GOOD = os.path.join(_FIX, "analyze_good.png")
BAD = os.path.join(_FIX, "analyze_bad.png")
TEE = os.path.join(_FIX, "tryon_tee.png")


class TestEndToEnd(unittest.TestCase):
    """analyze -> recommend(combo) -> tryon(combo) -> critic pass, all from cassettes."""

    def test_full_loop_offline(self):
        # 1) PHOTO -> profile (usable, both categories feasible).
        profile = stylist.analyze(GOOD, cassette="analyze_good")
        self.assertTrue(profile.image_quality.usable)
        self.assertTrue(profile.tryon_feasibility.hat)
        self.assertTrue(profile.tryon_feasibility.tshirt)

        # 2) profile -> ranked options + outfit combos. No cassette -> the deterministic
        #    TEMPLATED rationale path runs fully offline (P2 replay-miss is swallowed).
        catalog = load_catalog()
        opts = stylist.recommend(profile, n=2, combo=True, catalog=catalog)
        self.assertIsInstance(opts, Options)
        self.assertTrue(opts.hats, "expected at least one hat")
        self.assertTrue(opts.tshirts, "expected at least one tee")
        self.assertTrue(opts.combos, "expected at least one outfit combo")

        # Every returned option/combo carries a non-empty rationale (spoken line).
        for o in opts.hats + opts.tshirts:
            self.assertTrue(o.rationale.strip(), f"empty rationale on {o.product_id}")
        for c in opts.combos:
            self.assertTrue(c.rationale.strip(), f"empty rationale on combo {c.hat_id}")

        # 3) pick the top combo and render it on the base photo.
        combo = opts.combos[0]
        hat_id, tee_id = combo.hat_id, combo.tshirt_id
        # The combo respects harmony: a real, in-range score and the best of the set.
        self.assertGreater(combo.harmony_score, 0.0)
        self.assertLessEqual(combo.harmony_score, 1.0)
        self.assertGreaterEqual(
            combo.harmony_score, 0.5, "top combo should be a harmonious pairing"
        )
        self.assertEqual(combo.harmony_score, max(c.harmony_score for c in opts.combos))

        with tempfile.TemporaryDirectory() as d:
            res = stylist.tryon(
                GOOD,
                [hat_id, tee_id],
                combo=True,
                catalog=catalog,
                out_dir=d,
                cassette="e2e_combo",
                critic_cassette="tryon_critic_pass",
            )
            # A final image file exists at image_url, and it is a valid PNG.
            self.assertTrue(os.path.exists(res.image_url))
            with Image.open(res.image_url) as im:
                self.assertEqual(im.format, "PNG")
            self.assertEqual(res.rendered_option_ids, [hat_id, tee_id])

            # Join the background critic and assert it settled to a pass.
            self.assertTrue(hasattr(res, "_critic_thread"))
            res._critic_thread.join(timeout=15)
            self.assertFalse(res._critic_thread.is_alive())
            self.assertEqual(res.status, "pass")
            self.assertEqual(res.retry_count, 0)
            self.assertIsNotNone(res.critic_report)

            # TryOnResult validates via a from_dict(to_dict()) round-trip.
            rt = TryOnResult.from_dict(res.to_dict())
            self.assertEqual(rt.status, res.status)
            self.assertEqual(rt.image_url, res.image_url)
            self.assertEqual(rt.rendered_option_ids, res.rendered_option_ids)


class TestGracefulErrors(unittest.TestCase):
    """Bad input degrades to a clean, catchable, spoken-friendly signal — never a crash."""

    def test_empty_catalog_returns_empty_options(self):
        # An empty store must not raise — recommend returns empty lists the agent can speak to.
        profile = stylist.analyze(GOOD, cassette="analyze_good")
        opts = stylist.recommend(profile, combo=True, catalog=[])
        self.assertIsInstance(opts, Options)
        self.assertEqual(opts.hats, [])
        self.assertEqual(opts.tshirts, [])
        self.assertEqual(opts.combos, [])

    def test_bad_photo_surfaces_unusable(self):
        # analyze never invents a usable read — it reports the photo as unusable + infeasible.
        profile = stylist.analyze(BAD, cassette="analyze_bad")
        self.assertFalse(profile.image_quality.usable)
        self.assertFalse(profile.tryon_feasibility.hat)
        self.assertFalse(profile.tryon_feasibility.tshirt)
        self.assertTrue(profile.image_quality.issues)  # a reason to speak back

    def test_empty_option_ids_is_a_clean_typed_error(self):
        # Empty selection -> a typed ValueError with a usable message (the agent catches
        # and speaks it), NOT a raw traceback. (Contract pinned by test_tryon too.)
        with self.assertRaises(ValueError) as ctx:
            stylist.tryon(GOOD, [], out_dir=tempfile.mkdtemp())
        self.assertIn("option_ids", str(ctx.exception))

    def test_unknown_id_is_a_clean_typed_error(self):
        # An id that isn't in the catalog and isn't a resolvable path -> usable ValueError.
        with self.assertRaises(ValueError) as ctx:
            stylist.tryon(GOOD, ["NOT-A-REAL-ID-XYZ"], out_dir=tempfile.mkdtemp())
        self.assertIn("NOT-A-REAL-ID-XYZ", str(ctx.exception))

    def test_async_critic_failure_settles_to_error_not_crash(self):
        # The render still succeeds and is delivered; a critic that cannot run (missing
        # cassette, offline) settles status to "error" on the background thread and still
        # fires on_critic — it never crashes the worker or loses the rendered image.
        import threading

        done = threading.Event()
        seen = {}

        def cb(r):
            seen["status"] = r.status
            done.set()

        with tempfile.TemporaryDirectory() as d:
            res = stylist.tryon(
                GOOD,
                [TEE],
                cassette="tryon_tee",
                critic_cassette="e2e_no_such_critic_cassette",
                on_critic=cb,
                out_dir=d,
            )
            # Synchronous render delivered regardless of the (doomed) critic.
            self.assertTrue(os.path.exists(res.image_url))
            self.assertTrue(done.wait(timeout=15), "on_critic never fired")
            res._critic_thread.join(timeout=15)
            self.assertEqual(res.status, "error")
            self.assertEqual(seen["status"], "error")
            # The delivered image is still on disk at the same url.
            self.assertTrue(os.path.exists(res.image_url))

    def test_analyze_typed_failure_on_unreplayable_call(self):
        # With no cassette and offline, analyze raises a typed OpenAIError (anti-loop:
        # 2 attempts then stop) — a clean signal, never an unbounded hang or raw traceback.
        with self.assertRaises(OpenAIError):
            stylist.analyze(GOOD, cassette=None)


if __name__ == "__main__":
    unittest.main()
