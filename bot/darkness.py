"""Darkness checker for aurora visibility using astral library."""

from datetime import datetime, timezone

from astral import LocationInfo
from astral.sun import sun

from .config import TROMSO_LAT, TROMSO_LON

# Tromsø location for sun calculations
TROMSO = LocationInfo(
    name="Tromsø",
    region="Norway",
    timezone="Europe/Oslo",
    latitude=TROMSO_LAT,
    longitude=TROMSO_LON,
)

# Sun elevation threshold for darkness (nautical twilight = -12°)
# -6° = civil twilight (too bright for aurora)
# -12° = nautical twilight (better for aurora viewing)
# -18° = astronomical twilight (ideal for aurora)
DARKNESS_THRESHOLD = -12


def is_polar_night(date: datetime) -> bool:
    """
    Check if the given date falls within polar night period.
    Polar night in Tromsø: approximately Nov 21 - Jan 21
    """
    month_day = (date.month, date.day)
    return (month_day >= (11, 21)) or (month_day <= (1, 21))


def is_midnight_sun_period(date: datetime) -> bool:
    """
    Check if the given date falls within midnight sun period.
    Midnight sun in Tromsø: approximately May 20 - Jul 22
    Aurora not visible during this period.
    """
    month_day = (date.month, date.day)
    return (5, 20) <= month_day <= (7, 22)


def is_summer_sleep_period(date: datetime) -> bool:
    """
    Check if the given date falls within summer sleep period.
    Sleep period: Late April through mid-August (no aurora visible)
    """
    month_day = (date.month, date.day)
    return (4, 21) <= month_day <= (8, 15)


def get_sun_elevation(dt: datetime | None = None) -> float:
    """
    Calculate the sun's elevation angle at the given time.
    Returns degrees above/below horizon (negative = below).
    """
    if dt is None:
        dt = datetime.now(timezone.utc)

    try:
        s = sun(TROMSO.observer, date=dt.date(), tzinfo=timezone.utc)

        # Calculate approximate elevation based on time relative to noon/midnight
        noon = s.get("noon")
        if noon is None:
            # During polar night, sun never rises
            return -20.0

        # Simple approximation: use solar_elevation from astral
        from astral.sun import elevation
        return elevation(TROMSO.observer, dt)
    except Exception:
        # During polar night or midnight sun, calculations may fail
        # Return appropriate default based on time of year
        if is_polar_night(dt):
            return -20.0  # Always dark
        elif is_midnight_sun_period(dt):
            return 20.0  # Always light
        return 0.0


def is_dark_enough(dt: datetime | None = None) -> bool:
    """
    Check if it's dark enough to potentially see aurora.

    Returns True if:
    - It's polar night (always dark)
    - Sun is below civil twilight (-6°)

    Returns False if:
    - It's summer sleep period (Apr 21 - Aug 15)
    - Sun is above civil twilight threshold
    """
    if dt is None:
        dt = datetime.now(timezone.utc)

    # Never check during summer sleep period
    if is_summer_sleep_period(dt):
        return False

    # Always dark during polar night
    if is_polar_night(dt):
        return True

    # Check sun elevation
    elevation = get_sun_elevation(dt)
    return elevation < DARKNESS_THRESHOLD


def get_darkness_status() -> dict:
    """
    Get detailed darkness status for status reporting.

    Returns:
        dict with keys: is_dark, reason, sun_elevation, period
    """
    now = datetime.now(timezone.utc)

    if is_summer_sleep_period(now):
        return {
            "is_dark": False,
            "reason": "Summer sleep period (midnight sun)",
            "sun_elevation": get_sun_elevation(now),
            "period": "summer_sleep",
        }

    if is_polar_night(now):
        return {
            "is_dark": True,
            "reason": "Polar night - 24h darkness",
            "sun_elevation": get_sun_elevation(now),
            "period": "polar_night",
        }

    elevation = get_sun_elevation(now)
    is_dark = elevation < DARKNESS_THRESHOLD

    return {
        "is_dark": is_dark,
        "reason": f"Sun at {elevation:.1f}° ({'below' if elevation < 0 else 'above'} horizon)",
        "sun_elevation": elevation,
        "period": "normal",
    }
