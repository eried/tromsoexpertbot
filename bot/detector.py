"""Aurora color detection using HSV color space analysis."""

import io
import logging
from typing import Any

import numpy as np
from PIL import Image

from .config import AURORA_COLORS, MIN_AURORA_PIXEL_PERCENT
from .darkness import is_dark_enough

logger = logging.getLogger(__name__)

# Default minimum blob size as percentage of region (0.5%)
DEFAULT_MIN_BLOB_PERCENT = 0.5

# Maximum blob size to prevent huge images from having unrealistic thresholds
MAX_MIN_BLOB_SIZE = 500


def calculate_min_blob_size(regions: list[list[int]] | None, image_size: tuple[int, int] | None = None) -> int:
    """
    Calculate minimum blob size based on region size.
    Uses 0.5% of the smallest region's pixels, capped at MAX_MIN_BLOB_SIZE.
    """
    if not regions:
        # Full image - use default
        if image_size:
            total_pixels = image_size[0] * image_size[1]
            calculated = int(total_pixels * DEFAULT_MIN_BLOB_PERCENT / 100)
            return max(10, min(calculated, MAX_MIN_BLOB_SIZE))
        return 50  # Fallback

    # Find smallest region
    min_pixels = float('inf')
    for region in regions:
        x1, y1, x2, y2 = region
        pixels = (x2 - x1) * (y2 - y1)
        min_pixels = min(min_pixels, pixels)

    # 0.5% of region, minimum 10, maximum MAX_MIN_BLOB_SIZE
    calculated = int(min_pixels * DEFAULT_MIN_BLOB_PERCENT / 100)
    return max(10, min(calculated, MAX_MIN_BLOB_SIZE))


def rgb_to_hsv(rgb_array: np.ndarray) -> np.ndarray:
    """
    Convert RGB array to HSV color space.

    Args:
        rgb_array: numpy array of shape (H, W, 3) with RGB values 0-255

    Returns:
        numpy array of shape (H, W, 3) with HSV values
        H: 0-179, S: 0-255, V: 0-255
    """
    rgb_normalized = rgb_array.astype(np.float32) / 255.0

    r, g, b = rgb_normalized[:, :, 0], rgb_normalized[:, :, 1], rgb_normalized[:, :, 2]

    v = np.maximum(np.maximum(r, g), b)
    c = v - np.minimum(np.minimum(r, g), b)

    # Saturation (avoid divide-by-zero warning)
    s = np.divide(c, v, out=np.zeros_like(v), where=v != 0)

    # Hue calculation
    h = np.zeros_like(v)

    # When c != 0
    mask_r = (c != 0) & (v == r)
    mask_g = (c != 0) & (v == g)
    mask_b = (c != 0) & (v == b)

    h[mask_r] = 60 * (((g[mask_r] - b[mask_r]) / c[mask_r]) % 6)
    h[mask_g] = 60 * (((b[mask_g] - r[mask_g]) / c[mask_g]) + 2)
    h[mask_b] = 60 * (((r[mask_b] - g[mask_b]) / c[mask_b]) + 4)

    # Convert to OpenCV-style ranges: H: 0-179, S: 0-255, V: 0-255
    h = (h / 2).astype(np.uint8)  # 0-360 -> 0-180
    s = (s * 255).astype(np.uint8)
    v = (v * 255).astype(np.uint8)

    return np.stack([h, s, v], axis=-1)


def find_connected_components(mask: np.ndarray) -> tuple[np.ndarray, list[int]]:
    """
    Find connected components (blobs) in a binary mask.
    Uses simple flood-fill approach without scipy dependency.

    Args:
        mask: 2D boolean array

    Returns:
        Tuple of (labeled array, list of blob sizes)
    """
    labeled = np.zeros_like(mask, dtype=np.int32)
    blob_sizes = []
    current_label = 0

    height, width = mask.shape

    for y in range(height):
        for x in range(width):
            if mask[y, x] and labeled[y, x] == 0:
                # Found new blob, flood fill
                current_label += 1
                stack = [(y, x)]
                size = 0

                while stack:
                    cy, cx = stack.pop()
                    if (0 <= cy < height and 0 <= cx < width and
                        mask[cy, cx] and labeled[cy, cx] == 0):
                        labeled[cy, cx] = current_label
                        size += 1
                        # Add 4-connected neighbors
                        stack.extend([
                            (cy - 1, cx), (cy + 1, cx),
                            (cy, cx - 1), (cy, cx + 1)
                        ])

                blob_sizes.append(size)

    return labeled, blob_sizes


def get_aurora_mask(hsv_array: np.ndarray, color_config: dict) -> np.ndarray:
    """
    Get binary mask of pixels matching aurora color criteria.

    Args:
        hsv_array: HSV image array
        color_config: Dict with h_range, s_min, v_min

    Returns:
        Boolean mask array
    """
    h = hsv_array[:, :, 0]
    s = hsv_array[:, :, 1]
    v = hsv_array[:, :, 2]

    h_min, h_max = color_config["h_range"]
    s_min = color_config["s_min"]
    v_min = color_config["v_min"]

    # Handle hue wraparound for red colors
    if h_min <= h_max:
        h_mask = (h >= h_min) & (h <= h_max)
    else:
        h_mask = (h >= h_min) | (h <= h_max)

    s_mask = s >= s_min
    v_mask = v >= v_min

    return h_mask & s_mask & v_mask


