# Setup guide for Claude Code

This file is written for Claude Code. A user pasted the prompt from the README and
wants this repo installed and working. Follow the steps in order, tell the user what you
are doing, and check each step before the next.

## Rules

- **Ask before changing anything outside this repo**, especially `~/.claude/settings.json`
  and `~/.local/bin`. Show the exact change and wait for a yes.
- **Never print local keys or tokens** (or other secrets) in chat or logs. Write it straight into `devices.toml`.
- Only run third-party code (steps 3 and 3b) after the user agrees, and tell them what it does.
- Don't commit `devices.toml`. It is gitignored; keep it that way.

## 1. Clone and install (Python 3.11+)

```sh
git clone https://github.com/lokeshdevnani/lights.git
cd lights
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Skip the clone if the repo is already the working directory.

## 2. Find the bulb on the network

The bulb only supports 2.4 GHz Wi-Fi, and the computer must be on the same network
(a guest network or separate band can hide it).

```sh
.venv/bin/python -c "
import tinytuya
for ip, v in tinytuya.deviceScan(False, 25).items():
    print(ip, v.get('gwId'), 'v' + str(v.get('version')))"
```

- Exactly one device: that is it. Note the IP, device ID (`gwId`) and protocol version.
- Several: ask the user which one, or flip the bulb on/off and compare.
- None: ask the user to check the bulb has power and is on the same 2.4 GHz network, then retry.
  Do not guess an IP.

## 3. Get the local key

The bulb's commands are encrypted with a per-device local key that only Tuya's cloud holds.
Ask the user which route they prefer:

**a. QR login without a cloud project (usually easiest).** Uses
[tuya-local-key](https://github.com/vineetchoudhary/tuya-local-key), open source (Apache-2.0),
which logs in through the Smart Life app with Tuya's official device-sharing SDK.

1. Ask the user for their Smart Life **User Code** (Me, then the gear, then Account and Security).
2. Clone it into a **temporary directory outside this repo**, run its `./setup.sh`, then
   `.venv/bin/python tuya_devices.py --user-code <CODE> --json > <tmpdir>/devices.json`.
3. It prints a QR code and also saves `tuya-login-qr.png`. Open the image for the user
   (`open` on macOS). They scan it in Smart Life (+, then Scan) and tap **Confirm login**.
4. Read the matching device's `local_key` from the JSON by script and write it to `devices.toml` without showing it.
5. Delete the temp directory (it holds every key on the account) and the cached session at
   `~/.config/tuya-smartlife/session.json`.

**b. Tuya IoT cloud project.** Create a project at iot.tuya.com, link the Smart Life app account,
and use `python -m tinytuya wizard`. This only works if the project's data center matches the
app account's. A mismatch gives "Data centers inconsistency".

## 3b. Mi Bedside Lamp 2 (skip if the user has none)

It speaks Xiaomi's miIO protocol and needs a device token from the user's Mi Home account.

1. Find its IP and numeric device ID (this changes nothing on the lamp):

   ```sh
   .venv/bin/python - <<'EOT'
   import socket, time, subprocess
   hello = bytes.fromhex("21310020" + "ff" * 28)
   base = subprocess.check_output("ipconfig getifaddr en0", shell=True, text=True).strip().rsplit(".", 1)[0]
   s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
   s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1); s.settimeout(0.3)
   for t in [f"{base}.255"] + [f"{base}.{i}" for i in range(1, 255)]:
       try: s.sendto(hello, (t, 54321))
       except OSError: pass
   end = time.time() + 4
   while time.time() < end:
       try: d, (ip, _) = s.recvfrom(1024)
       except socket.timeout: continue
       if d[:2] == b"\x21\x31": print(ip, int.from_bytes(d[8:12], "big"))
   EOT
   ```

2. Get the token with [Xiaomi-cloud-tokens-extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor)
   (MIT) with **QR login**. Never ask for or handle the user's Mi password. Download it into a
   temporary directory outside this repo and run `python token_extractor.py -s "" -o out.json`,
   feeding it `q` for QR login. Leave the server empty so it checks every region (the lamp may be on
   a region that is not the user's own, such as `i2`). It serves the QR code on a local page
   (`http://127.0.0.1:31415`); open it for the user, who scans it in Mi Home and confirms.
3. Read the device whose model is `yeelink.light.bslamp2` from `out.json` by script and put its
   token straight into `devices.toml` without showing it.
4. Delete the temporary directory. It holds every device token on the account.

## 4. Write `devices.toml`

```sh
cp devices.example.toml devices.toml && chmod 600 devices.toml
```

Fill in one `[devices.NAME]` section per light (pick short names that are not commands or
colour names), set `status_device`, and delete sections the user does not have. Use the protocol version from the
scan for Tuya lights (usually 3.1 or 3.3). `devices.toml` is gitignored, so keep it that way.

## 5. Create the commands

After the user agrees, create two wrappers in `~/.local/bin` (make sure it is on `PATH`):

```sh
mkdir -p ~/.local/bin
for n in lights lights-status; do
  printf '#!/bin/sh\nexec %s/.venv/bin/python %s/%s "$@"\n' "$PWD" "$PWD" "$n" > ~/.local/bin/$n
  chmod +x ~/.local/bin/$n
done
```

Test it: `lights list`, `lights` (shows every light), then `lights NAME red` and `lights NAME white` on each light.
On a Tuya light, "Unable to Connect" means the Smart Life app is holding the one local connection:
ask the user to close it and retry.

## 6. Claude Code status light (optional)

Ask whether they want a light to show Claude's state: blue while working, orange when it needs
them, green when done (then it restores the previous light). If yes:

1. Back up `~/.claude/settings.json` to `settings.json.bak`.
2. Show the user the three hooks below and get a yes.
3. **Merge** them into the existing `hooks` object. Do not replace it. Keep any hooks already
   there. A short Python script that loads the JSON, appends to each event's list and writes
   it back works.

```json
"UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "~/.local/bin/lights-status working", "timeout": 5 }] }],
"Notification":     [{ "hooks": [{ "type": "command", "command": "~/.local/bin/lights-status needs-you", "timeout": 5 }] }],
"Stop":             [{ "hooks": [{ "type": "command", "command": "~/.local/bin/lights-status done", "timeout": 5 }] }]
```

4. Tell the user to run `/hooks` or start a new session so the hooks load.

`lights-status off` / `on` / `state` mutes and unmutes it. Errors go to `~/.cache/lights-status/error.log`.

## 7. Wrap up

Tell the user what was set up and where, and the basics: `lights` shows every light, `lights off`
turns everything off, `lights NAME orange` / `lights NAME 30` / `lights NAME warm` change one light,
and `lights fix-ip` re-finds lights whose IP changed.
