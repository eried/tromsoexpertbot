"""Main bot module with Telegram commands and aurora check scheduler."""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import (
    ADMIN_CHAT_ID,
    ARCHIVE_DIR,
    ARCHIVE_ENABLED,
    ARCHIVE_INTERVAL_MINUTES,
    ARCHIVE_MIN_FREE_MB,
    CALIBRATION_DIR,
    CHECK_INTERVAL_MINUTES,
    CHECK_INTERVAL_DAYLIGHT_MINUTES,
    MIN_CAMERAS_FOR_ALERT,
    SAVE_CALIBRATION_IMAGES,
    STATUS_FILE,
    TELEGRAM_BOT_TOKEN,
    get_cameras,
)
from .archiver import save_archive_images
from .cooldown import get_cooldown_status, save_alert_state, should_send_alert
from .darkness import get_darkness_status, is_dark_enough
from .detector import analyze_image
from .status_writer import write_status
from .fetcher import fetch_camera_image
from .notifier import send_aurora_alert
from .subscribers import (
    add_subscriber,
    get_subscriber_chat_ids,
    get_subscriber_count,
    get_subscriber_alert_level,
    set_subscriber_alert_level,
    is_subscribed,
    remove_subscriber,
)

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Track last calibration save time
last_calibration_save: datetime | None = None


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command - subscribe to alerts."""
    chat_id = update.effective_chat.id

    if add_subscriber(chat_id):
        await update.message.reply_text(
            "Welcome! You are now subscribed to Aurora Borealis alerts for Tromsø.\n\n"
            "Your alert level is set to Medium (2+ cameras).\n"
            "Use /level to adjust your sensitivity.\n\n"
            "Commands:\n"
            "/status - Check current status\n"
            "/level - Set alert sensitivity\n"
            "/cameras - List monitored cameras\n"
            "/stop - Unsubscribe from alerts"
        )
    else:
        await update.message.reply_text(
            "You are already subscribed to Aurora Borealis alerts.\n\n"
            "Use /level to adjust your sensitivity.\n"
            "Use /stop to unsubscribe."
        )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stop command - unsubscribe from alerts."""
    chat_id = update.effective_chat.id

    if remove_subscriber(chat_id):
        await update.message.reply_text(
            "You have been unsubscribed from Aurora Borealis alerts.\n\n"
            "Use /start to subscribe again."
        )
    else:
        await update.message.reply_text(
            "You are not currently subscribed.\n\n"
            "Use /start to subscribe."
        )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command - show current status."""
    chat_id = update.effective_chat.id

    # Get darkness status
    darkness = get_darkness_status()

    # Get cooldown status
    cooldown = get_cooldown_status()

    # Get subscriber count
    sub_count = get_subscriber_count()

    # Get camera count (only those with regions configured)
    all_cameras = get_cameras()
    active_cameras = [c for c in all_cameras if c.get("detection_regions")]

    # Get user's alert level
    level = get_subscriber_alert_level(chat_id) if is_subscribed(chat_id) else 2
    level_names = {1: "Low (1+)", 2: "Medium (2+)", 3: "High (3+)"}

    # Format status message
    lines = [
        "Aurora Borealis Monitor Status",
        "",
        f"Darkness: {'Yes' if darkness['is_dark'] else 'No'}",
        f"  Reason: {darkness['reason']}",
        f"  Period: {darkness['period']}",
        "",
        f"Monitoring: {len(active_cameras)} cameras",
        f"Subscribers: {sub_count}",
        f"Your status: {'Subscribed' if is_subscribed(chat_id) else 'Not subscribed'}",
    ]

    if is_subscribed(chat_id):
        lines.append(f"Your level: {level_names[level]}")

    lines.append("")

    if cooldown["last_alert"]:
        lines.extend([
            f"Last alert: {cooldown['last_alert'][:19]}",
            f"  Detection: {cooldown['last_detection_percent']:.1f}%",
            f"  Cameras: {', '.join(cooldown['cameras_detected']) or 'None'}",
        ])
        if cooldown["in_cooldown"]:
            lines.append(
                f"  Cooldown: {cooldown['cooldown_remaining_minutes']:.1f} min remaining"
            )
    else:
        lines.append("Last alert: None yet")

    await update.message.reply_text("\n".join(lines))




async def cmd_cameras(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cameras command - list monitored cameras with thresholds."""
    from .config import MIN_AURORA_PIXEL_PERCENT
    from .detector import calculate_min_blob_size

    cameras = get_cameras()

    if not cameras:
        await update.message.reply_text("No cameras configured.")
        return

    lines = [
        f"Monitoring {len(cameras)} cameras:",
        f"(Global threshold: {MIN_AURORA_PIXEL_PERCENT}%)",
        "",
    ]

    for cam in cameras:
        name = cam.get("name", cam.get("id", "Unknown"))
        regions = cam.get("detection_regions", [])
        threshold = cam.get("detection_threshold")
        noise = cam.get("noise_baseline", {})

        # Threshold display
        if threshold is not None:
            thresh_str = f"{threshold}%"
        else:
            thresh_str = f"{MIN_AURORA_PIXEL_PERCENT}% (default)"

        # Noise baseline summary
        noise_total = sum(noise.values()) if noise else 0

        lines.append(f"• {name}")
        lines.append(f"  Threshold: {thresh_str}")
        if noise_total > 0:
            lines.append(f"  Noise baseline: {noise_total:.2f}% total")

    await update.message.reply_text("\n".join(lines))


