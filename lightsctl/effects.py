"""Foreground light shows. They restore every light to how it was when they stop."""
import colorsys
import random
import time
from concurrent.futures import ThreadPoolExecutor


def party_color(previous_hue: float = None) -> tuple:
    """A random fully saturated colour whose hue differs clearly from the previous one."""
    while True:
        hue = random.random()
        if previous_hue is None or min(abs(hue - previous_hue), 1 - abs(hue - previous_hue)) > 0.15:
            break
    return tuple(round(c * 255) for c in colorsys.hsv_to_rgb(hue, 1, 1)), hue


def _save(lights: list) -> tuple:
    """Remember each light's state; returns (reachable lights, {name: (was_on, snapshot)})."""
    before = {}
    for light in lights:
        try:
            on = light.status()["on"]
            before[light.name] = (on, light.snapshot() if on else None)
        except Exception as e:
            print(f"{light.name}: can't read state ({e}); leaving it out")
    lights = [l for l in lights if l.name in before]
    if not lights:
        raise ConnectionError("no light reachable")
    return lights, before


def _restore(lights: list, before: dict) -> None:
    print("\nrestoring...")
    for light in lights:
        was_on, snap = before[light.name]
        try:
            light.restore(snap) if was_on else light.off()
        except Exception as e:
            print(f"{light.name}: could not restore ({e})")


def party(lights: list, duration: float = None, interval: float = 1.0) -> None:
    """Change every light to a new random colour each `interval` seconds."""
    lights, before = _save(lights)

    for light in lights:  # full brightness: some lights remember a dim level from earlier
        try:
            if not before[light.name][0]:
                light.on()
            light.brightness(100)
        except Exception:
            pass
    hues = {l.name: None for l in lights}
    end = time.time() + duration if duration else None
    step = lambda l: l.color(rgb[l.name])
    try:
        with ThreadPoolExecutor(len(lights)) as pool:
            while end is None or time.time() < end:
                started = time.time()
                rgb = {}
                for l in lights:
                    rgb[l.name], hues[l.name] = party_color(hues[l.name])
                list(pool.map(lambda l: _safe(l, rgb[l.name]), lights))
                time.sleep(max(0.0, interval - (time.time() - started)))
    except KeyboardInterrupt:
        pass
    finally:
        _restore(lights, before)


def pomodoro(lights: list, focus: float = 1500, rest: float = 300, rounds: int = 4) -> None:
    """Focus (red, or cool white) then break (green, or warm white), `rounds` times; then restore the lights."""
    lights, before = _save(lights)

    def show(phase: str) -> None:
        def one(light):
            light.on()
            if "color" in light.caps:
                light.color((255, 0, 0) if phase == "focus" else (0, 255, 0))
                light.brightness(100)
            else:
                light.white(6500 if phase == "focus" else 2700)
                light.brightness(100 if phase == "focus" else 40)
        with ThreadPoolExecutor(len(lights)) as pool:
            list(pool.map(lambda l: _try(one, l), lights))

    try:
        for n in range(1, rounds + 1):
            print(f"round {n}/{rounds}: focus")
            show("focus")
            time.sleep(focus)
            print(f"round {n}/{rounds}: break")
            show("break")
            time.sleep(rest)
    except KeyboardInterrupt:
        pass
    finally:
        _restore(lights, before)


def sunset(lights: list, duration: float = 1800) -> None:
    """Fade every light that is on from its current brightness down to 1%, then switch it off."""
    start = {}
    for light in lights:
        try:
            st = light.status()
            if st["on"]:
                start[light.name] = st["brightness"] or 100
        except Exception as e:
            print(f"{light.name}: can't read state ({e}); leaving it out")
    lights = [l for l in lights if l.name in start]
    if not lights:
        print("nothing is on")
        return
    steps = max(1, min(100, max(start.values()) - 1))
    with ThreadPoolExecutor(len(lights)) as pool:
        t0 = time.time()
        try:
            for i in range(1, steps + 1):
                time.sleep(max(0.0, t0 + i * duration / steps - time.time()))
                list(pool.map(lambda l: _try(l.brightness, max(1, round(start[l.name] * (1 - i / steps)))), lights))
            list(pool.map(lambda l: _try(lambda _: l.off(), None), lights))
        except KeyboardInterrupt:
            print("\nstopped; lights left as they are")


def sunrise(lights: list, duration: float = 100, warm: int = 2700) -> None:
    """Start at 1% in warm white and rise to 100% over `duration` seconds. Ctrl-C leaves the lights as they are."""
    def prepare(light):
        try:
            light.brightness(1)  # before switching on, so the old level never flashes
        except Exception:
            pass
        light.on()
        light.white(warm if "kelvin" in light.caps else None)
        light.brightness(1)

    with ThreadPoolExecutor(len(lights)) as pool:
        for light, err in zip(lights, pool.map(lambda l: _try(prepare, l), lights)):
            if err:
                print(f"{light.name}: could not start ({err})")
        start = time.time()
        try:
            for pct in range(2, 101):
                time.sleep(max(0.0, start + (pct - 1) * duration / 99 - time.time()))
                list(pool.map(lambda l: _try(l.brightness, pct), lights))
        except KeyboardInterrupt:
            print("\nstopped; lights left as they are")


def _try(fn, arg):
    try:
        fn(arg)
    except Exception as e:
        return e  # a missed step is fine; the next one tries again


def _safe(light, rgb) -> None:
    try:
        light.color(rgb)
    except Exception:
        pass  # a missed colour is fine; the next tick tries again
