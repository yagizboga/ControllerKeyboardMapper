import json
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import vgamepad as vg
from pynput import keyboard

# ----------------------------
# Helpers for key serialization
# ----------------------------
def key_to_str(k) -> str:
    if k is None:
        return ""
    if isinstance(k, keyboard.Key):
        return f"KEY:{k.name}"
    if isinstance(k, keyboard.KeyCode):
        if k.vk is not None:
            return f"VK:{k.vk}"
        if k.char is not None:
            return f"CHAR:{k.char}"
    return ""

def str_to_key(s):
    if not s:
        return None
    try:
        if s.startswith("KEY:"):
            name = s.split(":", 1)[1]
            return getattr(keyboard.Key, name)
        if s.startswith("VK:"):
            vk = int(s.split(":", 1)[1])
            return keyboard.KeyCode.from_vk(vk)
        if s.startswith("CHAR:"):
            ch = s.split(":", 1)[1]
            return keyboard.KeyCode.from_char(ch)
    except Exception:
        return None
    return None

def is_pressed(pressed_set, key_obj) -> bool:
    if key_obj is None:
        return False
    return key_obj in pressed_set

# ----------------------------
# Xbox control definitions
# ----------------------------
# Digital buttons (press/release)
XBTN = {
    "A": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
    "B": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
    "X": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
    "Y": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
    "LB": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
    "RB": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
    "BACK": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
    "START": vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
    "LS_CLICK": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
    "RS_CLICK": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
    "DPAD_UP": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
    "DPAD_DOWN": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
    "DPAD_LEFT": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
    "DPAD_RIGHT": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
}

AXIS_GROUPS = [
    ("LEFT_STICK", ["UP", "DOWN", "LEFT", "RIGHT"]),
    ("RIGHT_STICK", ["UP", "DOWN", "LEFT", "RIGHT"]),
]

TRIGGERS = ["LT", "RT"]  # treated as full press (255) when key is held

# Default mapping (empty)
DEFAULT_PROFILE = {
    # Buttons
    **{name: "" for name in XBTN.keys()},
    # Stick directions
    "LEFT_STICK_UP": "", "LEFT_STICK_DOWN": "", "LEFT_STICK_LEFT": "", "LEFT_STICK_RIGHT": "",
    "RIGHT_STICK_UP": "", "RIGHT_STICK_DOWN": "", "RIGHT_STICK_LEFT": "", "RIGHT_STICK_RIGHT": "",
    # Triggers (digital-to-analog full)
    "LT": "", "RT": "",
    # Exit combo
    "EXIT_KEY_1": "KEY:esc",
    "EXIT_KEY_2": "KEY:backspace",
    "EXIT_HOLD_SEC": 0.3,
    # Stick magnitude (0.0..1.0)
    "STICK_MAGNITUDE": 1.0,
}

# ----------------------------
# Mapper runtime
# ----------------------------
class MapperRuntime:
    def __init__(self, get_profile_callable, status_callable):
        self.get_profile = get_profile_callable
        self.set_status = status_callable

        self._stop = threading.Event()
        self._thread = None

        self.pressed = set()
        self.listener = None
        self.gamepad = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            if self.listener:
                self.listener.stop()
        except Exception:
            pass

    def _on_press(self, k):
        self.pressed.add(k)

    def _on_release(self, k):
        self.pressed.discard(k)

    @staticmethod
    def _axis_short(v_float: float) -> int:
        v = max(-1.0, min(1.0, v_float))
        return int(v * 32767)

    def _run(self):
        try:
            self.gamepad = vg.VX360Gamepad()
        except Exception as e:
            self.set_status(f"Gamepad init failed: {e}")
            return

        self.listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self.listener.start()

        self.set_status("Mapper RUNNING")

        exit_hold_start = None

        while not self._stop.is_set():
            profile = self.get_profile()

            # Exit combo
            exit1 = str_to_key(profile.get("EXIT_KEY_1", "KEY:esc"))
            exit2 = str_to_key(profile.get("EXIT_KEY_2", "KEY:backspace"))
            hold_sec = float(profile.get("EXIT_HOLD_SEC", 0.3))

            if is_pressed(self.pressed, exit1) and is_pressed(self.pressed, exit2):
                if exit_hold_start is None:
                    exit_hold_start = time.time()
                elif time.time() - exit_hold_start >= hold_sec:
                    self.set_status("Exit combo triggered")
                    break
            else:
                exit_hold_start = None

            mag = float(profile.get("STICK_MAGNITUDE", 1.0))
            mag = max(0.0, min(1.0, mag))

            # Left stick from 4 keys
            lx = (is_pressed(self.pressed, str_to_key(profile.get("LEFT_STICK_RIGHT", ""))) -
                  is_pressed(self.pressed, str_to_key(profile.get("LEFT_STICK_LEFT", ""))))
            ly = (is_pressed(self.pressed, str_to_key(profile.get("LEFT_STICK_UP", ""))) -
                  is_pressed(self.pressed, str_to_key(profile.get("LEFT_STICK_DOWN", ""))))
            self.gamepad.left_joystick(
                x_value=self._axis_short(lx * mag),
                y_value=self._axis_short(ly * mag)
            )

            # Right stick from 4 keys
            rx = (is_pressed(self.pressed, str_to_key(profile.get("RIGHT_STICK_RIGHT", ""))) -
                  is_pressed(self.pressed, str_to_key(profile.get("RIGHT_STICK_LEFT", ""))))
            ry = (is_pressed(self.pressed, str_to_key(profile.get("RIGHT_STICK_UP", ""))) -
                  is_pressed(self.pressed, str_to_key(profile.get("RIGHT_STICK_DOWN", ""))))
            self.gamepad.right_joystick(
                x_value=self._axis_short(rx * mag),
                y_value=self._axis_short(ry * mag)
            )

            # Triggers (full analog when key held)
            lt_key = str_to_key(profile.get("LT", ""))
            rt_key = str_to_key(profile.get("RT", ""))
            self.gamepad.left_trigger(value=255 if is_pressed(self.pressed, lt_key) else 0)
            self.gamepad.right_trigger(value=255 if is_pressed(self.pressed, rt_key) else 0)

            # Digital buttons
            for name, btn in XBTN.items():
                k = str_to_key(profile.get(name, ""))
                if is_pressed(self.pressed, k):
                    self.gamepad.press_button(btn)
                else:
                    self.gamepad.release_button(btn)

            self.gamepad.update()
            time.sleep(0.01)

        # cleanup
        try:
            self.gamepad.reset()
            self.gamepad.update()
        except Exception:
            pass
        try:
            if self.listener:
                self.listener.stop()
        except Exception:
            pass

        self.set_status("Mapper STOPPED")


