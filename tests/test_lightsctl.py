import tempfile
import unittest
from pathlib import Path

import datetime as dt

from lightsctl import cli, config, effects, timers
from lightsctl.base import Unsupported, parse_color, parse_kelvin
from lightsctl.tuya import TuyaWhiteLight, dp_to_white, hex_to_rgb, rgb_to_hex, white_to_dp


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


NAMES = ["bulb", "lampy"]


class CliParsingTests(unittest.TestCase):
    def test_selector(self):
        self.assertEqual(cli.split_selector(["off"], NAMES), (NAMES, ["off"]))
        self.assertEqual(cli.split_selector([], NAMES), (NAMES, []))
        self.assertEqual(cli.split_selector(["lampy", "orange"], NAMES), (["lampy"], ["orange"]))
        self.assertEqual(cli.split_selector(["lampy,bulb", "off"], NAMES), (["lampy", "bulb"], ["off"]))
        self.assertEqual(cli.split_selector(["all", "off"], NAMES), (NAMES, ["off"]))

    def test_unknown_light_is_not_a_selector(self):
        self.assertEqual(cli.split_selector(["lampyy", "on"], NAMES), (NAMES, ["lampyy", "on"]))

    def test_shorthands(self):
        n = cli.normalize
        self.assertEqual(n([], NAMES), ("status", []))
        self.assertEqual(n(["off"], NAMES), ("off", []))
        self.assertEqual(n(["orange"], NAMES), ("color", ["orange"]))
        self.assertEqual(n(["#ff8800"], NAMES), ("color", ["#ff8800"]))
        self.assertEqual(n(["30"], NAMES), ("brightness", ["30"]))
        self.assertEqual(n(["30%"], NAMES), ("brightness", ["30"]))
        self.assertEqual(n(["warm"], NAMES), ("white", ["warm"]))
        self.assertEqual(n(["3000k"], NAMES), ("white", ["3000k"]))
        self.assertEqual(n(["white"], NAMES), ("white", []))
        self.assertEqual(n(["color", "0", "0", "255"], NAMES), ("color", ["0", "0", "255"]))

    def test_unknown_command(self):
        with self.assertRaisesRegex(ValueError, "Lights: bulb, lampy"):
            cli.normalize(["lampyy", "on"], NAMES)
        with self.assertRaises(ValueError):
            cli.normalize(["banana"], NAMES)


class TimerTests(unittest.TestCase):
    def test_durations(self):
        self.assertEqual(timers.parse_duration("30s"), 30)
        self.assertEqual(timers.parse_duration("5m"), 300)
        self.assertEqual(timers.parse_duration("1h30m"), 5400)
        for bad in ("30", "5x", "", "m5"):
            with self.assertRaises(ValueError):
                timers.parse_duration(bad)

    def test_clock_rolls_to_tomorrow(self):
        now = dt.datetime(2026, 10, 13, 22, 0, 0)
        self.assertEqual(dt.datetime.fromtimestamp(timers.parse_clock("22:30", now)), dt.datetime(2026, 10, 13, 22, 30))
        self.assertEqual(dt.datetime.fromtimestamp(timers.parse_clock("07:15", now)), dt.datetime(2026, 10, 14, 7, 15))
        with self.assertRaises(ValueError):
            timers.parse_clock("25:00", now)

    def test_split_when(self):
        run_at, rest = timers.split_when(["lampy", "red", "in", "30s"], now=1000.0)
        self.assertEqual((run_at, rest), (1030.0, ["lampy", "red"]))
        self.assertEqual(timers.split_when(["off"], now=1000.0), (None, ["off"]))
        self.assertEqual(timers.split_when(["lampy", "off", "in", "1h"], now=0.0)[0], 3600.0)


class PartyTests(unittest.TestCase):
    def test_colors_are_vivid_and_change(self):
        prev = None
        for _ in range(200):
            rgb, hue = effects.party_color(prev)
            self.assertTrue(all(0 <= c <= 255 for c in rgb))
            self.assertEqual(max(rgb), 255)  # fully saturated and bright
            if prev is not None:
                self.assertGreater(min(abs(hue - prev), 1 - abs(hue - prev)), 0.15)
            prev = hue


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


class TuyaWhiteTests(unittest.TestCase):
    def light(self):
        l = TuyaWhiteLight("t", {})
        l.sent = []
        l._set = lambda dp, v: l.sent.append((dp, v))
        return l

    def test_white_sets_temperature_scale(self):
        l = self.light()
        l.white(2700); l.white(6500); l.white(4600)
        self.assertEqual(l.sent, [(23, 0), (23, 1000), (23, 500)])

    def test_brightness_scale_and_no_colour(self):
        l = self.light()
        l.brightness(1); l.brightness(100)
        self.assertEqual(l.sent, [(22, 10), (22, 1000)])
        with self.assertRaises(Unsupported):
            l.require("color")


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


class ServerTests(unittest.TestCase):
    def test_run_cli_refuses_internal_commands(self):
        from lightsctl import server
        self.assertEqual(server.run_cli("serve"), (False, "not allowed"))
        self.assertEqual(server.run_cli("--later 1 x off"), (False, "not allowed"))
        self.assertEqual(server.run_cli(""), (False, "not allowed"))


if __name__ == "__main__":
    unittest.main()
