"""Tuya backend (e.g. Wipro/Smart Life lights) using the local network protocol."""
import colorsys
import socket
from concurrent.futures import ThreadPoolExecutor

import tinytuya

from .base import Light, local_subnet

WHITE_MIN, WHITE_MAX = 25, 255  # white-mode brightness range (data point 3)


def rgb_to_hex(rgb: tuple) -> str:
    """Colour data point: rrggbb (at full value) + hhhh + ss + vv."""
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    full = colorsys.hsv_to_rgb(h, s, 1)
    return "".join(f"{round(c * 255):02x}" for c in full) + f"{int(h * 360):04x}{round(s * 255):02x}{round(v * 255):02x}"


def hex_to_rgb(value: str) -> tuple:
    """Inverse of rgb_to_hex, applying the value (brightness) byte."""
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    v = int(value[12:14], 16) / 255
    return tuple(round(c * v) for c in (r, g, b))


def white_to_dp(pct: int) -> int:
    return round(WHITE_MIN + (WHITE_MAX - WHITE_MIN) * pct / 100)


def dp_to_white(value: int) -> int:
    return max(1, min(100, round((value - WHITE_MIN) * 100 / (WHITE_MAX - WHITE_MIN))))


class TuyaLight(Light):
    caps = frozenset({"color", "brightness"})

    def _device(self, ip=None):
        d = tinytuya.Device(self.cfg["id"], ip or self.cfg["ip"], self.cfg["key"],
                            version=float(self.cfg.get("version", 3.1)))
        d.set_socketTimeout(3)
        d.set_socketRetryLimit(2)
        return d

    def _dps(self) -> dict:
        res = self._device().status()
        if not res or "dps" not in res:
            raise ConnectionError((res or {}).get("Error", "no response"))
        return res["dps"]

    def _set(self, dp: int, value) -> None:
        res = self._device().set_value(dp, value)
        if res and "Error" in res:
            raise ConnectionError(res["Error"])

    def on(self): self._set(1, True)
    def off(self): self._set(1, False)

    def color(self, rgb: tuple):
        self._set(2, "colour")
        self._set(5, rgb_to_hex(rgb))

    def brightness(self, pct: int):
        pct = max(1, min(100, pct))
        dps = self._dps()
        if dps.get("2") == "colour":
            self._set(5, dps["5"][:12] + f"{round(pct * 255 / 100):02x}")
        else:
            self._set(3, white_to_dp(pct))

    def white(self, kelvin=None):
        # These bulbs have one fixed white, so a requested kelvin is ignored.
        self._set(2, "white")

    def status(self) -> dict:
        dps = self._dps()
        colour = dps.get("2") == "colour"
        return {
            "on": bool(dps.get("1")),
            "mode": "color" if colour else "white",
            "rgb": hex_to_rgb(dps["5"]) if colour else None,
            "brightness": round(int(dps["5"][12:14], 16) * 100 / 255) if colour else dp_to_white(dps.get("3", WHITE_MAX)),
            "kelvin": None,
        }

    def snapshot(self) -> dict:
        dps = self._dps()
        return {k: dps.get(k) for k in ("1", "2", "3", "5")}

    def restore(self, snap: dict):
        if snap.get("2") == "colour":
            self._set(2, "colour")
            self._set(5, snap["5"])
        else:
            self._set(2, "white")
            self._set(3, snap["3"])

    def fingerprint(self) -> str:
        dps = self._dps()
        return f"{dps.get('2')}:{dps.get('5') if dps.get('2') == 'colour' else dps.get('3')}"

    def find_ip(self):
        """Look for the light by UDP broadcast, then by probing the local /24."""
        for ip, info in tinytuya.deviceScan(False, 20).items():
            if info.get("gwId") == self.cfg["id"]:
                return ip
        base = local_subnet()

        def probe(ip):
            try:
                socket.create_connection((ip, 6668), timeout=1).close()
            except OSError:
                return None
            d = self._device(ip)
            d.set_socketRetryLimit(1)
            res = d.status()
            return ip if res and "dps" in res else None

        with ThreadPoolExecutor(64) as pool:
            for ip in pool.map(probe, [f"{base}.{i}" for i in range(1, 255)]):
                if ip:
                    return ip
        return None