def count_aurora_pixels(
    hsv_array: np.ndarray,
    color_config: dict,
    min_blob_size: int = 0
) -> dict:
    """
    Count pixels matching aurora color criteria, optionally filtering by blob size.

    Args:
        hsv_array: HSV image array
        color_config: Dict with h_range, s_min, v_min
        min_blob_size: Minimum contiguous pixels to count (0 = count all)

    Returns:
        Dict with total_pixels, blob_count, largest_blob, filtered_pixels
    """
    mask = get_aurora_mask(hsv_array, color_config)
    total_raw = np.sum(mask)

    if min_blob_size <= 1 or total_raw == 0:
        # No blob filtering needed
        return {
            "total_pixels": int(total_raw),
            "filtered_pixels": int(total_raw),
            "blob_count": 0,
            "largest_blob": int(total_raw),
            "blobs": []
        }

    # Find connected components
    labeled, blob_sizes = find_connected_components(mask)

    # Filter blobs by minimum size
    valid_blobs = [s for s in blob_sizes if s >= min_blob_size]
    filtered_pixels = sum(valid_blobs)

    return {
        "total_pixels": int(total_raw),
        "filtered_pixels": int(filtered_pixels),
        "blob_count": len(valid_blobs),
        "largest_blob": max(valid_blobs) if valid_blobs else 0,
        "blobs": sorted(valid_blobs, reverse=True)[:10]  # Top 10 blob sizes
    }


def analyze_region(
    hsv_array: np.ndarray,
    region: list[int] | None = None,
    min_blob_size: int = 50,
    noise_baseline: dict | None = None,
    detection_threshold: float = MIN_AURORA_PIXEL_PERCENT,
) -> dict[str, Any]:
    """
    Analyze a region of the image for aurora colors.

    Args:
        hsv_array: Full HSV image array
        region: [x1, y1, x2, y2] or None for full image
        min_blob_size: Minimum contiguous pixels to count as aurora
        noise_baseline: Dict of {color: baseline_percent} to subtract
        detection_threshold: Minimum % to consider as aurora detection

    Returns:
        Dict with color analysis results
    """
    if region:
        x1, y1, x2, y2 = region
        region_hsv = hsv_array[y1:y2, x1:x2]
    else:
        region_hsv = hsv_array

    total_pixels = region_hsv.shape[0] * region_hsv.shape[1]
    if total_pixels == 0:
        return {
            "colors_found": [],
            "pixel_percentages": {},
            "raw_percentages": {},
            "total_aurora_percent": 0,
            "blob_info": {},
        }

    noise_baseline = noise_baseline or {}
    pixel_percentages = {}
    raw_percentages = {}
    colors_found = []
    blob_info = {}

    for color_name, color_config in AURORA_COLORS.items():
        result = count_aurora_pixels(region_hsv, color_config, min_blob_size)

        # Use filtered pixels (only from valid blobs)
        raw_pct = (result["total_pixels"] / total_pixels) * 100
        filtered_pct = (result["filtered_pixels"] / total_pixels) * 100

        # Subtract noise baseline
        baseline = noise_baseline.get(color_name, 0)
        adjusted_pct = max(0, filtered_pct - baseline)

        raw_percentages[color_name] = round(raw_pct, 3)
        pixel_percentages[color_name] = round(adjusted_pct, 3)

        blob_info[color_name] = {
            "raw_pixels": result["total_pixels"],
            "filtered_pixels": result["filtered_pixels"],
            "blob_count": result["blob_count"],
            "largest_blob": result["largest_blob"],
            "top_blobs": result["blobs"][:5],
        }

        if adjusted_pct >= detection_threshold:
            colors_found.append(color_name)

    # Calculate weighted total (green has most weight, red least)
    weighted_total = 0.0
    for color, pct in pixel_percentages.items():
        weight = AURORA_COLORS.get(color, {}).get("weight", 1.0)
        weighted_total += pct * weight

    # Unweighted total for reference
    raw_total = sum(pixel_percentages.values())

    return {
        "colors_found": colors_found,
        "pixel_percentages": pixel_percentages,
        "raw_percentages": raw_percentages,
        "total_aurora_percent": round(raw_total, 3),
        "weighted_aurora_percent": round(weighted_total, 3),
        "blob_info": blob_info,
    }


