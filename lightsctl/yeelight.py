"""Yeelight-protocol backend over Xiaomi miIO (e.g. Mi Bedside Lamp 2)."""
import logging
import socket
import time

import miio

from .base import Light, local_subnet

logging.getLogger("miio").setLevel(logging.CRITICAL)  # it logs retries that succeed


class YeelightLight(Light):
    caps = frozenset({"color", "brightness", "kelvin"})
    kelvin_range = (1700, 6500)

    def _y(self):
        return miio.Yeelight(self.cfg["ip"], self.cfg["token"], model=self.cfg.get("model"))

    def on(self): self._y().on()
    def off(self): self._y().off()
    def color(self, rgb: tuple): self._y().set_rgb(tuple(rgb))
    def brightness(self, pct: int): self._y().set_brightness(max(1, min(100, pct)))

    def white(self, kelvin=None):
        lo, hi = self.kelvin_range
        self._y().set_color_temp(max(lo, min(hi, kelvin or 4000)))

    def status(self) -> dict:
        s = self._y().status()
        colour = s.color_mode in (1, 3)
        return {
            "on": s.is_on,
            "mode": "color" if colour else "white",
            "rgb": tuple(s.rgb) if colour and s.rgb else None,
            "brightness": s.brightness,
            "kelvin": None if colour else s.color_temp,
        }

    def snapshot(self) -> dict:
        s = self.status()
        return {"mode": s["mode"], "rgb": s["rgb"], "kelvin": s["kelvin"], "brightness": s["brightness"]}

    def restore(self, snap: dict):
        y = self._y()
        if snap["mode"] == "color" and snap["rgb"]:
            y.set_rgb(tuple(snap["rgb"]))
        elif snap.get("kelvin"):
            y.set_color_temp(snap["kelvin"])
        if snap.get("brightness"):
            y.set_brightness(snap["brightness"])

    def fingerprint(self) -> str:
        s = self.status()
        return f"{s['mode']}:{s['rgb'] if s['mode'] == 'color' else s['kelvin']}"

    def find_ip(self):
        """Broadcast the miIO hello packet and match the reply's device id."""
        want = int(self.cfg["did"])
        hello = bytes.fromhex("21310020" + "ff" * 28)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(0.3)
        base = local_subnet()
        for target in [f"{base}.255"] + [f"{base}.{i}" for i in range(1, 255)]:
            try:
                s.sendto(hello, (target, 54321))
            except OSError:
                pass
        end = time.time() + 4
        while time.time() < end:
            try:
                data, (ip, _) = s.recvfrom(1024)
            except socket.timeout:
                continue
            if data[:2] == b"\x21\x31" and int.from_bytes(data[8:12], "big") == want:
                return ip
        return None
