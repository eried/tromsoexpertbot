"""Telegram notification sender for aurora alerts."""

import io
import logging
import random
from typing import Any

from telegram import Bot, InputMediaPhoto
from telegram.error import TelegramError

from .config import TELEGRAM_BOT_TOKEN
from .subscribers import get_subscribers_for_alert

logger = logging.getLogger(__name__)

# --- Alert message pools ---

# First alert of the night: gentle heads-up
FIRST_ALERT_MESSAGES = [
    "First hint of aurora tonight! I'll keep you posted if it gets stronger.",
    "Aurora might be waking up! Stay tuned, I'll update you.",
    "Something's happening in the sky... could be the start of a show!",
    "Early signs of aurora detected. Keep your coat ready!",
    "Heads up! First aurora activity spotted tonight.",
    "The northern lights might be coming out to play. I'll let you know if it grows.",
    "Just picked up the first glow. Fingers crossed it gets brighter!",
    "Aurora is stirring! I'll send another update if it builds up.",
    "A little green is showing up in the sky. Could be a good night!",
    "First detection of the night! Too early to tell, but I'm watching.",
]

# Follow-up: aurora is getting stronger
STRONGER_MESSAGES = [
    "It's getting brighter! Might be worth heading outside.",
    "Aurora is picking up! Go take a look if you can.",
    "The lights are growing stronger. Check the sky!",
    "It's building up nicely! Good time to step outside.",
    "Getting more intense now. Don't miss this!",
    "The show is ramping up! Worth a peek outside.",
    "Stronger activity now! Grab your camera and go!",
    "Aurora is on the rise. Looks like it could be a good one!",
    "More green in the sky now! Time to go outside.",
    "It's lighting up more! The northern lights are putting on a show.",
]

# Follow-up: aurora is stable or fading
STABLE_MESSAGES = [
    "Aurora is still visible, holding steady.",
    "Still some activity up there. Worth a look if you haven't been out yet.",
    "The lights are still hanging around. No big changes.",
    "Aurora is keeping at it. Steady glow in the sky.",
    "Still going! Not stronger, but still there if you want to check.",
    "The show continues, though it hasn't changed much.",
    "Northern lights still active. Same intensity as before.",
    "Still detecting aurora. It's calm but present.",
    "Lights are lingering. Could still be worth a look outside.",
    "Aurora hasn't faded yet. Steady as she goes!",
]


def get_bot() -> Bot:
    """Get Telegram bot instance."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not configured")
    return Bot(token=TELEGRAM_BOT_TOKEN)


def _pick_message(alert_type: str) -> str:
    """Pick a random message based on alert type."""
    if alert_type == "first":
        return random.choice(FIRST_ALERT_MESSAGES)
    elif alert_type == "stronger":
        return random.choice(STRONGER_MESSAGES)
    else:
        return random.choice(STABLE_MESSAGES)


def format_alert_message(detections: list[dict], alert_type: str = "first") -> str:
    """
    Format the aurora alert message.

    Args:
        detections: List of detection results with camera info
        alert_type: "first", "stronger", or "stable"

    Returns:
        Formatted message string
    """
    camera_count = len(detections)
    camera_word = "camera" if camera_count == 1 else "cameras"

    lines = [
        f"Aurora detected on {camera_count} {camera_word}!",
        "",
    ]

    for detection in detections:
        camera = detection["camera"]
        result = detection["result"]

        name = camera.get("name", camera.get("id", "Unknown"))
        confidence = result.get("confidence", 0) * 100
        colors = result.get("colors_found", [])
        percent = result.get("total_aurora_percent", 0)

        color_str = ", ".join(colors) if colors else "unknown"
        lines.append(
            f"- {name}: {confidence:.0f}% confidence ({color_str}, {percent:.1f}% pixels)"
        )

    lines.extend([
        "",
        _pick_message(alert_type),
    ])

    return "\n".join(lines)


async def send_aurora_alert(detections: list[dict[str, Any]], alert_type: str = "first"):
    """
    Send aurora alert to subscribers based on their alert level.

    Args:
        detections: List of dicts with 'camera', 'result', and optionally 'image' keys
        alert_type: "first", "stronger", or "stable"
    """
    camera_count = len(detections)
    chat_ids = get_subscribers_for_alert(camera_count)

    if not chat_ids:
        logger.info(f"No subscribers to notify for {camera_count} camera detection")
        return

    bot = get_bot()
    message = format_alert_message(detections, alert_type)

    # Collect images from detections
    images = []
    for detection in detections:
        if "image" in detection and detection["image"]:
            camera_name = detection["camera"].get("name", "Camera")
            images.append((camera_name, detection["image"]))

    # Send to each subscriber
    success_count = 0
    for chat_id in chat_ids:
        try:
            if images:
                # Send images with caption
                if len(images) == 1:
                    # Single image
                    name, img_bytes = images[0]
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=io.BytesIO(img_bytes),
                        caption=message,
                    )
                else:
                    # Multiple images as media group
                    media = []
                    for i, (name, img_bytes) in enumerate(images[:10]):  # Max 10 photos
                        media.append(
                            InputMediaPhoto(
                                media=io.BytesIO(img_bytes),
                                caption=message if i == 0 else None,
                            )
                        )
                    await bot.send_media_group(chat_id=chat_id, media=media)
            else:
                # No images, just send text
                await bot.send_message(chat_id=chat_id, text=message)

            success_count += 1
            logger.debug(f"Alert sent to {chat_id}")

        except TelegramError as e:
            logger.error(f"Failed to send alert to {chat_id}: {e}")

    logger.info(f"Aurora alert sent to {success_count}/{len(chat_ids)} subscribers")


async def send_message_to_chat(chat_id: int, message: str) -> bool:
    """
    Send a message to a specific chat.

    Args:
        chat_id: Telegram chat ID
        message: Message text

    Returns:
        True if successful, False otherwise
    """
    try:
        bot = get_bot()
        await bot.send_message(chat_id=chat_id, text=message)
        return True
    except TelegramError as e:
        logger.error(f"Failed to send message to {chat_id}: {e}")
        return False


async def send_photo_to_chat(
    chat_id: int, photo_bytes: bytes, caption: str | None = None
) -> bool:
    """
    Send a photo to a specific chat.

    Args:
        chat_id: Telegram chat ID
        photo_bytes: Image data
        caption: Optional caption

    Returns:
        True if successful, False otherwise
    """
    try:
        bot = get_bot()
        await bot.send_photo(
            chat_id=chat_id,
            photo=io.BytesIO(photo_bytes),
            caption=caption,
        )
        return True
    except TelegramError as e:
        logger.error(f"Failed to send photo to {chat_id}: {e}")
        return False
