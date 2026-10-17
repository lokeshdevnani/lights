"""duoCo StripX Bluetooth lights (MELK-* controllers, e.g. a Yugam corner lamp).

Frames follow https://github.com/wxx9248/Corner-Floor-Lamp-Controller: 9 bytes,
7E <len> <op> <payload> EF, written to characteristic FFF3. The lamp is write-only,
so status comes from the last state we sent, kept in a small cache file.
"""
import asyncio
import json

from bleak import BleakClient, BleakScanner

from . import config
from .base import Light

WRITE_UUID = "0000fff3-0000-1000-8000-00805f9b34fb"
DEFAULT_STATE = {"on": True, "rgb": [255, 255, 255], "brightness": 100, "effect": None}

# Built-in effects: ("mode", 0-212) animations or ("scene", 1-28) presets. Any other
# animation can be picked by number: `lights corner effect 57`.
EFFECTS = {
    "gradual": ("mode", 199), "auto": ("mode", 0), "magic": ("mode", 1), "trans": ("mode", 3),
    "tail": ("mode", 23), "water": ("mode", 39), "wave": ("mode", 83), "running": ("mode", 103),
    "flush": ("mode", 181), "jump": ("mode", 193), "strobe": ("mode", 196), "energy": ("mode", 212),
    "sunrise": ("scene", 1), "sunset": ("scene", 2), "candle": ("scene", 4), "fireworks": ("scene", 5),
    "party": ("scene", 6), "starry": ("scene", 8), "romantic": ("scene", 9), "disco": ("scene", 10),
    "rainbow": ("scene", 11), "christmas": ("scene", 13), "ocean": ("scene", 16), "forest": ("scene", 17),
    "fire": ("scene", 24), "lightning": ("scene", 25),
}


def frame(b1: int, op: int, p3=0xFF, p4=0xFF, p5=0xFF, p6=0xFF, p7=0x00) -> bytes:
    return bytes([0x7E, b1, op, p3, p4, p5, p6, p7, 0xEF])


def power_frame(on: bool) -> bytes:
    v = 1 if on else 0
    return frame(0x04, 0x04, v, 0x00, v)


def brightness_frame(pct: int) -> bytes:
    return frame(0x04, 0x01, max(0, min(100, pct)), 0x00)


def rgb_frame(rgb: tuple) -> bytes:
    r, g, b = rgb
    return frame(0x07, 0x05, 0x03, r, g, b, 0x10)


def effect_frame(name: str) -> bytes:
    kind, n = EFFECTS.get(name) or ("mode", int(name) if name.isdigit() and int(name) <= 212 else -1)
    if n < 0:
        raise ValueError(f"unknown effect {name!r}; try {', '.join(EFFECTS)} or a number 0-212")
    return frame(0x05, 0x03, n, 0x06) if kind == "mode" else frame(0x05, 0x31, n, 0x07, 0xFF, 0xFF, 0x01)


def speed_frame(pct: int) -> bytes:
    return frame(0x04, 0x02, max(0, min(100, pct)))


class MelkLight(Light):
    caps = frozenset({"color", "brightness", "effects"})
    addr_field = "address"

    def _state_file(self):
        return config.CACHE / f"melk-{self.name}.json"

    def _state(self) -> dict:
        try:
            return {**DEFAULT_STATE, **json.loads(self._state_file().read_text())}
        except (OSError, ValueError):
            return dict(DEFAULT_STATE)

    def _send(self, *frames: bytes, **changes) -> None:
        async def go():
            async with BleakClient(self.cfg["address"], timeout=15) as c:
                for f in frames:
                    await c.write_gatt_char(WRITE_UUID, f, response=False)
                    await asyncio.sleep(0.03)
        asyncio.run(go())
        self._state_file().parent.mkdir(parents=True, exist_ok=True)
        self._state_file().write_text(json.dumps({**self._state(), **changes}))

    def on(self): self._send(power_frame(True), on=True)
    def off(self): self._send(power_frame(False), on=False)
    def color(self, rgb: tuple): self._send(rgb_frame(rgb), rgb=list(rgb), effect=None)

    def effect(self, name: str, speed=None):
        frames = [effect_frame(name)] + ([speed_frame(speed)] if speed is not None else [])
        self._send(*frames, effect=name)
    def brightness(self, pct: int): self._send(brightness_frame(pct), brightness=pct)

    def white(self, kelvin=None):
        # RGB-only LEDs: there is no warm/cool channel, so white is plain RGB white.
        self.color((255, 255, 255))

    def status(self) -> dict:
        s = self._state()
        return {"on": s["on"], "mode": "color", "rgb": tuple(s["rgb"]),
                "brightness": s["brightness"], "kelvin": None, "effect": s["effect"]}

    def snapshot(self) -> dict:
        s = self._state()
        return {"rgb": s["rgb"], "brightness": s["brightness"], "effect": s["effect"]}

    def restore(self, snap: dict):
        look = effect_frame(snap["effect"]) if snap.get("effect") else rgb_frame(tuple(snap["rgb"]))
        self._send(look, brightness_frame(snap["brightness"]),
                   rgb=snap["rgb"], brightness=snap["brightness"], effect=snap.get("effect"))

    def fingerprint(self) -> str:
        s = self._state()
        return f"{s['effect'] or s['rgb']}:{s['brightness']}"

    def check(self): self._send()

    def find_ip(self):
        """Scan for the controller's Bluetooth name; returns its address on this computer."""
        dev = asyncio.run(BleakScanner.find_device_by_name(self.cfg["ble_name"], timeout=10))
        return dev.address if dev else None