async def cmd_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /level command - set alert sensitivity with inline buttons."""
    chat_id = update.effective_chat.id

    if not is_subscribed(chat_id):
        await update.message.reply_text("You need to /start first to subscribe.")
        return

    # Show current level with inline buttons
    current = get_subscriber_alert_level(chat_id)
    level_names = {1: "Low", 2: "Medium", 3: "High"}

    # Create inline keyboard with level buttons
    keyboard = [
        [
            InlineKeyboardButton("Low", callback_data="level_1"),
            InlineKeyboardButton("Medium", callback_data="level_2"),
            InlineKeyboardButton("High", callback_data="level_3"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Your alert level: {level_names[current]}\n\n"
        "Choose your sensitivity:\n"
        "• Low: Alert on any detection (1+ camera)\n"
        "• Medium: Alert on 2+ cameras (default)\n"
        "• High: Alert only on strong aurora (3+ cameras)",
        reply_markup=reply_markup
    )


async def handle_level_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button clicks for level selection."""
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    data = query.data

    if data.startswith("level_"):
        try:
            level = int(data.split("_")[1])
            if level in (1, 2, 3):
                set_subscriber_alert_level(chat_id, level)
                level_names = {1: "Low (1+ camera)", 2: "Medium (2+ cameras)", 3: "High (3+ cameras)"}
                await query.edit_message_text(f"Alert level set to: {level_names[level]}")
        except (ValueError, IndexError):
            pass


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command - show available commands."""
    help_text = """Aurora Borealis Monitor for Tromsø

/start - Subscribe to aurora alerts
/stop - Unsubscribe from alerts
/level - Set your alert sensitivity
/status - Check current monitoring status
/cameras - List monitored cameras
/about - How this bot works
/help - Show this help message

The bot checks webcams every 2 minutes during dark hours and sends alerts based on your sensitivity level."""
    await update.message.reply_text(help_text)


async def cmd_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /about command - show how the bot works."""
    about_text = """How Aurora Detection Works

We analyze webcam images using HSV color detection, looking for the green glow of aurora (557.7nm oxygen emission).
Multiple cameras must detect aurora simultaneously to reduce false positives from city lights.
The algorithm is under constant improvement based on real-world calibration data."""
    await update.message.reply_text(about_text)


