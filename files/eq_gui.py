#!/usr/bin/env python3
"""
Ecualizador de 10 bandas + preamp + compresor para PipeWire (control en vivo vía pw-cli)[cite: 1].
Requiere que eq.conf (y opcionalmente compressor.conf) ya estén cargados[cite: 1].
"""

import json
import math
import datetime
import locale
import os
import re
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox

EQ_NODE_NAME = "effect_input.eq"
EQ_PLAYBACK_NAME = "effect_output.eq"
COMP_NODE_NAME = "effect_input.comp"
COMP_PLAYBACK_NAME = "effect_output.comp"
PRESETS_FILE = os.path.expanduser("~/.config/eq-presets.json")
LAST_STATE_FILE = os.path.expanduser("~/.config/eq-last-state.json")

EQ_CONF_PATH = os.path.expanduser("~/.config/pipewire/pipewire.conf.d/eq.conf")
COMP_CONF_PATH = os.path.expanduser("~/.config/pipewire/pipewire.conf.d/compressor.conf")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
README_ES_NAME = "README.md"
README_EN_NAME = "README.en.md"

REQUIRED_BINARIES = ["pactl", "pw-cli", "pw-dump"]

CURRENT_LANG = "es"


def check_required_binaries():
    missing = [b for b in REQUIRED_BINARIES if subprocess.run(
        ["which", b], capture_output=True
    ).returncode != 0]
    return missing

BANDS = [
    ("preamp",    "Preamp", True),
    ("eq_band_1", "31 Hz", False),
    ("eq_band_2", "62 Hz", False),
    ("eq_band_3", "125 Hz", False),
    ("eq_band_4", "250 Hz", False),
    ("eq_band_5", "500 Hz", False),
    ("eq_band_6", "1000 Hz", False),
    ("eq_band_7", "2000 Hz", False),
    ("eq_band_8", "4000 Hz", False),
    ("eq_band_9", "8000 Hz", False),
    ("eq_band_10", "16000 Hz", False),
]

GAIN_MIN = -20.0
GAIN_MAX = 20.0


# ---------- utilidades genéricas PipeWire ----------

