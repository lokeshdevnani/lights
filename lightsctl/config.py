"""Load devices.toml and build Light objects from it."""
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "devices.toml"
CACHE = Path.home() / ".cache" / "lights-status"


def load() -> dict:
    if not CONFIG.exists():
        sys.exit("devices.toml not found. Copy devices.example.toml to devices.toml and fill it in.")
    return tomllib.loads(CONFIG.read_text())


def device_names(cfg: dict) -> list:
    return list(cfg.get("devices", {}))


def default_name(cfg: dict) -> str:
    return cfg.get("default") or device_names(cfg)[0]


def status_name(cfg: dict) -> str:
    """The light that shows Claude Code's state (see lights-status)."""
    return cfg.get("status_device") or default_name(cfg)


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