# ============ SECRET ADMIN COMMANDS ============

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Secret admin command: /scan - Run detection manually."""
    chat_id = update.effective_chat.id

    if chat_id != ADMIN_CHAT_ID:
        return  # Silently ignore non-admin

    await update.message.reply_text("Running manual scan...")

    all_cameras = get_cameras()
    # Only check cameras with detection regions configured
    cameras = [c for c in all_cameras if c.get("detection_regions")]

    if not cameras:
        await update.message.reply_text("No cameras with detection regions configured.")
        return

    # Check darkness
    darkness = get_darkness_status()
    dark_status = "Dark" if darkness["is_dark"] else "Not dark"

    results_lines = [
        f"Manual Scan Results",
        f"{dark_status} - {darkness['reason']}",
        "",
    ]

    detections = []
    for camera in cameras:
        image = await fetch_camera_image(camera)
        if image:
            result = analyze_image(
                image,
                camera.get("detection_regions", []),
                camera.get("min_blob_size"),
                camera.get("noise_baseline"),
                camera.get("detection_threshold"),
            )

            detected = result.get("detected", False)
            weighted = result.get("weighted_aurora_percent", 0)
            colors = result.get("colors_found", [])
            pcts = result.get("pixel_percentages", {})

            status = "YES" if detected else "NO"
            color_str = f"[{', '.join(colors)}]" if colors else ""

            results_lines.append(
                f"{status} {camera['name']}: {weighted:.2f}% {color_str}"
            )
            results_lines.append(
                f"   G:{pcts.get('green',0):.2f}% R:{pcts.get('red',0):.2f}% V:{pcts.get('violet',0):.2f}%"
            )

            if detected:
                detections.append({
                    "camera": camera,
                    "result": result,
                    "image": image,
                })
        else:
            results_lines.append(f"WARN {camera['name']}: Failed to fetch")

    results_lines.append("")
    results_lines.append(f"Detections: {len(detections)}/{len(cameras)}")
    results_lines.append(f"Would alert: {'YES' if len(detections) >= MIN_CAMERAS_FOR_ALERT else 'NO'}")

    await update.message.reply_text("\n".join(results_lines))


async def cmd_peek(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Secret admin command: /peek - View current camera images."""
    import io

    chat_id = update.effective_chat.id

    if chat_id != ADMIN_CHAT_ID:
        return  # Silently ignore non-admin

    await update.message.reply_text("Fetching camera images...")

    all_cameras = get_cameras()
    # Only show cameras with detection regions configured
    cameras = [c for c in all_cameras if c.get("detection_regions")]

    if not cameras:
        await update.message.reply_text("No cameras configured.")
        return

    # Fetch all images first
    camera_data = []
    for camera in cameras:
        image = await fetch_camera_image(camera)
        if image:
            result = analyze_image(
                image,
                camera.get("detection_regions", []),
                camera.get("min_blob_size"),
                camera.get("noise_baseline"),
                camera.get("detection_threshold"),
            )
            camera_data.append({
                "camera": camera,
                "image": image,
                "result": result,
            })

    if not camera_data:
        await update.message.reply_text("Failed to fetch any images.")
        return

    # Send each image with caption
    for data in camera_data:
        camera = data["camera"]
        image = data["image"]
        result = data["result"]

        detected = result.get("detected", False)
        weighted = result.get("weighted_aurora_percent", 0)
        colors = result.get("colors_found", [])
        pcts = result.get("pixel_percentages", {})

        status = "AURORA" if detected else "No"
        color_str = f" [{', '.join(colors)}]" if colors else ""

        caption = (
            f"{camera['name']}\n"
            f"{status}{color_str}\n"
            f"Weighted: {weighted:.2f}%\n"
            f"G:{pcts.get('green',0):.2f}% R:{pcts.get('red',0):.2f}% V:{pcts.get('violet',0):.2f}%"
        )
        await update.message.reply_photo(photo=io.BytesIO(image), caption=caption)


