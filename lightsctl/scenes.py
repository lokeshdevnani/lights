"""Scenes: named lists of `lights` commands from the [scenes] table in devices.toml."""
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from . import config
from .base import COMMANDS

LIGHTS = [sys.executable, str(config.ROOT / "lights")]
SLOW = {"party", "sunrise", "sunset", "pomodoro", "scene", "serve"}  # not for scenes: they run a while or nest


def names(cfg: dict) -> list:
    return list(cfg.get("scenes", {}))


def lines(cfg: dict, name: str) -> list:
    scenes = cfg.get("scenes", {})
    if name not in scenes:
        have = ", ".join(scenes) or "none defined"
        raise ValueError(f"unknown scene {name!r} (scenes: {have})")
    return list(scenes[name])


def run(cfg: dict, name: str) -> str:
    """Run a scene's commands. Commands for one light run in order; different lights run together."""
    groups = {}
    for line in lines(cfg, name):
        words = shlex.split(line)
        if SLOW & set(words) or not words:
            raise ValueError(f"scene {name!r}: {line!r} cannot be used in a scene")
        groups.setdefault(words[0], []).append(words)

    def work(group):
        for words in group:
            p = subprocess.run([*LIGHTS, *words], capture_output=True, text=True, timeout=40)
            if p.returncode != 0:
                return (p.stdout + p.stderr).strip()

    with ThreadPoolExecutor(len(groups) or 1) as pool:
        errors = [e for e in pool.map(work, groups.values()) if e]
    if errors:
        raise RuntimeError("; ".join(errors))
    return "ok"
