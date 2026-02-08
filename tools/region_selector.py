"""
Region Selector Tool

A GUI tool using tkinter to visually mark detection regions on webcam images.
These regions specify where to look for aurora colors in each camera image.

Usage:
    python tools/region_selector.py

Controls:
    - Click and drag to draw detection rectangles
    - Press 'N' for next camera
    - Press 'P' for previous camera
    - Press 'R' to reset current camera's regions
    - Press 'S' to save and exit
    - Press 'Q' or close window to quit without saving
"""

import asyncio
import io
import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from PIL import Image, ImageTk

from bot.config import CAMERAS_CONFIG_FILE
from bot.fetcher import fetch_camera_image

# Maximum display size for images
MAX_DISPLAY_WIDTH = 800
MAX_DISPLAY_HEIGHT = 600


class RegionSelector:
    def __init__(self, root: tk.Tk, cameras: list[dict], images: dict[str, bytes]):
        self.root = root
        self.cameras = cameras
        self.images = images  # Original image bytes
        self.pil_images = {}  # PIL Image objects (original size)
        self.current_index = 0

        # Store regions for each camera (in original image coordinates)
        self.regions: dict[str, list[list[int]]] = {
            cam["id"]: list(cam.get("detection_regions", []))
            for cam in cameras
        }

        # Drawing state
        self.start_x = 0
        self.start_y = 0
        self.rect_id = None

        # Scale factor for current image (display coords -> original coords)
        self.scale = 1.0
        self.offset_x = 0
        self.offset_y = 0

        self.setup_ui()
        self.load_camera(0)

    def setup_ui(self):
        self.root.title("Aurora Detection Region Selector")
        self.root.geometry(f"{MAX_DISPLAY_WIDTH + 40}x{MAX_DISPLAY_HEIGHT + 200}")

        # Main frame
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Info label
        self.info_label = tk.Label(
            main_frame,
            text="",
            font=("Arial", 12),
            anchor="w",
        )
        self.info_label.pack(fill=tk.X, padx=10, pady=5)

        # Canvas frame with fixed size
        canvas_frame = tk.Frame(main_frame, width=MAX_DISPLAY_WIDTH, height=MAX_DISPLAY_HEIGHT)
        canvas_frame.pack(padx=10, pady=5)
        canvas_frame.pack_propagate(False)

        # Canvas for image
        self.canvas = tk.Canvas(canvas_frame, bg="black", cursor="cross",
                                width=MAX_DISPLAY_WIDTH, height=MAX_DISPLAY_HEIGHT)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Bind mouse events
        self.canvas.bind("<Button-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)

        # Bind keyboard events
        self.root.bind("<n>", lambda e: self.next_camera())
        self.root.bind("<N>", lambda e: self.next_camera())
        self.root.bind("<p>", lambda e: self.prev_camera())
        self.root.bind("<P>", lambda e: self.prev_camera())
        self.root.bind("<r>", lambda e: self.reset_regions())
        self.root.bind("<R>", lambda e: self.reset_regions())
        self.root.bind("<s>", lambda e: self.save_and_exit())
        self.root.bind("<S>", lambda e: self.save_and_exit())
        self.root.bind("<q>", lambda e: self.quit_without_saving())
        self.root.bind("<Q>", lambda e: self.quit_without_saving())

        # Help label
        help_text = (
            "Click+drag: Draw region | N: Next | P: Previous | "
            "R: Reset | S: Save | Q: Quit"
        )
        help_label = tk.Label(main_frame, text=help_text, font=("Arial", 10))
        help_label.pack(fill=tk.X, padx=10, pady=5)

        # Button frame
        btn_frame = tk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        tk.Button(btn_frame, text="Previous (P)", command=self.prev_camera).pack(
            side=tk.LEFT, padx=5
        )
        tk.Button(btn_frame, text="Next (N)", command=self.next_camera).pack(
            side=tk.LEFT, padx=5
        )
        tk.Button(btn_frame, text="Reset (R)", command=self.reset_regions).pack(
            side=tk.LEFT, padx=5
        )
        tk.Button(btn_frame, text="Save (S)", command=self.save_and_exit).pack(
            side=tk.RIGHT, padx=5
        )

    def load_camera(self, index: int):
        """Load and display a camera image."""
        if not self.cameras:
            return

        self.current_index = index % len(self.cameras)
        camera = self.cameras[self.current_index]
        cam_id = camera["id"]
        cam_name = camera.get("name", cam_id)

        # Update info
        region_count = len(self.regions.get(cam_id, []))
        self.info_label.config(
            text=f"Camera {self.current_index + 1}/{len(self.cameras)}: "
            f"{cam_name} | Regions: {region_count}"
        )

        # Load image
        image_bytes = self.images.get(cam_id)
        if not image_bytes:
            self.canvas.delete("all")
            self.canvas.create_text(
                MAX_DISPLAY_WIDTH // 2, MAX_DISPLAY_HEIGHT // 2,
                text=f"Failed to load image for {cam_name}", fill="red"
            )
            self.scale = 1.0
            return

        # Get or create PIL image
        if cam_id not in self.pil_images:
            self.pil_images[cam_id] = Image.open(io.BytesIO(image_bytes))

        original_image = self.pil_images[cam_id]
        orig_width, orig_height = original_image.size

        # Calculate scale to fit in canvas
        scale_w = MAX_DISPLAY_WIDTH / orig_width
        scale_h = MAX_DISPLAY_HEIGHT / orig_height
        self.scale = min(scale_w, scale_h, 1.0)  # Don't upscale small images

        # Calculate display size
        display_width = int(orig_width * self.scale)
        display_height = int(orig_height * self.scale)

        # Calculate offset to center image
        self.offset_x = (MAX_DISPLAY_WIDTH - display_width) // 2
        self.offset_y = (MAX_DISPLAY_HEIGHT - display_height) // 2

        # Resize image for display
        if self.scale < 1.0:
            display_image = original_image.resize(
                (display_width, display_height),
                Image.Resampling.LANCZOS
            )
        else:
            display_image = original_image

        self.photo = ImageTk.PhotoImage(display_image)

        # Update info with image size
        self.info_label.config(
            text=f"Camera {self.current_index + 1}/{len(self.cameras)}: "
            f"{cam_name} | {orig_width}x{orig_height} | Regions: {region_count}"
        )

        self.canvas.delete("all")
        self.canvas.create_image(self.offset_x, self.offset_y, anchor=tk.NW, image=self.photo)

        # Draw existing regions
        self.draw_regions()

    def to_display_coords(self, x: int, y: int) -> tuple[int, int]:
        """Convert original image coordinates to display coordinates."""
        return (
            int(x * self.scale) + self.offset_x,
            int(y * self.scale) + self.offset_y
        )

    def to_original_coords(self, x: int, y: int) -> tuple[int, int]:
        """Convert display coordinates to original image coordinates."""
        return (
            int((x - self.offset_x) / self.scale),
            int((y - self.offset_y) / self.scale)
        )

    def draw_regions(self):
        """Draw all regions for current camera."""
        camera = self.cameras[self.current_index]
        cam_id = camera["id"]

        for i, region in enumerate(self.regions.get(cam_id, [])):
            x1, y1, x2, y2 = region
            # Convert to display coordinates
            dx1, dy1 = self.to_display_coords(x1, y1)
            dx2, dy2 = self.to_display_coords(x2, y2)

            self.canvas.create_rectangle(
                dx1, dy1, dx2, dy2,
                outline="green",
                width=2,
                tags="region",
            )
            self.canvas.create_text(
                dx1 + 5, dy1 + 5,
                text=str(i + 1),
                anchor=tk.NW,
                fill="green",
                font=("Arial", 12, "bold"),
                tags="region",
            )

    def on_mouse_down(self, event):
        """Handle mouse button press."""
        self.start_x = event.x
        self.start_y = event.y
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="yellow",
            width=2,
        )

    def on_mouse_drag(self, event):
        """Handle mouse drag."""
        if self.rect_id:
            self.canvas.coords(
                self.rect_id,
                self.start_x, self.start_y,
                event.x, event.y,
            )

    def on_mouse_up(self, event):
        """Handle mouse button release."""
        if self.rect_id:
            # Get final display coordinates
            dx1 = min(self.start_x, event.x)
            dy1 = min(self.start_y, event.y)
            dx2 = max(self.start_x, event.x)
            dy2 = max(self.start_y, event.y)

            # Delete temp rectangle
            self.canvas.delete(self.rect_id)
            self.rect_id = None

            # Convert to original image coordinates
            x1, y1 = self.to_original_coords(dx1, dy1)
            x2, y2 = self.to_original_coords(dx2, dy2)

            # Clamp to image bounds
            if self.cameras and self.current_index < len(self.cameras):
                cam_id = self.cameras[self.current_index]["id"]
                if cam_id in self.pil_images:
                    img = self.pil_images[cam_id]
                    x1 = max(0, min(x1, img.width))
                    y1 = max(0, min(y1, img.height))
                    x2 = max(0, min(x2, img.width))
                    y2 = max(0, min(y2, img.height))

            # Only save if region is large enough (in original coords)
            if (x2 - x1) > 5 and (y2 - y1) > 5:
                camera = self.cameras[self.current_index]
                cam_id = camera["id"]

                if cam_id not in self.regions:
                    self.regions[cam_id] = []

                self.regions[cam_id].append([x1, y1, x2, y2])

                # Redraw
                self.canvas.delete("region")
                self.draw_regions()

                # Update info
                self.info_label.config(
                    text=f"Camera {self.current_index + 1}/{len(self.cameras)}: "
                    f"{camera.get('name', cam_id)} | Regions: {len(self.regions[cam_id])}"
                )

    def next_camera(self):
        """Move to next camera."""
        self.load_camera(self.current_index + 1)

    def prev_camera(self):
        """Move to previous camera."""
        self.load_camera(self.current_index - 1)

    def reset_regions(self):
        """Reset regions for current camera."""
        camera = self.cameras[self.current_index]
        cam_id = camera["id"]
        self.regions[cam_id] = []
        self.load_camera(self.current_index)

    def save_and_exit(self):
        """Save regions to config file and exit."""
        # Update cameras with new regions
        for camera in self.cameras:
            cam_id = camera["id"]
            camera["detection_regions"] = self.regions.get(cam_id, [])

        # Save to file
        config_data = {"cameras": self.cameras}

        try:
            with open(CAMERAS_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)

            messagebox.showinfo(
                "Saved",
                f"Configuration saved to {CAMERAS_CONFIG_FILE}"
            )
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save: {e}")
            return

        self.root.destroy()

    def quit_without_saving(self):
        """Quit without saving."""
        if messagebox.askyesno("Quit", "Quit without saving changes?"):
            self.root.destroy()