async def cmd_simonsays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Secret admin command: /simonsays <message> - Broadcast message to all subscribers."""
    chat_id = update.effective_chat.id

    if chat_id != ADMIN_CHAT_ID:
        return  # Silently ignore non-admin

    # Get message text after the command
    if not context.args:
        await update.message.reply_text("Usage: /simonsays <message>")
        return

    message = " ".join(context.args)

    # Get all subscribers
    subscriber_ids = get_subscriber_chat_ids()

    if not subscriber_ids:
        await update.message.reply_text("No subscribers to send to.")
        return

    # Send to all subscribers
    sent_count = 0
    failed_count = 0

    for sub_id in subscriber_ids:
        try:
            await context.bot.send_message(chat_id=sub_id, text=message)
            sent_count += 1
        except Exception as e:
            logger.warning(f"Failed to send to {sub_id}: {e}")
            failed_count += 1

    await update.message.reply_text(
        f"Broadcast complete.\nSent: {sent_count}\nFailed: {failed_count}"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular text messages - show help."""
    chat_id = update.effective_chat.id

    if is_subscribed(chat_id):
        await update.message.reply_text(
            "Hi! You're subscribed to aurora alerts.\n\n"
            "Use /status to check monitoring status.\n"
            "Use /help to see all available commands."
        )
    else:
        await update.message.reply_text(
            "Hi! I'm the Aurora Borealis Monitor bot.\n\n"
            "Use /start to subscribe to aurora alerts.\n"
            "Use /help to see all available commands."
        )


def cleanup_old_calibration_images(max_age_hours: int = 24):
    """Delete calibration image folders older than max_age_hours."""
    if not CALIBRATION_DIR.exists():
        return

    now = datetime.now(timezone.utc)
    deleted_count = 0

    for folder in CALIBRATION_DIR.iterdir():
        if not folder.is_dir():
            continue

        try:
            # Parse timestamp from folder name (YYYYMMDD_HHMMSS)
            folder_time = datetime.strptime(folder.name, "%Y%m%d_%H%M%S")
            folder_time = folder_time.replace(tzinfo=timezone.utc)

            age_hours = (now - folder_time).total_seconds() / 3600

            if age_hours > max_age_hours:
                # Delete folder and contents
                for file in folder.iterdir():
                    file.unlink()
                folder.rmdir()
                deleted_count += 1
        except (ValueError, OSError):
            # Skip folders that don't match format or can't be deleted
            continue

    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} old calibration folders")


async def save_calibration_images(cameras: list[dict], camera_images: dict[str, bytes]):
    """Save camera images for calibration analysis."""
    global last_calibration_save

    if not SAVE_CALIBRATION_IMAGES:
        return

    now = datetime.now(timezone.utc)

    # Only save once per hour
    if last_calibration_save:
        elapsed = (now - last_calibration_save).total_seconds()
        if elapsed < 3600:  # 1 hour
            return

    last_calibration_save = now

    # Cleanup old images first (keep max 24 hours)
    cleanup_old_calibration_images(max_age_hours=24)

    # Create calibration directory
    CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)

    # Create timestamped subdirectory
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    save_dir = CALIBRATION_DIR / timestamp
    save_dir.mkdir(exist_ok=True)

    # Save each camera image
    for camera in cameras:
        cam_id = camera["id"]
        if cam_id in camera_images:
            image_path = save_dir / f"{cam_id}.jpg"
            image_path.write_bytes(camera_images[cam_id])

    logger.info(f"Saved {len(camera_images)} calibration images to {save_dir}")


