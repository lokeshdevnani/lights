# smarthome-bulb-cli

Control a Tuya-based smart bulb (tested with a Wipro bulb, protocol 3.1) from the
terminal over the LAN. No cloud calls at runtime. Includes an optional status light
for Claude Code.

## Setup

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env     # fill in the values below
```

`.env` needs the bulb's device ID, its LAN IP and its **local key**.

- **Device ID and IP:** `.venv/bin/python -m tinytuya scan` lists Tuya devices on your network.
- **Local key:** the Tuya IoT cloud project route requires your app account and the project
  to be in the same data center. If that fails, a QR login through the Smart Life app works
  without a cloud project, for example
  [tuya-local-key](https://github.com/vineetchoudhary/tuya-local-key).

## Usage

```sh
.venv/bin/python bulb on
.venv/bin/python bulb off
.venv/bin/python bulb color red          # red green blue yellow orange purple pink cyan
.venv/bin/python bulb color 0 0 255      # raw R G B
.venv/bin/python bulb brightness 30      # 1-100
.venv/bin/python bulb white
.venv/bin/python bulb status
.venv/bin/python bulb fix-ip             # re-find the bulb if its IP changed, updates .env
```

### Shortcut

Put a wrapper on your PATH so you can just type `bulb on`:

```sh
cat > ~/.local/bin/bulb <<EOT
#!/bin/sh
exec $PWD/.venv/bin/python $PWD/bulb "\$@"
EOT
chmod +x ~/.local/bin/bulb
```

## Claude Code status light

`bulb-status` shows what Claude Code is doing on the bulb:

| Event | Light |
|---|---|
| prompt submitted | blue |
| waiting for you (permission prompt) | orange |
| finished | green for 8 s, then the bulb returns to how it was |

It saves the bulb's state first and restores it afterwards, does nothing if the bulb is off
or unreachable, and returns immediately so it never slows Claude down.

Add a wrapper like the one above for `bulb-status`, then add these hooks to
`~/.claude/settings.json`:

```json
"hooks": {
  "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "~/.local/bin/bulb-status working", "timeout": 5 }] }],
  "Notification":     [{ "hooks": [{ "type": "command", "command": "~/.local/bin/bulb-status needs-you", "timeout": 5 }] }],
  "Stop":             [{ "hooks": [{ "type": "command", "command": "~/.local/bin/bulb-status done", "timeout": 5 }] }]
}
```

Merge these into any existing `hooks` object instead of replacing it.

Turn it off and on:

```sh
bulb-status off     # disable (restores the bulb if it is mid-status)
bulb-status on
bulb-status state
```

Errors are logged to `~/.cache/bulb-status/error.log`.

## Troubleshooting

- **"Unable to Connect" or timeouts:** the bulb accepts one local connection at a time. Close the
  Smart Life app and retry.
- **Bulb moved IP:** run `bulb fix-ip`.
- **Decrypt errors:** the local key changed (re-pairing or resetting the bulb does this). Fetch the new key.
- **Not found on the network:** the bulb only supports 2.4 GHz Wi-Fi. Your computer must be on the same network.
