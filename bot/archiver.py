"""Photo archiver for camera images.

Saves camera photos periodically for later download/review.
Automatically cleans up old photos when disk space is low.
"""

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def get_last_archive_time(archive_dir: Path) -> datetime | None:
    """Get the timestamp of the most recently archived photo."""
    if not archive_dir.exists():
        return None

    # Find the newest file by modification time
    newest_time = None
    for file in archive_dir.glob("*.jpg"):
        mtime = datetime.fromtimestamp(file.stat().st_mtime, tz=timezone.utc)
        if newest_time is None or mtime > newest_time:
            newest_time = mtime

    return newest_time


def get_free_space_mb(path: Path) -> float:
    """Get free disk space in MB for the drive containing path."""
    try:
        usage = shutil.disk_usage(path)
        return usage.free / (1024 * 1024)
    except OSError as e:
        logger.warning(f"Could not get disk usage for {path}: {e}")
        return float("inf")  # Assume infinite space if we can't check


def get_archive_groups(archive_dir: Path) -> list[tuple[str, list[Path]]]:
    """
    Get all archive groups sorted by timestamp (oldest first).

    Returns list of (timestamp_prefix, [file_paths]) tuples.
    Timestamp prefix format: YYYYMMDD-hhmmss
    """
    if not archive_dir.exists():
        return []

    # Group files by their timestamp prefix
    groups: dict[str, list[Path]] = {}
    for file in archive_dir.glob("*.jpg"):
        # Extract timestamp prefix: YYYYMMDD-hhmmss from YYYYMMDD-hhmmss-camera_name.jpg
        name = file.stem  # Without extension
        parts = name.split("-", 2)  # Split into [YYYYMMDD, hhmmss, camera_name]
        if len(parts) >= 2:
            prefix = f"{parts[0]}-{parts[1]}"
            if prefix not in groups:
                groups[prefix] = []
            groups[prefix].append(file)

    # Sort by prefix (oldest first)
    sorted_groups = sorted(groups.items(), key=lambda x: x[0])
    return sorted_groups


def cleanup_old_archives(archive_dir: Path, min_free_mb: float = 100.0) -> int:
    """
    Delete oldest archive groups until free space >= min_free_mb.

    Returns number of files deleted.
    """
    deleted_count = 0

    while get_free_space_mb(archive_dir) < min_free_mb:
        groups = get_archive_groups(archive_dir)
        if not groups:
            logger.warning(f"No archive groups to delete, but free space still low")
            break

        # Delete the oldest group
        oldest_prefix, oldest_files = groups[0]
        for file in oldest_files:
            try:
                file.unlink()
                deleted_count += 1
            except OSError as e:
                logger.error(f"Failed to delete {file}: {e}")

        logger.info(f"Deleted archive group {oldest_prefix} ({len(oldest_files)} files)")

    return deleted_count


def save_archive_images(
    archive_dir: Path,
    camera_images: dict[str, bytes],
    cameras: list[dict],
    detection_results: dict[str, dict] = None,
    min_interval_minutes: float = 20.0,
    min_free_mb: float = 100.0,
) -> bool:
    """
    Save camera images to archive directory.

    Args:
        archive_dir: Directory to save images to
        camera_images: Dict of camera_id -> image_bytes
        cameras: List of camera configs (to get names)
        detection_results: Dict of camera_id -> detection result (for percentage suffix)
        min_interval_minutes: Minimum time between saves
        min_free_mb: Minimum free space required (triggers cleanup if below)

    Returns:
        True if images were saved, False if skipped
    """
    if detection_results is None:
        detection_results = {}
    if not camera_images:
        return False

    logger.debug(f"Archive dir: {archive_dir}")

    # Check if enough time has passed since last archive
    last_time = get_last_archive_time(archive_dir)
    now = datetime.now(timezone.utc)

    if last_time is not None:
        elapsed_minutes = (now - last_time).total_seconds() / 60
        logger.info(f"Last archive: {elapsed_minutes:.1f} min ago")
        if elapsed_minutes < min_interval_minutes:
            logger.info(f"Archive skipped: need {min_interval_minutes} min interval")
            return False
    else:
        logger.info("No previous archives found, saving first set")

    # Create archive directory if needed
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Cleanup old archives if disk space is low
    free_mb = get_free_space_mb(archive_dir)
    if free_mb < min_free_mb:
        logger.info(f"Free space low ({free_mb:.1f} MB), cleaning up old archives")
        deleted = cleanup_old_archives(archive_dir, min_free_mb)
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old archive files")

    # Generate timestamp for this batch
    timestamp = now.strftime("%Y%m%d-%H%M%S")

    # Build camera_id -> name mapping
    id_to_name = {cam["id"]: cam.get("name", cam["id"]) for cam in cameras}

    # Save each image
    saved_count = 0
    for cam_id, image_bytes in camera_images.items():
        # Sanitize camera name for filename (replace spaces, special chars)
        cam_name = id_to_name.get(cam_id, cam_id)
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in cam_name)

        # Get detection percentage (0-100), default 0
        result = detection_results.get(cam_id, {})
        weighted_pct = result.get("weighted_aurora_percent", 0)
        pct_int = min(100, max(0, int(weighted_pct)))  # Clamp to 0-100

        filename = f"{timestamp}-{safe_name}_{pct_int:03d}.jpg"
        filepath = archive_dir / filename

        try:
            filepath.write_bytes(image_bytes)
            saved_count += 1
        except OSError as e:
            logger.error(f"Failed to save archive {filename}: {e}")

    logger.info(f"Archived {saved_count} camera images with timestamp {timestamp}")
    return True
