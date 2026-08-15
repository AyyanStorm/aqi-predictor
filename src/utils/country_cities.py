"""
country_cities.py — country -> cities lookup for the dynamic Top-10 section.

The old leaderboard was hardcoded to Pakistan (src.config.CITIES). This
module replaces that assumption with a static global city dataset:

    src/data/worldcities.json.gz  — simplemaps World Cities Database
    (Basic; 47,868 cities, 242 countries; built by
    src/utils/build_world_cities.py; CC-BY 4.0, attribution:
    simplemaps.com).

The selected city's country (from the location picker's `loc["country"]`,
e.g. "United States", "United Kingdom", "United Arab Emirates") is
normalised against the dataset and the largest cities by population are
returned as the ranking candidates. Pure Python (no Streamlit import) so
the lookup is unit-testable headlessly — same pattern as src/utils/geo.py.
"""

import gzip
import json
from functools import lru_cache
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger(__name__)

_DATASET = Path(__file__).resolve().parents[1] / "data" / "worldcities.json.gz"

# Common naming mismatches between the location picker's country strings
# (Open-Meteo geocoding / ipapi / Nominatim) and simplemaps country
# names. Keys are lowercase; values are the canonical simplemaps name.
_COUNTRY_ALIASES = {
    "usa": "United States",
    "us": "United States",
    "united states of america": "United States",
    "uk": "United Kingdom",
    "uae": "United Arab Emirates",
    "tanzania": "Tanzania, United Republic of",
    "moldova": "Moldova, Republic of",
    "bolivia": "Bolivia, Plurinational State of",
    "venezuela": "Venezuela, Bolivarian Republic of",
    "cabo verde": "Cape Verde",
    "cape verde": "Cape Verde",
    "ivory coast": "Côte d'Ivoire",
    "cote d'ivoire": "Côte d'Ivoire",
    "cote divoire": "Côte d'Ivoire",
    "palestine": "Palestinian Territory",
    "swaziland": "Eswatini",
    "macedonia": "North Macedonia",
    "east timor": "Timor-Leste",
    "democratic republic of the congo": "Democratic Republic of the Congo",
    "republic of the congo": "Republic of the Congo",
    "congo": "Republic of the Congo",
    "hong kong": "Hong Kong",
    "macau": "Macao",
    "macao": "Macao",
    "russia": "Russia",
    "south korea": "South Korea",
    "north korea": "North Korea",
    "czechia": "Czechia",
    "czech republic": "Czechia",
    "burma": "Myanmar",
    "laos": "Laos",
    "syria": "Syria",
    "iran": "Iran",
    "vietnam": "Vietnam",
    "taiwan": "Taiwan",
}


@lru_cache(maxsize=1)
def _load():
    """The full dataset, cached: list of {name, lat, lon, country, population}."""
    try:
        with gzip.open(_DATASET, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        logger.error(
            f"City dataset not found at {_DATASET}. Run "
            "`python -m src.utils.build_world_cities` to generate it."
        )
        return []


@lru_cache(maxsize=1)
def _by_country():
    """
    country name (exact) -> cities sorted by population, descending.

    Built once from the raw list; city names are de-duplicated within a
    country (keeping the largest population) so a country never offers
    two identical labels.
    """
    index = {}
    for c in _load():
        best = index.setdefault(c["country"], {})
        cur = best.get(c["name"])
        if cur is None or c["population"] > cur["population"]:
            best[c["name"]] = c
    return {
        country: sorted(cities.values(), key=lambda c: c["population"], reverse=True)
        for country, cities in index.items()
    }


def _lookup_country(country):
    """Resolve a picker country string to a canonical simplemaps country name."""
    if not country or not str(country).strip():
        return None
    key = str(country).strip().lower()
    if key in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[key]
    if key in _by_country():
        return key  # exact lowercase hit (e.g. "pakistan", "japan")
    # Case-insensitive scan over the dataset's country names.
    for name in _by_country():
        if name.lower() == key:
            return name
    logger.info(f"No city dataset for country: {country}")
    return None


def normalize_country(country):
    """Canonical country name for a picker string, or None if unknown."""
    return _lookup_country(country)


def cities_for_country(country, limit=15):
    """
    Largest cities (by population) for a country, capped at `limit`.

    Parameters
    ----------
    country : str | None
        Country string from the location picker (e.g. "United States").
    limit : int
        Max candidates to return (the leaderboard fetches AQI for these,
        so this doubles as the API-call budget).

    Returns
    -------
    list of dict
        [{name, lat, lon, country, population}, ...] sorted by population
        descending. Empty list when the country is unknown or has no
        cities in the dataset — callers show an empty state.
    """
    canonical = _lookup_country(country)
    if canonical is None:
        return []
    return _by_country().get(canonical, [])[:limit]


def other_cities(country, exclude_name=None, limit=15):
    """
    Largest cities for a country, minus the currently selected city.

    Powers the dynamic "Or pick any other city from {Country}" picker:
    the selection is excluded so the list never offers the city the
    user is already looking at. Matching is on the first comma-part of
    the picker's display name ("London, England, United Kingdom" ->
    "London"), so search labels and dataset names line up.

    Parameters
    ----------
    country : str | None
        Country of the current selection (picker country).
    exclude_name : str | None
        Current city display name to exclude (None = no exclusion).
    limit : int
        Max options to return.

    Returns
    -------
    list of dict
        [{name, lat, lon, country, population}, ...] — may be shorter
        than `limit` when the country has few cities or the current
        city is the only one; empty when nothing is left to offer.
    """
    cities = cities_for_country(country, limit=limit + 1)
    if exclude_name:
        base = _name_key(exclude_name)
        cities = [c for c in cities if _name_key(c["name"]) != base]
    return cities[:limit]


def _name_key(name):
    """Normalised comparison key for a city name.

    Lowercases, keeps only the first comma-part (search labels are
    "City, Region, Country") and folds typographic apostrophes to
    straight ones (dataset: "Saint John’s" vs typed "Saint John's").
    """
    base = str(name).split(",")[0].strip().lower()
    return base.replace("’", "'").replace("‘", "'")


def country_of_city(name):
    """
    Country for a city name (most populous match), or None if unknown.

    Reverse lookup used where a country must be derived from a city
    WITHOUT a geocoding call (e.g. the default Karachi location):
    returns the country of the highest-population dataset entry with
    that name ("London" -> "United Kingdom", not the Canadian one).
    """
    if not name:
        return None
    base = str(name).split(",")[0].strip().lower()
    if not base:
        return None
    best, best_pop = None, -1
    for c in _load():
        if c["name"].lower() == base and c["population"] > best_pop:
            best, best_pop = c["country"], c["population"]
    return best
