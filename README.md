# lights

Control smart lights from the terminal over your local network. No cloud calls at runtime.
Works with Tuya / Smart Life lights (Wipro and many others) and the Xiaomi Mi Bedside Lamp 2
(Yeelight protocol over miIO). Includes an optional status light for Claude Code.

```
$ lights on
$ lights lampy color orange
$ lights brightness 30
$ lights all off
$ lights status
bulb: on, colour (0, 60, 255), brightness 100%
```

## Quick start with Claude Code

Paste this into Claude Code. It does the whole setup, asks before changing any settings, and
never prints your keys or tokens:

> Set up https://github.com/lokeshdevnani/lights for me. Clone it, read `SETUP.md`, and follow it step by step. Ask me before changing any settings.

## Manual setup

Needs Python 3.11+.

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp devices.example.toml devices.toml    # then fill it in, see below
```

Put a wrapper on your PATH so you can type `lights`:

```sh
mkdir -p ~/.local/bin
for n in lights lights-status; do
  printf '#!/bin/sh\nexec %s/.venv/bin/python %s/%s "$@"\n' "$PWD" "$PWD" "$n" > ~/.local/bin/$n
  chmod +x ~/.local/bin/$n
done
```

### devices.toml

One `[devices.NAME]` section per light. See `devices.example.toml`. The file holds secrets
and is gitignored.

**Tuya / Smart Life light**: needs the device ID, LAN IP and *local key*.
- ID and IP: `.venv/bin/python -m tinytuya scan` lists Tuya lights on your network.
- Local key: a QR login through the Smart Life app works without a Tuya cloud project, for
  example [tuya-local-key](https://github.com/vineetchoudhary/tuya-local-key).

**Mi Bedside Lamp 2**: needs the lamp's IP, numeric device ID (`did`) and token. Get the token with
[Xiaomi-cloud-tokens-extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor)
using QR login. Leave its server prompt empty to check every region, because the lamp may be on
a region other than your own (here it was `i2`).

## Usage

```
lights [DEVICE|all] COMMAND [ARGS]

  on | off | toggle
  color NAME | #RRGGBB | R G B      red green blue yellow orange purple pink cyan white
  brightness 1-100
  white [KELVIN|warm|neutral|cool]  kelvin only where supported (the Mi lamp: 1700-6500)
  status
  fix-ip      find the light again after its IP changed; updates devices.toml
  list
```

Without a device name, the `default` light from `devices.toml` is used. `all` runs the command
on every light and skips lights that cannot do it (for example `color` on a white-only light).

## Claude Code status light

`lights-status` shows what Claude Code is doing on one light (`status_device` in `devices.toml`):

| Event | Light |
|---|---|
| prompt submitted | blue |
| waiting for you (permission prompt) | orange |
| finished | green for 8 s, then the light returns to how it was |

It saves the light's state first and restores it afterwards. If you change the light yourself in
the meantime, your change is kept. It does nothing if the light is off or unreachable and returns
immediately, so it never slows Claude down.

Add these hooks to `~/.claude/settings.json` (merge them into any existing `hooks` object):

```json
"hooks": {
  "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "~/.local/bin/lights-status working", "timeout": 5 }] }],
  "Notification":     [{ "hooks": [{ "type": "command", "command": "~/.local/bin/lights-status needs-you", "timeout": 5 }] }],
  "Stop":             [{ "hooks": [{ "type": "command", "command": "~/.local/bin/lights-status done", "timeout": 5 }] }]
}
```

Then run `/hooks` or start a new session. Mute it with `lights-status off`, re-enable with
`lights-status on`, and check with `lights-status state`. Errors go to
`~/.cache/lights-status/error.log`.

## Adding another kind of light

A backend is one small class in `lightsctl/` that subclasses `Light` (`lightsctl/base.py`):
`on`, `off`, `color`, `brightness`, `white`, `status`, `snapshot`/`restore`/`fingerprint`
(for the status light) and `find_ip`. Register it in `config.make`.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -t .
```

## Troubleshooting

- **"Unable to Connect" or timeouts on a Tuya light:** it accepts one local connection at a time.
  Close the Smart Life app and retry.
- **A light moved IP:** `lights NAME fix-ip`.
- **Decrypt errors on a Tuya light:** the local key changed (re-pairing or resetting does this). Fetch the new key.
- **Light not found:** Tuya and Mi lights only support 2.4 GHz Wi-Fi; your computer must be on the same network.

## License

MIT, see [LICENSE](LICENSE).
