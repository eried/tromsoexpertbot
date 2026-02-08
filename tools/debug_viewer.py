"""
Debug Viewer Tool with Calibration

Fetches current images from all cameras, runs aurora detection,
and displays results with detection regions and statistics overlay.
Includes calibration feature to set noise baselines and detection thresholds.

Usage:
    python tools/debug_viewer.py
"""

import asyncio
import io
import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from PIL import Image, ImageDraw, ImageFont, ImageTk

from bot.config import get_cameras, AURORA_COLORS, MIN_AURORA_PIXEL_PERCENT, CAMERAS_CONFIG_FILE

# Get weights from config
def get_weights():
    return {color: cfg.get("weight", 1.0) for color, cfg in AURORA_COLORS.items()}
from bot.detector import analyze_image, calculate_min_blob_size
from bot.fetcher import fetch_camera_image
from bot.darkness import get_darkness_status


class DebugViewer:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cameras = []
        self.images = {}
        self.results = {}
        self.current_index = 0

        self.setup_ui()

    def setup_ui(self):
        self.root.title("Aurora Detection Debug Viewer & Calibrator")
        self.root.geometry("950x900")

        # Main frame
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Status frame at top
        status_frame = tk.LabelFrame(main_frame, text="System Status")
        status_frame.pack(fill=tk.X, pady=(0, 10))

        self.darkness_label = tk.Label(status_frame, text="Loading...", anchor="w")
        self.darkness_label.pack(fill=tk.X, padx=10, pady=5)

        # Camera selector
        selector_frame = tk.Frame(main_frame)
        selector_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(selector_frame, text="Camera:").pack(side=tk.LEFT)
        self.camera_combo = ttk.Combobox(selector_frame, state="readonly", width=40)
        self.camera_combo.pack(side=tk.LEFT, padx=5)
        self.camera_combo.bind("<<ComboboxSelected>>", self.on_camera_select)

        tk.Button(selector_frame, text="Prev", command=self.prev_camera, width=6).pack(side=tk.LEFT, padx=2)
        tk.Button(selector_frame, text="Next", command=self.next_camera, width=6).pack(side=tk.LEFT, padx=2)

        tk.Button(selector_frame, text="Refresh All", command=self.refresh_all).pack(side=tk.RIGHT)

        # Keyboard bindings for camera navigation
        self.root.bind("<Prior>", lambda e: self.prev_camera())  # Page Up
        self.root.bind("<Next>", lambda e: self.next_camera())   # Page Down

        # Image display
        self.canvas = tk.Canvas(main_frame, bg="black", width=600, height=350)
        self.canvas.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Results frame
        results_frame = tk.LabelFrame(main_frame, text="Detection Results")
        results_frame.pack(fill=tk.X)

        self.results_text = tk.Text(results_frame, height=10, font=("Consolas", 10))
        self.results_text.pack(fill=tk.X, padx=10, pady=10)

        # Calibration frame
        calib_frame = tk.LabelFrame(main_frame, text="Calibration (per camera)")
        calib_frame.pack(fill=tk.X, pady=(10, 0))

        # Row 1: Current readings display
        readings_frame = tk.Frame(calib_frame)
        readings_frame.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(readings_frame, text="Current adjusted readings:", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        self.current_readings_label = tk.Label(readings_frame, text="G: 0% R: 0% V: 0%", fg="blue")
        self.current_readings_label.pack(side=tk.LEFT, padx=10)

        # Row 2: Noise baseline settings
        baseline_frame = tk.Frame(calib_frame)
        baseline_frame.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(baseline_frame, text="Noise baseline:").pack(side=tk.LEFT)
        tk.Label(baseline_frame, text="G:").pack(side=tk.LEFT, padx=(10, 0))
        self.green_baseline_var = tk.StringVar(value="0")
        tk.Entry(baseline_frame, textvariable=self.green_baseline_var, width=6).pack(side=tk.LEFT)
        tk.Label(baseline_frame, text="R:").pack(side=tk.LEFT, padx=(5, 0))
        self.red_baseline_var = tk.StringVar(value="0")
        tk.Entry(baseline_frame, textvariable=self.red_baseline_var, width=6).pack(side=tk.LEFT)
        tk.Label(baseline_frame, text="V:").pack(side=tk.LEFT, padx=(5, 0))
        self.violet_baseline_var = tk.StringVar(value="0")
        tk.Entry(baseline_frame, textvariable=self.violet_baseline_var, width=6).pack(side=tk.LEFT)
        tk.Label(baseline_frame, text="%").pack(side=tk.LEFT)

        tk.Button(
            baseline_frame, text="Set from Current (No Aurora)",
            command=self.set_no_aurora, bg="#ffcccc"
        ).pack(side=tk.LEFT, padx=20)

        # Row 3: Detection threshold
        threshold_frame = tk.Frame(calib_frame)
        threshold_frame.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(threshold_frame, text="Detection threshold:").pack(side=tk.LEFT)
        self.threshold_var = tk.StringVar(value=str(MIN_AURORA_PIXEL_PERCENT))
        tk.Entry(threshold_frame, textvariable=self.threshold_var, width=6).pack(side=tk.LEFT, padx=5)
        tk.Label(threshold_frame, text="% (notify when adjusted value exceeds this)").pack(side=tk.LEFT)

        tk.Button(
            threshold_frame, text="Set from Current (Aurora Present)",
            command=self.set_aurora_present, bg="#ccffcc"
        ).pack(side=tk.LEFT, padx=20)

        # Row 4: Min blob size (auto or manual)
        blob_frame = tk.Frame(calib_frame)
        blob_frame.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(blob_frame, text="Min blob size:").pack(side=tk.LEFT)
        self.blob_auto_var = tk.BooleanVar(value=True)
        tk.Checkbutton(blob_frame, text="Auto", variable=self.blob_auto_var, command=self.toggle_blob_auto).pack(side=tk.LEFT)
        self.blob_size_var = tk.StringVar(value="auto")
        self.blob_size_entry = tk.Entry(blob_frame, textvariable=self.blob_size_var, width=8, state=tk.DISABLED)
        self.blob_size_entry.pack(side=tk.LEFT, padx=5)
        self.blob_auto_label = tk.Label(blob_frame, text="(calculated: --)")
        self.blob_auto_label.pack(side=tk.LEFT)

        # Row 5: Save button
        save_frame = tk.Frame(calib_frame)
        save_frame.pack(fill=tk.X, padx=10, pady=10)

        tk.Button(save_frame, text="Save This Camera", command=self.save_current_camera, width=20).pack(side=tk.LEFT)
        tk.Button(save_frame, text="Save All Cameras (No Aurora)", command=self.calibrate_all_no_aurora, width=25).pack(side=tk.LEFT, padx=10)
        tk.Button(save_frame, text="Reset to Defaults", command=self.reset_to_defaults, width=15).pack(side=tk.LEFT)

        # Summary frame
        summary_frame = tk.LabelFrame(main_frame, text="All Cameras Summary")
        summary_frame.pack(fill=tk.X, pady=(10, 0))

        self.summary_text = tk.Text(summary_frame, height=5, font=("Consolas", 10))
        self.summary_text.pack(fill=tk.X, padx=10, pady=10)

    def toggle_blob_auto(self):
        if self.blob_auto_var.get():
            self.blob_size_entry.config(state=tk.DISABLED)
            self.blob_size_var.set("auto")
        else:
            self.blob_size_entry.config(state=tk.NORMAL)
            # Set to calculated value as starting point
            if self.cameras and self.current_index < len(self.cameras):
                camera = self.cameras[self.current_index]
                regions = camera.get("detection_regions", [])
                calc = calculate_min_blob_size(regions)
                self.blob_size_var.set(str(calc))

    def update_darkness_status(self):
        status = get_darkness_status()
        dark_str = "YES - Monitoring active" if status["is_dark"] else "NO - Monitoring paused"
        self.darkness_label.config(
            text=f"Dark enough for aurora: {dark_str} | {status['reason']} | Period: {status['period']}"
        )

    def refresh_all(self):
        self.results_text.delete(1.0, tk.END)
        self.results_text.insert(tk.END, "Fetching camera images...\n")
        self.root.update()
        asyncio.run(self.fetch_and_analyze())

    async def fetch_and_analyze(self):
        self.cameras = get_cameras()
        self.images = {}
        self.results = {}

        self.update_darkness_status()

        camera_names = [f"{cam['name']} ({cam['id']})" for cam in self.cameras]
        self.camera_combo['values'] = camera_names

        for camera in self.cameras:
            cam_id = camera["id"]
            cam_name = camera["name"]

            self.results_text.delete(1.0, tk.END)
            self.results_text.insert(tk.END, f"Fetching {cam_name}...\n")
            self.root.update()

            image_bytes = await fetch_camera_image(camera)

            if image_bytes:
                self.images[cam_id] = image_bytes
                regions = camera.get("detection_regions", [])
                min_blob = camera.get("min_blob_size")  # None = auto
                noise_baseline = camera.get("noise_baseline")
                detection_threshold = camera.get("detection_threshold")

                result = analyze_image(image_bytes, regions, min_blob, noise_baseline, detection_threshold, skip_darkness_check=True)
                self.results[cam_id] = result
            else:
                self.results[cam_id] = {"error": "Failed to fetch image"}

        self.update_summary()

        if self.cameras:
            self.camera_combo.current(0)
            self.show_camera(0)

    def update_summary(self):
        self.summary_text.delete(1.0, tk.END)

        detected_count = 0
        lines = []

        for camera in self.cameras:
            cam_id = camera["id"]
            cam_name = camera["name"]
            result = self.results.get(cam_id, {})

            if "error" in result:
                lines.append(f"  {cam_name}: ERROR - {result['error']}")
            else:
                detected = result.get("detected", False)
                weighted_pct = result.get("weighted_aurora_percent", result.get("total_aurora_percent", 0))
                threshold = result.get("detection_threshold_used", MIN_AURORA_PIXEL_PERCENT)
                colors = result.get("colors_found", [])

                status = "DETECTED" if detected else "no"
                if detected:
                    detected_count += 1

                color_str = f" [{', '.join(colors)}]" if colors else ""
                lines.append(f"  {cam_name}: {status}{color_str} | weighted: {weighted_pct:.2f}% (threshold: {threshold}%)")

        would_alert = detected_count >= 2

        summary = f"Detections: {detected_count}/{len(self.cameras)} | Would alert: {'YES' if would_alert else 'NO'}\n"
        summary += "\n".join(lines)

        self.summary_text.insert(tk.END, summary)

    def on_camera_select(self, event):
        index = self.camera_combo.current()
        self.show_camera(index)

    def prev_camera(self):
        """Go to previous camera (loops around)."""
        if not self.cameras:
            return
        new_index = (self.current_index - 1) % len(self.cameras)
        self.camera_combo.current(new_index)
        self.show_camera(new_index)

    def next_camera(self):
        """Go to next camera (loops around)."""
        if not self.cameras:
            return
        new_index = (self.current_index + 1) % len(self.cameras)
        self.camera_combo.current(new_index)
        self.show_camera(new_index)

    def show_camera(self, index: int):
        if not self.cameras or index >= len(self.cameras):
            return

        self.current_index = index
        camera = self.cameras[index]
        cam_id = camera["id"]

        # Load saved calibration values
        noise_baseline = camera.get("noise_baseline") or {}
        detection_threshold = camera.get("detection_threshold")
        min_blob = camera.get("min_blob_size")

        self.green_baseline_var.set(str(noise_baseline.get("green", 0)))
        self.red_baseline_var.set(str(noise_baseline.get("red", 0)))
        self.violet_baseline_var.set(str(noise_baseline.get("violet", 0)))
        self.threshold_var.set(str(detection_threshold if detection_threshold is not None else MIN_AURORA_PIXEL_PERCENT))

        # Min blob size
        if min_blob is None:
            self.blob_auto_var.set(True)
            self.blob_size_entry.config(state=tk.DISABLED)
            self.blob_size_var.set("auto")
        else:
            self.blob_auto_var.set(False)
            self.blob_size_entry.config(state=tk.NORMAL)
            self.blob_size_var.set(str(min_blob))

        # Update auto-calculated blob size display
        regions = camera.get("detection_regions", [])
        calc_blob = calculate_min_blob_size(regions)
        self.blob_auto_label.config(text=f"(auto: {calc_blob}px)")

        result = self.results.get(cam_id, {})

        # Update current readings label
        if "error" not in result:
            adj = result.get("pixel_percentages", {})
            self.current_readings_label.config(
                text=f"G: {adj.get('green', 0):.2f}%  R: {adj.get('red', 0):.2f}%  V: {adj.get('violet', 0):.2f}%"
            )
        else:
            self.current_readings_label.config(text="Error loading image")

        # Update results text
        self.results_text.delete(1.0, tk.END)

        if "error" in result:
            self.results_text.insert(tk.END, f"Error: {result['error']}\n")
            self.canvas.delete("all")
            return

        # Format results
        blob_used = result.get("min_blob_size_used", "?")
        thresh_used = result.get("detection_threshold_used", MIN_AURORA_PIXEL_PERCENT)
        weighted_pct = result.get("weighted_aurora_percent", result.get("total_aurora_percent", 0))
        total_pct = result.get("total_aurora_percent", 0)

        # Explain detection logic
        detected = result.get("detected", False)
        colors_found = result.get("colors_found", [])
        detection_reason = ""
        if detected:
            if "green" in colors_found:
                detection_reason = "(green detected = primary indicator)"
            elif "red" in colors_found and "violet" not in colors_found:
                detection_reason = "(red-only: required 3x threshold)"
            else:
                detection_reason = f"(weighted {weighted_pct:.2f}% >= {thresh_used}%)"
        else:
            adj_pcts = result.get("pixel_percentages", {})
            if adj_pcts.get("red", 0) > 0 and adj_pcts.get("green", 0) == 0:
                detection_reason = "(red-only needs 3x threshold to avoid city light false positives)"

        weights = get_weights()
        weight_str = ", ".join(f"{c}={w}" for c, w in weights.items())

        lines = [
            f"Camera: {camera['name']} | Regions: {len(regions)} | Blob size: {blob_used}px | Threshold: {thresh_used}%",
            f"Detected: {'YES' if detected else 'NO'} {detection_reason}",
            f"Weighted: {weighted_pct:.3f}% ({weight_str}) | Raw total: {total_pct:.3f}%",
            "",
            "Color     | Weight | Raw %   | Adjusted % | Blobs | Largest | Status",
            "-" * 75,
        ]

        raw_pcts = result.get("raw_percentages", {})
        adj_pcts = result.get("pixel_percentages", {})
        blob_info = result.get("blob_info", {})

        for color in ["green", "red", "violet"]:
            raw = raw_pcts.get(color, 0)
            adj = adj_pcts.get(color, 0)
            info = blob_info.get(color, {})
            blob_count = info.get("blob_count", 0)
            largest = info.get("largest_blob", 0)
            weight = weights[color]
            status = "PASS" if adj >= thresh_used else ""

            lines.append(f"{color:9} | {weight:5.1f}x | {raw:6.3f}% | {adj:9.3f}% | {blob_count:5} | {largest:7}px | {status}")

        self.results_text.insert(tk.END, "\n".join(lines))

        # Display image
        image_bytes = self.images.get(cam_id)
        if image_bytes:
            self.display_image_with_overlay(image_bytes, camera, result)

    def display_image_with_overlay(self, image_bytes: bytes, camera: dict, result: dict):
        image = Image.open(io.BytesIO(image_bytes))
        draw = ImageDraw.Draw(image)

        try:
            font = ImageFont.truetype("arial.ttf", 14)
            font_small = ImageFont.truetype("arial.ttf", 11)
        except:
            font = ImageFont.load_default()
            font_small = font

        # Draw detection regions
        regions = camera.get("detection_regions", [])
        for i, region in enumerate(regions):
            x1, y1, x2, y2 = region
            color = "lime" if result.get("detected") else "yellow"
            draw.rectangle([x1, y1, x2, y2], outline=color, width=2)
            draw.text((x1 + 3, y1 + 3), f"R{i+1}", fill=color, font=font_small)

        # Status overlay
        detected = result.get("detected", False)
        weighted_pct = result.get("weighted_aurora_percent", result.get("total_aurora_percent", 0))
        thresh = result.get("detection_threshold_used", MIN_AURORA_PIXEL_PERCENT)

        status_text = f"{'AURORA!' if detected else 'No aurora'} | weighted: {weighted_pct:.2f}% (thresh: {thresh}%)"
        text_bbox = draw.textbbox((0, 0), status_text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        draw.rectangle([0, 0, text_width + 20, 25], fill=(0, 0, 0))
        draw.text((10, 5), status_text, fill="lime" if detected else "white", font=font)

        # Color readings at bottom with weights from config
        y_pos = image.height - 55
        adj_pcts = result.get("pixel_percentages", {})
        weights = get_weights()
        for color_name in ["green", "red", "violet"]:
            adj = adj_pcts.get(color_name, 0)
            weight = weights.get(color_name, 1.0)
            color_map = {"green": "lime", "red": "red", "violet": "magenta"}
            draw.text((10, y_pos), f"{color_name} ({weight}x): {adj:.2f}%", fill=color_map[color_name], font=font_small)
            y_pos += 15

        # Resize for display
        canvas_width = self.canvas.winfo_width() or 600
        canvas_height = self.canvas.winfo_height() or 350

        img_ratio = image.width / image.height
        canvas_ratio = canvas_width / canvas_height

        if img_ratio > canvas_ratio:
            new_width = canvas_width
            new_height = int(canvas_width / img_ratio)
        else:
            new_height = canvas_height
            new_width = int(canvas_height * img_ratio)

        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

        self.photo = ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        x_offset = (canvas_width - new_width) // 2
        y_offset = (canvas_height - new_height) // 2
        self.canvas.create_image(x_offset, y_offset, anchor=tk.NW, image=self.photo)

    def set_no_aurora(self):
        """Set current RAW readings as noise baseline (use when NO aurora visible)."""
        if not self.cameras or self.current_index >= len(self.cameras):
            return

        camera = self.cameras[self.current_index]
        result = self.results.get(camera["id"], {})

        if "error" in result:
            messagebox.showerror("Error", "No image data available")
            return

        # Use RAW percentages (before baseline subtraction) + 20% margin
        raw_pcts = result.get("raw_percentages", {})
        margin = 1.2

        self.green_baseline_var.set(f"{raw_pcts.get('green', 0) * margin:.3f}")
        self.red_baseline_var.set(f"{raw_pcts.get('red', 0) * margin:.3f}")
        self.violet_baseline_var.set(f"{raw_pcts.get('violet', 0) * margin:.3f}")

        messagebox.showinfo(
            "Baseline Set",
            f"Noise baseline set from current raw readings (+20% margin).\n\n"
            f"Green: {raw_pcts.get('green', 0):.3f}% -> {float(self.green_baseline_var.get()):.3f}%\n"
            f"Red: {raw_pcts.get('red', 0):.3f}% -> {float(self.red_baseline_var.get()):.3f}%\n"
            f"Violet: {raw_pcts.get('violet', 0):.3f}% -> {float(self.violet_baseline_var.get()):.3f}%\n\n"
            f"Click 'Save This Camera' to apply."
        )

    def set_aurora_present(self):
        """Set detection threshold based on current readings (use when aurora IS visible)."""
        if not self.cameras or self.current_index >= len(self.cameras):
            return

        camera = self.cameras[self.current_index]
        result = self.results.get(camera["id"], {})

        if "error" in result:
            messagebox.showerror("Error", "No image data available")
            return

        # Use current ADJUSTED percentages - set threshold to 50% of current value
        adj_pcts = result.get("pixel_percentages", {})
        max_adj = max(adj_pcts.values()) if adj_pcts else 0

        if max_adj < 0.1:
            messagebox.showwarning(
                "Low Readings",
                f"Current adjusted readings are very low ({max_adj:.3f}%).\n"
                f"Make sure aurora is actually visible and noise baseline is set correctly first."
            )
            return

        # Set threshold to 50% of current reading (so it triggers at half this intensity)
        suggested_threshold = max_adj * 0.5
        self.threshold_var.set(f"{suggested_threshold:.3f}")

        messagebox.showinfo(
            "Threshold Set",
            f"Detection threshold set to {suggested_threshold:.3f}%\n"
            f"(50% of current max reading: {max_adj:.3f}%)\n\n"
            f"This means the bot will notify you when aurora reaches\n"
            f"at least half of the current intensity.\n\n"
            f"Click 'Save This Camera' to apply."
        )

    def save_current_camera(self):
        """Save calibration settings for current camera."""
        if not self.cameras or self.current_index >= len(self.cameras):
            return

        camera = self.cameras[self.current_index]

        try:
            # Noise baseline
            camera["noise_baseline"] = {
                "green": float(self.green_baseline_var.get()),
                "red": float(self.red_baseline_var.get()),
                "violet": float(self.violet_baseline_var.get()),
            }

            # Detection threshold
            thresh = float(self.threshold_var.get())
            if thresh != MIN_AURORA_PIXEL_PERCENT:
                camera["detection_threshold"] = thresh
            elif "detection_threshold" in camera:
                del camera["detection_threshold"]  # Use global default

            # Min blob size
            if self.blob_auto_var.get():
                if "min_blob_size" in camera:
                    del camera["min_blob_size"]  # Use auto
            else:
                camera["min_blob_size"] = int(self.blob_size_var.get())

        except ValueError as e:
            messagebox.showerror("Error", f"Invalid value: {e}")
            return

        self._save_config()
        messagebox.showinfo("Saved", f"Settings saved for {camera['name']}")
        self.refresh_all()

    def calibrate_all_no_aurora(self):
        """Set noise baseline for ALL cameras from current readings."""
        if not self.cameras:
            return

        if not messagebox.askyesno(
            "Calibrate All",
            "This will set noise baselines for ALL cameras based on current readings.\n\n"
            "Make sure there is NO aurora visible right now!\n\n"
            "Continue?"
        ):
            return

        for camera in self.cameras:
            result = self.results.get(camera["id"], {})
            if "error" not in result:
                raw_pcts = result.get("raw_percentages", {})
                margin = 1.2
                camera["noise_baseline"] = {
                    "green": round(raw_pcts.get("green", 0) * margin, 3),
                    "red": round(raw_pcts.get("red", 0) * margin, 3),
                    "violet": round(raw_pcts.get("violet", 0) * margin, 3),
                }

        self._save_config()
        messagebox.showinfo("Calibrated", f"Noise baselines set for all {len(self.cameras)} cameras.")
        self.refresh_all()

    def reset_to_defaults(self):
        """Reset current camera to default settings."""
        if not self.cameras or self.current_index >= len(self.cameras):
            return

        camera = self.cameras[self.current_index]

        if "noise_baseline" in camera:
            del camera["noise_baseline"]
        if "detection_threshold" in camera:
            del camera["detection_threshold"]
        if "min_blob_size" in camera:
            del camera["min_blob_size"]

        self._save_config()
        messagebox.showinfo("Reset", f"Settings reset to defaults for {camera['name']}")
        self.refresh_all()

    def _save_config(self):
        config_data = {"cameras": self.cameras}
        with open(CAMERAS_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)


def main():
    print("Aurora Detection Debug Viewer & Calibrator")
    print("=" * 45)

    root = tk.Tk()
    app = DebugViewer(root)
    root.after(100, app.refresh_all)
    root.mainloop()


if __name__ == "__main__":
    main()
