#!/usr/bin/env python3
"""
Simple Tkinter UI wrapper for NovelMotion main.py
- Lets you pick chapter.txt, cards.json, outdir, BGM, and tweak common knobs
- Runs main.py in a background thread and streams logs to a console pane
- Supports presets (save/load JSON) for quick iteration

Requirements: Python stdlib only (tkinter comes with Python on macOS).
Place this file at the repo root next to main.py and run:
  python novelmotion_ui.py
"""
from __future__ import annotations

import json
import os
import queue
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import re

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_MAIN = REPO_ROOT / "main.py"
PRESET_PATH = REPO_ROOT / "ui_preset.json"

class NovelMotionUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("NovelMotion — GUI Runner")
        self.geometry("980x720")
        self.minsize(900, 640)
        self.proc: subprocess.Popen | None = None
        self.total_shots: int = 0

        self._build_widgets()
        self._wire_events()
        self._load_preset_if_exists()

    # ---------------- UI LAYOUT -----------------
    def _build_widgets(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)

        nb = ttk.Notebook(self)
        nb.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        self.tab_inputs = ttk.Frame(nb)
        self.tab_llm = ttk.Frame(nb)
        self.tab_sd = ttk.Frame(nb)
        self.tab_audio = ttk.Frame(nb)
        nb.add(self.tab_inputs, text="Inputs")
        nb.add(self.tab_llm, text="LLM / Style")
        nb.add(self.tab_sd, text="Stable Diffusion")
        nb.add(self.tab_audio, text="Audio & Render")

        # ---- Inputs tab ----
        f = self.tab_inputs
        for i in range(8): f.rowconfigure(i, weight=0)
        f.columnconfigure(1, weight=1)

        self.var_main = tk.StringVar(value=str(DEFAULT_MAIN))
        self._entry_with_browse(f, 0, "main.py:", self.var_main, filetypes=[("Python","*.py" )])

        self.var_chapter = tk.StringVar()
        self._entry_with_browse(f, 1, "chapter.txt:", self.var_chapter, filetypes=[("Text","*.txt")])

        self.var_outdir = tk.StringVar(value=str(REPO_ROOT/"outputs/gui_run"))
        self._entry_with_browse(f, 2, "outdir:", self.var_outdir, is_dir=True)

        self.var_orientation = tk.StringVar(value="landscape")
        ttk.Label(f, text="orientation:").grid(row=3, column=0, sticky="e", padx=6, pady=4)
        ttk.Combobox(f, textvariable=self.var_orientation, values=["landscape","portrait"], width=18, state="readonly").grid(row=3, column=1, sticky="w", padx=6, pady=4)

        self.var_seconds = tk.DoubleVar(value=5.0)
        self._labeled_spin(f, 4, "seconds per sentence:", self.var_seconds, 1.0, 15.0, 0.5)

        self.var_title = tk.StringVar(value="NovelMotion GUI Demo")
        self._labeled_entry(f, 5, "title:", self.var_title)

        # ---- LLM / Style tab ----
        f = self.tab_llm
        for i in range(10): f.rowconfigure(i, weight=0)
        f.columnconfigure(1, weight=1)

        self.var_prompt_engine = tk.StringVar(value="ai")
        ttk.Label(f, text="prompt engine:").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        ttk.Combobox(f, textvariable=self.var_prompt_engine, values=["ai","simple"], width=18, state="readonly").grid(row=0, column=1, sticky="w", padx=6, pady=4)

        self.var_llm_provider = tk.StringVar(value="gemini")
        ttk.Label(f, text="llm provider:").grid(row=1, column=0, sticky="e", padx=6, pady=4)
        ttk.Combobox(f, textvariable=self.var_llm_provider, values=["gemini","openai"], width=18, state="readonly").grid(row=1, column=1, sticky="w", padx=6, pady=4)

        self.var_llm_base = tk.StringVar(value="https://generativelanguage.googleapis.com")
        self._labeled_entry(f, 2, "llm base url:", self.var_llm_base)

        self.var_llm_model = tk.StringVar(value="gemini-1.5-flash")
        self._labeled_entry(f, 3, "llm model:", self.var_llm_model)

        self.var_llm_lang = tk.StringVar(value="en")
        ttk.Label(f, text="llm lang:").grid(row=4, column=0, sticky="e", padx=6, pady=4)
        ttk.Combobox(f, textvariable=self.var_llm_lang, values=["en","zh"], width=18, state="readonly").grid(row=4, column=1, sticky="w", padx=6, pady=4)

        self.var_llm_temp = tk.DoubleVar(value=0.3)
        self._labeled_spin(f, 5, "llm temperature:", self.var_llm_temp, 0.0, 1.0, 0.1)

        self.var_cards = tk.StringVar()
        self._entry_with_browse(f, 6, "character cards:", self.var_cards, filetypes=[("JSON","*.json")])

        self.var_style_pack = tk.StringVar(value="anime_high")
        ttk.Label(f, text="style pack:").grid(row=7, column=0, sticky="e", padx=6, pady=4)
        ttk.Combobox(f, textvariable=self.var_style_pack, values=["anime_high","cinematic","watercolor"], width=18, state="readonly").grid(row=7, column=1, sticky="w", padx=6, pady=4)

        self.var_global_style = tk.StringVar(value="ancient Chinese style, ink painting vibe, poetic atmosphere, hanfu details")
        self._labeled_entry(f, 8, "global style:", self.var_global_style)

        # ---- SD tab ----
        f = self.tab_sd
        for i in range(12): f.rowconfigure(i, weight=0)
        f.columnconfigure(1, weight=1)

        self.var_renderer = tk.StringVar(value="sd")
        ttk.Label(f, text="renderer:").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        ttk.Combobox(f, textvariable=self.var_renderer, values=["sd","placeholder"], width=18, state="readonly").grid(row=0, column=1, sticky="w", padx=6, pady=4)

        self.var_sd_model = tk.StringVar(value="https://huggingface.co/gsdf/Counterfeit-V3.0/resolve/main/Counterfeit-V3.0_fix_fp16.safetensors")
        self._labeled_entry(f, 1, "sd model id:", self.var_sd_model)
        ttk.Label(f, text="Tip: ckpt/safetensors use file path or URL. For Counterfeit-V3.0 use the *_fix_fp16.safetensors link.", foreground="#666").grid(row=1, column=2, sticky="w", padx=6, pady=4)

        self.var_sd_steps = tk.IntVar(value=12)
        self._labeled_spin(f, 2, "sd steps:", self.var_sd_steps, 1, 100, 1)

        self.var_sd_guidance = tk.DoubleVar(value=6.5)
        self._labeled_spin(f, 3, "sd guidance:", self.var_sd_guidance, 0.0, 20.0, 0.5)

        self.var_sd_seed = tk.IntVar(value=42)
        self._labeled_spin(f, 4, "sd seed:", self.var_sd_seed, -1, 999999, 1)

        self.var_sd_neg = tk.StringVar(value="blurry, deformed hands, extra fingers, worst quality, watermark, text")
        self._labeled_entry(f, 5, "sd negative:", self.var_sd_neg)

        self.var_sd_max_side = tk.IntVar(value=1024)
        self._labeled_spin(f, 6, "sd max side:", self.var_sd_max_side, 256, 2048, 64)

        self.var_sd_precision = tk.StringVar(value="fp32")
        ttk.Label(f, text="sd precision:").grid(row=7, column=0, sticky="e", padx=6, pady=4)
        ttk.Combobox(f, textvariable=self.var_sd_precision, values=["auto","fp16","fp32"], width=18, state="readonly").grid(row=7, column=1, sticky="w", padx=6, pady=4)

        self.var_fix_hands = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="fix hands/face", variable=self.var_fix_hands).grid(row=8, column=1, sticky="w", padx=6, pady=4)

        # ---- Audio & Render tab ----
        f = self.tab_audio
        for i in range(10): f.rowconfigure(i, weight=0)
        f.columnconfigure(1, weight=1)

        self.var_auto_render = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="auto render (ffmpeg)", variable=self.var_auto_render).grid(row=0, column=1, sticky="w", padx=6, pady=4)

        self.var_bgm = tk.StringVar()
        self._entry_with_browse(f, 1, "bgm file:", self.var_bgm, filetypes=[("Audio","*.mp3 *.wav")])

        self.var_bgm_gain = tk.DoubleVar(value=-16.0)
        self._labeled_spin(f, 2, "bgm gain (dB):", self.var_bgm_gain, -48.0, 0.0, 1.0)

        self.var_bgm_fade_in = tk.DoubleVar(value=1.0)
        self._labeled_spin(f, 3, "bgm fade in (s):", self.var_bgm_fade_in, 0.0, 10.0, 0.5)

        self.var_bgm_fade_out = tk.DoubleVar(value=2.0)
        self._labeled_spin(f, 4, "bgm fade out (s):", self.var_bgm_fade_out, 0.0, 10.0, 0.5)

        # ---- Bottom controls ----
        bar = ttk.Frame(self)
        bar.grid(row=1, column=0, sticky="ew", padx=8, pady=(0,8))
        bar.columnconfigure(0, weight=1)

        self.lbl_env = ttk.Label(bar, text=self._env_hint(), foreground="#666")
        self.lbl_env.grid(row=0, column=0, sticky="w")

        # Progress bar (indeterminate)
        self.prog = ttk.Progressbar(bar, mode="indeterminate", length=180)
        self.prog.grid(row=0, column=1, sticky="e", padx=(0,8))
        self.prog.configure(mode="indeterminate", maximum=100, value=0)

        btns = ttk.Frame(bar)
        btns.grid(row=0, column=2, sticky="e")
        ttk.Button(btns, text="Save preset", command=self.save_preset).grid(row=0, column=0, padx=4)
        ttk.Button(btns, text="Load preset", command=self.load_preset).grid(row=0, column=1, padx=4)
        self.btn_run = ttk.Button(btns, text="Run ▶", command=self.run)
        self.btn_run.grid(row=0, column=2, padx=8)
        self.btn_stop = ttk.Button(btns, text="Stop ■", command=self.stop, state="disabled")
        self.btn_stop.grid(row=0, column=3, padx=4)

        # Console removed

    # -------------- helpers ---------------
    def _prog_set_total(self, n: int):
        def _apply():
            try:
                self.prog.stop()
                self.prog.configure(mode="determinate", maximum=max(1, n))
                self.prog["value"] = 0
            except Exception:
                pass
        self.after(0, _apply)

    def _prog_set_value(self, v: int):
        def _apply():
            try:
                if str(self.prog.cget("mode")) != "determinate":
                    # switch if needed
                    self.prog.configure(mode="determinate")
                self.prog["value"] = max(0, v)
            except Exception:
                pass
        self.after(0, _apply)

    def _prog_reset(self):
        def _apply():
            try:
                self.prog.stop()
                self.prog.configure(mode="indeterminate", maximum=100)
                self.prog["value"] = 0
            except Exception:
                pass
        self.after(0, _apply)
    def _env_hint(self) -> str:
        g = os.getenv("GOOGLE_API_KEY")
        mark = "✅" if g else "⚠️"
        return f"Gemini GOOGLE_API_KEY: {mark} {'set' if g else 'not set'}"

    def _labeled_entry(self, parent, row, label, var):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=6, pady=4)

    def _labeled_spin(self, parent, row, label, var, frm, to, inc):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e", padx=6, pady=4)
        sp = ttk.Spinbox(parent, textvariable=var, from_=frm, to=to, increment=inc, width=10)
        sp.grid(row=row, column=1, sticky="w", padx=6, pady=4)

    def _entry_with_browse(self, parent, row, label, var, *, is_dir=False, filetypes=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e", padx=6, pady=4)
        ent = ttk.Entry(parent, textvariable=var)
        ent.grid(row=row, column=1, sticky="ew", padx=6, pady=4)
        def browse():
            if is_dir:
                p = filedialog.askdirectory(initialdir=REPO_ROOT)
            else:
                p = filedialog.askopenfilename(initialdir=REPO_ROOT, filetypes=filetypes or [("All","*.*")])
            if p:
                var.set(p)
        ttk.Button(parent, text="…", width=3, command=browse).grid(row=row, column=2, sticky="w", padx=4)

    # -------------- run logic ---------------
    def _normalize_sd_model_id(self, raw: str) -> str:
        v = (raw or "").strip()
        # Common aliases that are not valid diffusers repos
        aliases = {"gsdf/Counterfeit-V3.0", "ckpt/Counterfeit-V3.0", "Counterfeit-V3.0"}
        if v in aliases:
            return "https://huggingface.co/gsdf/Counterfeit-V3.0/resolve/main/Counterfeit-V3.0_fix_fp16.safetensors"
        return v
    def build_cmd(self) -> list[str]:
        main_path = Path(self.var_main.get()).expanduser().resolve()
        if not main_path.exists():
            raise FileNotFoundError(f"main.py not found: {main_path}")
        sd_model_id = self._normalize_sd_model_id(self.var_sd_model.get())
        args = [sys.executable, str(main_path),
                "--input", self.var_chapter.get(),
                "--outdir", self.var_outdir.get(),
                "--orientation", self.var_orientation.get(),
                "--seconds-per-sentence", str(self.var_seconds.get()),
                "--title", self.var_title.get(),
                "--prompt-engine", self.var_prompt_engine.get(),
                "--llm-provider", self.var_llm_provider.get(),
                "--llm-base-url", self.var_llm_base.get(),
                "--llm-model", self.var_llm_model.get(),
                "--llm-lang", self.var_llm_lang.get(),
                "--llm-temp", str(self.var_llm_temp.get()),
                "--renderer", self.var_renderer.get(),
                "--sd-model-id", sd_model_id,
                "--sd-steps", str(self.var_sd_steps.get()),
                "--sd-guidance", str(self.var_sd_guidance.get()),
                "--sd-seed", str(self.var_sd_seed.get()),
                "--sd-neg", self.var_sd_neg.get(),
                "--sd-max-side", str(self.var_sd_max_side.get()),
                "--sd-precision", self.var_sd_precision.get(),
               ]
        cards = self.var_cards.get().strip()
        if cards:
            args += ["--character-cards", cards]
        gstyle = self.var_global_style.get().strip()
        if gstyle:
            args += ["--style-pack", self.var_style_pack.get(), "--global-style", gstyle]
        if self.var_fix_hands.get():
            args += ["--fix-hands-face"]
        if self.var_auto_render.get():
            args += ["--auto-render"]
            bgm = self.var_bgm.get().strip()
            if bgm:
                args += ["--bgm", bgm,
                         "--bgm-gain", str(self.var_bgm_gain.get()),
                         "--bgm-fade-in", str(self.var_bgm_fade_in.get()),
                         "--bgm-fade-out", str(self.var_bgm_fade_out.get()),]
        return args

    def run(self):
        if self.proc and self.proc.poll() is None:
            messagebox.showinfo("Running", "A process is already running.")
            return
        try:
            cmd = self.build_cmd()
        except Exception as e:
            messagebox.showerror("Invalid inputs", str(e))
            return
        print("$ " + " ".join(shlex.quote(x) for x in cmd) + "\n", flush=True)
        self.prog.start(8)  # start indeterminate spinner
        self.btn_run.config(state="disabled")
        self.btn_stop.config(state="normal")
        t = threading.Thread(target=self._run_subprocess, args=(cmd,), daemon=True)
        t.start()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self._prog_reset()
        self.after(0, lambda: (self.btn_run.config(state="normal"), self.btn_stop.config(state="disabled")))

    def _run_subprocess(self, cmd: list[str]):
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, text=True)
            assert self.proc.stdout is not None
            for raw in self.proc.stdout:
                line = raw.rstrip("\n")
                # Parse progress signals
                if line.startswith("NM_TOTAL_SHOTS"):
                    # Format: NM_TOTAL_SHOTS N
                    try:
                        parts = line.split()
                        self.total_shots = int(parts[1])
                        self._prog_set_total(self.total_shots)
                    except Exception:
                        pass
                elif line.startswith("NM_TOTAL_UNITS"):
                    # Format: NM_TOTAL_UNITS N
                    try:
                        parts = line.split()
                        total_units = int(parts[1])
                        self._prog_set_total(total_units)
                    except Exception:
                        pass
                elif line.startswith("NM_UNITS"):
                    # Format: NM_UNITS a/b
                    try:
                        _, frac = line.split(maxsplit=1)
                        a_str, b_str = frac.strip().split("/")
                        a, b = int(a_str), int(b_str)
                        self._prog_set_total(b)
                        self._prog_set_value(a)
                    except Exception:
                        pass
                elif line.startswith("NM_PROGRESS"):
                    # Format: NM_PROGRESS a/b
                    try:
                        _, frac = line.split(maxsplit=1)
                        a_str, b_str = frac.strip().split("/")
                        a, b = int(a_str), int(b_str)
                        self.total_shots = b
                        self._prog_set_total(b)
                        self._prog_set_value(a)
                    except Exception:
                        pass
                # Always echo to outer terminal
                print(line)
            rc = self.proc.wait()
            print(f"\n[process exited with code {rc}]\n")
        except FileNotFoundError as e:
            print(f"ERROR: {e}")
        finally:
            self._prog_reset()
            self.after(0, lambda: (self.btn_run.config(state="normal"), self.btn_stop.config(state="disabled")))

    # Embedded console methods removed

    # -------------- presets ---------------
    def _load_preset_if_exists(self):
        """Load preset silently at startup if the preset file exists."""
        try:
            data = json.loads(PRESET_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return  # no preset, that's fine
        except json.JSONDecodeError:
            # preset exists but broken; inform user in the console area without blocking
            try:
                messagebox.showwarning("Preset", "Found ui_preset.json but it's invalid JSON. Ignoring it.")
            except Exception:
                pass
            return
        # Apply settings
        try:
            self._apply_preset_dict(data)
        except Exception:
            # Best-effort: ignore any unexpected keys/errors during early load
            try:
                messagebox.showwarning("Preset", "Preset loaded with some fields ignored due to errors.")
            except Exception:
                pass
    def save_preset(self):
        data = {
            "main": self.var_main.get(),
            "chapter": self.var_chapter.get(),
            "outdir": self.var_outdir.get(),
            "orientation": self.var_orientation.get(),
            "seconds": self.var_seconds.get(),
            "title": self.var_title.get(),
            "prompt_engine": self.var_prompt_engine.get(),
            "llm_provider": self.var_llm_provider.get(),
            "llm_base": self.var_llm_base.get(),
            "llm_model": self.var_llm_model.get(),
            "llm_lang": self.var_llm_lang.get(),
            "llm_temp": self.var_llm_temp.get(),
            "cards": self.var_cards.get(),
            "style_pack": self.var_style_pack.get(),
            "global_style": self.var_global_style.get(),
            "renderer": self.var_renderer.get(),
            "sd_model": self.var_sd_model.get(),
            "sd_steps": self.var_sd_steps.get(),
            "sd_guidance": self.var_sd_guidance.get(),
            "sd_seed": self.var_sd_seed.get(),
            "sd_neg": self.var_sd_neg.get(),
            "sd_max_side": self.var_sd_max_side.get(),
            "sd_precision": self.var_sd_precision.get(),
            "auto_render": self.var_auto_render.get(),
            "bgm": self.var_bgm.get(),
            "bgm_gain": self.var_bgm_gain.get(),
            "bgm_fade_in": self.var_bgm_fade_in.get(),
            "bgm_fade_out": self.var_bgm_fade_out.get(),
        }
        PRESET_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        messagebox.showinfo("Preset", f"Saved preset → {PRESET_PATH}")

    def load_preset(self):
        try:
            data = json.loads(PRESET_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            messagebox.showwarning("Preset", "No preset file found.")
            return
        except json.JSONDecodeError as e:
            messagebox.showerror("Preset", f"Invalid preset: {e}")
            return
        self._apply_preset_dict(data)

    def _apply_preset_dict(self, d: dict):
        self.var_main.set(d.get("main", self.var_main.get()))
        self.var_chapter.set(d.get("chapter", self.var_chapter.get()))
        self.var_outdir.set(d.get("outdir", self.var_outdir.get()))
        self.var_orientation.set(d.get("orientation", self.var_orientation.get()))
        self.var_seconds.set(float(d.get("seconds", self.var_seconds.get())))
        self.var_title.set(d.get("title", self.var_title.get()))
        self.var_prompt_engine.set(d.get("prompt_engine", self.var_prompt_engine.get()))
        self.var_llm_provider.set(d.get("llm_provider", self.var_llm_provider.get()))
        self.var_llm_base.set(d.get("llm_base", self.var_llm_base.get()))
        self.var_llm_model.set(d.get("llm_model", self.var_llm_model.get()))
        self.var_llm_lang.set(d.get("llm_lang", self.var_llm_lang.get()))
        self.var_llm_temp.set(float(d.get("llm_temp", self.var_llm_temp.get())))
        self.var_cards.set(d.get("cards", self.var_cards.get()))
        self.var_style_pack.set(d.get("style_pack", self.var_style_pack.get()))
        self.var_global_style.set(d.get("global_style", self.var_global_style.get()))
        self.var_renderer.set(d.get("renderer", self.var_renderer.get()))
        self.var_sd_model.set(d.get("sd_model", self.var_sd_model.get()))
        self.var_sd_steps.set(int(d.get("sd_steps", self.var_sd_steps.get())))
        self.var_sd_guidance.set(float(d.get("sd_guidance", self.var_sd_guidance.get())))
        self.var_sd_seed.set(int(d.get("sd_seed", self.var_sd_seed.get())))
        self.var_sd_neg.set(d.get("sd_neg", self.var_sd_neg.get()))
        self.var_sd_max_side.set(int(d.get("sd_max_side", self.var_sd_max_side.get())))
        self.var_sd_precision.set(d.get("sd_precision", self.var_sd_precision.get()))
        self.var_auto_render.set(bool(d.get("auto_render", self.var_auto_render.get())))
        self.var_bgm.set(d.get("bgm", self.var_bgm.get()))
        self.var_bgm_gain.set(float(d.get("bgm_gain", self.var_bgm_gain.get())))
        self.var_bgm_fade_in.set(float(d.get("bgm_fade_in", self.var_bgm_fade_in.get())))
        self.var_bgm_fade_out.set(float(d.get("bgm_fade_out", self.var_bgm_fade_out.get())))

    def _wire_events(self):
        self.bind("<Escape>", lambda e: self.stop())


def main():
    app = NovelMotionUI()
    app.mainloop()

if __name__ == "__main__":
    main()
