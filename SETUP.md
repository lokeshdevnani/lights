# Setup guide for Claude Code

This file is written for Claude Code. A user pasted the prompt from the README and
wants this repo installed and working. Follow the steps in order, tell the user what you
are doing, and check each step before the next.

## Rules

- **Ask before changing anything outside this repo**, especially `~/.claude/settings.json`
  and `~/.local/bin`. Show the exact change and wait for a yes.
- **Never print the local key** (or other secrets) in chat or logs. Write it straight into `.env`.
- Only run third-party code (step 3) after the user agrees, and tell them what it does.
- Don't commit `.env`. It is gitignored; keep it that way.

## 1. Clone and install

```sh
git clone https://github.com/lokeshdevnani/smarthome-bulb-cli.git
cd smarthome-bulb-cli
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
4. Read the matching device's `local_key` from the JSON by script and write it to `.env` without showing it.
5. Delete the temp directory (it holds every key on the account) and the cached session at
   `~/.config/tuya-smartlife/session.json`.

**b. Tuya IoT cloud project.** Create a project at iot.tuya.com, link the Smart Life app account,
and use `python -m tinytuya wizard`. This only works if the project's data center matches the
app account's. A mismatch gives "Data centers inconsistency".

## 4. Write `.env`

```sh
cp .env.example .env && chmod 600 .env
```

Fill in `TUYA_DEVICE_ID`, `TUYA_DEVICE_IP`, `TUYA_LOCAL_KEY` and `TUYA_VERSION`
(use the version from the scan, usually 3.1 or 3.3).

## 5. Create the commands

After the user agrees, create two wrappers in `~/.local/bin` (make sure it is on `PATH`):

```sh
mkdir -p ~/.local/bin
for n in bulb bulb-status; do
  printf '#!/bin/sh\nexec %s/.venv/bin/python %s/%s "$@"\n' "$PWD" "$PWD" "$n" > ~/.local/bin/$n
  chmod +x ~/.local/bin/$n
done
```

Test it: `bulb status`, then `bulb color red`, `bulb white`. If you get "Unable to Connect",
ask the user to close the Smart Life app (the bulb allows one local connection) and retry.

## 6. Claude Code status light (optional)

Ask whether they want the bulb to show Claude's state: blue while working, orange when it
needs them, green when done (then it restores the previous light). If yes:

1. Back up `~/.claude/settings.json` to `settings.json.bak`.
2. Show the user the three hooks below and get a yes.
3. **Merge** them into the existing `hooks` object. Do not replace it. Keep any hooks already
   there. A short Python script that loads the JSON, appends to each event's list and writes
   it back works.

```json
"UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "~/.local/bin/bulb-status working", "timeout": 5 }] }],
"Notification":     [{ "hooks": [{ "type": "command", "command": "~/.local/bin/bulb-status needs-you", "timeout": 5 }] }],
"Stop":             [{ "hooks": [{ "type": "command", "command": "~/.local/bin/bulb-status done", "timeout": 5 }] }]
```

4. Tell the user to run `/hooks` or start a new session so the hooks load.

`bulb-status off` / `on` / `state` mutes and unmutes it. Errors go to `~/.cache/bulb-status/error.log`.

## 7. Wrap up

Tell the user what was set up and where, the commands (`bulb on|off|color|brightness|white|status|fix-ip`),
and that `bulb fix-ip` re-finds the bulb if its IP changes.
