"""Command-line interface: lights [LIGHT[,LIGHT...]] COMMAND."""
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from . import config, effects, timers
from .base import COMMANDS, KELVIN_NAMES, Unsupported, parse_color, parse_kelvin

USAGE = """\
Usage: lights [LIGHT[,LIGHT...]] [COMMAND]

  lights                    show every light
  lights on | off | toggle  all lights
  lights lampy on           one light      (lights bulb,lampy off: several)
  lights lampy orange       a colour name or #RRGGBB
  lights lampy 30           brightness 1-100 (30% works too)
  lights lampy warm         warm | neutral | cool | 3000k   (kelvin where supported)
  lights lampy warmth 70    warmth 0-100 (0 coolest, 100 warmest)
  lights lampy white        plain white mode

Wake:   lights tube sunrise [DURATION]   1% to 100% in warm white over 100s (or e.g. 5m); lights sunrise at 7:00
Focus:  lights lampy pomodoro [FOCUS [BREAK [ROUNDS]]]   red focus, green break (25m, 5m, 4 rounds by default)
Show:   lights party [DURATION]   random colours until Ctrl-C (or for e.g. 30s, 2m); restores the lights after.
Later:  add `in 30s|5m|1h30m` or `at 22:30` to any command:  lights lampy red in 30s,  lights off at 22:30
        lights timers (list scheduled commands), lights cancel [ID] (cancel them),
        lights stop (end a running sunrise or party).

Long forms: color NAME|#RRGGBB|R G B, brightness N, warmth 0-100, white [KELVIN].
Also: status, list, fix-ip (re-finds lights whose IP changed).
Phone:  lights serve [PORT]   web page for your phone (see README).
No light name means all lights; lights that cannot do a command are skipped.
"""


def split_selector(args: list, names: list) -> tuple:
    """('lampy,bulb', 'off') -> (['lampy', 'bulb'], ['off']); no light named -> all of them."""
    if args:
        wanted = [p for p in args[0].split(",") if p]
        if wanted and all(p == "all" or p in names for p in wanted):
            return (names if "all" in wanted else wanted), args[1:]
    return names, args


def normalize(rest: list, names: list) -> tuple:
    """Turn user input, including shorthands, into (command, args)."""
    if not rest:
        return "status", []
    head = rest[0].lower()
    if head in COMMANDS:
        return head, rest[1:]
    if len(rest) == 1:
        if re.fullmatch(r"\d{1,3}%?", head):
            return "brightness", [head.rstrip("%")]
        if head in KELVIN_NAMES or re.fullmatch(r"\d{4}k", head):
            return "white", [head]
        try:
            parse_color([head])
            return "color", [head]
        except ValueError:
            pass
    hint = f" Lights: {', '.join(names)}." if len(rest) > 1 else ""
    raise ValueError(f"unknown light or command {rest[0]!r}.{hint} Run `lights help` for usage.")


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


def cancel_status_restore() -> None:
    """A manual change wins over a pending lights-status restore."""
    if config.CACHE.exists():
        (config.CACHE / "saved.json").unlink(missing_ok=True)
        (config.CACHE / "latest").write_text(str(time.time_ns()))


def ensure_on(light) -> None:
    if not light.status()["on"]:
        light.on()


def run(cfg: dict, name: str, cmd: str, args: list) -> str:
    light = config.make(cfg, name)
    if cmd == "status":
        return describe(light.status())
    if cmd == "fix-ip":
        try:
            light.status()
            return f"reachable at {cfg['devices'][name].get('ip')}"
        except Exception:
            pass
        ip = light.find_ip()
        if not ip:
            raise ConnectionError("not found; check it has power and is on the same network")
        config.update_field(name, "ip", ip)
        return f"found at {ip} (was {cfg['devices'][name].get('ip')}), devices.toml updated"

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
        pct = int(args[0]) if args else -1
        if not 1 <= pct <= 100:
            raise ValueError("brightness must be 1-100")
        ensure_on(light)
        light.brightness(pct)
    elif cmd == "warmth":
        light.require("kelvin")
        pct = int(args[0]) if args else -1
        if not 0 <= pct <= 100:
            raise ValueError("warmth must be 0-100 (0 coolest, 100 warmest)")
        lo, hi = light.kelvin_range
        ensure_on(light)
        light.white(round(hi - (hi - lo) * pct / 100))
    elif cmd == "white":
        kelvin = parse_kelvin(args[0]) if args else None
        ensure_on(light)
        light.white(kelvin)
    return "ok"


