"""Load devices.toml and build Light objects from it."""
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "devices.toml"
CACHE = Path.home() / ".cache" / "lights-status"


def load() -> dict:
    from .base import RESERVED_WORDS

    if not CONFIG.exists():
        sys.exit("devices.toml not found. Copy devices.example.toml to devices.toml and fill it in.")
    cfg = tomllib.loads(CONFIG.read_text())
    if not cfg.get("devices"):
        sys.exit("devices.toml has no [devices.NAME] sections.")
    for name in cfg["devices"]:
        if name.lower() in RESERVED_WORDS:
            sys.exit(f"devices.toml: {name!r} clashes with a command or colour name; pick another name.")
    return cfg


def device_names(cfg: dict) -> list:
    return list(cfg.get("devices", {}))


def status_name(cfg: dict) -> str:
    """The light that shows Claude Code's state (see lights-status); the first light by default."""
    return cfg.get("status_device") or device_names(cfg)[0]


def make(cfg: dict, name: str):
    from .tuya import TuyaLight
    from .yeelight import YeelightLight

    kinds = {"tuya": TuyaLight, "yeelight": YeelightLight}
    dev = cfg["devices"][name]
    if dev["type"] not in kinds:
        sys.exit(f"{name}: unknown type {dev['type']!r} (expected one of {', '.join(kinds)})")
    return kinds[dev["type"]](name, dev)


def update_field(name: str, key: str, value: str) -> None:
    """Rewrite one string field of [devices.NAME] in devices.toml, keeping everything else."""
    text = CONFIG.read_text()
    head = re.search(rf"^\[devices\.{re.escape(name)}\]\s*$", text, re.M)
    if not head:
        raise KeyError(name)
    nxt = re.search(r"^\[", text[head.end():], re.M)
    end = head.end() + nxt.start() if nxt else len(text)
    section, n = re.subn(rf"^{key}\s*=.*$", f'{key} = "{value}"', text[head.end():end], count=1, flags=re.M)
    if n == 0:
        raise KeyError(key)
    CONFIG.write_text(text[:head.end()] + section + text[end:])
