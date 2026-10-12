import tempfile
import unittest
from pathlib import Path

from lightsctl import config
from lightsctl.base import parse_color, parse_kelvin
from lightsctl.tuya import dp_to_white, hex_to_rgb, rgb_to_hex, white_to_dp


class ParseTests(unittest.TestCase):
    def test_color_forms(self):
        self.assertEqual(parse_color(["red"]), (255, 0, 0))
        self.assertEqual(parse_color(["#00ff3c"]), (0, 255, 60))
        self.assertEqual(parse_color(["0", "0", "255"]), (0, 0, 255))

    def test_bad_color(self):
        for bad in (["nope"], ["300", "0", "0"], []):
            with self.assertRaises(ValueError):
                parse_color(bad)

    def test_kelvin(self):
        self.assertEqual(parse_kelvin("warm"), 2700)
        self.assertEqual(parse_kelvin("3500K"), 3500)


class TuyaEncodingTests(unittest.TestCase):
    def test_known_values_from_the_device(self):
        self.assertEqual(rgb_to_hex((255, 0, 0)), "ff00000000ffff")
        self.assertEqual(rgb_to_hex((0, 255, 60)), "00ff3c0086ffff")
        self.assertEqual(rgb_to_hex((0, 60, 255)), "003cff00e1ffff")

    def test_roundtrip(self):
        self.assertEqual(hex_to_rgb(rgb_to_hex((0, 60, 255))), (0, 60, 255))

    def test_dim_colour_keeps_hue(self):
        h = rgb_to_hex((0, 0, 128))
        self.assertEqual(h[:6], "0000ff")
        self.assertEqual(h[12:], "80")

    def test_white_range(self):
        self.assertEqual(white_to_dp(100), 255)
        self.assertEqual(white_to_dp(1), 27)
        self.assertEqual(dp_to_white(255), 100)
        self.assertEqual(dp_to_white(white_to_dp(50)), 50)


class ConfigTests(unittest.TestCase):
    def test_update_ip_only_touches_that_device(self):
        text = '[devices.a]\nip = "1.1.1.1"\n\n[devices.b]\nip = "2.2.2.2"\nkey = "k"\n'
        with tempfile.TemporaryDirectory() as d:
            config.CONFIG = Path(d) / "devices.toml"
            config.CONFIG.write_text(text)
            config.update_field("b", "ip", "9.9.9.9")
            self.assertEqual(config.CONFIG.read_text(),
                             '[devices.a]\nip = "1.1.1.1"\n\n[devices.b]\nip = "9.9.9.9"\nkey = "k"\n')
            with self.assertRaises(KeyError):
                config.update_field("c", "ip", "1")


if __name__ == "__main__":
    unittest.main()
