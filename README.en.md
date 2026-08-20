# PipeWire Equalizer + Compressor

![Python](https://img.shields.io/badge/Python-3-3776AB?logo=python&logoColor=white)
![PipeWire](https://img.shields.io/badge/PipeWire-filter--chain-1A5FB4)
![Calf Plugins](https://img.shields.io/badge/Calf-Compressor%20(LV2)-orange)
![Tkinter](https://img.shields.io/badge/GUI-Tkinter-yellow)
![Platform](https://img.shields.io/badge/platform-Linux%20(x86__64%20%7C%20ARM)-blue)
![Status](https://img.shields.io/badge/status-working-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

![](eq_gui-captura.png)

Python (Tkinter) GUI with live control of a 10-band equalizer + preamp, chained into a dynamic compressor (Calf), implemented as PipeWire virtual sinks (`libpipewire-module-filter-chain`).

Does not depend on real PulseAudio or EasyEffects — it controls the filter-chain nodes directly via `pw-cli`.

## Compatibility

Nothing here is architecture-specific. Works on any Linux distro with a modern PipeWire (x86_64, ARM, etc.).  

Tested on:

- Orange Pi 5 Max (RK3588, aarch64) — Armbian, PipeWire 1.4.2

## Requirements

- PipeWire 0.3.50+ (with `filter-chain`)
- calf-plugins
- python3-tk (GUI, Tkinter)
- pactl
- pw-cli / pw-dump
- lilv-utils (optional, to inspect other LV2 plugin ports)
  - Python modules:
    - import json
    - import math
    - import datetime
    - import locale
    - import os
    - import re
    - import subprocess
    - import sys
    - import tkinter as tk
    - from tkinter import ttk, simpledialog, messagebox

## Typical install on Debian/Ubuntu/Armbian:

```bash
sudo apt install calf-plugins python3-tk
```

## File Location

To allow the GUI to open and read the README file via its integrated viewer button, the documentation files (`README.md` or `README.en.md`) must be placed in the **same directory** as the `eq_gui.py` script.

```
eq.conf             → ~/.config/pipewire/pipewire.conf.d/eq.conf
compressor.conf     → ~/.config/pipewire/pipewire.conf.d/compressor.conf
eq_gui.py           → anywhere, run with python3
README.md    → in the same directory as the script (for GUI access)
README.en.md → in the same directory as the script (optional English version)
```

The GUI also generates, at runtime (don't version these, they're user data):

```
~/.config/eq-presets.json      → user-saved presets
~/.config/eq-last-state.json   → last state (bands + volume), auto-saved on close
```

### `eq.conf` — Equalizer Sink

Filter-chain with a `preamp` node (bq_highshelf) + 10 `bq_peaking` bands (31 / 62 / 125 / 250 / 500 / 1000 / 2000 / 4000 / 8000 / 16000 Hz), chained in series. Exposes the `effect_input.eq` sink.

Its output (`effect_output.eq`) is explicitly routed to the Compressor Sink via `target.object = "effect_input.comp"` in `playback.props`.

### `compressor.conf` — Compressor Sink

Filter-chain with a single LV2 node (`http://calf.sourceforge.net/plugins/Compressor`), which is inherently stereo (`in_l`/`in_r`/`out_l`/`out_r` ports). Exposes the `effect_input.comp` sink. Its output is passive (`node.passive = true`) and auto-connects to whichever real sink (hardware/bluetooth) is the system default at the moment PipeWire loads the module.

**Why two separate files instead of one:** the LV2 compressor has explicit stereo ports (`in_l`/`in_r`), while the equalizer bands are mono "builtin" nodes that PipeWire automatically duplicates per channel. Mixing both styles in the same graph triggers a PipeWire error (`invalid ports... input:2 / input:1 != output:2 / output:2`) and can bring the service down. Splitting them into two chained sinks avoids the problem entirely.

### `eq_gui.py`

Tkinter GUI with two tabs:

- **Equalizer**: 11 vertical sliders (preamp + 10 bands), ±20 dB range, live control with no audio dropouts.
- **Compressor**: Threshold, Ratio, Attack, Release, Makeup Gain, Knee, and a Bypass checkbox. This tab hides itself automatically if `effect_input.comp` isn't loaded (e.g. if you only installed `eq.conf` without the compressor).

Top & bottom bars:
- **Presets**: save/load/delete combinations of the 10 bands + preamp, stored in `~/.config/eq-presets.json` (plain JSON, editable by hand).
- **Mute EQ**: quick mute/unmute of the sink, without closing the app.
- **Volume**: master slider (0–150%) over `effect_input.eq`, via `pactl set-sink-volume`.
- **Output**: dropdown listing the detected real audio devices (internal ALSA, HDMI, bluetooth, etc.), excluding the EQ/compressor's own virtual sinks. Selecting one moves the audio live with `pactl move-sink-input`. The **↻** button next to it refreshes the list without restarting the app.
- **Save as startup values**: Permanently updates the PipeWire configuration files (`eq.conf` and `compressor.conf`) in `~/.config/pipewire/pipewire.conf.d/` by writing the current gains and parameters into them. Automatically creates a backup (`.bak`) before saving, ensuring that PipeWire loads your custom default values on future restarts instead of 0 dB.
- **README button**: Opens a dedicated window within the GUI to read the documentation.

On window close, the app **automatically saves** the current state (the 10 bands + preamp + volume + compressor params) to `~/.config/eq-last-state.json`, and restores it when reopened. This is needed because PipeWire resets the filter-chain to 0dB on every service restart (e.g. on a system reboot).

All sink/volume information is fetched via `pactl -f json` instead of parsing text — so the script works the same regardless of the system's configured locale (`es_AR.UTF-8`, `en_US`, etc.).

## Installation

The repository includes the base configuration files eq.conf and compressor.conf. These files are generic templates that allow PipeWire to create the necessary virtual audio nodes.

```bash
# 1. Copy the PipeWire configs
mkdir -p ~/.config/pipewire/pipewire.conf.d
cp eq.conf compressor.conf ~/.config/pipewire/pipewire.conf.d/

# 2. Restart the PipeWire stack
systemctl --user restart pipewire wireplumber pipewire-pulse

# 3. Verify both sinks loaded
pactl list sinks short
# should show: effect_input.eq and effect_input.comp

# 4. Set the equalizer as the audio output
pactl set-default-sink effect_input.eq

# 5. Run the GUI
chmod +x eq_gui.py
python3 eq_gui.py
```

On first launch, check the "Output" dropdown and pick the actual device (speakers/headphones, HDMI, bluetooth) if it's not already the one connected by default.

## Using only the equalizer (no compressor)

If you don't want to install `calf-plugins` or prefer to skip the compressor, it's enough to copy `eq.conf` alone — but you need to remove the `target.object = "effect_input.comp"` line from `playback.props` (otherwise the EQ will try to route to a nonexistent sink and end up silent, though the PipeWire service will still start fine without crashing).

## Precautions — live PipeWire changes

A syntax or port-reference error in these `.conf` files can make `pipewire.service` fail to start (retry loop, "Start request repeated too quickly"), leaving you without audio until it's fixed. Recommendations:

1. **Back up** any `.conf` that's currently working before replacing it:
   ```bash
   cp ~/.config/pipewire/pipewire.conf.d/eq.conf ~/eq-backup.conf
   ```
2. **Quick rollback** if the service won't come up:
   ```bash
   mv ~/.config/pipewire/pipewire.conf.d/eq.conf ~/.config/pipewire/pipewire.conf.d/eq.conf.disabled
   systemctl --user reset-failed pipewire.service
   systemctl --user start pipewire wireplumber pipewire-pulse
   ```
3. To test a suspect `.conf` without risking the live service, first **stop the sockets** (not just the services) and run an isolated instance:
   ```bash
   systemctl --user stop pipewire.socket pipewire-pulse.socket pipewire wireplumber pipewire-pulse
   pipewire -c /tmp/file-to-test.conf 2>&1 | head -30
   # Ctrl+C to stop it, and immediately:
   systemctl --user start pipewire.socket pipewire-pulse.socket pipewire wireplumber pipewire-pulse
   ```
   This only validates syntax and port counts — it does **not** validate the actual routing to hardware (`target.object`), which can only be confirmed by testing against the real service.

## Finding another LV2 plugin's ports/parameters

If you want to add another LV2 effect in the future (LSP, another Calf plugin, etc.), confirm the exact port names before writing them into a `.conf` — the "Name" shown by `lv2info` doesn't always match the "Symbol" that `filter-chain` expects in `links`:

```bash
lv2info <plugin-uri> | grep -B2 -A6 -i "port"
```

The `.conf`'s `links` use the **Symbol** (e.g. `in_l`), not the capitalized/spaced "Name" (e.g. `In L`).

## Technologies

`PipeWire` `filter-chain` `LV2` `Calf Plugins` `Python 3` `Tkinter` `pactl` `pw-cli` `pw-dump` `JSON` `Bash` `systemd (user services)` `ALSA` `Bluez (A2DP)` `Armbian` `aarch64 / RK3588`

## License

This project is licensed under the **MIT** License. See the `LICENSE` file for details.

## Credits

- **Daniel Horacio Braga (DHB)** — Design, technical decisions, real-hardware testing (Orange Pi 5 Max), and audio recovery across each iteration.
- **Claude (Anthropic)** — `.conf`/GUI implementation, PipeWire/Calf API research, and live error diagnosis.
- **Gemini (Google AI)** — Multi-language support & UI: environment-based language detection (`LANG`/`LC_ALL`), CLI flags (`--lang`), real-time language switcher, and internationalization assistance.

`orquidealucinada.net`

