"""`lights serve`: a small phone-friendly web page that runs the same commands as the CLI."""
import datetime as dt
import json
import re
import shlex
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import config, timers

PAGE = config.ROOT / "lightsctl" / "web.html"
LIGHTS = [sys.executable, str(config.ROOT / "lights")]
KEY = None  # server_key from devices.toml; None means no login
LOCK = threading.Lock()  # lights allow one local connection at a time


def run_cli(line: str) -> tuple:
    """Run `lights <line>` and return (ok, output). Parties get a length so they always end."""
    args = shlex.split(line)
    if not args or "serve" in args or "--later" in args:
        return False, "not allowed"
    scheduling = len(args) >= 3 and args[-2] in ("in", "at")  # that just sets a timer and returns
    if ("party" in args or "sunrise" in args or "pomodoro" in args) and not scheduling:  # long-running: start it and return
        if "party" in args and not any(re.fullmatch(r"\d+[smh]", a) for a in args):
            args.append("30s")
        subprocess.Popen([*LIGHTS, *args], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return True, "started"
    with LOCK:
        p = subprocess.run([*LIGHTS, *args], capture_output=True, text=True, timeout=40)
    return p.returncode == 0, (p.stdout + p.stderr).strip()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def allowed(self, url) -> bool:
        return KEY is None or parse_qs(url.query).get("key") == [KEY]

    def do_GET(self):
        url = urlparse(self.path)
        if not self.allowed(url):
            return self.send(401, "add ?key=... to the address", "text/plain")
        if url.path == "/":
            return self.send(200, PAGE.read_text())
        if url.path == "/api/status":
            ok, out = run_cli("status")
            lights = {m[1]: m[2] for m in re.finditer(r"^(\w+): (.*)$", out, re.M)}
            cfg = config.load()
            caps = {n: sorted(config.make(cfg, n).caps) for n in lights if n in cfg["devices"]}
            return self.send(200, json.dumps({"lights": lights, "caps": caps}), "application/json")
        if url.path == "/api/timers":
            jobs = [{"id": j["id"], "at": f"{dt.datetime.fromtimestamp(j['run_at']):%a %H:%M}", "what": " ".join(j["argv"])}
                    for j in timers.pending()]
            shows = [{"what": r["what"], "since": r["started"]} for r in timers.running()]
            return self.send(200, json.dumps({"timers": jobs, "running": shows}), "application/json")
        self.send(404, "not found", "text/plain")

    def do_POST(self):
        url = urlparse(self.path)
        if url.path != "/api/run" or not self.allowed(url):
            return self.send(401, "add ?key=... to the address", "text/plain")
        try:
            length = min(int(self.headers.get("Content-Length", 0)), 1000)
            ok, out = run_cli(json.loads(self.rfile.read(length))["args"])
        except Exception as e:
            ok, out = False, str(e)
        self.send(200, json.dumps({"ok": ok, "output": out}), "application/json")


def serve(port: int = 8080) -> None:
    global KEY
    KEY = config.load().get("server_key")
    suffix = f"?key={KEY}" if KEY else ""
    print(f"Lights: http://localhost:{port}/{suffix}")
    if not KEY:
        print("No login: set server_key in devices.toml to require ?key=... in the address.")
    print("Open it on your phone and add it to your home screen. Ctrl-C to stop.")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
