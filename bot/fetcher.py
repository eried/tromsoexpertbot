"""Async image fetcher for webcam images."""

import asyncio
import logging
import ssl
import time

import aiohttp

logger = logging.getLogger(__name__)

# Request timeout in seconds
REQUEST_TIMEOUT = 60

# User agent to mimic browser requests
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


async def fetch_camera_image(camera: dict) -> bytes | None:
    """
    Fetch image from camera URL with timeout and error handling.

    Args:
        camera: Camera configuration dict with 'url' and 'name' keys

    Returns:
        Image bytes if successful, None on failure
    """
    url = camera.get("url", "")
    name = camera.get("name", "Unknown")

    if not url:
        logger.error(f"No URL configured for camera: {name}")
        return None

    # Add cache-busting timestamp parameter
    separator = "&" if "?" in url else "?"
    cache_bust_url = f"{url}{separator}_t={int(time.time())}"

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    try:
        # Create SSL context that's more compatible
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.get(cache_bust_url, headers=headers) as response:
                if response.status == 200:
                    content_type = response.headers.get("Content-Type", "")
                    if "image" in content_type or response.content_length:
                        image_data = await response.read()
                        logger.debug(
                            f"Successfully fetched image from {name}: "
                            f"{len(image_data)} bytes"
                        )
                        return image_data
                    else:
                        logger.warning(
                            f"Unexpected content type from {name}: {content_type}"
                        )
                        return None
                else:
                    logger.warning(
                        f"HTTP {response.status} fetching image from {name}"
                    )
                    return None

    except asyncio.TimeoutError:
        logger.warning(f"Timeout fetching image from {name}")
        return None
    except aiohttp.ClientError as e:
        logger.warning(f"Client error fetching image from {name}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching image from {name}: {e}")
        return None


async def fetch_all_camera_images(cameras: list[dict]) -> list[tuple[dict, bytes | None]]:
    """
    Fetch images from all cameras concurrently.

    Args:
        cameras: List of camera configuration dicts

    Returns:
        List of (camera, image_bytes) tuples
    """
    tasks = [fetch_camera_image(camera) for camera in cameras]
    results = await asyncio.gather(*tasks)
    return list(zip(cameras, results))
