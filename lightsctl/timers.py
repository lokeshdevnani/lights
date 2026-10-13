"""Run a lights command later: `lights lampy red in 30s`, `lights off at 22:30`."""
import datetime as dt
import contextlib
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import config

JOBS = Path.home() / ".cache" / "lights-timers"
RUNNING = Path.home() / ".cache" / "lights-running"
UNITS = {"h": 3600, "m": 60, "s": 1}


def parse_duration(text: str) -> int:
    """'30s', '5m', '1h30m' -> seconds."""
    if not re.fullmatch(r"(\d+[hms])+", text.lower()):
        raise ValueError(f"bad duration {text!r}; use e.g. 30s, 5m, 1h30m")
    return sum(int(n) * UNITS[u] for n, u in re.findall(r"(\d+)([hms])", text.lower()))


def parse_clock(text: str, now: dt.datetime = None) -> float:
    """'22:30' -> epoch seconds of the next 22:30 (today, or tomorrow if already past)."""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not m or int(m[1]) > 23 or int(m[2]) > 59:
        raise ValueError(f"bad time {text!r}; use 24-hour HH:MM, e.g. 22:30")
    now = now or dt.datetime.now()
    when = now.replace(hour=int(m[1]), minute=int(m[2]), second=0, microsecond=0)
    if when <= now:
        when += dt.timedelta(days=1)
    return when.timestamp()


def split_when(args: list, now: float = None):
    """Strip a trailing `in DURATION` / `at HH:MM`; return (run_at or None, remaining args)."""
    if len(args) >= 3 and args[-2].lower() in ("in", "at"):
        now = time.time() if now is None else now
        word, value = args[-2].lower(), args[-1]
        run_at = now + parse_duration(value) if word == "in" else parse_clock(value, dt.datetime.fromtimestamp(now))
        return run_at, args[:-2]
    return None, args


def schedule(run_at: float, argv: list) -> str:
    JOBS.mkdir(parents=True, exist_ok=True)
    job = secrets.token_hex(2)
    log = open(JOBS / "error.log", "a")
    proc = subprocess.Popen(
        [sys.executable, str(config.ROOT / "lights"), "--later", str(run_at), job, *argv],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log, start_new_session=True,
    )
    (JOBS / f"{job}.json").write_text(json.dumps({"pid": proc.pid, "run_at": run_at, "argv": argv}))
    return job


def wait_until(run_at: float, job: str) -> None:
    """Worker side: sleep (robust to the Mac sleeping), then drop the job file."""
    while time.time() < run_at:
        time.sleep(min(1.0, max(0.05, run_at - time.time())))
    (JOBS / f"{job}.json").unlink(missing_ok=True)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def pending() -> list:
    jobs = []
    for f in sorted(JOBS.glob("*.json")) if JOBS.exists() else []:
        info = json.loads(f.read_text())
        if not _alive(info["pid"]):
            f.unlink(missing_ok=True)
            continue
        jobs.append({"id": f.stem, **info})
    return sorted(jobs, key=lambda j: j["run_at"])


def cancel(which: str = "all") -> int:
    n = 0
    for j in pending():
        if which in ("all", j["id"]):
            os.kill(j["pid"], signal.SIGTERM)
            (JOBS / f"{j['id']}.json").unlink(missing_ok=True)
            n += 1
    return n


def describe(run_at: float) -> str:
    left = max(0, round(run_at - time.time()))
    h, rem = divmod(left, 3600)
    m, s = divmod(rem, 60)
    span = (f"{h}h" if h else "") + (f"{m}m" if m else "") + (f"{s}s" if s or not (h or m) else "")
    return f"{dt.datetime.fromtimestamp(run_at):%H:%M:%S} (in {span})"


@contextlib.contextmanager
def running_as(what: str):
    """Record this process as a running show (sunrise, party) so `lights stop` can end it.

    SIGTERM is turned into Ctrl-C, so the show restores or leaves the lights the same way."""
    RUNNING.mkdir(parents=True, exist_ok=True)
    f = RUNNING / f"{os.getpid()}.json"
    f.write_text(json.dumps({"pid": os.getpid(), "what": what, "started": time.time()}))

    def on_term(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, on_term)
    try:
        yield
    finally:
        f.unlink(missing_ok=True)


def running() -> list:
    shows = []
    for f in sorted(RUNNING.glob("*.json")) if RUNNING.exists() else []:
        info = json.loads(f.read_text())
        if _alive(info["pid"]):
            shows.append(info)
        else:
            f.unlink(missing_ok=True)
    return shows


def stop() -> int:
    shows = running()
    for info in shows:
        os.kill(info["pid"], signal.SIGTERM)
    return len(shows)
