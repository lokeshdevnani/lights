import tempfile
import unittest
from pathlib import Path

import datetime as dt

from lightsctl import cli, config, effects, melk, scenes, timers
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


class SunriseTests(unittest.TestCase):
    def test_ramps_one_percent_per_step_from_warm_white(self):
        class Fake:
            name, caps = "f", frozenset({"brightness", "kelvin"})
            def __init__(self): self.log = []
            def on(self): self.log.append("on")
            def white(self, k=None): self.log.append(("white", k))
            def brightness(self, pct): self.log.append(pct)
        light = Fake()
        effects.sunrise([light], duration=0.2)
        self.assertEqual(light.log[:4], [1, "on", ("white", 2700), 1])
        self.assertEqual(light.log[4:], list(range(2, 101)))


class PomodoroTests(unittest.TestCase):
    def fake(self, caps):
        class Fake:
            name = "f"
            def __init__(self): self.log = []
            def status(self): return {"on": True}
            def snapshot(self): return {"s": 1}
            def restore(self, snap): self.log.append("restore")
            def on(self): pass
            def color(self, rgb): self.log.append(rgb)
            def white(self, k=None): self.log.append(k)
            def brightness(self, pct): pass
        f = Fake(); f.caps = frozenset(caps); return f

    def test_colour_light_goes_red_then_green_then_restores(self):
        light = self.fake({"color", "brightness"})
        effects.pomodoro([light], focus=0, rest=0, rounds=2)
        self.assertEqual(light.log, [(255, 0, 0), (0, 255, 0)] * 2 + ["restore"])

    def test_white_only_light_goes_cool_then_warm(self):
        light = self.fake({"kelvin", "brightness"})
        effects.pomodoro([light], focus=0, rest=0, rounds=1)
        self.assertEqual(light.log, [6500, 2700, "restore"])


class SceneTests(unittest.TestCase):
    cfg = {"scenes": {"night": ["tube warmth 100", "tube 10"], "bad": ["party 5s"]}}

    def test_lists_and_looks_up_scenes(self):
        self.assertEqual(scenes.names(self.cfg), ["night", "bad"])
        self.assertEqual(scenes.lines(self.cfg, "night"), ["tube warmth 100", "tube 10"])
        with self.assertRaises(ValueError):
            scenes.lines(self.cfg, "nope")

    def test_long_running_commands_are_refused(self):
        with self.assertRaises(ValueError):
            scenes.run(self.cfg, "bad")


class SunsetTests(unittest.TestCase):
    def test_fades_down_to_one_percent_then_off(self):
        class Fake:
            name, caps = "f", frozenset({"brightness"})
            def __init__(self): self.log = []
            def status(self): return {"on": True, "brightness": 40}
            def brightness(self, pct): self.log.append(pct)
            def off(self): self.log.append("off")
        light = Fake()
        effects.sunset([light], duration=0.1)
        self.assertEqual(light.log[-2:], [1, "off"])
        self.assertEqual(light.log[:-1], sorted(light.log[:-1], reverse=True))


class RunningShowTests(unittest.TestCase):
    def test_show_is_listed_while_running_and_gone_after(self):
        with tempfile.TemporaryDirectory() as d:
            timers.RUNNING = Path(d)
            with timers.running_as("sunrise 100s on tube"):
                self.assertEqual([r["what"] for r in timers.running()], ["sunrise 100s on tube"])
            self.assertEqual(timers.running(), [])


class FakeBle:
    sent = []

    def __init__(self, address, timeout): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): pass
    async def write_gatt_char(self, uuid, data, response): FakeBle.sent.append(data.hex())


class MelkTests(unittest.TestCase):
    def test_frames_that_worked_on_the_lamp(self):
        self.assertEqual(melk.power_frame(True).hex(), "7e0404010001ff00ef")
        self.assertEqual(melk.power_frame(False).hex(), "7e0404000000ff00ef")
        self.assertEqual(melk.rgb_frame((255, 0, 0)).hex(), "7e070503ff000010ef")
        self.assertEqual(melk.brightness_frame(100).hex(), "7e04016400ffff00ef")
        self.assertEqual(melk.effect_frame("gradual").hex(), "7e0503c706ffff00ef")

    def test_effects_by_name_scene_or_number(self):
        self.assertEqual(melk.effect_frame("rainbow").hex(), "7e05310b07ffff01ef")
        self.assertEqual(melk.effect_frame("57"), melk.frame(0x05, 0x03, 57, 0x06))
        for bad in ("nope", "213"):
            with self.assertRaises(ValueError):
                melk.effect_frame(bad)

    def test_remembers_what_it_sent(self):
        with tempfile.TemporaryDirectory() as d:
            old = config.CACHE, melk.BleakClient
            config.CACHE, melk.BleakClient = Path(d), FakeBle
            try:
                FakeBle.sent = []
                l = melk.MelkLight("corner", {"address": "x"})
                l.color((0, 0, 255)); l.brightness(40); l.off()
                self.assertEqual(FakeBle.sent, [melk.rgb_frame((0, 0, 255)).hex(),
                                                melk.brightness_frame(40).hex(), melk.power_frame(False).hex()])
                self.assertEqual(l.status(), {"on": False, "mode": "color", "rgb": (0, 0, 255),
                                              "brightness": 40, "kelvin": None, "effect": None})
                l.effect("ocean", 70)
                self.assertEqual(FakeBle.sent[-2:], [melk.effect_frame("ocean").hex(), melk.speed_frame(70).hex()])
                self.assertEqual(cli.describe({**l.status(), "on": True}), "on, effect ocean, brightness 40%")
                l.color((255, 0, 0))
                self.assertIsNone(l.status()["effect"])
            finally:
                config.CACHE, melk.BleakClient = old


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
