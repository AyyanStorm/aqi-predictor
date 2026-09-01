"""
build_world_cities.py — generate src/data/worldcities.json.gz (committed).

Source: simplemaps "World Cities Database" (Basic) — the free, curated
version used by the Top-10 section. The official simplemaps download is
Cloudflare-gated for scripts, so we pull the identical dataset from a
GitHub mirror (simplemaps-worldcities-basic-v1.77).

License: CC-BY 4.0 — attribution required:
    "World Cities Database by simplemaps.com, CC BY 4.0."
The dashboard shows this attribution next to the chart.

Why simplemaps instead of GeoNames: curated city-level entries (metro
populations, no NYC-borough noise like Brooklyn/Queens as separate
"cities"), 47,868 cities across 242 countries, with population — which
the Top-10 candidate pool sorts by.

Output columns (subset we actually need):
    name, lat, lon, country, population

Run:  python -m src.utils.build_world_cities
"""

import csv
import gzip
import json
import sys
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger(__name__)

CITIES_CSV = "/tmp/simplemaps_worldcities.csv"   # raw simplemaps basic dump
OUT = Path(__file__).resolve().parents[1] / "data" / "worldcities.json.gz"


def main() -> int:
    cities: list[dict] = []
    with open(CITIES_CSV, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            name = (r.get("city") or r.get("city_ascii") or "").strip()
            country = (r.get("country") or "").strip()
            try:
                lat, lon = float(r["lat"]), float(r["lng"])
                population = int(float(r["population"] or 0))
            except (TypeError, ValueError):
                continue
            if not name or not country:
                continue
            cities.append({
                "name": name,
                "lat": lat,
                "lon": lon,
                "country": country,
                "population": population,
            })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as fh:
        json.dump(cities, fh)

    by_country: dict[str, int] = {}
    for c in cities:
        by_country[c["country"]] = by_country.get(c["country"], 0) + 1
    smallest = sorted(by_country.items(), key=lambda kv: kv[1])[:5]
    logger.info(f"cities written: {len(cities)}")
    logger.info(f"countries: {len(by_country)}")
    logger.info(f"smallest country coverage: {smallest}")
    logger.info(f"output: {OUT} ({OUT.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    sys.exit(main())
