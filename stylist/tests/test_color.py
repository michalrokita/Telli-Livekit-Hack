"""Tests for stylist._color — colour science self-checks (stdlib unittest).

Run from anywhere:
    python3 -m unittest discover -s stylist/tests -v
"""

import os
import sys
import unittest

# Make `import stylist...` work regardless of the current working directory.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stylist import _color  # noqa: E402


class TestHexRgb(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_color.hex_to_rgb("#ffffff"), (255, 255, 255))
        self.assertEqual(_color.hex_to_rgb("#000000"), (0, 0, 0))
        self.assertEqual(_color.hex_to_rgb("#556b2f"), (0x55, 0x6b, 0x2f))

    def test_no_hash_ok(self):
        self.assertEqual(_color.hex_to_rgb("556b2f"), (0x55, 0x6b, 0x2f))

    def test_invalid_raises(self):
        # note: a bare 6-digit hex (no '#') is accepted by design; these are not hex.
        for bad in ("#12345", "#gggggg", "blue", "12345", "", 123, None):
            with self.assertRaises(ValueError):
                _color.hex_to_rgb(bad)

    def test_is_hex(self):
        self.assertTrue(_color.is_hex("#abcdef"))
        self.assertTrue(_color.is_hex("ABCDEF"))
        self.assertFalse(_color.is_hex("#xyz"))
        self.assertFalse(_color.is_hex(None))


class TestLab(unittest.TestCase):
    def test_white(self):
        L, a, b = _color.srgb_to_lab((255, 255, 255))
        self.assertAlmostEqual(L, 100.0, places=2)
        self.assertAlmostEqual(a, 0.0, places=2)
        self.assertAlmostEqual(b, 0.0, places=2)

    def test_black(self):
        L, a, b = _color.srgb_to_lab((0, 0, 0))
        self.assertAlmostEqual(L, 0.0, places=4)
        self.assertAlmostEqual(a, 0.0, places=4)
        self.assertAlmostEqual(b, 0.0, places=4)

    def test_mid_grey_neutral(self):
        # A neutral grey has a*≈0, b*≈0.
        _, a, b = _color.srgb_to_lab((128, 128, 128))
        self.assertAlmostEqual(a, 0.0, places=1)
        self.assertAlmostEqual(b, 0.0, places=1)


class TestDeltaE(unittest.TestCase):
    def test_identical_zero(self):
        self.assertAlmostEqual(_color.delta_e_hex("#556b2f", "#556b2f"), 0.0, places=6)
        lab = _color.hex_to_lab("#b7410e")
        self.assertAlmostEqual(_color.delta_e_ciede2000(lab, lab), 0.0, places=6)

    def test_white_black_large(self):
        de = _color.delta_e_hex("#ffffff", "#000000")
        # L1=100,L2=0 with Sl=1 -> ΔE00 = 100.
        self.assertGreater(de, 95.0)
        self.assertAlmostEqual(de, 100.0, places=2)

    def test_ciede2000_reference_pair(self):
        # Sharma/Wu/Dalal CIEDE2000 test data, pair #1.
        lab1 = (50.0000, 2.6772, -79.7751)
        lab2 = (50.0000, 0.0000, -82.7485)
        self.assertAlmostEqual(_color.delta_e_ciede2000(lab1, lab2), 2.0425, places=3)

    def test_ciede2000_reference_pair_2(self):
        # Sharma test data, a hue-driven pair.
        lab1 = (50.0000, 2.5000, 0.0000)
        lab2 = (73.0000, 25.0000, -18.0000)
        self.assertAlmostEqual(_color.delta_e_ciede2000(lab1, lab2), 27.1492, places=3)

    def test_near_colours_small(self):
        # Two olives a hair apart -> small ΔE; far warmer/cooler -> large.
        near = _color.delta_e_hex("#556b2f", "#566b2e")
        far = _color.delta_e_hex("#556b2f", "#cfe8ff")  # olive vs icy blue
        self.assertLess(near, 2.0)
        self.assertGreater(far, near)


class TestHsl(unittest.TestCase):
    def test_primary_hues(self):
        self.assertAlmostEqual(_color.hue_deg("#ff0000"), 0.0, places=1)
        self.assertAlmostEqual(_color.hue_deg("#00ff00"), 120.0, places=1)
        self.assertAlmostEqual(_color.hue_deg("#0000ff"), 240.0, places=1)

    def test_saturation_lightness(self):
        self.assertAlmostEqual(_color.saturation("#808080"), 0.0, places=3)  # grey
        self.assertAlmostEqual(_color.saturation("#ff0000"), 1.0, places=3)  # pure red
        self.assertAlmostEqual(_color.lightness("#ffffff"), 1.0, places=3)
        self.assertAlmostEqual(_color.lightness("#000000"), 0.0, places=3)

    def test_hue_distance_circular(self):
        self.assertAlmostEqual(_color.hue_distance(10.0, 350.0), 20.0, places=3)
        self.assertAlmostEqual(_color.hue_distance(0.0, 180.0), 180.0, places=3)

    def test_analogous(self):
        self.assertTrue(_color.is_analogous("#ff0000", "#ff5500"))   # red / orange (~20°)
        self.assertFalse(_color.is_analogous("#ff0000", "#00ff00"))  # red / green

    def test_complementary(self):
        self.assertTrue(_color.is_complementary("#ff0000", "#00ffff"))   # red / cyan
        self.assertFalse(_color.is_complementary("#ff0000", "#ff8000"))  # red / orange


if __name__ == "__main__":
    unittest.main()