def main(argv: list) -> None:
    if argv[:1] in (["help"], ["-h"], ["--help"]):
        print(USAGE)
        return
    argv = list(argv)
    if argv[:1] == ["serve"]:
        from .server import serve
        serve(int(argv[1]) if len(argv) > 1 else 8080)
        return
    if argv[:1] == ["--later"]:  # background worker started by timers.schedule
        timers.wait_until(float(argv[1]), argv[2])
        argv = argv[3:]
    cfg = config.load()
    names = config.device_names(cfg)
    try:
        run_at, argv = timers.split_when(argv, None)
        targets, rest = split_selector(argv, names)
        cmd, args = normalize(rest, names)
    except ValueError as e:
        sys.exit(str(e))

    if cmd == "timers":
        jobs = timers.pending()
        for j in jobs:
            print(f"{j['id']}  {timers.describe(j['run_at']):26} lights {' '.join(j['argv'])}")
        if not jobs:
            print("no timers")
        return
    if cmd == "cancel":
        n = timers.cancel(args[0] if args else "all")
        print(f"cancelled {n} timer{'s' if n != 1 else ''}")
        return
    if cmd == "stop":
        n = timers.stop()
        print(f"stopped {n} running show{'s' if n != 1 else ''}" if n else "nothing running")
        return
    if cmd == "sunrise":
        lights = [config.make(cfg, n) for n in targets if "brightness" in config.make(cfg, n).caps]
        if not lights:
            sys.exit("none of the selected lights can change brightness")
        seconds = timers.parse_duration(args[0]) if args else 100
        if run_at is None:
            cancel_status_restore() if config.status_name(cfg) in targets else None
            print(f"sunrise on {', '.join(l.name for l in lights)} over {seconds}s. Ctrl-C to stop.")
            with timers.running_as(f"sunrise {seconds}s on {', '.join(l.name for l in lights)}"):
                effects.sunrise(lights, seconds)
            return
    if cmd == "pomodoro":
        durations = [timers.parse_duration(a) for a in args[:2]]
        focus, rest = (durations + [1500, 300][len(durations):])[:2]
        rounds = int(args[2]) if len(args) > 2 else 4
        lights = [config.make(cfg, n) for n in targets
                  if {"color", "kelvin"} & config.make(cfg, n).caps]
        if not lights:
            sys.exit("none of the selected lights can show a colour or a white temperature")
        if run_at is None:
            cancel_status_restore() if config.status_name(cfg) in targets else None
            print(f"pomodoro on {', '.join(l.name for l in lights)}: {focus}s focus, {rest}s break, {rounds} rounds. Ctrl-C to stop.")
            with timers.running_as(f"pomodoro {focus // 60}m/{rest // 60}m x{rounds} on {', '.join(l.name for l in lights)}"):
                effects.pomodoro(lights, focus, rest, rounds)
            return
    if cmd == "party":
        if run_at and not args:
            sys.exit("give the party a length when scheduling it, e.g. `lights party 2m in 10m`")
        lights = [config.make(cfg, n) for n in targets if "color" in config.make(cfg, n).caps]
        if not lights:
            sys.exit("none of the selected lights can show colours")
        if run_at is None:
            cancel_status_restore() if config.status_name(cfg) in targets else None
            print(f"party on {', '.join(l.name for l in lights)}! Ctrl-C to stop.")
            with timers.running_as(f"party on {', '.join(l.name for l in lights)}"):
                effects.party(lights, timers.parse_duration(args[0]) if args else None)
            return
    if run_at:
        job = timers.schedule(run_at, argv)
        print(f"will run `lights {' '.join(argv)}` at {timers.describe(run_at)}  [timer {job}]")
        return

    if cmd == "list":
        for n in names:
            d = cfg["devices"][n]
            print(f"{n:10} {d['type']:9} {d.get('ip', '?'):15} {'status light' if n == config.status_name(cfg) else ''}")
        return

    if cmd not in ("status", "fix-ip") and config.status_name(cfg) in targets:
        cancel_status_restore()

    def one(name):
        try:
            return name, run(cfg, name, cmd, args), None
        except Unsupported as e:
            return name, f"skipped ({e})", None if len(targets) > 1 else str(e)
        except Exception as e:
            return name, None, str(e)

    with ThreadPoolExecutor(len(targets)) as pool:
        results = list(pool.map(one, targets))

    failed = False
    for name, out, err in results:
        if err:
            print(f"{name}: error: {err}", file=sys.stderr)
            failed = True
        else:
            print(f"{name}: {out}")
    sys.exit(1 if failed else 0)