async def check_aurora():
    """
    Main aurora check cycle.
    Called periodically by the scheduler.
    During daylight: only fetch and archive images.
    During darkness: full aurora detection and alerting.
    """
    is_dark = is_dark_enough()
    mode = "dark" if is_dark else "daylight"
    logger.info(f"Running scheduled check ({mode} mode)")

    all_cameras = get_cameras()
    # Only check cameras with detection regions configured
    cameras = [c for c in all_cameras if c.get("detection_regions")]

    if not cameras:
        logger.warning("No cameras with detection regions configured")
        return

    detections = []
    all_results = {}  # Store all detection results for archive naming
    total_percent = 0.0
    camera_images = {}  # Store all images for calibration/archive

    for camera in cameras:
        try:
            image = await fetch_camera_image(camera)
            if image:
                camera_images[camera["id"]] = image
                # Only run detection during darkness
                if is_dark:
                    result = analyze_image(
                        image,
                        camera.get("detection_regions", []),
                        camera.get("min_blob_size"),  # None = auto-calculate
                        camera.get("noise_baseline"),
                        camera.get("detection_threshold"),  # None = use global default
                    )
                    all_results[camera["id"]] = result
                    if result["detected"]:
                        detections.append({
                            "camera": camera,
                            "result": result,
                            "image": image,
                        })
                        # Use weighted percent for more accurate scoring
                        total_percent += result.get("weighted_aurora_percent", result.get("total_aurora_percent", 0))
        except Exception as e:
            logger.error(f"Error checking camera {camera.get('name')}: {e}")

    # Save calibration images if enabled
    await save_calibration_images(cameras, camera_images)

    # Archive images for later download
    if ARCHIVE_ENABLED and camera_images:
        archived = save_archive_images(
            ARCHIVE_DIR,
            camera_images,
            cameras,
            detection_results=all_results,
            min_interval_minutes=ARCHIVE_INTERVAL_MINUTES,
            min_free_mb=ARCHIVE_MIN_FREE_MB,
        )
        if not archived:
            logger.debug(f"Archive skipped (interval not reached)")

    # Calculate aggregate percentages for status file (average of detecting cameras only)
    avg_green = 0.0
    avg_red = 0.0
    avg_violet = 0.0
    avg_weighted = 0.0

    if is_dark and detections:
        for d in detections:
            pcts = d["result"].get("pixel_percentages", {})
            avg_green += pcts.get("green", 0)
            avg_red += pcts.get("red", 0)
            avg_violet += pcts.get("violet", 0)
            avg_weighted += d["result"].get("weighted_aurora_percent", 0)
        avg_green /= len(detections)
        avg_red /= len(detections)
        avg_violet /= len(detections)
        avg_weighted /= len(detections)

    if is_dark:
        logger.info(f"Check complete: {len(detections)}/{len(cameras)} cameras detected aurora")

        # Check if we should alert
        if len(detections) >= MIN_CAMERAS_FOR_ALERT:
            avg_percent = total_percent / len(detections) if detections else 0

            send, alert_type = should_send_alert(avg_percent)
            if send:
                logger.info(f"Sending aurora alert (type: {alert_type})")
                await send_aurora_alert(detections, alert_type)

                # Save alert state
                camera_ids = [d["camera"]["id"] for d in detections]
                save_alert_state(avg_percent, camera_ids)
            else:
                logger.debug("Alert skipped due to cooldown")
    else:
        logger.info(f"Daylight check complete: archived {len(camera_images)} images")

    # Write simple status file for ESP32 polling
    write_status(
        STATUS_FILE,
        is_dark=is_dark,
        detected=len(detections) > 0,
        detection_count=len(detections),
        camera_count=len(cameras),
        green_pct=avg_green,
        red_pct=avg_red,
        violet_pct=avg_violet,
        weighted_pct=avg_weighted,
    )


async def scheduler_loop():
    """Background scheduler loop for periodic aurora checks."""
    while True:
        try:
            await check_aurora()
        except Exception as e:
            logger.error(f"Error in scheduled check: {e}")

        # Use shorter interval during darkness, longer during daylight
        if is_dark_enough():
            interval_seconds = CHECK_INTERVAL_MINUTES * 60
        else:
            interval_seconds = CHECK_INTERVAL_DAYLIGHT_MINUTES * 60

        await asyncio.sleep(interval_seconds)


async def run_bot():
    """Initialize and run the Telegram bot with scheduler."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        return

    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("stop", cmd_stop))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("cameras", cmd_cameras))
    application.add_handler(CommandHandler("level", cmd_level))
    application.add_handler(CommandHandler("about", cmd_about))
    application.add_handler(CommandHandler("help", cmd_help))

    # Secret admin commands (not listed in /help)
    application.add_handler(CommandHandler("scan", cmd_scan))
    application.add_handler(CommandHandler("peek", cmd_peek))
    application.add_handler(CommandHandler("simonsays", cmd_simonsays))

    # Add callback handler for inline buttons
    application.add_handler(CallbackQueryHandler(handle_level_callback, pattern="^level_"))

    # Handle regular text messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Initialize the application
    await application.initialize()
    await application.start()

    # Start polling in background
    await application.updater.start_polling(drop_pending_updates=True)

    logger.info("Bot started, beginning scheduler loop")

    # Run scheduler loop
    try:
        await scheduler_loop()
    finally:
        # Cleanup
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


def main():
    """Entry point for the bot."""
    logger.info("Starting Aurora Borealis Telegram Bot")
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