async def fetch_all_images(cameras: list[dict]) -> dict[str, bytes]:
    """Fetch images from all cameras."""
    images = {}
    for camera in cameras:
        print(f"Fetching image from {camera.get('name', camera['id'])}...")
        image = await fetch_camera_image(camera)
        if image:
            images[camera["id"]] = image
            print(f"  OK ({len(image)} bytes)")
        else:
            print(f"  Failed to fetch image")
    return images


def load_cameras() -> list[dict]:
    """Load camera configuration."""
    if not CAMERAS_CONFIG_FILE.exists():
        print(f"Config file not found: {CAMERAS_CONFIG_FILE}")
        return []

    with open(CAMERAS_CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("cameras", [])


def main():
    """Main entry point for region selector tool."""
    print("Aurora Detection Region Selector")
    print("=" * 40)

    # Load cameras
    cameras = load_cameras()
    if not cameras:
        print("No cameras configured. Please check cameras_config.json")
        return

    print(f"Found {len(cameras)} cameras")

    # Fetch images
    print("\nFetching camera images...")
    images = asyncio.run(fetch_all_images(cameras))

    if not images:
        print("Failed to fetch any images. Check network connection.")
        return

    print(f"Successfully fetched {len(images)} images")

    # Start GUI
    print("\nStarting region selector GUI...")
    root = tk.Tk()
    app = RegionSelector(root, cameras, images)
    root.mainloop()


if __name__ == "__main__":
    main()
