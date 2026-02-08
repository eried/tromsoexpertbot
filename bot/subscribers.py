"""File-based subscription management for Telegram users."""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .config import DATA_DIR, SUBSCRIBERS_FILE

logger = logging.getLogger(__name__)


def _ensure_data_dir():
    """Ensure the data directory exists."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write(filepath: Path, data: dict):
    """
    Write data to file atomically (write to temp, then rename).
    This prevents corruption if the process is interrupted.
    """
    _ensure_data_dir()

    # Write to temp file first
    fd, temp_path = tempfile.mkstemp(
        dir=filepath.parent, prefix=".tmp_", suffix=".json"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Atomic rename
        temp_path_obj = Path(temp_path)
        temp_path_obj.replace(filepath)

    except Exception:
        # Clean up temp file on error
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def load_subscribers() -> list[dict]:
    """
    Load subscribers from JSON file.

    Returns:
        List of subscriber dicts with chat_id and subscribed_at
    """
    if not SUBSCRIBERS_FILE.exists():
        return []

    try:
        with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("subscribers", [])
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error loading subscribers: {e}")
        return []


def save_subscribers(subscribers: list[dict]):
    """
    Save subscribers to JSON file atomically.

    Args:
        subscribers: List of subscriber dicts
    """
    data = {"subscribers": subscribers}
    try:
        _atomic_write(SUBSCRIBERS_FILE, data)
        logger.debug(f"Saved {len(subscribers)} subscribers")
    except Exception as e:
        logger.error(f"Error saving subscribers: {e}")
        raise


def add_subscriber(chat_id: int) -> bool:
    """
    Add a new subscriber.

    Args:
        chat_id: Telegram chat ID to add

    Returns:
        True if added, False if already subscribed
    """
    subscribers = load_subscribers()

    # Check if already subscribed
    for sub in subscribers:
        if sub["chat_id"] == chat_id:
            return False

    # Add new subscriber with default alert level (1 = low, 2 = medium, 3 = high)
    subscribers.append({
        "chat_id": chat_id,
        "subscribed_at": datetime.now(timezone.utc).isoformat(),
        "alert_level": 2,  # Default: medium (notify on 2+ cameras)
    })

    save_subscribers(subscribers)
    logger.info(f"Added subscriber: {chat_id}")
    return True


def get_subscriber_alert_level(chat_id: int) -> int:
    """
    Get a subscriber's alert level.

    Returns:
        1 = Low (any detection), 2 = Medium (2+ cameras), 3 = High (3+ cameras)
    """
    subscribers = load_subscribers()
    for sub in subscribers:
        if sub["chat_id"] == chat_id:
            return sub.get("alert_level", 2)
    return 2


def set_subscriber_alert_level(chat_id: int, level: int) -> bool:
    """
    Set a subscriber's alert level.

    Args:
        chat_id: Telegram chat ID
        level: 1 (low), 2 (medium), or 3 (high)

    Returns:
        True if updated, False if not found
    """
    if level not in (1, 2, 3):
        return False

    subscribers = load_subscribers()

    for sub in subscribers:
        if sub["chat_id"] == chat_id:
            sub["alert_level"] = level
            save_subscribers(subscribers)
            logger.info(f"Set alert level for {chat_id}: {level}")
            return True

    return False


def get_subscribers_for_alert(camera_count: int) -> list[int]:
    """
    Get chat IDs of subscribers who should receive an alert.

    Args:
        camera_count: Number of cameras that detected aurora

    Returns:
        List of chat IDs to notify
    """
    subscribers = load_subscribers()
    chat_ids = []

    for sub in subscribers:
        level = sub.get("alert_level", 2)
        # Level 1: any detection (1+ cameras)
        # Level 2: medium (2+ cameras)
        # Level 3: high (3+ cameras)
        min_cameras = level

        if camera_count >= min_cameras:
            chat_ids.append(sub["chat_id"])

    return chat_ids


def remove_subscriber(chat_id: int) -> bool:
    """
    Remove a subscriber.

    Args:
        chat_id: Telegram chat ID to remove

    Returns:
        True if removed, False if not found
    """
    subscribers = load_subscribers()
    original_count = len(subscribers)

    subscribers = [s for s in subscribers if s["chat_id"] != chat_id]

    if len(subscribers) < original_count:
        save_subscribers(subscribers)
        logger.info(f"Removed subscriber: {chat_id}")
        return True

    return False


def get_subscriber_chat_ids() -> list[int]:
    """
    Get list of all subscriber chat IDs.

    Returns:
        List of chat IDs
    """
    subscribers = load_subscribers()
    return [s["chat_id"] for s in subscribers]


def get_subscriber_count() -> int:
    """Get total number of subscribers."""
    return len(load_subscribers())


def is_subscribed(chat_id: int) -> bool:
    """Check if a chat ID is subscribed."""
    subscribers = load_subscribers()
    return any(s["chat_id"] == chat_id for s in subscribers)
