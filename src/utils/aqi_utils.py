"""
aqi_utils.py — US EPA AQI bands: category, colour, health message.

The single source of truth for turning an AQI number into what a human
should see: a category name, the official US EPA colour band, and the
EPA health message. Used by the dashboard cards, the trend chart, the
leaderboard, and the FastAPI response — so the bands can never drift
between surfaces.

US EPA breakpoints (the standard 0–500 scale used by Open-Meteo's
`us_aqi` field):

    0–50        Good                        green   #00E400
    51–100      Moderate                    yellow  #FFFF00
    101–150     Unhealthy for Sensitive     orange  #FF7E00
    151–200     Unhealthy                   red     #FF0000
    201–300     Very Unhealthy              purple  #8F3F97
    301–500     Hazardous                   maroon  #7E0023
"""

from typing import Tuple

# Type alias for AQI band tuple
AQIBand = Tuple[int, int, str, str, str]  # (min, max, label, color, message)

# Each band: (min_aqi, max_aqi, label, colour_hex, health_message)
# Ranges are inclusive of min, exclusive of max except the last (500).
AQI_BANDS: list[AQIBand] = [
    (
        0, 50,
        "Good",
        "#00E400",
        "Air quality is satisfactory, and air pollution poses little "
        "or no risk.",
    ),
    (
        51, 100,
        "Moderate",
        "#FFFF00",
        "Air quality is acceptable. However, there may be a risk for "
        "some people, particularly those who are unusually sensitive "
        "to air pollution.",
    ),
    (
        101, 150,
        "Unhealthy for Sensitive Groups",
        "#FF7E00",
        "Members of sensitive groups may experience health effects. "
        "The general public is less likely to be affected.",
    ),
    (
        151, 200,
        "Unhealthy",
        "#FF0000",
        "Some members of the general public may experience health "
        "effects; members of sensitive groups may experience more "
        "serious health effects.",
    ),
    (
        201, 300,
        "Very Unhealthy",
        "#8F3F97",
        "Health alert: the risk of health effects is increased for "
        "everyone.",
    ),
    (
        301, 500,
        "Hazardous",
        "#7E0023",
        "Health warning of emergency conditions: everyone is more "
        "likely to be affected.",
    ),
]

# AQI at or above this is "hazardous air" for alert purposes
# (EPA: 151+ is the first band where the general public is affected).
HAZARDOUS_THRESHOLD = 151


def aqi_category(aqi: float) -> str:
    """Band label for an AQI value, e.g. 42 -> 'Good'.
    
    Args:
        aqi: Air Quality Index value (0-500+)
        
    Returns:
        Category name (e.g., 'Good', 'Moderate', 'Unhealthy')
    """
    return _band_for(aqi)[2]


def aqi_color(aqi: float) -> str:
    """Official US EPA colour hex for an AQI value.
    
    Args:
        aqi: Air Quality Index value (0-500+)
        
    Returns:
        Hex color code (e.g., '#00E400' for Good)
    """
    return _band_for(aqi)[3]


def health_message(aqi: float) -> str:
    """EPA health message for an AQI value.
    
    Args:
        aqi: Air Quality Index value (0-500+)
        
    Returns:
        Health guidance message for the AQI level
    """
    return _band_for(aqi)[4]


def is_hazardous(aqi: float) -> bool:
    """True when AQI >= 151 — the 'Unhealthy' band and above.
    
    Args:
        aqi: Air Quality Index value (0-500+)
        
    Returns:
        True if AQI is hazardous (>= 151), False otherwise
    """
    return aqi >= HAZARDOUS_THRESHOLD


def _band_for(aqi: float) -> AQIBand:
    """Return the (min, max, label, color, message) tuple for an AQI.
    
    Args:
        aqi: Air Quality Index value (0-500+)
        
    Returns:
        AQI band tuple matching the AQI value
    """
    for band in AQI_BANDS:
        lo, hi = band[0], band[1]
        if lo <= aqi <= hi:
            return band
    # Defensive: values outside 0–500 clamp to the nearest band edge.
    if aqi < 0:
        return AQI_BANDS[0]
    return AQI_BANDS[-1]
