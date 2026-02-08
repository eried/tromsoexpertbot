"""Simple status file writer for ESP32 polling.

Writes a simple key=value format that's easy to parse on microcontrollers.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def write_status(
    status_file: Path,
    is_dark: bool,
    detected: bool,
    detection_count: int,
    camera_count: int,
    green_pct: float = 0.0,
    red_pct: float = 0.0,
    violet_pct: float = 0.0,
    weighted_pct: float = 0.0,
):
    """
    Write simple status file for ESP32 polling.

    Format (easy to parse with simple string operations):
    ```
    ts=1706900000
    dark=1
    detected=0
    count=0
    cameras=7
    green=0.12
    red=0.05
    violet=0.02
    weighted=0.15
    ```
    """
    now = datetime.now(timezone.utc)
    timestamp = int(now.timestamp())

    lines = [
        f"ts={timestamp}",
        f"dark={1 if is_dark else 0}",
        f"detected={1 if detected else 0}",
        f"count={detection_count}",
        f"cameras={camera_count}",
        f"green={green_pct:.2f}",
        f"red={red_pct:.2f}",
        f"violet={violet_pct:.2f}",
        f"weighted={weighted_pct:.2f}",
    ]

    content = "\n".join(lines) + "\n"

    try:
        status_file.parent.mkdir(parents=True, exist_ok=True)
        status_file.write_text(content, encoding="utf-8")
        logger.debug(f"Status written: detected={detected}, weighted={weighted_pct:.2f}%")
    except OSError as e:
        logger.error(f"Failed to write status file: {e}")
