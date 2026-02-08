"""Configuration loader for the Aurora Borealis Telegram Bot."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Telegram configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Admin chat ID (for secret commands) - set via environment variable
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))

# Aurora detection thresholds (HSV color space)
# H: 0-179 (in OpenCV/Pillow), S: 0-255, V: 0-255
# Green (557.7nm oxygen emission) is the most reliable aurora indicator
# Red can be confused with city lights, so it needs stricter thresholds
AURORA_COLORS = {
    "green": {
        "h_range": (35, 85),
        "s_min": 30,
        "v_min": 30,
        "weight": 1.0,  # Primary aurora indicator
    },
    "red": {
        "h_range": (0, 15),
        "s_min": 60,  # Higher saturation required (was 40)
        "v_min": 50,  # Higher value required (was 40)
        "weight": 0.15,  # Very low weight - often false positive from city lights
    },
    "violet": {
        "h_range": (130, 160),
        "s_min": 35,
        "v_min": 35,
        "weight": 0.044,  # Very low - often sky/daylight false positive
    },
}

# Color weights explanation:
# - Green (weight 1.0): Most dominant auroral emission (557.7nm oxygen)
# - Violet (weight 0.044): Minimal weight - often confused with daylight/sky
# - Red (weight 0.15): Often confused with artificial lights, heavily discounted

# Minimum percentage of pixels that must be aurora-colored
MIN_AURORA_PIXEL_PERCENT = 0.5

# Minimum number of cameras that must detect aurora for an alert
MIN_CAMERAS_FOR_ALERT = 2

# Tromsø coordinates for darkness calculation
TROMSO_LAT = 69.6496
TROMSO_LON = 18.9560

# Check interval in minutes
CHECK_INTERVAL_MINUTES = 2
CHECK_INTERVAL_DAYLIGHT_MINUTES = 15  # Less frequent during daylight (just for archiving)

# Data directory
DATA_DIR = Path(__file__).parent.parent / "data"
SUBSCRIBERS_FILE = DATA_DIR / "subscribers.json"
ALERT_STATE_FILE = DATA_DIR / "alert_state.json"

# Cameras config file
CAMERAS_CONFIG_FILE = Path(__file__).parent.parent / "cameras_config.json"

# Calibration mode - save images hourly for analysis
SAVE_CALIBRATION_IMAGES = os.getenv("SAVE_CALIBRATION_IMAGES", "false").lower() == "true"
CALIBRATION_DIR = DATA_DIR / "calibration_images"

# Photo archive settings
ARCHIVE_ENABLED = os.getenv("ARCHIVE_ENABLED", "true").lower() == "true"
ARCHIVE_DIR = DATA_DIR / "archive"
ARCHIVE_INTERVAL_MINUTES = 15  # Save new set if last save was > 15 min ago
ARCHIVE_MIN_FREE_MB = 100  # Cleanup old archives if free space < 100 MB

# Simple status file for ESP32 polling
STATUS_FILE = DATA_DIR / "status.txt"

# Pterodactyl API for remote status reading (optional)
PTERODACTYL_API_KEY = os.getenv("PTERODACTYL_API_KEY", "")
PTERODACTYL_PANEL_URL = os.getenv("PTERODACTYL_PANEL_URL", "")
PTERODACTYL_SERVER_ID = os.getenv("PTERODACTYL_SERVER_ID", "")


def load_cameras() -> list[dict]:
    """Load camera configuration from JSON file."""
    if not CAMERAS_CONFIG_FILE.exists():
        return []

    with open(CAMERAS_CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("cameras", [])


def get_cameras() -> list[dict]:
    """Get the list of configured cameras."""
    return load_cameras()