# ----------------------------
# UI
# ----------------------------
class MapperUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ShreddersMapper - Xbox Button Mapper UI")
        self.geometry("820x720")

        self.profile = dict(DEFAULT_PROFILE)

        self.capture_target = None  # key in profile dict
        self.capture_listener = None

        self.runtime = MapperRuntime(self.get_profile_copy, self.set_status)

        self._build()

    def _build(self):
        # Top bar
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=10)

        ttk.Button(top, text="Load Profile", command=self.load_profile).pack(side="left")
        ttk.Button(top, text="Save Profile", command=self.save_profile).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Reset Defaults", command=self.reset_defaults).pack(side="left", padx=(8, 0))

        ttk.Separator(self).pack(fill="x", padx=10, pady=10)

        # Settings row
        settings = ttk.Frame(self)
        settings.pack(fill="x", padx=10)

        ttk.Label(settings, text="Stick Magnitude (0.0 - 1.0):").pack(side="left")
        self.mag_var = tk.DoubleVar(value=self.profile["STICK_MAGNITUDE"])
        mag = ttk.Spinbox(settings, from_=0.0, to=1.0, increment=0.1, textvariable=self.mag_var, width=6)
        mag.pack(side="left", padx=6)

        ttk.Label(settings, text="Exit Hold (sec):").pack(side="left", padx=(18, 0))
        self.exit_hold_var = tk.DoubleVar(value=self.profile["EXIT_HOLD_SEC"])
        hold = ttk.Spinbox(settings, from_=0.0, to=2.0, increment=0.1, textvariable=self.exit_hold_var, width=6)
        hold.pack(side="left", padx=6)

        ttk.Separator(self).pack(fill="x", padx=10, pady=10)

        # Scrollable mapping area
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        canvas = tk.Canvas(container)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        self.map_frame = ttk.Frame(canvas)

        self.map_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.map_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Sections
        self._section_title("Buttons")
        self.mapping_vars = {}  # profile_key -> StringVar

        for name in ["A", "B", "X", "Y", "LB", "RB", "LT", "RT",
                     "BACK", "START", "LS_CLICK", "RS_CLICK",
                     "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT"]:
            self._row(name, name)

        self._section_title("Left Stick (4-direction keys)")
        for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
            self._row(f"LEFT_STICK_{d}", f"LEFT_STICK_{d}")

        self._section_title("Right Stick (4-direction keys)")
        for d in ["UP", "DOWN", "LEFT", "RIGHT"]:
            self._row(f"RIGHT_STICK_{d}", f"RIGHT_STICK_{d}")

        self._section_title("Exit Combo")
        self._row("EXIT_KEY_1", "EXIT_KEY_1")
        self._row("EXIT_KEY_2", "EXIT_KEY_2")

        # Bottom controls
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=10, pady=(0, 10))

        ttk.Button(bottom, text="Start Mapper", command=self.start_mapper).pack(side="left")
        ttk.Button(bottom, text="Stop Mapper", command=self.stop_mapper).pack(side="left", padx=(8, 0))

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(bottom, textvariable=self.status_var).pack(side="right")

        note = ttk.Label(self, text="Tip: Bir kontrole 'Set' deyip tuşa bas. Çıkış: EXIT_KEY_1 + EXIT_KEY_2 (varsayılan ESC + Backspace).",
                         foreground="#444")
        note.pack(fill="x", padx=10, pady=(0, 10))

    def _section_title(self, text):
        lbl = ttk.Label(self.map_frame, text=text, font=("Segoe UI", 11, "bold"))
        lbl.pack(anchor="w", pady=(10, 6))

    def _row(self, label, profile_key):
        row = ttk.Frame(self.map_frame)
        row.pack(fill="x", pady=2)

        ttk.Label(row, text=label, width=22).pack(side="left")

        var = tk.StringVar(value=self.profile.get(profile_key, ""))
        self.mapping_vars[profile_key] = var

        ent = ttk.Entry(row, textvariable=var, width=30)
        ent.pack(side="left", padx=(0, 8))

        ttk.Button(row, text="Set", command=lambda k=profile_key: self.begin_capture(k)).pack(side="left")
        ttk.Button(row, text="Clear", command=lambda k=profile_key: self.clear_mapping(k)).pack(side="left", padx=(6, 0))

        # Nice human-readable hint
        hint = ttk.Label(row, text=self._pretty_key(var.get()), foreground="#666")
        hint.pack(side="left", padx=(10, 0))

        def refresh_hint(*_):
            hint.configure(text=self._pretty_key(var.get()))
        var.trace_add("write", refresh_hint)

    def _pretty_key(self, s):
        if not s:
            return "(unmapped)"
        if s.startswith("KEY:"):
            return s.replace("KEY:", "Key.")
        if s.startswith("VK:"):
            return f"VK {s.split(':',1)[1]}"
        if s.startswith("CHAR:"):
            return f"'{s.split(':',1)[1]}'"
        return s

    def set_status(self, s):
        self.status_var.set(s)

    def get_profile_copy(self):
        # sync vars -> profile
        self.profile["STICK_MAGNITUDE"] = float(self.mag_var.get())
        self.profile["EXIT_HOLD_SEC"] = float(self.exit_hold_var.get())
        for k, v in self.mapping_vars.items():
            self.profile[k] = v.get()
        return dict(self.profile)

    # ---------------- Capture logic ----------------
    def begin_capture(self, profile_key):
        if self.capture_target is not None:
            messagebox.showinfo("Capture", "Zaten bir capture aktif. Önce onu bitir.")
            return
        self.capture_target = profile_key
        self.set_status(f"Press a key for: {profile_key}")

        def on_press(k):
            # record first key and stop
            s = key_to_str(k)
            if not s:
                return
            self.mapping_vars[profile_key].set(s)
            self.set_status(f"Mapped {profile_key} -> {s}")
            self.capture_target = None
            try:
                return False  # stop listener
            finally:
                pass

        # one-shot listener
        self.capture_listener = keyboard.Listener(on_press=on_press)
        self.capture_listener.start()

    def clear_mapping(self, profile_key):
        self.mapping_vars[profile_key].set("")

    # ---------------- Profile IO ----------------
    def save_profile(self):
        self.get_profile_copy()
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON profile", "*.json")]
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.profile, f, indent=2, ensure_ascii=False)
        self.set_status(f"Saved: {path}")

    def load_profile(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON profile", "*.json")]
        )
        if not path:
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # merge
        self.profile.update(data)

        # apply to UI vars
        self.mag_var.set(float(self.profile.get("STICK_MAGNITUDE", 1.0)))
        self.exit_hold_var.set(float(self.profile.get("EXIT_HOLD_SEC", 0.3)))
        for k, var in self.mapping_vars.items():
            var.set(self.profile.get(k, ""))

        self.set_status(f"Loaded: {path}")

    def reset_defaults(self):
        if not messagebox.askyesno("Reset", "Tüm mappingleri sıfırlamak istiyor musun?"):
            return
        self.profile = dict(DEFAULT_PROFILE)
        self.mag_var.set(float(self.profile["STICK_MAGNITUDE"]))
        self.exit_hold_var.set(float(self.profile["EXIT_HOLD_SEC"]))
        for k, var in self.mapping_vars.items():
            var.set(self.profile.get(k, ""))
        self.set_status("Reset to defaults")

    # ---------------- Runtime controls ----------------
    def start_mapper(self):
        self.get_profile_copy()
        self.runtime.start()
        self.set_status("Starting mapper...")

    def stop_mapper(self):
        self.runtime.stop()
        self.set_status("Stopping mapper...")

    def on_close(self):
        try:
            self.runtime.stop()
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    app = MapperUI()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