def resolve_node_id(name):
    result = subprocess.run(["pw-dump"], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    for obj in data:
        props = obj.get("info", {}).get("props", {})
        if props.get("node.name") == name:
            return obj["id"]
    return None


def read_current_params(node_id, keys):
    result = subprocess.run(["pw-dump", str(node_id)], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)

    values = {}

    for obj in data:
        try:
            props_param = obj["info"]["params"]["Props"]
        except (KeyError, TypeError):
            continue
        for entry in props_param:
            params = entry.get("params")
            if not params:
                continue
            for i in range(0, len(params) - 1, 2):
                key = params[i]
                value = params[i + 1]
                if key in keys:
                    values[key] = value
        break

    return values


def set_param(node_id, key, value):
    payload = json.dumps({"params": [key, value]})
    subprocess.run(["pw-cli", "s", str(node_id), "Props", payload], check=False)


def load_presets():
    if not os.path.exists(PRESETS_FILE):
        return {}
    try:
        with open(PRESETS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_presets(presets):
    os.makedirs(os.path.dirname(PRESETS_FILE), exist_ok=True)
    with open(PRESETS_FILE, "w") as f:
        json.dump(presets, f, indent=2)


def _pactl_json_sinks():
    result = subprocess.run(
        ["pactl", "-f", "json", "list", "sinks"], capture_output=True, text=True, check=False
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def get_sink_volume_percent(name):
    for s in _pactl_json_sinks():
        if s.get("name") == name:
            volume = s.get("volume", {})
            for _, ch in volume.items():
                pct = ch.get("value_percent", "100%")
                try:
                    return int(pct.replace("%", "").strip())
                except ValueError:
                    pass
    return 100


def set_sink_volume_percent(name, percent):
    subprocess.run(["pactl", "set-sink-volume", name, f"{int(percent)}%"], check=False)


def is_sink_muted(name):
    for s in _pactl_json_sinks():
        if s.get("name") == name:
            return bool(s.get("mute", False))
    return False


def toggle_mute(name):
    subprocess.run(["pactl", "set-sink-mute", name, "toggle"], check=False)


# ---------- dispositivos de salida reales ----------

VIRTUAL_SINK_NAMES = {EQ_NODE_NAME, COMP_NODE_NAME}


def list_real_output_sinks():
    sinks = []
    seen_labels = {}
    for s in _pactl_json_sinks():
        name = s.get("name")
        if not name or name in VIRTUAL_SINK_NAMES:
            continue
        desc = s.get("description", name)
        props = s.get("properties", {})
        card_name = props.get("alsa.card_name")

        label = desc
        if card_name and card_name not in desc:
            label = f"{desc} ({card_name})"

        if label in seen_labels:
            label = f"{label} [{name}]"
        seen_labels[label] = name

        sinks.append((name, label))
    return sinks


def find_sink_input_id(node_name):
    result = subprocess.run(["pactl", "-f", "json", "list", "sink-inputs"], capture_output=True, text=True, check=False)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    for entry in data:
        props = entry.get("properties", {})
        if props.get("node.name") == node_name:
            return entry.get("index")
    return None


def move_output_to_sink(target_sink_name, playback_node_name):
    sink_input_id = find_sink_input_id(playback_node_name)
    if sink_input_id is None:
        return False
    subprocess.run(["pactl", "move-sink-input", str(sink_input_id), target_sink_name], check=False)
    return True


# ---------- recordar último estado ----------

def load_last_state():
    if not os.path.exists(LAST_STATE_FILE):
        return {}
    try:
        with open(LAST_STATE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_last_state(state):
    os.makedirs(os.path.dirname(LAST_STATE_FILE), exist_ok=True)
    with open(LAST_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ---------- idioma de la interfaz ----------

def detect_ui_lang():
    # 1. Argumento por línea de comandos (--lang en)
    if "--lang" in sys.argv:
        try:
            idx = sys.argv.index("--lang")
            arg_lang = sys.argv[idx + 1].lower()
            if arg_lang in ("es", "en"):
                return arg_lang
        except IndexError:
            pass

    # 2. Si pasaste LANG=en... explícitamente en la terminal
    lang_env = os.environ.get("LANG", "").lower()
    if lang_env.startswith("en"):
        return "en"

    # 3. Resto de variables de entorno (LC_ALL, LC_MESSAGES, etc.)
    for env_var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        val = os.environ.get(env_var, "").lower()
        if val:
            if val.startswith("es"):
                return "es"
            if val.startswith("en"):
                return "en"

    return "en"


_STRINGS = {
    "app_title": {
        "es": "Ecualizador + Compresor PipeWire",
        "en": "PipeWire Equalizer + Compressor",
    },
    "error_node_not_found": {
        "es": "No se encontró el nodo '{node}'. ¿Está cargado eq.conf?",
        "en": "Could not find node '{node}'. Is eq.conf loaded?",
    },
    "confirm_title": {
        "es": "Guardar como valores de arranque",
        "en": "Save as startup values",
    },
    "confirm_body": {
        "es": (
            "Esto va a reescribir los archivos eq.conf{comp_suffix} con los "
            "valores actuales, para que PipeWire arranque siempre así de ahora "
            "en más.\n\nSe guarda una copia de respaldo (.bak) antes de "
            "modificar nada.\nEl cambio recién se aplica en el próximo "
            "reinicio de PipeWire (no reinicia el servicio ahora, tu audio "
            "actual no se corta).\n\n¿Continuar?"
        ),
        "en": (
            "This will rewrite eq.conf{comp_suffix} with the current values, "
            "so PipeWire always starts up this way from now on.\n\nA backup "
            "(.bak) is saved before changing anything.\nThe change only "
            "takes effect on the next PipeWire restart (it does not restart "
            "the service now, your current audio won't drop).\n\nContinue?"
        ),
    },
    "comp_suffix": {
        "es": " y compressor.conf",
        "en": " and compressor.conf",
    },
    "done_title": {"es": "Listo", "en": "Done"},
    "done_body": {
        "es": "Valores guardados como arranque por defecto.\n\n",
        "en": "Values saved as default startup settings.\n\n",
    },
    "error_title": {
        "es": "No se pudo completar",
        "en": "Could not complete",
    },
    "error_body": {
        "es": "Hubo un problema:",
        "en": "There was a problem:",
    },
    "eq_conf_not_found": {
        "es": "No se encontró {path}",
        "en": "Could not find {path}",
    },
    "eq_conf_missing_nodes": {
        "es": "No se pudo ubicar el nodo/Gain de: {names}. No se modificó el archivo por seguridad.",
        "en": "Could not locate the node/Gain for: {names}. The file was not modified for safety.",
    },
    "eq_conf_ok": {
        "es": "eq.conf actualizado.",
        "en": "eq.conf updated.",
    },
    "comp_conf_missing_params": {
        "es": "No se pudo ubicar el parámetro: {names}. No se modificó el archivo por seguridad.",
        "en": "Could not locate the parameter: {names}. The file was not modified for safety.",
    },
    "comp_conf_ok": {
        "es": "compressor.conf actualizado.",
        "en": "compressor.conf updated.",
    },
    "view_readme_btn": {
        "es": "README",
        "en": "README",
    },
    "readme_window_title": {
        "es": "README",
        "en": "README",
    },
    "readme_not_found": {
        "es": "No se encontró ningún README junto al script ({names}).",
        "en": "Could not find any README next to the script ({names}).",
    },
    "close_btn": {
        "es": "Cerrar",
        "en": "Close",
    },
    "tab_eq": {"es": "Ecualizador", "en": "Equalizer"},
    "tab_comp": {"es": "Compresor", "en": "Compressor"},
    "preset_label": {"es": "Preset:", "en": "Preset:"},
    "volume_label": {"es": "Volumen:", "en": "Volume:"},
    "output_label": {"es": "Salida:", "en": "Output:"},
    "lang_label": {"es": "Idioma / Lang:", "en": "Language / Lang:"},
    "mute_on": {"es": "Silenciar EQ", "en": "Mute EQ"},
    "mute_off": {"es": "Activar EQ", "en": "Unmute EQ"},
    "save_preset": {"es": "Guardar preset", "en": "Save preset"},
    "delete_preset": {"es": "Borrar preset", "en": "Delete preset"},
    "reset_eq": {"es": "Resetear EQ a 0 dB", "en": "Reset EQ to 0 dB"},
    "bake_startup": {"es": "Guardar como valores de arranque", "en": "Save as startup values"},
    "save_preset_title": {"es": "Guardar preset", "en": "Save preset"},
    "save_preset_prompt": {"es": "Nombre del preset:", "en": "Preset name:"},
    "comp_not_detected": {
        "es": "(Compressor Sink no detectado — panel de compresor oculto. Verificá que compressor.conf esté cargado.)",
        "en": "(Compressor Sink not detected — compressor panel hidden. Check that compressor.conf is loaded.)",
    },
    "comp_bypass_check": {"es": "Bypass (desactivar compresión)", "en": "Bypass (disable compression)"},
    "comp_threshold": {"es": "Threshold (dB)", "en": "Threshold (dB)"},
    "comp_ratio": {"es": "Ratio (x:1)", "en": "Ratio (x:1)"},
    "comp_attack": {"es": "Attack (ms)", "en": "Attack (ms)"},
    "comp_release": {"es": "Release (ms)", "en": "Release (ms)"},
    "comp_makeup": {"es": "Makeup Gain (dB)", "en": "Makeup Gain (dB)"},
    "comp_knee": {"es": "Knee", "en": "Knee"},
    "refresh_outputs_btn": {"es": "↻ Actualizar", "en": "↻ Refresh"},
    "move_output_warning_title": {"es": "Aviso", "en": "Warning"},
    "move_output_warning_body": {
        "es": "No se pudo mover la salida automáticamente. Probá reproducir algo de audio primero y reintentá.",
        "en": "Could not move output automatically. Try playing audio first and retry.",
    },
    "missing_deps_title": {"es": "Faltan dependencias", "en": "Missing dependencies"},
    "missing_deps_body": {
        "es": "No se encontraron en el PATH: {missing}\n\n¿Está instalado y corriendo PipeWire? Estos binarios vienen con los paquetes 'pipewire' y 'pipewire-pulse'.",
        "en": "Not found in PATH: {missing}\n\nIs PipeWire installed and running? These binaries come with 'pipewire' and 'pipewire-pulse' packages.",
    },
}


def t(key, **kwargs):
    template = _STRINGS[key].get(CURRENT_LANG, _STRINGS[key]["en"])
    return template.format(**kwargs)


def find_readme_path():
    preferred = README_EN_NAME if CURRENT_LANG == "en" else README_ES_NAME
    fallback = README_ES_NAME if CURRENT_LANG == "en" else README_EN_NAME

    for name in (preferred, fallback):
        path = os.path.join(SCRIPT_DIR, name)
        if os.path.exists(path):
            return path
    return None


# ---------- "hornear" valores como arranque por defecto en los .conf ----------

def _format_num(value):
    s = f"{float(value):.6f}".rstrip("0").rstrip(".")
    if "." not in s:
        s += ".0"
    return s


def backup_conf(path):
    if not os.path.exists(path):
        return None
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = f"{path}.bak-{timestamp}"
    with open(path, "r") as src, open(backup_path, "w") as dst:
        dst.write(src.read())
    return backup_path


def bake_eq_gains(gains_by_node):
    if not os.path.exists(EQ_CONF_PATH):
        return False, t("eq_conf_not_found", path=EQ_CONF_PATH)

    with open(EQ_CONF_PATH, "r") as f:
        text = f.read()

    missing = []
    for node_name, gain in gains_by_node.items():
        pattern = re.compile(
            r'(name\s*=\s*' + re.escape(node_name) + r'\b.*?"Gain"\s*=\s*)([-\d.]+)',
            re.DOTALL,
        )
        new_text, n = pattern.subn(lambda m: m.group(1) + _format_num(gain), text, count=1)
        if n != 1:
            missing.append(node_name)
        else:
            text = new_text

    if missing:
        return False, t("eq_conf_missing_nodes", names=", ".join(missing))

    backup_conf(EQ_CONF_PATH)
    with open(EQ_CONF_PATH, "w") as f:
        f.write(text)
    return True, t("eq_conf_ok")


def bake_compressor_params(params):
    if not os.path.exists(COMP_CONF_PATH):
        return False, t("eq_conf_not_found", path=COMP_CONF_PATH)

    with open(COMP_CONF_PATH, "r") as f:
        text = f.read()

    missing = []
    for key, value in params.items():
        value_str = str(int(value)) if key == "bypass" else _format_num(value)
        pattern = re.compile(r'("' + re.escape(key) + r'"\s*=\s*)([-\d.]+)')
        new_text, n = pattern.subn(lambda m: m.group(1) + value_str, text, count=1)
        if n != 1:
            missing.append(key)
        else:
            text = new_text

    if missing:
        return False, t("comp_conf_missing_params", names=", ".join(missing))

    backup_conf(COMP_CONF_PATH)
    with open(COMP_CONF_PATH, "w") as f:
        f.write(text)
    return True, t("comp_conf_ok")


# ---------- conversiones para el compresor ----------

def db_to_linear(db):
    return 10 ** (db / 20.0)


def linear_to_db(lin):
    lin = max(lin, 1e-6)
    return 20.0 * math.log10(lin)


class EqualizerApp:
    def __init__(self, root):
        self.root = root
        global CURRENT_LANG
        CURRENT_LANG = detect_ui_lang()

        self.root.title(t("app_title"))
        self.root.geometry("860x560")

        self.eq_node_id = resolve_node_id(EQ_NODE_NAME)
        if self.eq_node_id is None:
            messagebox.showerror(
                "Error", t("error_node_not_found", node=EQ_NODE_NAME)
            )
            root.destroy()
            sys.exit(1)

        self.comp_node_id = resolve_node_id(COMP_NODE_NAME)
        self.comp_controls = {}
        self.comp_bypass_var = None

        self.band_ids = [b[0] for b in BANDS]
        gain_keys = [f"{b}:Gain" for b in self.band_ids]
        current = read_current_params(self.eq_node_id, gain_keys)
        self.current_gains = {
            b: current.get(f"{b}:Gain", 0.0) for b in self.band_ids
        }

        last_state = load_last_state()
        saved_gains = last_state.get("gains", {})
        for band_id, val in saved_gains.items():
            if band_id in self.current_gains:
                self.current_gains[band_id] = val
                set_param(self.eq_node_id, f"{band_id}:Gain", val)

        self.initial_volume = last_state.get("volume", get_sink_volume_percent(EQ_NODE_NAME))
        set_sink_volume_percent(EQ_NODE_NAME, self.initial_volume)

        self.sliders = {}
        self.value_labels = {}

        self.build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def build_ui(self):
        for widget in self.root.winfo_children():
            widget.destroy()

        self.root.title(t("app_title"))

        top_frame = ttk.Frame(self.root, padding=8)
        top_frame.pack(fill="x")

        muted = is_sink_muted(EQ_NODE_NAME)
        self.mute_btn = ttk.Button(
            top_frame, text=t("mute_off") if muted else t("mute_on"), command=self.on_toggle_mute
        )
        self.mute_btn.pack(side="left", padx=4)

        ttk.Label(top_frame, text=t("preset_label")).pack(side="left", padx=(12, 4))
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(top_frame, textvariable=self.preset_var, state="readonly", width=18)
        self.preset_combo.pack(side="left", padx=4)
        self.preset_combo.bind("<<ComboboxSelected>>", self.on_load_preset)
        self.refresh_preset_list()

        ttk.Button(top_frame, text=t("save_preset"), command=self.on_save_preset).pack(side="left", padx=2)
        ttk.Button(top_frame, text=t("delete_preset"), command=self.on_delete_preset).pack(side="left", padx=2)

        ttk.Label(top_frame, text=t("lang_label")).pack(side="left", padx=(12, 4))
        self.lang_var = tk.StringVar(value="ES" if CURRENT_LANG == "es" else "EN")
        self.lang_combo = ttk.Combobox(top_frame, textvariable=self.lang_var, values=["ES", "EN"], state="readonly", width=4)
        self.lang_combo.pack(side="left", padx=2)
        self.lang_combo.bind("<<ComboboxSelected>>", self.on_lang_change)

        second_row = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        second_row.pack(fill="x")

        ttk.Label(second_row, text=t("volume_label")).pack(side="left", padx=(0, 4))
        self.volume_label = ttk.Label(second_row, text=f"{self.initial_volume}%", width=5)
        self.volume_label.pack(side="left", padx=(0, 4))
        volume_scale = ttk.Scale(
            second_row, from_=0, to=150, orient="horizontal", length=180,
            command=self.on_volume_change,
        )
        volume_scale.set(self.initial_volume)
        volume_scale.pack(side="left", padx=4)

        ttk.Label(second_row, text=t("output_label")).pack(side="left", padx=(12, 4))
        self.output_var = tk.StringVar()
        self.output_combo = ttk.Combobox(second_row, textvariable=self.output_var, state="readonly", width=32)
        self.output_combo.pack(side="left", padx=4)
        self.output_combo.bind("<<ComboboxSelected>>", self.on_output_change)
        self.refresh_output_list()

        ttk.Button(second_row, text=t("refresh_outputs_btn"), command=self.on_refresh_outputs).pack(side="left", padx=2)

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        eq_tab = ttk.Frame(notebook)
        notebook.add(eq_tab, text=t("tab_eq"))
        self.build_eq_tab(eq_tab)

        if self.comp_node_id is not None:
            comp_tab = ttk.Frame(notebook)
            notebook.add(comp_tab, text=t("tab_comp"))
            self.build_compressor_tab(comp_tab)
        else:
            info = ttk.Label(
                self.root,
                text=t("comp_not_detected"),
                foreground="#888",
            )
            info.pack(pady=4)

        bottom_frame = ttk.Frame(self.root, padding=8)
        bottom_frame.pack(fill="x")
        ttk.Button(bottom_frame, text=t("reset_eq"), command=self.on_reset).pack(side="left", padx=4)
        ttk.Button(
            bottom_frame, text=t("bake_startup"),
            command=self.on_bake_startup_values,
        ).pack(side="left", padx=4)
        ttk.Button(
            bottom_frame, text=t("view_readme_btn"),
            command=self.on_view_readme,
        ).pack(side="right", padx=4)

    def on_lang_change(self, event=None):
        global CURRENT_LANG
        selected = self.lang_var.get().lower()
        if selected in ("es", "en"):
            CURRENT_LANG = selected
            self.build_ui()

    def build_eq_tab(self, parent):
        sliders_frame = ttk.Frame(parent, padding=12)
        sliders_frame.pack(fill="both", expand=True)

        for col, (band_id, freq_label, is_preamp) in enumerate(BANDS):
            col_frame = ttk.Frame(sliders_frame)
            col_frame.grid(row=0, column=col, padx=8, sticky="ns")

            label_text = freq_label + (" ★" if is_preamp else "")
            ttk.Label(col_frame, text=label_text).pack()

            value_label = ttk.Label(col_frame, text="+0.0 dB")
            value_label.pack()
            self.value_labels[band_id] = value_label

            scale = ttk.Scale(
                col_frame, from_=GAIN_MAX, to=GAIN_MIN, orient="vertical", length=280,
                command=lambda v, b=band_id: self.on_slider_change(b, v),
            )
            initial = self.current_gains.get(band_id, 0.0)
            scale.set(initial)
            value_label.config(text=f"{initial:+.1f} dB")
            scale.pack(fill="y", expand=True)
            self.sliders[band_id] = scale

    def build_compressor_tab(self, parent):
        keys = [
            "compressor:threshold", "compressor:ratio", "compressor:attack",
            "compressor:release", "compressor:makeup", "compressor:knee",
            "compressor:bypass",
        ]
        current = read_current_params(self.comp_node_id, keys)

        last_state = load_last_state()
        saved_comp = last_state.get("compressor", {})
        for key, val in saved_comp.items():
            if key in keys:
                current[key] = val
                set_param(self.comp_node_id, key, val)

        self.comp_controls = {}

        frame = ttk.Frame(parent, padding=16)
        frame.pack(fill="both", expand=True)

        row = 0

        threshold_db = linear_to_db(current.get("compressor:threshold", 0.125))
        row = self.add_db_control(
            frame, row, t("comp_threshold"), threshold_db, -60.0, 0.0,
            lambda db: set_param(self.comp_node_id, "compressor:threshold", db_to_linear(db)),
            register_key="compressor:threshold", native_transform=db_to_linear,
        )

        ratio = current.get("compressor:ratio", 2.0)
        row = self.add_linear_control(
            frame, row, t("comp_ratio"), ratio, 1.0, 20.0,
            lambda v: set_param(self.comp_node_id, "compressor:ratio", v),
            register_key="compressor:ratio",
        )

        attack = current.get("compressor:attack", 20.0)
        row = self.add_linear_control(
            frame, row, t("comp_attack"), attack, 0.1, 200.0,
            lambda v: set_param(self.comp_node_id, "compressor:attack", v),
            register_key="compressor:attack",
        )

        release = current.get("compressor:release", 250.0)
        row = self.add_linear_control(
            frame, row, t("comp_release"), release, 10.0, 1000.0,
            lambda v: set_param(self.comp_node_id, "compressor:release", v),
            register_key="compressor:release",
        )

        makeup_db = linear_to_db(current.get("compressor:makeup", 1.0))
        row = self.add_db_control(
            frame, row, t("comp_makeup"), makeup_db, 0.0, 24.0,
            lambda db: set_param(self.comp_node_id, "compressor:makeup", db_to_linear(db)),
            register_key="compressor:makeup", native_transform=db_to_linear,
        )

        knee = current.get("compressor:knee", 2.828430)
        row = self.add_linear_control(
            frame, row, t("comp_knee"), knee, 1.0, 8.0,
            lambda v: set_param(self.comp_node_id, "compressor:knee", v),
            register_key="compressor:knee",
        )

        self.comp_bypass_var = tk.BooleanVar(value=bool(current.get("compressor:bypass", 0)))

        def on_bypass_toggle():
            set_param(self.comp_node_id, "compressor:bypass", 1.0 if self.comp_bypass_var.get() else 0.0)

        ttk.Checkbutton(
            frame, text=t("comp_bypass_check"), variable=self.comp_bypass_var, command=on_bypass_toggle
        ).grid(row=row, column=0, columnspan=3, pady=12, sticky="w")

    def add_db_control(self, frame, row, label, initial_db, min_db, max_db, on_change,
                        register_key=None, native_transform=None):
        return self._add_control(
            frame, row, label, initial_db, min_db, max_db, on_change, fmt="{:+.1f} dB",
            register_key=register_key, native_transform=native_transform or (lambda v: v),
        )

    def add_linear_control(self, frame, row, label, initial, min_v, max_v, on_change, register_key=None):
        return self._add_control(
            frame, row, label, initial, min_v, max_v, on_change, fmt="{:.2f}",
            register_key=register_key, native_transform=lambda v: v,
        )

    def _debounced_call(self, key, delay_ms, func):
        if not hasattr(self, "_debounce_jobs"):
            self._debounce_jobs = {}
        pending = self._debounce_jobs.get(key)
        if pending is not None:
            self.root.after_cancel(pending)
        self._debounce_jobs[key] = self.root.after(delay_ms, func)

    def _add_control(self, frame, row, label, initial, min_v, max_v, on_change, fmt,
                      register_key=None, native_transform=None):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=6)
        value_label = ttk.Label(frame, text=fmt.format(initial), width=12)
        value_label.grid(row=row, column=2, sticky="e", padx=8)

        def callback(v):
            fval = float(v)
            value_label.config(text=fmt.format(fval))
            self._debounced_call(f"comp:{label}", 80, lambda: on_change(fval))

        scale = ttk.Scale(frame, from_=min_v, to=max_v, orient="horizontal", length=320, command=callback)
        scale.set(initial)
        scale.grid(row=row, column=1, padx=8, pady=6)

        if register_key is not None:
            self.comp_controls[register_key] = (scale, native_transform or (lambda x: x))

        return row + 1

    def on_slider_change(self, band_id, value):
        fval = float(value)
        self.value_labels[band_id].config(text=f"{fval:+.1f} dB")
        self.current_gains[band_id] = fval
        self._debounced_call(f"eq:{band_id}", 80, lambda: set_param(self.eq_node_id, f"{band_id}:Gain", fval))

    def on_reset(self):
        for band_id in self.band_ids:
            self.sliders[band_id].set(0.0)
            self.value_labels[band_id].config(text="+0.0 dB")
            self.current_gains[band_id] = 0.0
            set_param(self.eq_node_id, f"{band_id}:Gain", 0.0)

    def on_toggle_mute(self):
        toggle_mute(EQ_NODE_NAME)
        muted = is_sink_muted(EQ_NODE_NAME)
        self.mute_btn.config(text=t("mute_off") if muted else t("mute_on"))

    def on_volume_change(self, value):
        percent = int(float(value))
        self.volume_label.config(text=f"{percent}%")
        self._last_volume = percent
        self._debounced_call("volume", 80, lambda: set_sink_volume_percent(EQ_NODE_NAME, percent))

    def refresh_output_list(self):
        sinks = list_real_output_sinks()
        self._output_map = {desc: name for name, desc in sinks}
        self.output_combo["values"] = list(self._output_map.keys())

    def on_refresh_outputs(self):
        previous_selection = self.output_var.get()
        self.refresh_output_list()
        if previous_selection in self._output_map:
            self.output_var.set(previous_selection)
        else:
            self.output_var.set("")

    def on_output_change(self, event=None):
        desc = self.output_var.get()
        target_name = self._output_map.get(desc)
        if not target_name:
            return
        playback_node = COMP_PLAYBACK_NAME if self.comp_node_id is not None else EQ_PLAYBACK_NAME
        moved = move_output_to_sink(target_name, playback_node)
        if not moved:
            messagebox.showwarning(
                t("move_output_warning_title"),
                t("move_output_warning_body"),
            )

    def on_bake_startup_values(self):
        comp_suffix = t("comp_suffix") if self.comp_controls else ""
        confirm = messagebox.askyesno(
            t("confirm_title"),
            t("confirm_body", comp_suffix=comp_suffix),
        )
        if not confirm:
            return

        gains = {band_id: self.sliders[band_id].get() for band_id in self.band_ids}
        ok_eq, msg_eq = bake_eq_gains(gains)

        ok_comp, msg_comp = True, ""
        if self.comp_controls:
            comp_params = {
                key.split(":", 1)[1]: transform(scale.get())
                for key, (scale, transform) in self.comp_controls.items()
            }
            if self.comp_bypass_var is not None:
                comp_params["bypass"] = 1 if self.comp_bypass_var.get() else 0
            ok_comp, msg_comp = bake_compressor_params(comp_params)

        if ok_eq and ok_comp:
            messagebox.showinfo(
                t("done_title"),
                t("done_body") + f"{msg_eq}" + (f"\n{msg_comp}" if msg_comp else ""),
            )
        else:
            detail = ("\n" + msg_eq) if not ok_eq else ""
            detail += ("\n" + msg_comp) if not ok_comp else ""
            messagebox.showerror(t("error_title"), t("error_body") + detail)

    def on_view_readme(self):
        path = find_readme_path()
        if path is None:
            messagebox.showwarning(
                t("error_title"),
                t("readme_not_found", names=f"{README_ES_NAME} / {README_EN_NAME}"),
            )
            return

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        win = tk.Toplevel(self.root)
        win.title(f"{t('readme_window_title')} — {os.path.basename(path)}")
        win.geometry("700x600")

        text_frame = ttk.Frame(win, padding=8)
        text_frame.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")

        text_widget = tk.Text(
            text_frame, wrap="word", yscrollcommand=scrollbar.set,
            font=("monospace", 10),
        )
        text_widget.insert("1.0", content)
        text_widget.config(state="disabled")
        text_widget.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=text_widget.yview)

        ttk.Button(win, text=t("close_btn"), command=win.destroy).pack(pady=8)

    def on_close(self):
        gains = {band_id: self.sliders[band_id].get() for band_id in self.band_ids}
        volume = getattr(self, "_last_volume", self.initial_volume)
        state = {"gains": gains, "volume": volume}

        if self.comp_controls:
            compressor = {
                key: transform(scale.get())
                for key, (scale, transform) in self.comp_controls.items()
            }
            if self.comp_bypass_var is not None:
                compressor["compressor:bypass"] = 1.0 if self.comp_bypass_var.get() else 0.0
            state["compressor"] = compressor

        save_last_state(state)
        self.root.destroy()

    def refresh_preset_list(self):
        presets = load_presets()
        self.preset_combo["values"] = list(presets.keys())

    def on_save_preset(self):
        name = simpledialog.askstring(t("save_preset_title"), t("save_preset_prompt"))
        if not name:
            return
        presets = load_presets()
        presets[name] = {band_id: self.sliders[band_id].get() for band_id in self.band_ids}
        save_presets(presets)
        self.refresh_preset_list()
        self.preset_var.set(name)

    def on_load_preset(self, event=None):
        name = self.preset_var.get()
        presets = load_presets()
        values = presets.get(name)
        if not values:
            return
        for band_id, val in values.items():
            if band_id in self.sliders:
                self.sliders[band_id].set(val)
                self.value_labels[band_id].config(text=f"{val:+.1f} dB")
                self.current_gains[band_id] = val
                set_param(self.eq_node_id, f"{band_id}:Gain", val)

    def on_delete_preset(self):
        name = self.preset_var.get()
        if not name:
            return
        presets = load_presets()
        if name in presets:
            del presets[name]
            save_presets(presets)
            self.refresh_preset_list()
            self.preset_var.set("")


def main():
    missing = check_required_binaries()
    if missing:
        global CURRENT_LANG
        CURRENT_LANG = detect_ui_lang()
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            t("missing_deps_title"),
            t("missing_deps_body", missing=", ".join(missing)),
        )
        sys.exit(1)

    root = tk.Tk()
    app = EqualizerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()