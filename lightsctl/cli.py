"""Command-line interface: lights [DEVICE|all] COMMAND [ARGS]."""
import sys
import time

from . import config
from .base import Unsupported, parse_color, parse_kelvin

USAGE = """\
Usage: lights [DEVICE|all] COMMAND [ARGS]    (or: lights -d DEVICE COMMAND)

  on | off | toggle
  color NAME | #RRGGBB | R G B     red green blue yellow orange purple pink cyan white
  brightness 1-100
  white [KELVIN|warm|neutral|cool]  white mode; kelvin only on lights that support it
  status                            show state
  fix-ip                            find the light again after its IP changed (updates devices.toml)
  list                              show configured lights

DEVICE is a name from devices.toml; without one the default light is used.
`all` runs the command on every light and skips ones that cannot do it.
"""


def describe(st: dict) -> str:
    if not st["on"]:
        return "off"
    parts = ["on"]
    if st["mode"] == "color" and st["rgb"]:
        parts.append(f"colour {st['rgb']}")
    else:
        parts.append("white" + (f" {st['kelvin']}K" if st["kelvin"] else ""))
    if st["brightness"]:
        parts.append(f"brightness {st['brightness']}%")
    return ", ".join(parts)


def cancel_status_restore(cfg: dict, name: str) -> None:
    """A manual change wins over a pending lights-status restore."""
    if name != config.status_name(cfg) or not config.CACHE.exists():
        return
    (config.CACHE / "saved.json").unlink(missing_ok=True)
    (config.CACHE / "latest").write_text(str(time.time_ns()))


def ensure_on(light) -> None:
    if not light.status()["on"]:
        light.on()


def run(cfg: dict, name: str, cmd: str, args: list) -> str:
    light = config.make(cfg, name)
    if cmd == "fix-ip":
        ip = light.find_ip()
        if not ip:
            raise ConnectionError("not found; check it has power and is on the same network")
        old = cfg["devices"][name].get("ip")
        config.update_field(name, "ip", ip)
        return f"at {ip}" + (" (unchanged)" if ip == old else f" (was {old}), devices.toml updated")
    if cmd == "status":
        return describe(light.status())

    cancel_status_restore(cfg, name)
    if cmd == "on":
        light.on()
    elif cmd == "off":
        light.off()
    elif cmd == "toggle":
        light.off() if light.status()["on"] else light.on()
    elif cmd == "color":
        light.require("color")
        rgb = parse_color(args)
        ensure_on(light)
        light.color(rgb)
    elif cmd == "brightness":
        light.require("brightness")
        pct = int(args[0])
        ensure_on(light)
        light.brightness(pct)
    elif cmd == "white":
        kelvin = parse_kelvin(args[0]) if args else None
        ensure_on(light)
        light.white(kelvin)
    else:
        sys.exit(f"unknown command {cmd!r}. Run `lights` with no arguments for usage.")
    return "ok"


def main(argv: list) -> None:
    cfg = config.load()
    names = config.device_names(cfg)
    args = list(argv)
    target = None
    if args[:1] == ["-d"] and len(args) > 1:
        target, args = args[1], args[2:]
    elif args and (args[0] in names or args[0] == "all"):
        target = args.pop(0)
    if not args:
        sys.exit(USAGE)

    if args[0] == "list":
        for n in names:
            d = cfg["devices"][n]
            tags = [t for t, v in (("default", config.default_name(cfg)), ("status light", config.status_name(cfg))) if v == n]
            print(f"{n:10} {d['type']:9} {d.get('ip', '?'):15} {', '.join(tags)}")
        return

    if target not in (None, "all") and target not in names:
        sys.exit(f"unknown light {target!r}. Configured: {', '.join(names)}")
    targets = names if target == "all" else [target or config.default_name(cfg)]
    many = len(targets) > 1
    failed = False
    for n in targets:
        try:
            out = run(cfg, n, args[0], args[1:])
        except Unsupported as e:
            if not many:
                sys.exit(f"{n}: {e}")
            out = f"skipped ({e})"
        except Exception as e:
            print(f"{n}: error: {e}", file=sys.stderr)
            failed = True
            continue
        print(f"{n}: {out}" if many or args[0] in ("status", "fix-ip") else out)
    sys.exit(1 if failed else 0)
