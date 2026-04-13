import importlib
import json
import os
import shutil
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
import tkinter.font as tkfont

try:
    evdev = importlib.import_module("evdev")
except Exception:
    evdev = None


class FootPedalApp:
    MAX_PEDALS = 8

    def __init__(self, root):
        self.root = root
        self.root.title("Foot Pedal Configurator")
        self.root.geometry("1060x760")
        self.root.minsize(980, 700)
        self.base_dir = Path(__file__).resolve().parent

        self.baseline_signatures = set()
        self.new_devices = []
        self.mapping_rows = []
        self.last_process = None

        self.status_var = tk.StringVar(value="Ready. Click 'Scan Current Keyboards' to begin.")
        self.pedal_count_var = tk.IntVar(value=1)
        self.device_path_var = tk.StringVar()
        self.selected_device_label_var = tk.StringVar(value="No pedal device selected")
        self.show_advanced_var = tk.BooleanVar(value=False)

        self.theme_var = tk.StringVar(value="Normal")
        self.font_size_var = tk.IntVar(value=12)
        self.font_family_var = tk.StringVar(value="Courier 10 Pitch")
        self.running_widget = None
        self.detect_popup = None
        self.detect_poll_cancelled = False
        self.detect_poll_deadline = 0.0

        self._build_ui()
        self.font_family_var.set(self._resolve_font_family("Courier 10 Pitch"))
        self._apply_appearance()
        self._rebuild_mapping_rows()
        self.root.protocol("WM_DELETE_WINDOW", self._on_main_close)

    def _build_ui(self):
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        self.container = ttk.Frame(self.root, padding=14)
        self.container.pack(fill="both", expand=True)
        self.container.columnconfigure(0, weight=1)
        self.container.rowconfigure(1, weight=1)

        top = ttk.Frame(self.container)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        top.columnconfigure(0, weight=1)

        self.title_label = ttk.Label(top, text="Foot Pedal Configurator", style="Title.TLabel")
        self.title_label.grid(row=0, column=0, sticky="w")

        self.subtitle_label = ttk.Label(
            top,
            text="Simple flow: Scan baseline -> Plug pedal -> Detect -> Learn -> Assign -> Run",
            style="Subtitle.TLabel",
        )
        self.subtitle_label.grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.notebook = ttk.Notebook(self.container)
        self.notebook.grid(row=1, column=0, sticky="nsew")

        self.setup_tab = ttk.Frame(self.notebook, padding=14)
        self.settings_tab = ttk.Frame(self.notebook, padding=14)
        self.about_tab = ttk.Frame(self.notebook, padding=14)
        self.notebook.add(self.setup_tab, text="Setup")
        self.notebook.add(self.settings_tab, text="Settings")
        self.notebook.add(self.about_tab, text="About")

        self._build_setup_tab()
        self._build_settings_tab()
        self._build_about_tab()

        footer = ttk.Frame(self.container, padding=(0, 10, 0, 0))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(footer, textvariable=self.status_var, style="Status.TLabel", anchor="w")
        self.status_label.grid(row=0, column=0, sticky="ew")

    def _build_setup_tab(self):
        self.setup_tab.columnconfigure(0, weight=1)
        self.setup_tab.rowconfigure(2, weight=1)

        device_card = ttk.LabelFrame(self.setup_tab, text="Step 1: Detect pedal device", style="Card.TLabelframe", padding=12)
        device_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        device_card.columnconfigure(1, weight=1)

        ttk.Button(device_card, text="1) Scan Current Keyboards", command=self.scan_baseline).grid(row=0, column=0, sticky="w")
        ttk.Button(device_card, text="2) Detect Newly Added Device", command=self.detect_new_devices).grid(
            row=0, column=1, sticky="w", padx=(10, 0)
        )

        ttk.Label(device_card, text="Detected pedal device:").grid(row=1, column=0, sticky="w", pady=(12, 0))
        self.detected_combo = ttk.Combobox(device_card, state="readonly", width=72)
        self.detected_combo.grid(row=1, column=1, sticky="ew", pady=(12, 0))
        self.detected_combo.bind("<<ComboboxSelected>>", self.assign_selected_device)

        ttk.Label(device_card, text="Selected Linux event path:").grid(row=2, column=0, sticky="nw", pady=(10, 0))
        self.selected_path_label = ttk.Label(device_card, textvariable=self.selected_device_label_var, style="Hint.TLabel", wraplength=760)
        self.selected_path_label.grid(row=2, column=1, sticky="w", pady=(10, 0))

        ttk.Label(
            device_card,
            text="Important: Choose a '*-event-kbd' style device, not '*-event-mouse'.",
            style="Hint.TLabel",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Checkbutton(
            device_card,
            text="Show advanced device options",
            variable=self.show_advanced_var,
            command=self._toggle_advanced_visibility,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.advanced_frame = ttk.Frame(device_card)
        self.advanced_frame.columnconfigure(1, weight=1)
        ttk.Label(self.advanced_frame, text="Manual Linux event path:").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.advanced_frame, textvariable=self.device_path_var, width=60).grid(row=0, column=1, sticky="ew")

        ttk.Label(self.advanced_frame, text="Baseline keyboard list:", style="Hint.TLabel").grid(row=1, column=0, sticky="nw", pady=(8, 0))
        self.baseline_listbox = tk.Listbox(self.advanced_frame, height=5, activestyle="none")
        self.baseline_listbox.grid(row=1, column=1, sticky="ew", pady=(8, 0))

        map_card = ttk.LabelFrame(self.setup_tab, text="Step 2: Configure pedal mappings", style="Card.TLabelframe", padding=12)
        map_card.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        map_card.columnconfigure(0, weight=1)
        map_card.rowconfigure(1, weight=1)

        top_row = ttk.Frame(map_card)
        top_row.grid(row=0, column=0, sticky="ew")
        ttk.Label(top_row, text="How many pedal keys?").pack(side="left")

        self.pedal_count_combo = ttk.Combobox(
            top_row,
            textvariable=self.pedal_count_var,
            width=5,
            state="readonly",
            values=[str(i) for i in range(1, self.MAX_PEDALS + 1)],
        )
        self.pedal_count_combo.pack(side="left", padx=(8, 0))
        self.pedal_count_combo.bind("<<ComboboxSelected>>", lambda _event: self._rebuild_mapping_rows())

        ttk.Label(top_row, text="Use Learn so users do not type trigger codes.", style="Hint.TLabel").pack(side="left", padx=(12, 0))

        self.mapping_container = ttk.Frame(map_card)
        self.mapping_container.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        for i in range(5):
            self.mapping_container.columnconfigure(i, weight=1 if i in (3, 4) else 0)

        run_card = ttk.LabelFrame(self.setup_tab, text="Step 3: Run", style="Card.TLabelframe", padding=12)
        run_card.grid(row=2, column=0, sticky="ew")

        ttk.Button(run_card, text="Run Footswitch", command=self.run_footswitch).pack(side="left")
        ttk.Button(run_card, text="Stop Running Footswitch", command=self.stop_footswitch).pack(side="left", padx=(8, 0))

        self._toggle_advanced_visibility()

    def _build_settings_tab(self):
        self.settings_tab.columnconfigure(0, weight=1)

        settings_card = ttk.LabelFrame(self.settings_tab, text="Display Settings", style="Card.TLabelframe", padding=14)
        settings_card.grid(row=0, column=0, sticky="ew")
        settings_card.columnconfigure(1, weight=1)

        ttk.Label(settings_card, text="Theme mode:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(settings_card, textvariable=self.theme_var, state="readonly", values=["Normal", "Dark"], width=14).grid(
            row=0, column=1, sticky="w", padx=(10, 0)
        )

        ttk.Label(settings_card, text="Font family:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.font_family_combo = ttk.Combobox(
            settings_card,
            textvariable=self.font_family_var,
            state="readonly",
            values=["Courier 10 Pitch", "Ubuntu", "Noto Sans", "DejaVu Sans", "Liberation Sans", "Arial"],
            width=18,
        )
        self.font_family_combo.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=(10, 0))

        ttk.Button(settings_card, text="Refresh Fonts", command=self._refresh_font_families).grid(
            row=1, column=2, sticky="w", padx=(12, 0), pady=(10, 0)
        )

        ttk.Button(settings_card, text="Install Missing Fonts", command=self._install_missing_fonts).grid(
            row=1, column=3, sticky="w", padx=(8, 0), pady=(10, 0)
        )

        ttk.Label(settings_card, text="Font size:").grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Spinbox(settings_card, from_=10, to=20, textvariable=self.font_size_var, width=8).grid(
            row=2, column=1, sticky="w", padx=(10, 0), pady=(10, 0)
        )

        ttk.Button(settings_card, text="Apply Settings", command=self._apply_appearance).grid(row=4, column=0, columnspan=2, sticky="w", pady=(14, 0))

        ttk.Label(
            settings_card,
            text="Tip: Courier 10 Pitch is now default. If missing, use Install Missing Fonts.",
            style="Hint.TLabel",
        ).grid(row=5, column=0, columnspan=4, sticky="w", pady=(10, 0))

        self._refresh_font_families(initial=True)

    def _build_about_tab(self):
        self.about_tab.columnconfigure(0, weight=1)

        hero = ttk.LabelFrame(self.about_tab, text="Foot Pedal Configurator", style="Card.TLabelframe", padding=16)
        hero.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        hero.columnconfigure(0, weight=1)

        ttk.Label(hero, text="Professional Footswitch Mapping for Ubuntu", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(hero, text="Version 2.3", style="Hint.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 8))
        ttk.Label(
            hero,
            text="Designed for simple, reliable operation: detect pedal, learn inputs, assign outputs, and run safely.",
            wraplength=860,
            justify="left",
        ).grid(row=2, column=0, sticky="w")

        highlights = ttk.LabelFrame(self.about_tab, text="Product Highlights", style="Card.TLabelframe", padding=16)
        highlights.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        highlights.columnconfigure(0, weight=1)
        feature_text = (
            "• Guided setup with scan/detect/learn prompts\n"
            "• Pedal-only remapping without altering normal keyboard behavior\n"
            "• Single key, combo, and macro output support\n"
            "• Floating stop-control tool while remapper is active\n"
            "• Theme, font, and readability settings"
        )
        ttk.Label(highlights, text=feature_text, justify="left").grid(row=0, column=0, sticky="w")

        creator = ttk.LabelFrame(self.about_tab, text="Creator", style="Card.TLabelframe", padding=16)
        creator.grid(row=2, column=0, sticky="ew")
        creator.columnconfigure(0, weight=1)

        ttk.Label(creator, text="Kyle Josef Bonachita", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(creator, text="Rafael Sarmiento", style="Title.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Label(creator, text="Technical Support Team", style="Hint.TLabel").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Label(creator, text="HCLTech | NVIDIA - Gr00t Robotics PH", style="Hint.TLabel").grid(row=3, column=0, sticky="w")
        ttk.Label(
            creator,
            text="© 2026 | For NVIDIA GR00T Project PH Use Only",
            style="Hint.TLabel",
        ).grid(row=4, column=0, sticky="w", pady=(10, 0))

    def _apply_appearance(self):
        size = int(self.font_size_var.get())
        family = self._resolve_font_family(self.font_family_var.get().strip() or "Ubuntu")

        fonts_to_update = ["TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"]
        for font_name in fonts_to_update:
            try:
                tkfont.nametofont(font_name).configure(family=family, size=size)
            except Exception:
                pass

        self.style.configure("Title.TLabel", font=(family, size + 6, "bold"))
        self.style.configure("Subtitle.TLabel", font=(family, size + 1))
        self.style.configure("Hint.TLabel", font=(family, max(10, size - 1)))
        self.style.configure("Status.TLabel", font=(family, size, "bold"))
        self.style.configure("TLabel", font=(family, size))
        self.style.configure("TButton", font=(family, size, "bold"), padding=(12, 6))
        self.style.configure("TCombobox", font=(family, size), padding=4)
        self.style.configure("TCheckbutton", font=(family, size))
        self.style.configure("TNotebook.Tab", font=(family, size, "bold"), padding=(12, 8))
        self.style.configure("Card.TLabelframe.Label", font=(family, size + 1, "bold"))
        self.style.configure("TLabelframe", borderwidth=1)
        self.style.configure("Card.TLabelframe", borderwidth=1)

        if self.theme_var.get() == "Dark":
            bg_main = "#161a22"
            panel = "#202633"
            panel_2 = "#2b3444"
            fg = "#eef3ff"
            hint = "#b9c3d9"
            status = "#7dc4ff"
            accent = "#4e89ff"

            self.root.configure(bg=bg_main)
            self.style.configure("TFrame", background=bg_main)
            self.style.configure("TLabelframe", background=panel, foreground=fg, bordercolor=panel_2)
            self.style.configure("Card.TLabelframe", background=panel, foreground=fg, bordercolor=panel_2)
            self.style.configure("TLabel", background=panel, foreground=fg)
            self.style.configure("Title.TLabel", background=bg_main, foreground=fg)
            self.style.configure("Subtitle.TLabel", background=bg_main, foreground=hint)
            self.style.configure("Hint.TLabel", background=panel, foreground=hint)
            self.style.configure("Status.TLabel", background=bg_main, foreground=status)
            self.style.configure("TCheckbutton", background=panel, foreground=fg)
            self.style.configure("TNotebook", background=bg_main, borderwidth=0)
            self.style.configure("TNotebook.Tab", background=panel, foreground=hint)
            self.style.map("TNotebook.Tab", background=[("selected", accent)], foreground=[("selected", "#ffffff")])
            self.style.configure("TEntry", fieldbackground=panel_2, foreground=fg)
            self.style.configure("TCombobox", fieldbackground=panel_2, foreground=fg, background=panel_2, arrowcolor=fg)
            self.style.map(
                "TCombobox",
                fieldbackground=[("readonly", panel_2), ("!readonly", panel_2)],
                foreground=[("readonly", fg), ("!readonly", fg)],
                background=[("readonly", panel_2), ("!readonly", panel_2)],
            )
            self.style.map("TButton", background=[("active", accent)], foreground=[("active", "#ffffff")])
            self.baseline_listbox.configure(bg="#121722", fg="#eef3ff", highlightthickness=1, relief="flat")
        else:
            bg_main = "#f3f5f8"
            fg = "#1e1e1e"
            self.root.configure(bg=bg_main)
            self.style.configure("TFrame", background=bg_main)
            self.style.configure("TLabelframe", background="#ffffff", foreground=fg, bordercolor="#dbe2ec")
            self.style.configure("Card.TLabelframe", background="#ffffff", foreground=fg, bordercolor="#dbe2ec")
            self.style.configure("TLabel", background="#ffffff", foreground=fg)
            self.style.configure("Title.TLabel", background=bg_main, foreground="#0f172a")
            self.style.configure("Subtitle.TLabel", background=bg_main, foreground="#334155")
            self.style.configure("Hint.TLabel", background="#ffffff", foreground="#4b5563")
            self.style.configure("Status.TLabel", background=bg_main, foreground="#0A4D8C")
            self.style.configure("TCheckbutton", background="#ffffff", foreground="#1f2937")
            self.style.configure("TNotebook", background=bg_main, borderwidth=0)
            self.style.configure("TNotebook.Tab", background="#e5e7eb", foreground="#111827")
            self.style.map("TNotebook.Tab", background=[("selected", "#ffffff")], foreground=[("selected", "#0f172a")])
            self.style.configure("TEntry", fieldbackground="#ffffff", foreground="#111827")
            self.style.configure("TCombobox", fieldbackground="#ffffff", foreground="#111827", background="#ffffff", arrowcolor="#111827")
            self.style.map(
                "TCombobox",
                fieldbackground=[("readonly", "#ffffff"), ("!readonly", "#ffffff")],
                foreground=[("readonly", "#111827"), ("!readonly", "#111827")],
                background=[("readonly", "#ffffff"), ("!readonly", "#ffffff")],
            )
            self.baseline_listbox.configure(bg="white", fg="#111827", highlightthickness=1, relief="solid")

        self._set_status(f"Display settings applied: {self.theme_var.get()} mode, {family} {size}px.")

    def _resolve_font_family(self, preferred: str) -> str:
        available_list = list(tkfont.families())
        available_set = set(available_list)
        preferred_clean = (preferred or "").strip()

        if preferred_clean in available_set:
            return preferred_clean

        lower_map = {name.lower(): name for name in available_list}
        if preferred_clean.lower() in lower_map:
            return lower_map[preferred_clean.lower()]

        best_courier = self._find_best_courier_family(available_list)
        if best_courier:
            self.font_family_var.set(best_courier)
            return best_courier

        fallbacks = ["Ubuntu", "Noto Sans", "DejaVu Sans", "Liberation Sans", "TkDefaultFont"]
        for candidate in fallbacks:
            if candidate in available_set:
                self.font_family_var.set(candidate)
                return candidate

        self.font_family_var.set("TkDefaultFont")
        return "TkDefaultFont"

    @staticmethod
    def _find_best_courier_family(available_list: list[str]) -> str:
        lowered = [(name, name.lower()) for name in available_list]

        for original, low in lowered:
            if low == "courier 10 pitch":
                return original

        for original, low in lowered:
            if "courier" in low and "pitch" in low:
                return original

        for original, low in lowered:
            if low.startswith("courier"):
                return original

        return ""

    def _refresh_font_families(self, initial: bool = False):
        recommended = ["Courier 10 Pitch", "Ubuntu", "Noto Sans", "DejaVu Sans", "Liberation Sans", "Arial"]
        available = sorted(set(tkfont.families()))

        merged = []
        for name in recommended + available:
            if name not in merged:
                merged.append(name)

        if hasattr(self, "font_family_combo"):
            self.font_family_combo["values"] = merged

        current = self.font_family_var.get().strip()
        if current not in merged:
            fallback = self._resolve_font_family("Courier 10 Pitch")
            self.font_family_var.set(fallback)
        elif initial:
            self.font_family_var.set(self._resolve_font_family(current or "Courier 10 Pitch"))

        if not initial:
            self._set_status(f"Font list refreshed. Detected {len(available)} font families.")

    def _install_missing_fonts(self):
        required_families = ["Courier 10 Pitch", "Ubuntu", "Noto Sans", "DejaVu Sans", "Liberation Sans"]
        available = set(tkfont.families())
        missing = [family for family in required_families if family not in available]

        if not missing:
            messagebox.showinfo("Fonts ready", "All recommended fonts are already installed.")
            return

        proceed = messagebox.askokcancel(
            "Install fonts",
            "Missing fonts detected:\n"
            + "\n".join(f"- {family}" for family in missing)
            + "\n\nThe app will install required font packages now. Continue?",
        )
        if not proceed:
            return

        try:
            apt_cmd = [
                "apt",
                "install",
                "-y",
                "fonts-ubuntu",
                "fonts-noto-core",
                "fonts-dejavu-core",
                "fonts-liberation",
                "xfonts-base",
            ]

            if os.geteuid() == 0:
                subprocess.run(["apt", "update"], check=True)
                subprocess.run(apt_cmd, check=True)
                subprocess.run(["fc-cache", "-f"], check=True)
            else:
                if shutil.which("pkexec") is not None:
                    pk_script = "apt update && apt install -y fonts-ubuntu fonts-noto-core fonts-dejavu-core fonts-liberation xfonts-base && fc-cache -f"
                    subprocess.run(["pkexec", "bash", "-lc", pk_script], check=True)
                else:
                    raise RuntimeError("pkexec is not available")
        except Exception as exc:
            install_script = (
                "sudo apt update && "
                "sudo apt install -y fonts-ubuntu fonts-noto-core fonts-dejavu-core fonts-liberation xfonts-base && "
                "fc-cache -f"
            )
            terminal_candidates = [
                ["xterm", "-e", f"bash -lc '{install_script}'"],
                ["konsole", "-e", "bash", "-lc", install_script],
                ["xfce4-terminal", "--command", f"bash -lc '{install_script}'"],
                ["mate-terminal", "-e", f"bash -lc '{install_script}'"],
                ["lxterminal", "-e", f"bash -lc '{install_script}'"],
            ]

            for cmd in terminal_candidates:
                if shutil.which(cmd[0]) is None:
                    continue
                try:
                    subprocess.Popen(cmd)
                    self._set_status("Font installation terminal launched. After completion, click 'Refresh Fonts'.")
                    return
                except Exception:
                    continue

            messagebox.showerror(
                "Font install failed",
                "Automatic font installation failed.\n\n"
                "Run manually:\n"
                "sudo apt update && sudo apt install -y fonts-ubuntu fonts-noto-core fonts-dejavu-core fonts-liberation xfonts-base\n"
                "fc-cache -f\n\n"
                f"Details: {exc}",
            )
            return

        messagebox.showinfo("Fonts installed", "Fonts installed successfully. Font list and appearance were refreshed automatically.")
        self._refresh_font_families()
        self._apply_appearance()
        self._set_status("Fonts installed, refreshed, and applied.")

    def _toggle_advanced_visibility(self):
        if self.show_advanced_var.get():
            self.advanced_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        else:
            self.advanced_frame.grid_remove()

    def _set_status(self, text):
        self.status_var.set(text)

    @staticmethod
    def _is_permission_denied_error(exc: Exception) -> bool:
        if isinstance(exc, PermissionError):
            return True
        message = str(exc).lower()
        return "permission denied" in message or "errno 13" in message

    def _build_self_launch_command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable]
        return [sys.executable, str(self.base_dir / "gui.py")]

    def _relaunch_as_admin(self) -> bool:
        launch_cmd = self._build_self_launch_command()

        if shutil.which("pkexec") is not None:
            try:
                subprocess.Popen(["pkexec", *launch_cmd], cwd=str(self.base_dir))
                self.root.destroy()
                return True
            except Exception:
                return False

        return False

    def _offer_admin_relaunch(self, reason: str):
        if os.geteuid() == 0:
            return

        should_relaunch = messagebox.askyesno(
            "Permission required",
            f"{reason}\n\n"
            "This action needs elevated Linux input permissions.\n"
            "Relaunch the app as administrator now?",
        )
        if not should_relaunch:
            return

        if not self._relaunch_as_admin():
            messagebox.showerror(
                "Elevation failed",
                "Could not relaunch automatically as administrator.\n\n"
                "Run this executable with sudo or set udev input/uinput permissions.",
            )

    @staticmethod
    def _normalize_path(value):
        if isinstance(value, bytes):
            return value.decode(errors="ignore")
        if value is None:
            return ""
        return str(value)

    def _device_signature(self, device):
        path = self._normalize_path(device.get("path"))
        if path:
            return path

        return "|".join(
            [
                f"{int(device.get('vendor_id') or 0):04X}",
                f"{int(device.get('product_id') or 0):04X}",
                str(device.get("serial_number") or ""),
            ]
        )

    def _format_device(self, device):
        name = device.get("product_string") or "Unknown"
        vid = int(device.get("vendor_id") or 0)
        pid = int(device.get("product_id") or 0)
        path = self._normalize_path(device.get("path"))
        return f"{name} | VID:{vid:04X} PID:{pid:04X} | {path}"

    @staticmethod
    def _safe_read_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            return ""

    @staticmethod
    def _parse_hex_or_zero(raw: str) -> int:
        text = (raw or "").strip().lower()
        if text.startswith("0x"):
            text = text[2:]
        if not text:
            return 0
        try:
            return int(text, 16)
        except ValueError:
            return 0

    @staticmethod
    def _is_probable_keyboard_name(name: str) -> bool:
        lowered = (name or "").lower()
        blocked = ("mouse", "touchpad", "trackpoint", "joystick")
        return not any(token in lowered for token in blocked)

    @staticmethod
    def _is_keyboard_like_codes(codes: list[int], ecodes_mod) -> bool:
        if not codes:
            return False

        required_candidates = [ecodes_mod.KEY_1, ecodes_mod.KEY_A, ecodes_mod.KEY_ENTER, ecodes_mod.KEY_SPACE]
        available = set(int(code) for code in codes)
        return any(candidate in available for candidate in required_candidates)

    def _enumerate_sysfs_keyboards(self):
        root = Path("/sys/class/input")
        if not root.exists():
            return []

        devices = []
        for event_dir in sorted(root.glob("event*")):
            dev_dir = event_dir / "device"
            key_caps = self._safe_read_text(dev_dir / "capabilities" / "key")
            if not key_caps:
                continue

            has_any_key_bit = any(token.strip("0") for token in key_caps.split())
            if not has_any_key_bit:
                continue

            vendor_id = self._parse_hex_or_zero(self._safe_read_text(dev_dir / "id" / "vendor"))
            product_id = self._parse_hex_or_zero(self._safe_read_text(dev_dir / "id" / "product"))
            product_string = self._safe_read_text(dev_dir / "name") or "Unknown"
            serial_number = self._safe_read_text(dev_dir / "uniq")

            if not self._is_probable_keyboard_name(product_string):
                continue

            devices.append(
                {
                    "path": f"/dev/input/{event_dir.name}",
                    "product_string": product_string,
                    "vendor_id": vendor_id,
                    "product_id": product_id,
                    "serial_number": serial_number,
                }
            )

        return devices

    def _enumerate_linux_keyboards(self):
        permission_denied = False

        if evdev is not None:
            devices = []
            for path in evdev.list_devices():
                try:
                    dev = evdev.InputDevice(path)
                    caps = dev.capabilities()
                except PermissionError:
                    permission_denied = True
                    continue
                except Exception:
                    continue

                if evdev.ecodes.EV_KEY not in caps:
                    dev.close()
                    continue

                key_codes = caps.get(evdev.ecodes.EV_KEY, [])
                if not self._is_probable_keyboard_name(dev.name or ""):
                    dev.close()
                    continue
                if not self._is_keyboard_like_codes(key_codes, evdev.ecodes):
                    dev.close()
                    continue

                devices.append(
                    {
                        "path": dev.path,
                        "product_string": dev.name or "Unknown",
                        "vendor_id": int(dev.info.vendor),
                        "product_id": int(dev.info.product),
                        "serial_number": dev.uniq or "",
                    }
                )
                dev.close()

            if devices:
                return devices

        fallback = self._enumerate_sysfs_keyboards()
        if fallback and permission_denied:
            self._set_status("Limited /dev/input permissions detected. Using fallback scan mode.")
        return fallback

    def scan_baseline(self):
        proceed = messagebox.askokcancel(
            "Before scanning",
            "Please make sure the footswitch pedal is NOT plugged in yet.\n\n"
            "This will scan your current keyboard devices as baseline.",
        )
        if not proceed:
            return

        devices = self._enumerate_linux_keyboards()
        if not devices:
            self.baseline_signatures = set()
            self.baseline_listbox.delete(0, tk.END)
            self._set_status("No keyboard-capable devices found. Check permissions and try again.")
            return

        self.baseline_signatures = {self._device_signature(d) for d in devices}

        self.baseline_listbox.delete(0, tk.END)
        for idx, device in enumerate(devices, start=1):
            self.baseline_listbox.insert(tk.END, f"{idx}. {self._format_device(device)}")

        self._set_status(f"Baseline scan complete ({len(devices)} devices).")

        messagebox.showinfo(
            "Baseline complete",
            "Current keyboards were scanned successfully.\n\n"
            "Now plug in the footswitch pedal, then click 'Detect Newly Added Device'.",
        )

    def detect_new_devices(self):
        if not self.baseline_signatures:
            messagebox.showwarning("Baseline missing", "Run Step 1 (Scan Current Keyboards) first.")
            return

        self.detect_poll_cancelled = False
        self.detect_poll_deadline = time.time() + 30.0
        self._open_detect_popup()
        self._poll_new_device_detection()

    def _open_detect_popup(self):
        if self.detect_popup is not None:
            try:
                self.detect_popup.destroy()
            except Exception:
                pass

        popup = tk.Toplevel(self.root)
        popup.title("Detecting footswitch")
        popup.geometry("640x240")
        popup.resizable(False, False)
        popup.transient(self.root)
        popup.grab_set()

        bg = "#1f2937" if self.theme_var.get() == "Dark" else "#ffffff"
        fg = "#f8fafc" if self.theme_var.get() == "Dark" else "#0f172a"
        hint = "#cbd5e1" if self.theme_var.get() == "Dark" else "#475569"

        popup.configure(bg=bg)
        tk.Label(
            popup,
            text="Plug in the footswitch pedal now",
            font=(self.font_family_var.get(), 14, "bold"),
            bg=bg,
            fg=fg,
        ).pack(pady=(26, 8))
        tk.Label(
            popup,
            text="This window closes automatically once a newly plugged pedal device is detected.",
            font=(self.font_family_var.get(), 11),
            bg=bg,
            fg=hint,
            wraplength=590,
            justify="center",
        ).pack(pady=(0, 16))

        progress = ttk.Progressbar(popup, mode="indeterminate", length=360)
        progress.pack(pady=(0, 16))
        progress.start(10)

        def cancel_detection():
            self.detect_poll_cancelled = True
            try:
                progress.stop()
            except Exception:
                pass
            try:
                popup.destroy()
            except Exception:
                pass
            self.detect_popup = None
            self._set_status("Device detection cancelled.")

        ttk.Button(popup, text="Cancel", command=cancel_detection).pack()
        popup.protocol("WM_DELETE_WINDOW", cancel_detection)
        self.detect_popup = popup
        self._set_status("Waiting for newly plugged footswitch device...")

    def _close_detect_popup(self):
        if self.detect_popup is None:
            return
        try:
            self.detect_popup.destroy()
        except Exception:
            pass
        self.detect_popup = None

    def _poll_new_device_detection(self):
        if self.detect_poll_cancelled:
            return

        current_devices = self._enumerate_linux_keyboards()
        current_by_sig = {self._device_signature(d): d for d in current_devices}
        new_signatures = [sig for sig in current_by_sig if sig not in self.baseline_signatures]
        found_devices = [current_by_sig[sig] for sig in new_signatures]

        if found_devices:
            self.new_devices = found_devices
            values = [self._format_device(device) for device in self.new_devices]
            self.detected_combo["values"] = values
            self.detected_combo.current(0)
            self.assign_selected_device()
            self._close_detect_popup()
            self._set_status(f"Detected {len(self.new_devices)} new device(s). Confirm selected pedal.")
            return

        if time.time() >= self.detect_poll_deadline:
            self._close_detect_popup()
            self.detected_combo["values"] = []
            self.detected_combo.set("")
            self.selected_device_label_var.set("No new pedal found")
            self._set_status("No new device detected within timeout. Replug pedal and detect again.")
            return

        self.root.after(400, self._poll_new_device_detection)

    def assign_selected_device(self, _event=None):
        idx = self.detected_combo.current()
        if idx < 0 or idx >= len(self.new_devices):
            return

        selected = self.new_devices[idx]
        path = self._normalize_path(selected.get("path"))
        self.device_path_var.set(path)
        self.selected_device_label_var.set(path)

    @staticmethod
    def _single_presets():
        letters = [chr(c) for c in range(ord("A"), ord("Z") + 1)]
        return letters + ["Enter", "Space", "Tab", "Esc", "Backspace", "F1", "F2", "F3", "F4", "F5"]

    @staticmethod
    def _combo_presets():
        return ["Ctrl+C", "Ctrl+V", "Ctrl+X", "Ctrl+Z", "Alt+Tab", "Ctrl+S"]

    @staticmethod
    def _macro_presets():
        return ["hello", "sample text", "Line one\\nLine two"]

    def _output_presets(self, mode: str):
        mode = mode.strip().lower()
        if mode == "combo":
            return self._combo_presets()
        if mode == "macro":
            return self._macro_presets()
        return self._single_presets()

    def _rebuild_mapping_rows(self):
        old_rows = []
        for row in self.mapping_rows:
            old_rows.append(
                {
                    "trigger_code": row["trigger_code_var"].get(),
                    "trigger_label": row["trigger_label_var"].get(),
                    "mode": row["mode_var"].get(),
                    "output": row["output_var"].get(),
                }
            )

        self.mapping_rows = []

        for child in self.mapping_container.winfo_children():
            child.destroy()

        headers = ["#", "Pedal input", "Learn", "Output type", "Output value"]
        for index, header in enumerate(headers):
            ttk.Label(self.mapping_container, text=header).grid(row=0, column=index, padx=(0, 8), sticky="w")

        count = max(1, min(self.MAX_PEDALS, int(self.pedal_count_var.get())))

        for i in range(count):
            default_mode = "single"
            default_output = "C"
            default_trigger_label = "Not captured"
            default_trigger_code = ""

            if i < len(old_rows):
                default_mode = old_rows[i]["mode"] or default_mode
                default_output = old_rows[i]["output"] or default_output
                default_trigger_label = old_rows[i]["trigger_label"] or default_trigger_label
                default_trigger_code = old_rows[i]["trigger_code"] or default_trigger_code

            trigger_code_var = tk.StringVar(value=default_trigger_code)
            trigger_label_var = tk.StringVar(value=default_trigger_label)
            mode_var = tk.StringVar(value=default_mode)
            output_var = tk.StringVar(value=default_output)

            ttk.Label(self.mapping_container, text=str(i + 1)).grid(row=i + 1, column=0, padx=(0, 8), pady=5, sticky="w")
            ttk.Label(self.mapping_container, textvariable=trigger_label_var, width=20).grid(
                row=i + 1, column=1, padx=(0, 8), pady=5, sticky="w"
            )
            ttk.Button(
                self.mapping_container,
                text="Learn",
                command=lambda idx=i: self.learn_trigger(idx),
                width=10,
            ).grid(row=i + 1, column=2, padx=(0, 8), pady=5, sticky="w")

            mode_combo = ttk.Combobox(
                self.mapping_container,
                textvariable=mode_var,
                state="readonly",
                width=12,
                values=["single", "combo", "macro"],
            )
            mode_combo.grid(row=i + 1, column=3, padx=(0, 8), pady=5, sticky="ew")

            output_combo = ttk.Combobox(
                self.mapping_container,
                textvariable=output_var,
                state="normal",
                width=22,
                values=self._output_presets(default_mode),
            )
            output_combo.grid(row=i + 1, column=4, pady=5, sticky="ew")

            def on_mode_change(_event, local_mode_var=mode_var, local_output_combo=output_combo):
                mode = local_mode_var.get().strip().lower()
                local_output_combo["values"] = self._output_presets(mode)

            mode_combo.bind("<<ComboboxSelected>>", on_mode_change)

            self.mapping_rows.append(
                {
                    "trigger_code_var": trigger_code_var,
                    "trigger_label_var": trigger_label_var,
                    "mode_var": mode_var,
                    "output_var": output_var,
                }
            )

    def _build_learning_popup(self, row_index: int):
        popup = tk.Toplevel(self.root)
        popup.title("Learning pedal input")
        popup.geometry("480x220")
        popup.resizable(False, False)
        popup.transient(self.root)
        popup.grab_set()

        bg = "#2c3e50"
        popup.configure(bg=bg)

        tk.Label(
            popup,
            text=f"Pedal key {row_index + 1} is learning",
            font=("Arial", 15, "bold"),
            bg=bg,
            fg="white",
        ).pack(pady=(28, 10))

        tk.Label(
            popup,
            text="Press the pedal now...",
            font=("Arial", 13),
            bg=bg,
            fg="#d1ecff",
        ).pack()

        tk.Label(
            popup,
            text="This window closes automatically after a successful pedal press.",
            font=("Arial", 10),
            bg=bg,
            fg="#b8c7d9",
        ).pack(pady=(18, 0))

        popup.update_idletasks()
        return popup

    def learn_trigger(self, row_index: int):
        if evdev is None:
            messagebox.showerror("Missing dependency", "Install evdev with: pip install evdev")
            return

        if row_index < 0 or row_index >= len(self.mapping_rows):
            return

        device_path = self.device_path_var.get().strip()
        if not device_path:
            messagebox.showerror("Device required", "Select a pedal device before learning triggers.")
            return

        try:
            device = evdev.InputDevice(device_path)
        except Exception as exc:
            if self._is_permission_denied_error(exc):
                self._offer_admin_relaunch(f"Unable to open {device_path}:\n{exc}")
            messagebox.showerror("Device open failed", f"Unable to open {device_path}:\n{exc}")
            return

        popup = self._build_learning_popup(row_index)
        timeout_seconds = 8.0
        deadline = time.time() + timeout_seconds
        found_code = None

        self._set_status(f"Learning pedal {row_index + 1}. Press pedal now...")
        self.root.update_idletasks()

        try:
            device.grab()
            while time.time() < deadline:
                self.root.update()
                event = device.read_one()
                if event is None:
                    time.sleep(0.01)
                    continue

                if event.type == evdev.ecodes.EV_KEY and event.value == 1:
                    found_code = int(event.code)
                    break
        except PermissionError:
            self._offer_admin_relaunch(
                "Permission denied while reading/grabbing pedal device."
            )
            messagebox.showerror(
                "Permission denied",
                "Permission denied while reading/grabbing pedal device. Use sudo or configure input/uinput permissions.",
            )
            return
        except Exception as exc:
            messagebox.showerror("Learn failed", str(exc))
            return
        finally:
            try:
                popup.destroy()
            except Exception:
                pass
            try:
                device.ungrab()
            except Exception:
                pass
            device.close()

        if found_code is None:
            self._set_status(f"No pedal press detected for row {row_index + 1}.")
            messagebox.showwarning("Learn timeout", f"No pedal press detected for row {row_index + 1}.")
            return

        key_name = evdev.ecodes.KEY.get(found_code, f"KEY_{found_code}")
        row = self.mapping_rows[row_index]
        row["trigger_code_var"].set(str(found_code))
        row["trigger_label_var"].set(f"{key_name} ({found_code})")
        self._set_status(f"Captured pedal {row_index + 1}: {key_name} ({found_code}).")

    def _build_mappings_payload(self):
        payload = []
        used_triggers = set()

        for i, row in enumerate(self.mapping_rows, start=1):
            trigger_code_text = row["trigger_code_var"].get().strip()
            mode = row["mode_var"].get().strip().lower()
            output = row["output_var"].get().strip()

            if not trigger_code_text:
                raise ValueError(f"Row {i}: trigger not captured yet.")
            if not trigger_code_text.isdigit():
                raise ValueError(f"Row {i}: invalid trigger code.")
            trigger_code = int(trigger_code_text)
            if trigger_code in used_triggers:
                raise ValueError(f"Row {i}: duplicate trigger code {trigger_code}.")
            used_triggers.add(trigger_code)

            if mode not in {"single", "combo", "macro"}:
                raise ValueError(f"Row {i}: invalid output mode.")
            if not output:
                raise ValueError(f"Row {i}: output value cannot be empty.")

            payload.append({"trigger_code": trigger_code, "mode": mode, "output": output})

        return payload

    def _build_remapper_command(self, device_path: str, mappings_json: str):
        helper_names = ["footswitch-remapper", "footswitch_linux"]

        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            search_paths = []
            for helper_name in helper_names:
                search_paths.extend(
                    [
                        exe_dir / helper_name,
                        exe_dir.parent / helper_name,
                        exe_dir.parent / helper_name / helper_name,
                    ]
                )

            for helper_path in search_paths:
                if helper_path.exists():
                    return [str(helper_path), "--device", device_path, "--mappings-json", mappings_json]

        script_path = self.base_dir / "footswitch_linux.py"
        if script_path.exists():
            return [sys.executable, str(script_path), "--device", device_path, "--mappings-json", mappings_json]

        if getattr(sys, "frozen", False):
            return [sys.executable, "--run-remapper", "--device", device_path, "--mappings-json", mappings_json]

        raise FileNotFoundError("Could not find Linux remapper helper.")

    def run_footswitch(self):
        if os.name != "posix":
            messagebox.showinfo("Linux backend", "This build uses the Ubuntu evdev backend.")
            return

        device_path = self.device_path_var.get().strip()
        if not device_path:
            messagebox.showerror("Device required", "Select or enter a Linux event device path first.")
            return

        if os.geteuid() != 0 and not os.access(device_path, os.R_OK):
            self._offer_admin_relaunch(
                f"Cannot read selected device path:\n{device_path}"
            )
            return

        try:
            mappings_payload = self._build_mappings_payload()
            mappings_json = json.dumps(mappings_payload, ensure_ascii=False)
            cmd = self._build_remapper_command(device_path, mappings_json)
        except (ValueError, FileNotFoundError) as exc:
            messagebox.showerror("Invalid setup", str(exc))
            return

        try:
            self.last_process = subprocess.Popen(cmd, cwd=str(self.base_dir))
        except Exception as exc:
            messagebox.showerror("Failed to launch", f"Unable to run Linux remapper:\n{exc}")
            return

        self._set_status(f"Remapper started on {device_path} with {len(mappings_payload)} mapping(s).")
        self._show_running_widget()
        self.root.iconify()
        self.root.after(1000, self._monitor_running_process)

    def stop_footswitch(self):
        if not self.last_process or self.last_process.poll() is not None:
            self._set_status("No running footswitch process found in this app session.")
            self._close_running_widget(restore_main=True)
            return

        self.last_process.terminate()
        self._close_running_widget(restore_main=True)
        self._set_status("Footswitch process stopped.")

    def _show_running_widget(self):
        self._close_running_widget(restore_main=False)

        widget = tk.Toplevel(self.root)
        widget.withdraw()
        widget.resizable(False, False)
        widget.attributes("-topmost", True)
        widget.overrideredirect(True)

        theme = self.theme_var.get()
        if theme == "Dark":
            bg = "#1b2230"
            fg = "#eef3ff"
            hint = "#afbddb"
            btn_bg = "#2f70ff"
            btn_active = "#215ee0"
        else:
            bg = "#f8fafc"
            fg = "#0f172a"
            hint = "#475569"
            btn_bg = "#2563eb"
            btn_active = "#1d4ed8"

        widget.configure(bg=bg, highlightthickness=1, highlightbackground=btn_bg)
        padding = 14
        tk.Label(widget, text="Foot Pedal Configurator", font=(self.font_family_var.get(), 11, "bold"), bg=bg, fg=fg).pack(
            padx=padding, pady=(12, 4), anchor="w"
        )
        tk.Label(widget, text="Running in background", font=(self.font_family_var.get(), 10), bg=bg, fg=hint).pack(
            padx=padding, pady=(0, 10), anchor="w"
        )
        tk.Button(
            widget,
            text="Stop Running",
            command=self.stop_footswitch,
            bg=btn_bg,
            fg="white",
            activebackground=btn_active,
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            font=(self.font_family_var.get(), 10, "bold"),
            padx=16,
            pady=8,
        ).pack(padx=padding, pady=(0, 12), anchor="w")

        widget.update_idletasks()
        width = 280
        height = 120
        screen_w = widget.winfo_screenwidth()
        screen_h = widget.winfo_screenheight()
        x = max(0, screen_w - width - 16)
        y = max(0, screen_h - height - 56)
        widget.geometry(f"{width}x{height}+{x}+{y}")
        widget.deiconify()
        widget.protocol("WM_DELETE_WINDOW", lambda: None)

        self.running_widget = widget

    def _close_running_widget(self, restore_main: bool):
        if self.running_widget is not None:
            try:
                self.running_widget.destroy()
            except Exception:
                pass
            self.running_widget = None

        if restore_main:
            try:
                self.root.state("normal")
                self.root.deiconify()
                self.root.lift()
                self.root.attributes("-topmost", True)
                self.root.after(120, lambda: self.root.attributes("-topmost", False))
                self.root.focus_force()
            except Exception:
                pass

    def _monitor_running_process(self):
        if self.last_process and self.last_process.poll() is None:
            self.root.after(1000, self._monitor_running_process)
            return

        if self.running_widget is not None:
            self._close_running_widget(restore_main=True)
            self._set_status("Remapper process ended.")

    def _on_main_close(self):
        if self.last_process and self.last_process.poll() is None:
            self.root.iconify()
            self._set_status("Footswitch is running. Use 'Stop Running' from the floating control.")
            return
        self.root.destroy()


def _auto_elevate_startup() -> tuple[bool, str]:
    if os.name != "posix":
        return False, ""

    if os.geteuid() == 0:
        return False, ""

    pkexec_path = shutil.which("pkexec")
    if pkexec_path is None:
        return (
            False,
            "Auto-elevation is unavailable because 'pkexec' is not installed. "
            "Run with sudo -E or install polkit.",
        )

    if getattr(sys, "frozen", False):
        launch_cmd = [sys.executable, *sys.argv[1:]]
    else:
        launch_cmd = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]

    env_keys = ["DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"]
    env_args = [f"{key}={os.environ.get(key)}" for key in env_keys if os.environ.get(key)]

    pkexec_cmd = [pkexec_path]
    if env_args:
        pkexec_cmd.extend(["env", *env_args])
    pkexec_cmd.extend(launch_cmd)

    try:
        completed = subprocess.run(pkexec_cmd, cwd=str(Path(__file__).resolve().parent), check=False)
        if completed.returncode == 0:
            return True, ""
        return (
            False,
            "Admin authentication was cancelled or failed. "
            "The app will open normally; if Learn/Run fails, launch with sudo -E.",
        )
    except Exception as exc:
        return (
            False,
            f"Auto-elevation failed: {exc}. Run with sudo -E.",
        )


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--run-remapper":
        from footswitch_linux import main as remapper_main

        remapper_main(sys.argv[2:])
        return

    elevated, warning = _auto_elevate_startup()
    if elevated:
        return

    root = tk.Tk()
    app = FootPedalApp(root)
    if warning:
        messagebox.showwarning("Admin mode warning", warning)
    root.mainloop()


if __name__ == "__main__":
    main()
