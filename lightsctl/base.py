"""The interface every light backend implements, plus shared parsing helpers."""
import re
import socket

NAMED_COLORS = {
    "red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255),
    "yellow": (255, 255, 0), "orange": (255, 100, 0), "purple": (150, 0, 255),
    "pink": (255, 60, 150), "cyan": (0, 255, 255), "white": (255, 255, 255),
}
KELVIN_NAMES = {"warm": 2700, "neutral": 4000, "cool": 6500}


COMMANDS = frozenset({"on", "off", "toggle", "status", "list", "fix-ip", "color", "brightness", "white"})
RESERVED_WORDS = COMMANDS | NAMED_COLORS.keys() | KELVIN_NAMES.keys() | {"all"}


class Unsupported(Exception):
    """The light cannot do what was asked (e.g. colour on a white-only light)."""


def parse_color(args: list) -> tuple:
    if len(args) == 3:
        rgb = tuple(int(a) for a in args)
    elif len(args) == 1:
        a = args[0].lower().lstrip("#")
        if a in NAMED_COLORS:
            rgb = NAMED_COLORS[a]
        elif re.fullmatch(r"[0-9a-f]{6}", a):
            rgb = tuple(int(a[i:i + 2], 16) for i in (0, 2, 4))
        else:
            raise ValueError(f"unknown colour {args[0]!r}")
    else:
        raise ValueError("usage: color NAME | #RRGGBB | R G B")
    if not all(0 <= c <= 255 for c in rgb):
        raise ValueError("RGB values must be 0-255")
    return rgb


def parse_kelvin(arg: str) -> int:
    if arg.lower() in KELVIN_NAMES:
        return KELVIN_NAMES[arg.lower()]
    return int(arg.lower().rstrip("k"))


def local_subnet() -> str:
    """First three octets of this machine's LAN address, e.g. '192.168.0'."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip.rsplit(".", 1)[0]


class Light:
    """One physical light. Subclasses talk to a specific protocol.

    caps: subset of {"color", "brightness", "kelvin"}; the CLI skips commands a light lacks.
    status() returns {"on": bool, "mode": "color"|"white", "rgb": (r,g,b)|None,
                      "brightness": 1-100|None, "kelvin": int|None}.
    """

    caps = frozenset()
    kelvin_range = None

    def __init__(self, name: str, cfg: dict):
        self.name = name
        self.cfg = cfg

    def require(self, cap: str) -> None:
        if cap not in self.caps:
            raise Unsupported(f"{cap} not supported")

    def on(self): raise NotImplementedError
    def off(self): raise NotImplementedError
    def color(self, rgb: tuple): raise NotImplementedError
    def brightness(self, pct: int): raise NotImplementedError
    def white(self, kelvin=None): raise NotImplementedError
    def status(self) -> dict: raise NotImplementedError
    def find_ip(self): raise NotImplementedError

    # Used by lights-status to put the light back after showing a status colour.
    def snapshot(self) -> dict: raise NotImplementedError
    def restore(self, snap: dict): raise NotImplementedError
    def fingerprint(self) -> str:
        """Changes whenever the colour/mode changes; used to detect manual changes."""
        raise NotImplementedError