def analyze_image(
    image_bytes: bytes,
    regions: list[list[int]] | None = None,
    min_blob_size: int | None = None,
    noise_baseline: dict | None = None,
    detection_threshold: float | None = None,
    skip_darkness_check: bool = False,
) -> dict:
    """
    Analyze image for aurora colors using HSV color space.

    Args:
        image_bytes: Raw image bytes
        regions: List of [x1, y1, x2, y2] detection regions, or empty/None for full image
        min_blob_size: Minimum contiguous pixels to count (None = auto-calculate from region size)
        noise_baseline: Dict of {color: baseline_percent} to subtract per color
        detection_threshold: Per-camera threshold to override global MIN_AURORA_PIXEL_PERCENT
        skip_darkness_check: If True, analyze even during daylight (for debugging)

    Returns:
        {
            "detected": bool,
            "confidence": float,  # 0.0 - 1.0
            "colors_found": ["green", "violet"],
            "pixel_percentages": {"green": 2.3, "red": 0.1, "violet": 0.8},
            "raw_percentages": {"green": 2.5, "red": 0.3, "violet": 0.9},
            "total_aurora_percent": float,
            "blob_info": {...},
            "min_blob_size_used": int,
            "detection_threshold_used": float
        }
    """
    # No aurora detection during daylight
    if not skip_darkness_check and not is_dark_enough():
        return {
            "detected": False,
            "confidence": 0.0,
            "colors_found": [],
            "pixel_percentages": {},
            "raw_percentages": {},
            "total_aurora_percent": 0,
            "weighted_aurora_percent": 0,
            "blob_info": {},
            "not_dark": True,
        }

    try:
        # Load image with Pillow
        image = Image.open(io.BytesIO(image_bytes))

        # Convert to RGB if necessary
        if image.mode != "RGB":
            image = image.convert("RGB")

        # Auto-calculate min_blob_size if not specified
        if min_blob_size is None:
            min_blob_size = calculate_min_blob_size(regions, (image.width, image.height))

        # Use per-camera threshold or global default
        threshold = detection_threshold if detection_threshold is not None else MIN_AURORA_PIXEL_PERCENT

        # Convert to numpy array
        rgb_array = np.array(image)

        # Convert to HSV
        hsv_array = rgb_to_hsv(rgb_array)

        # Analyze regions
        if regions:
            # Analyze each region and combine results
            all_colors = set()
            all_percentages = {"green": 0, "red": 0, "violet": 0}
            all_raw_percentages = {"green": 0, "red": 0, "violet": 0}
            all_blob_info = {}
            total_percent = 0
            weighted_percent = 0

            for region in regions:
                result = analyze_region(hsv_array, region, min_blob_size, noise_baseline, threshold)
                all_colors.update(result["colors_found"])
                for color, pct in result["pixel_percentages"].items():
                    all_percentages[color] = max(all_percentages[color], pct)
                for color, pct in result.get("raw_percentages", {}).items():
                    all_raw_percentages[color] = max(all_raw_percentages[color], pct)
                total_percent = max(total_percent, result["total_aurora_percent"])
                weighted_percent = max(weighted_percent, result.get("weighted_aurora_percent", total_percent))
                # Merge blob info (keep max values)
                for color, info in result.get("blob_info", {}).items():
                    if color not in all_blob_info:
                        all_blob_info[color] = info
                    else:
                        existing = all_blob_info[color]
                        all_blob_info[color] = {
                            "raw_pixels": max(existing["raw_pixels"], info["raw_pixels"]),
                            "filtered_pixels": max(existing["filtered_pixels"], info["filtered_pixels"]),
                            "blob_count": max(existing["blob_count"], info["blob_count"]),
                            "largest_blob": max(existing["largest_blob"], info["largest_blob"]),
                            "top_blobs": info["top_blobs"] if info["largest_blob"] > existing["largest_blob"] else existing["top_blobs"],
                        }

            colors_found = list(all_colors)
            pixel_percentages = all_percentages
            raw_percentages = all_raw_percentages
            blob_info = all_blob_info

        else:
            # Analyze full image
            result = analyze_region(hsv_array, None, min_blob_size, noise_baseline, threshold)
            colors_found = result["colors_found"]
            pixel_percentages = result["pixel_percentages"]
            raw_percentages = result.get("raw_percentages", pixel_percentages)
            total_percent = result["total_aurora_percent"]
            weighted_percent = result.get("weighted_aurora_percent", total_percent)
            blob_info = result.get("blob_info", {})

        # Determine if aurora detected
        has_green = "green" in colors_found

        # Aurora is ONLY detected if green is present
        # Green (557.7nm oxygen emission) is the primary reliable aurora indicator
        # Red and violet alone are too unreliable (sky, city lights, clouds)
        detected = has_green

        # Calculate confidence based on weighted percentage (green-heavy)
        # Higher percentage = higher confidence, max at ~5%
        confidence = min(1.0, weighted_percent / 5.0)

        return {
            "detected": detected,
            "confidence": round(confidence, 2),
            "colors_found": colors_found,
            "pixel_percentages": pixel_percentages,
            "raw_percentages": raw_percentages,
            "total_aurora_percent": total_percent,
            "weighted_aurora_percent": weighted_percent,
            "blob_info": blob_info,
            "min_blob_size_used": min_blob_size,
            "detection_threshold_used": threshold,
        }

    except Exception as e:
        logger.error(f"Error analyzing image: {e}")
        return {
            "detected": False,
            "confidence": 0.0,
            "colors_found": [],
            "pixel_percentages": {},
            "raw_percentages": {},
            "total_aurora_percent": 0,
            "weighted_aurora_percent": 0,
            "blob_info": {},
            "error": str(e),
        }
