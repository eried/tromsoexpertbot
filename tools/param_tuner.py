"""
Aurora Parameter Tuner

Batch analysis tool for tuning AURORA_COLORS detection parameters.
Load a folder of photos, select which to analyze via checkboxes,
then run before/after analysis in parallel across up to 64 CPU cores.

Camera is auto-detected from filenames (e.g. 20260204-165743-Tromsdalen_004.jpg)
so each photo uses the correct detection_regions and noise_baseline.

Usage:
    python tools/param_tuner.py
"""

import copy
import io
import json
import os
import re
import sys
import tkinter as tk
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFont, ImageTk

import bot.detector as detector_module
from bot.config import AURORA_COLORS, MIN_AURORA_PIXEL_PERCENT, CAMERAS_CONFIG_FILE, get_cameras

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
MAX_WORKERS = min(64, os.cpu_count() or 4)

CHECK_ON = "\u2611"   # ☑
CHECK_OFF = "\u2610"  # ☐


def _sanitize_cam_name(name: str) -> str:
    """Same sanitization as bot/archiver.py line 159."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def _build_camera_lookup(cameras: list[dict]) -> dict[str, dict]:
    """Build a lookup: sanitized_name_lower -> camera config."""
    lookup = {}
    for cam in cameras:
        # Match by sanitized display name (what the archiver uses)
        safe = _sanitize_cam_name(cam.get("name", cam["id"]))
        lookup[safe.lower()] = cam
        # Also match by raw id
        lookup[cam["id"].lower()] = cam
    return lookup


def _match_camera(filename: str, cam_lookup: dict[str, dict]) -> dict | None:
    """Extract camera name from filename and match to camera config.
    Filename format: YYYYMMDD-HHMMSS-CameraName_NNN.jpg
                  or YYYYMMDD-HHMMSS-CameraName.jpg
    """
    stem = Path(filename).stem
    parts = stem.split("-", 2)
    if len(parts) < 3:
        return None
    name_part = parts[2]
    # Strip trailing _NNN (digits-only suffix)
    name_part = re.sub(r"_\d+$", "", name_part)
    return cam_lookup.get(name_part.lower())


def _analyze_worker(args):
    """Worker for parallel analysis. Top-level function required for pickling."""
    filepath_str, aurora_colors, threshold, blob_size, regions, noise_baseline = args
    old_c = detector_module.AURORA_COLORS
    old_t = detector_module.MIN_AURORA_PIXEL_PERCENT
    try:
        image_bytes = Path(filepath_str).read_bytes()
        detector_module.AURORA_COLORS = aurora_colors
        detector_module.MIN_AURORA_PIXEL_PERCENT = threshold
        return detector_module.analyze_image(
            image_bytes,
            regions=regions or None,
            min_blob_size=blob_size,
            noise_baseline=noise_baseline or None,
            detection_threshold=threshold,
            skip_darkness_check=True,
        )
    except Exception as e:
        return {"error": str(e)}
    finally:
        detector_module.AURORA_COLORS = old_c
        detector_module.MIN_AURORA_PIXEL_PERCENT = old_t


class ParamTuner:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.folder_path: str | None = None
        self.image_files: list[Path] = []
        self.image_bytes_cache: dict[str, bytes] = {}  # on-demand for preview
        self.before_results: dict[str, dict] = {}
        self.after_results: dict[str, dict] = {}
        self.checked: set[str] = set()

        self.original_aurora_colors = copy.deepcopy(AURORA_COLORS)
        self.original_threshold = MIN_AURORA_PIXEL_PERCENT

        self.cameras = get_cameras()
        self.cam_lookup = _build_camera_lookup(self.cameras)
        self.file_cameras: dict[str, dict | None] = {}  # filename -> matched camera

        # Noise baseline overrides: cam_id -> {green, red, violet}
        self.noise_overrides: dict[str, dict[str, float]] = {}
        self.original_noise: dict[str, dict[str, float]] = {}
        for cam in self.cameras:
            baseline = cam.get("noise_baseline", {})
            self.original_noise[cam["id"]] = {
                "green": baseline.get("green", 0.0),
                "red": baseline.get("red", 0.0),
                "violet": baseline.get("violet", 0.0),
            }
            self.noise_overrides[cam["id"]] = dict(self.original_noise[cam["id"]])

        self.sliders: dict = {}
        self.setup_ui()

    # -- UI Construction --

    def setup_ui(self):
        self.root.title("Aurora Parameter Tuner")
        self.root.geometry("1350x880")

        main = tk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # -- Toolbar --
        toolbar = tk.Frame(main)
        toolbar.pack(fill=tk.X, pady=(0, 6))
        tk.Button(toolbar, text="Select Folder...",
                  command=self.select_folder).pack(side=tk.LEFT)
        self.folder_label = tk.Label(
            toolbar, text="(no folder selected)", anchor="w", fg="gray")
        self.folder_label.pack(side=tk.LEFT, padx=8, fill=tk.X, expand=True)

        # -- Sliders Panel --
        sliders_frame = tk.LabelFrame(main, text="Detection Parameters")
        sliders_frame.pack(fill=tk.X, pady=(0, 6))

        self.sliders = {}
        for color_name, cfg in [
            ("green", self.original_aurora_colors["green"]),
            ("red", self.original_aurora_colors["red"]),
            ("violet", self.original_aurora_colors["violet"]),
        ]:
            self.sliders[color_name] = self._create_color_row(
                sliders_frame, color_name, cfg)

        # Global row
        global_frame = tk.Frame(sliders_frame)
        global_frame.pack(fill=tk.X, padx=6, pady=(2, 4))
        tk.Label(global_frame, text="Global:", width=7, anchor="e",
                 font=("Arial", 9, "bold")).pack(side=tk.LEFT)

        det_var = tk.DoubleVar(value=self.original_threshold)
        tk.Label(global_frame, text="Det. threshold %:").pack(
            side=tk.LEFT, padx=(12, 0))
        tk.Scale(global_frame, variable=det_var, from_=0.0, to=5.0,
                 orient=tk.HORIZONTAL, resolution=0.01,
                 length=160).pack(side=tk.LEFT)

        blob_var = tk.IntVar(value=50)
        tk.Label(global_frame, text="Min blob px:").pack(
            side=tk.LEFT, padx=(12, 0))
        tk.Scale(global_frame, variable=blob_var, from_=1, to=500,
                 orient=tk.HORIZONTAL, resolution=1,
                 length=160).pack(side=tk.LEFT)

        self.sliders["global"] = {
            "detection_threshold": det_var,
            "min_blob_size": blob_var,
        }

        # Reset button
        btn_row = tk.Frame(sliders_frame)
        btn_row.pack(fill=tk.X, padx=6, pady=(0, 6))
        tk.Button(btn_row, text="Reset to Current Config",
                  command=self.reset_sliders).pack(side=tk.LEFT)

        # -- Noise Baseline Panel --
        noise_frame = tk.LabelFrame(main, text="Noise Baseline (per camera)")
        noise_frame.pack(fill=tk.X, pady=(0, 6))

        cam_row = tk.Frame(noise_frame)
        cam_row.pack(fill=tk.X, padx=6, pady=(4, 2))

        tk.Label(cam_row, text="Camera:", font=("Arial", 9, "bold")).pack(
            side=tk.LEFT)
        self.noise_cam_var = tk.StringVar()
        cam_names = [cam["name"] for cam in self.cameras] if self.cameras else ["(none)"]
        self.noise_cam_combo = ttk.Combobox(
            cam_row, textvariable=self.noise_cam_var,
            values=cam_names, state="readonly", width=20)
        self.noise_cam_combo.pack(side=tk.LEFT, padx=(6, 0))
        if cam_names:
            self.noise_cam_combo.current(0)
        self.noise_cam_combo.bind("<<ComboboxSelected>>", self._on_noise_cam_change)

        slider_row = tk.Frame(noise_frame)
        slider_row.pack(fill=tk.X, padx=6, pady=(0, 4))

        self.noise_green_var = tk.DoubleVar(value=0.0)
        self.noise_red_var = tk.DoubleVar(value=0.0)
        self.noise_violet_var = tk.DoubleVar(value=0.0)

        for label, var, color in [
            ("Green", self.noise_green_var, "#228B22"),
            ("Red", self.noise_red_var, "#CC0000"),
            ("Violet", self.noise_violet_var, "#8B008B"),
        ]:
            tk.Label(slider_row, text=f"{label}:", fg=color,
                     font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=(12, 0))
            tk.Scale(slider_row, variable=var, from_=0.0, to=50.0,
                     orient=tk.HORIZONTAL, resolution=0.001,
                     length=200, command=self._on_noise_slider_change).pack(
                side=tk.LEFT)

        # Load initial values for first camera
        self._load_noise_for_selected_cam()

        # -- Action row --
        action_row = tk.Frame(main)
        action_row.pack(fill=tk.X, pady=(0, 4))

        tk.Button(action_row, text="Select All",
                  command=self.select_all, width=9).pack(side=tk.LEFT)
        tk.Button(action_row, text="Select None",
                  command=self.select_none, width=9).pack(
            side=tk.LEFT, padx=(4, 16))

        tk.Button(
            action_row, text="Analyze as Before",
            command=self.analyze_before,
            bg="#cce5ff", activebackground="#99caff",
        ).pack(side=tk.LEFT)
        tk.Button(
            action_row, text="Analyze as After",
            command=self.analyze_after,
            bg="#ffe0cc", activebackground="#ffbb99",
        ).pack(side=tk.LEFT, padx=(6, 0))

        self.hide_unchanged_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            action_row, text="Hide unchanged",
            variable=self.hide_unchanged_var, command=self.refresh_table,
        ).pack(side=tk.RIGHT)

        # -- Content: table + preview --
        content = tk.PanedWindow(main, orient=tk.HORIZONTAL, sashwidth=6)
        content.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        # Left: Treeview
        table_frame = tk.Frame(content)
        content.add(table_frame, width=650, minsize=350)

        columns = ("sel", "filename", "camera",
                   "before_det", "before_pct", "after_det", "after_pct")
        self.tree = ttk.Treeview(
            table_frame, columns=columns, show="headings",
            selectmode="extended")
        self.tree.heading("sel", text=CHECK_ON)
        self.tree.heading("filename", text="Filename")
        self.tree.heading("camera", text="Camera")
        self.tree.heading("before_det", text="Before")
        self.tree.heading("before_pct", text="Before W%")
        self.tree.heading("after_det", text="After")
        self.tree.heading("after_pct", text="After W%")

        self.tree.column("sel", width=32, minwidth=28,
                         anchor="center", stretch=False)
        self.tree.column("filename", width=200, minwidth=80)
        self.tree.column("camera", width=90, minwidth=50)
        self.tree.column("before_det", width=50, minwidth=35, anchor="center")
        self.tree.column("before_pct", width=75, minwidth=50, anchor="e")
        self.tree.column("after_det", width=50, minwidth=35, anchor="center")
        self.tree.column("after_pct", width=75, minwidth=50, anchor="e")

        vsb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL,
                            command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<<TreeviewSelect>>", self.on_row_select)

        self.tree.tag_configure("changed", background="#fff3cd")
        self.tree.tag_configure("unchanged", background="")

        # Right: Preview
        preview_frame = tk.Frame(content)
        content.add(preview_frame, minsize=300)
        self.preview_canvas = tk.Canvas(preview_frame, bg="black")
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)
        self.preview_photo = None

        # -- Status bar --
        status_bar = tk.Frame(main)
        status_bar.pack(fill=tk.X)
        self.status_label = tk.Label(
            status_bar, text="Select a folder to begin.", anchor="w")
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(
            status_bar, text="Write Parameters to Config",
            command=self.write_config,
            bg="#d4edda", activebackground="#a3d9a5",
        ).pack(side=tk.RIGHT)

    def _create_color_row(self, parent, color_name, cfg):
        row = tk.Frame(parent)
        row.pack(fill=tk.X, padx=6, pady=1)

        colors = {"green": "#228B22", "red": "#CC0000", "violet": "#8B008B"}
        tk.Label(row, text=f"{color_name.capitalize()}:", width=7, anchor="e",
                 font=("Arial", 9, "bold"),
                 fg=colors.get(color_name, "black")).pack(side=tk.LEFT)

        h_min, h_max = cfg["h_range"]
        v = {}

        def sl(label, lo, hi, val, res, length=110):
            tk.Label(row, text=label).pack(side=tk.LEFT, padx=(8, 0))
            if isinstance(val, float) and res < 1:
                var = tk.DoubleVar(value=val)
            else:
                var = tk.IntVar(value=int(val))
            tk.Scale(row, variable=var, from_=lo, to=hi,
                     orient=tk.HORIZONTAL, resolution=res,
                     length=length).pack(side=tk.LEFT)
            return var

        v["h_min"] = sl("H min", 0, 179, h_min, 1)
        v["h_max"] = sl("H max", 0, 179, h_max, 1)
        v["s_min"] = sl("S min", 0, 255, cfg["s_min"], 1)
        v["v_min"] = sl("V min", 0, 255, cfg["v_min"], 1)
        v["weight"] = sl("Weight", 0.0, 2.0, cfg["weight"], 0.001, 130)
        return v

    # -- Slider helpers --

    def build_aurora_colors_from_sliders(self):
        colors = {}
        for name in ["green", "red", "violet"]:
            s = self.sliders[name]
            colors[name] = {
                "h_range": (s["h_min"].get(), s["h_max"].get()),
                "s_min": s["s_min"].get(),
                "v_min": s["v_min"].get(),
                "weight": s["weight"].get(),
            }
        return colors

    def reset_sliders(self):
        for name in ["green", "red", "violet"]:
            cfg = self.original_aurora_colors[name]
            s = self.sliders[name]
            s["h_min"].set(cfg["h_range"][0])
            s["h_max"].set(cfg["h_range"][1])
            s["s_min"].set(cfg["s_min"])
            s["v_min"].set(cfg["v_min"])
            s["weight"].set(cfg["weight"])
        self.sliders["global"]["detection_threshold"].set(self.original_threshold)
        self.sliders["global"]["min_blob_size"].set(50)
        # Reset noise baselines
        for cam_id in self.noise_overrides:
            self.noise_overrides[cam_id] = dict(self.original_noise[cam_id])
        self._load_noise_for_selected_cam()

    # -- Noise baseline helpers --

    def _get_selected_cam_id(self) -> str | None:
        name = self.noise_cam_var.get()
        for cam in self.cameras:
            if cam["name"] == name:
                return cam["id"]
        return None

    def _load_noise_for_selected_cam(self):
        cam_id = self._get_selected_cam_id()
        if cam_id and cam_id in self.noise_overrides:
            nb = self.noise_overrides[cam_id]
            self.noise_green_var.set(nb["green"])
            self.noise_red_var.set(nb["red"])
            self.noise_violet_var.set(nb["violet"])
        else:
            self.noise_green_var.set(0.0)
            self.noise_red_var.set(0.0)
            self.noise_violet_var.set(0.0)

    def _on_noise_cam_change(self, event=None):
        self._load_noise_for_selected_cam()

    def _on_noise_slider_change(self, _value=None):
        cam_id = self._get_selected_cam_id()
        if cam_id:
            self.noise_overrides[cam_id] = {
                "green": self.noise_green_var.get(),
                "red": self.noise_red_var.get(),
                "violet": self.noise_violet_var.get(),
            }

    def _select_noise_cam_by_id(self, cam_id: str):
        """Switch the noise baseline dropdown to show the given camera."""
        for cam in self.cameras:
            if cam["id"] == cam_id:
                self.noise_cam_var.set(cam["name"])
                self._load_noise_for_selected_cam()
                return

    # -- Checkbox logic --

    def _on_tree_click(self, event):
        col = self.tree.identify_column(event.x)
        item = self.tree.identify_row(event.y)
        if item and col == "#1":
            # Toggle clicked item + all currently selected items
            selected = set(self.tree.selection())
            selected.add(item)
            new_state = item not in self.checked
            for iid in selected:
                if new_state:
                    self.checked.add(iid)
                else:
                    self.checked.discard(iid)
                vals = list(self.tree.item(iid, "values"))
                vals[0] = CHECK_ON if iid in self.checked else CHECK_OFF
                self.tree.item(iid, values=vals)
            self._update_status()
            return "break"

    def select_all(self):
        self.checked = {fp.name for fp in self.image_files}
        self.refresh_table()

    def select_none(self):
        self.checked.clear()
        self.refresh_table()

    # -- Folder selection --

    def select_folder(self):
        folder = filedialog.askdirectory(title="Select folder with aurora photos")
        if not folder:
            return

        self.folder_path = folder
        self.folder_label.config(text=folder, fg="black")

        self.image_files = sorted(
            f for f in Path(folder).iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
        )

        if not self.image_files:
            messagebox.showwarning(
                "No Images", "No image files found in the selected folder.")
            return

        self.image_bytes_cache.clear()
        self.before_results.clear()
        self.after_results.clear()
        self.checked = {fp.name for fp in self.image_files}

        # Auto-detect camera for each file
        self.file_cameras.clear()
        matched = 0
        for fp in self.image_files:
            cam = _match_camera(fp.name, self.cam_lookup)
            self.file_cameras[fp.name] = cam
            if cam:
                matched += 1

        self.refresh_table()
        self.status_label.config(
            text=f"Loaded {len(self.image_files)} images "
                 f"({matched} matched to cameras). Select and click Analyze.")

    # -- Parallel analysis --

    def _get_checked_filepaths(self):
        return [fp for fp in self.image_files if fp.name in self.checked]

    def _run_parallel(self, filepaths, aurora_colors, threshold,
                      blob_size, label):
        """Run analysis in parallel. Each file uses its auto-detected camera
        for regions and noise_baseline."""
        results = {}
        total = len(filepaths)
        if total == 0:
            return results

        n_workers = min(MAX_WORKERS, total)
        args_list = []
        for fp in filepaths:
            cam = self.file_cameras.get(fp.name)
            regions = (cam.get("detection_regions") or None) if cam else None
            # Use noise overrides from sliders instead of config values
            if cam and cam["id"] in self.noise_overrides:
                noise = self.noise_overrides[cam["id"]]
            else:
                noise = None
            args_list.append(
                (str(fp), aurora_colors, threshold, blob_size, regions, noise))

        self.status_label.config(
            text=f"{label}: 0/{total}  ({n_workers} workers)...")
        self.root.update()

        completed = 0
        update_every = max(1, total // 20)

        with ProcessPoolExecutor(max_workers=n_workers) as executor:
            future_map = {
                executor.submit(_analyze_worker, a): filepaths[i].name
                for i, a in enumerate(args_list)
            }
            for future in as_completed(future_map):
                fname = future_map[future]
                try:
                    results[fname] = future.result()
                except Exception as e:
                    results[fname] = {"error": str(e)}
                completed += 1
                if completed % update_every == 0 or completed == total:
                    self.status_label.config(
                        text=f"{label}: {completed}/{total}  "
                             f"({n_workers} workers)...")
                    self.root.update()

        return results

    def _analyze_selected(self, target: str):
        """Run analysis on checked photos using current slider params.
        target: 'before' or 'after' -- which column to fill."""
        selected = self._get_checked_filepaths()
        if not selected:
            messagebox.showwarning(
                "Nothing selected",
                "Check at least one photo to analyze.")
            return

        colors = self.build_aurora_colors_from_sliders()
        threshold = self.sliders["global"]["detection_threshold"].get()
        blob = self.sliders["global"]["min_blob_size"].get()
        label = "Before" if target == "before" else "After"
        results = self._run_parallel(
            selected, colors, threshold, blob, f"{label} analysis")

        if target == "before":
            self.before_results.update(results)
        else:
            self.after_results.update(results)

        self.refresh_table()

        if self.tree.selection():
            self.on_row_select(None)

    def analyze_before(self):
        self._analyze_selected("before")

    def analyze_after(self):
        self._analyze_selected("after")

    # -- Table --

    def refresh_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        hide = self.hide_unchanged_var.get()

        for filepath in self.image_files:
            fn = filepath.name
            before = self.before_results.get(fn)
            after = self.after_results.get(fn)

            b_det, b_pct = self._fmt(before)
            a_det, a_pct = self._fmt(after)

            cam = self.file_cameras.get(fn)
            cam_label = cam["name"] if cam else "--"

            changed = False
            if (before and after
                    and "error" not in before and "error" not in after):
                changed = (before.get("detected", False)
                           != after.get("detected", False))

            if hide and not changed:
                continue

            check = CHECK_ON if fn in self.checked else CHECK_OFF
            tag = "changed" if changed else "unchanged"
            self.tree.insert(
                "", tk.END, iid=fn,
                values=(check, fn, cam_label, b_det, b_pct, a_det, a_pct),
                tags=(tag,),
            )

        self._update_status()

    @staticmethod
    def _fmt(result):
        if result is None:
            return "--", "--"
        if "error" in result:
            return "ERR", ""
        det = "Yes" if result.get("detected", False) else "No"
        pct = f"{result.get('weighted_aurora_percent', 0):.3f}%"
        return det, pct

    def _update_status(self):
        total = len(self.image_files)
        n_sel = len(self.checked)
        n_bef = sum(1 for f in self.image_files
                    if f.name in self.before_results)
        n_aft = sum(1 for f in self.image_files
                    if f.name in self.after_results)
        self.status_label.config(
            text=f"Images: {total} | Selected: {n_sel} | "
                 f"Before: {n_bef} | After: {n_aft}")

    # -- Image Preview --

    def on_row_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return

        filename = sel[0]

        # Load bytes on demand
        if filename not in self.image_bytes_cache:
            fp = next((f for f in self.image_files if f.name == filename), None)
            if fp is None:
                return
            try:
                self.image_bytes_cache[filename] = fp.read_bytes()
            except Exception:
                return

        raw = self.image_bytes_cache[filename]
        before = self.before_results.get(filename, {})
        after = self.after_results.get(filename, {})

        # Auto-switch noise baseline dropdown to this photo's camera
        cam_sel = self.file_cameras.get(filename)
        if cam_sel:
            self._select_noise_cam_by_id(cam_sel["id"])

        image = Image.open(io.BytesIO(raw)).convert("RGB")

        self.preview_canvas.update_idletasks()
        cw = self.preview_canvas.winfo_width() or 500
        ch = self.preview_canvas.winfo_height() or 400

        ratio = image.width / image.height
        cratio = cw / ch
        if ratio > cratio:
            nw, nh = cw, int(cw / ratio)
        else:
            nh, nw = ch, int(ch * ratio)

        # Draw detection regions on the original-size image before resizing
        cam = self.file_cameras.get(filename)
        regions = (cam.get("detection_regions") or []) if cam else []
        if regions:
            draw_orig = ImageDraw.Draw(image)
            try:
                font_sm = ImageFont.truetype("arial.ttf", 11)
            except Exception:
                font_sm = ImageFont.load_default()
            for i, r in enumerate(regions):
                x1, y1, x2, y2 = r
                draw_orig.rectangle([x1, y1, x2, y2],
                                    outline="yellow", width=2)
                draw_orig.text((x1 + 3, y1 + 3), f"R{i+1}",
                               fill="yellow", font=font_sm)

        image = image.resize((nw, nh), Image.Resampling.LANCZOS)

        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype("arial.ttf", 14)
        except Exception:
            font = ImageFont.load_default()

        cam_name = cam["name"] if cam else "(full image)"
        b_text = self._label("BEFORE", before)
        a_text = self._label("AFTER", after)

        draw.rectangle([0, 0, nw, 60], fill=(0, 0, 0))
        draw.text((6, 2), f"Camera: {cam_name}", fill="yellow", font=font)
        draw.text((6, 20), b_text, fill="white", font=font)
        a_color = "lime" if after.get("detected") else "white"
        draw.text((6, 38), a_text, fill=a_color, font=font)

        self.preview_photo = ImageTk.PhotoImage(image)
        self.preview_canvas.delete("all")
        xo = (cw - nw) // 2
        yo = (ch - nh) // 2
        self.preview_canvas.create_image(
            xo, yo, anchor=tk.NW, image=self.preview_photo)

    @staticmethod
    def _label(prefix, result):
        if not result:
            return f"{prefix}: (not analyzed)"
        if "error" in result:
            return f"{prefix}: ERROR - {result['error']}"
        det = "AURORA" if result.get("detected") else "No aurora"
        wpct = result.get("weighted_aurora_percent", 0)
        return f"{prefix}: {det}  weighted={wpct:.3f}%"

    # -- Write Config --

    def write_config(self):
        colors = self.build_aurora_colors_from_sliders()
        threshold = self.sliders["global"]["detection_threshold"].get()

        summary = []
        for cname in ["green", "red", "violet"]:
            c, o = colors[cname], self.original_aurora_colors[cname]
            diffs = []
            if c["h_range"] != o["h_range"]:
                diffs.append(f"h_range {o['h_range']} -> {c['h_range']}")
            if c["s_min"] != o["s_min"]:
                diffs.append(f"s_min {o['s_min']} -> {c['s_min']}")
            if c["v_min"] != o["v_min"]:
                diffs.append(f"v_min {o['v_min']} -> {c['v_min']}")
            if abs(c["weight"] - o["weight"]) > 0.0001:
                diffs.append(f"weight {o['weight']} -> {c['weight']}")
            if diffs:
                summary.append(f"  {cname}: {', '.join(diffs)}")

        if abs(threshold - self.original_threshold) > 0.0001:
            summary.append(
                f"  threshold: {self.original_threshold} -> {threshold}")

        # Check noise baseline changes
        noise_changes = []
        for cam in self.cameras:
            cid = cam["id"]
            orig = self.original_noise.get(cid, {})
            curr = self.noise_overrides.get(cid, {})
            diffs = []
            for color in ["green", "red", "violet"]:
                ov = orig.get(color, 0.0)
                cv = curr.get(color, 0.0)
                if abs(cv - ov) > 0.0001:
                    diffs.append(f"{color} {ov} -> {cv}")
            if diffs:
                noise_changes.append(f"  {cam['name']}: {', '.join(diffs)}")

        if not summary and not noise_changes:
            messagebox.showinfo(
                "No Changes",
                "Slider values match current config. Nothing to write.")
            return

        msg_parts = []
        if summary:
            msg_parts.append(
                "Detection parameters (bot/config.py):\n" + "\n".join(summary))
        if noise_changes:
            msg_parts.append(
                "Noise baselines (cameras_config.json):\n"
                + "\n".join(noise_changes))

        msg = "The following changes will be written:\n\n" + "\n\n".join(msg_parts)
        if not messagebox.askyesno("Confirm Write", msg):
            return

        try:
            if summary:
                self._write_to_config_file(colors, threshold)
            if noise_changes:
                self._write_noise_to_cameras_config()
            saved_to = []
            if summary:
                saved_to.append("bot/config.py")
            if noise_changes:
                saved_to.append("cameras_config.json")
            messagebox.showinfo(
                "Saved",
                f"Parameters written to {' and '.join(saved_to)}.\n"
                "Restart the bot for changes to take effect.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to write config:\n{e}")

    def _write_to_config_file(self, colors, threshold):
        config_path = Path(__file__).resolve().parent.parent / "bot" / "config.py"
        lines = config_path.read_text(encoding="utf-8").splitlines(keepends=True)

        start_idx = end_idx = None
        brace_depth = 0

        for i, line in enumerate(lines):
            if start_idx is None:
                s = line.strip()
                if (s.startswith("AURORA_COLORS")
                        and "=" in s and "{" in s):
                    start_idx = i
                    brace_depth = line.count("{") - line.count("}")
                    if brace_depth <= 0:
                        end_idx = i
                        break
            else:
                brace_depth += line.count("{") - line.count("}")
                if brace_depth <= 0:
                    end_idx = i
                    break

        if start_idx is None or end_idx is None:
            raise ValueError(
                "Could not locate AURORA_COLORS block in config.py")

        replacement = self._format_aurora_colors_lines(colors)
        new_lines = lines[:start_idx] + replacement + lines[end_idx + 1:]

        for i, line in enumerate(new_lines):
            if (line.strip().startswith("MIN_AURORA_PIXEL_PERCENT")
                    and "=" in line):
                new_lines[i] = f"MIN_AURORA_PIXEL_PERCENT = {threshold}\n"
                break

        config_path.write_text("".join(new_lines), encoding="utf-8")

    def _write_noise_to_cameras_config(self):
        config_path = CAMERAS_CONFIG_FILE
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for cam_data in data.get("cameras", []):
            cid = cam_data.get("id")
            if cid in self.noise_overrides:
                cam_data["noise_baseline"] = {
                    "green": round(self.noise_overrides[cid]["green"], 3),
                    "red": round(self.noise_overrides[cid]["red"], 3),
                    "violet": round(self.noise_overrides[cid]["violet"], 3),
                }

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")

    @staticmethod
    def _format_aurora_colors_lines(colors):
        lines = ["AURORA_COLORS = {\n"]
        comments = {
            "green": "Primary aurora indicator",
            "red": "Often false positive from city lights",
            "violet": "Often sky/daylight false positive",
        }
        for name in ["green", "red", "violet"]:
            cfg = colors[name]
            h_min, h_max = cfg["h_range"]
            lines.append(f'    "{name}": {{\n')
            lines.append(f'        "h_range": ({h_min}, {h_max}),\n')
            lines.append(f'        "s_min": {cfg["s_min"]},\n')
            lines.append(f'        "v_min": {cfg["v_min"]},\n')
            cmt = comments.get(name, "")
            lines.append(f'        "weight": {cfg["weight"]},  # {cmt}\n')
            lines.append(f"    }},\n")
        lines.append("}\n")
        return lines


def main():
    print("Aurora Parameter Tuner")
    print("=" * 30)
    print(f"CPU cores available: {os.cpu_count()}, using up to {MAX_WORKERS} workers")

    root = tk.Tk()
    ParamTuner(root)
    root.mainloop()


if __name__ == "__main__":
    main()
