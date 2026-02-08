"""Smart alert cooldown logic to prevent notification spam."""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ALERT_STATE_FILE, DATA_DIR

logger = logging.getLogger(__name__)

# Cooldown periods
COOLDOWN_INCREASING = timedelta(minutes=10)  # When aurora intensity increases
COOLDOWN_STABLE = timedelta(minutes=30)  # When aurora stable or decreasing


def _ensure_data_dir():
    """Ensure the data directory exists."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_alert_state() -> dict:
    """
    Load last alert state from JSON file.

    Returns:
        Dict with last_alert_time, last_detection_percent, cameras_detected
    """
    if not ALERT_STATE_FILE.exists():
        return {
            "last_alert_time": None,
            "last_detection_percent": 0.0,
            "cameras_detected": [],
        }

    try:
        with open(ALERT_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Parse ISO timestamp back to datetime
            if data.get("last_alert_time"):
                data["last_alert_time"] = datetime.fromisoformat(
                    data["last_alert_time"]
                )
            return data
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error loading alert state: {e}")
        return {
            "last_alert_time": None,
            "last_detection_percent": 0.0,
            "cameras_detected": [],
        }


def save_alert_state(
    detection_percent: float, cameras_detected: list[str]
):
    """
    Save current alert state to JSON file.

    Args:
        detection_percent: Average detection percentage across cameras
        cameras_detected: List of camera IDs that detected aurora
    """
    _ensure_data_dir()

    data = {
        "last_alert_time": datetime.now(timezone.utc).isoformat(),
        "last_detection_percent": detection_percent,
        "cameras_detected": cameras_detected,
    }

    try:
        with open(ALERT_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Saved alert state: {detection_percent}% from {cameras_detected}")
    except IOError as e:
        logger.error(f"Error saving alert state: {e}")


# How long since last alert before we consider it a "new night"
NEW_NIGHT_THRESHOLD = timedelta(hours=4)


def should_send_alert(new_detection_percent: float) -> tuple[bool, str]:
    """
    Determine if an alert should be sent based on cooldown logic.

    Logic:
    - 10 minutes cooldown if new detection is HIGHER (increasing activity)
    - 30 minutes cooldown if new detection is SAME or LOWER (stable/fading)

    Args:
        new_detection_percent: The detection percentage for the new detection

    Returns:
        Tuple of (should_send, alert_type) where alert_type is
        "first", "stronger", or "stable"
    """
    state = load_alert_state()

    last_alert_time = state.get("last_alert_time")
    last_detection_percent = state.get("last_detection_percent", 0.0)

    # First alert ever - always send
    if last_alert_time is None:
        return True, "first"

    now = datetime.now(timezone.utc)

    # Ensure timezone awareness
    if last_alert_time.tzinfo is None:
        last_alert_time = last_alert_time.replace(tzinfo=timezone.utc)

    time_since_last = now - last_alert_time

    # If it's been a long time, treat as first alert of a new night
    if time_since_last >= NEW_NIGHT_THRESHOLD:
        return True, "first"

    # Determine cooldown and alert type based on whether aurora is increasing
    if new_detection_percent > last_detection_percent:
        cooldown = COOLDOWN_INCREASING
        alert_type = "stronger"
        logger.debug(
            f"Aurora increasing ({last_detection_percent}% -> {new_detection_percent}%), "
            f"using {cooldown.total_seconds()/60}min cooldown"
        )
    else:
        cooldown = COOLDOWN_STABLE
        alert_type = "stable"
        logger.debug(
            f"Aurora stable/decreasing ({last_detection_percent}% -> {new_detection_percent}%), "
            f"using {cooldown.total_seconds()/60}min cooldown"
        )

    should_send = time_since_last >= cooldown

    if not should_send:
        remaining = cooldown - time_since_last
        logger.debug(f"In cooldown, {remaining.total_seconds()/60:.1f} min remaining")

    return should_send, alert_type


def get_cooldown_status() -> dict:
    """
    Get current cooldown status for status reporting.

    Returns:
        Dict with cooldown info
    """
    state = load_alert_state()

    last_alert_time = state.get("last_alert_time")
    last_detection_percent = state.get("last_detection_percent", 0.0)
    cameras_detected = state.get("cameras_detected", [])

    if last_alert_time is None:
        return {
            "last_alert": None,
            "last_detection_percent": 0.0,
            "cameras_detected": [],
            "in_cooldown": False,
            "cooldown_remaining": 0,
        }

    now = datetime.now(timezone.utc)
    if last_alert_time.tzinfo is None:
        last_alert_time = last_alert_time.replace(tzinfo=timezone.utc)

    time_since_last = now - last_alert_time

    # Assume stable cooldown for status display
    in_cooldown = time_since_last < COOLDOWN_STABLE
    remaining = max(0, (COOLDOWN_STABLE - time_since_last).total_seconds())

    return {
        "last_alert": last_alert_time.isoformat(),
        "last_detection_percent": last_detection_percent,
        "cameras_detected": cameras_detected,
        "in_cooldown": in_cooldown,
        "cooldown_remaining_minutes": round(remaining / 60, 1),
    }
