"""Tests for the dynamic country -> cities lookup (Top-10 section)."""

import pytest

from src.utils.country_cities import (
    cities_for_country,
    normalize_country,
)


# ---------------------------------------------------------------
# Country normalisation (picker strings -> canonical GeoNames names)
# ---------------------------------------------------------------
def test_normalize_full_names():
    assert normalize_country("Pakistan") == "Pakistan"
    assert normalize_country("Japan") == "Japan"
    assert normalize_country("United States") == "United States"
    assert normalize_country("United Kingdom") == "United Kingdom"
    assert normalize_country("United Arab Emirates") == "United Arab Emirates"


def test_normalize_case_insensitive():
    assert normalize_country("pakistan") == "Pakistan"
    assert normalize_country("JAPAN") == "Japan"


def test_normalize_aliases():
    assert normalize_country("USA") == "United States"
    assert normalize_country("UK") == "United Kingdom"
    assert normalize_country("UAE") == "United Arab Emirates"
    assert normalize_country("United States of America") == "United States"


def test_normalize_unknown_and_empty():
    assert normalize_country("Atlantis") is None
    assert normalize_country("") is None
    assert normalize_country(None) is None


# ---------------------------------------------------------------
# Candidate pool selection
# ---------------------------------------------------------------
def test_cities_for_country_pakistan():
    cities = cities_for_country("Pakistan", limit=15)
    assert len(cities) > 0
    assert all(c["country"] == "Pakistan" for c in cities)
    names = [c["name"] for c in cities]
    assert "Karachi" in names
    assert "Lahore" in names
    # Sorted by population, descending.
    pops = [c["population"] for c in cities]
    assert pops == sorted(pops, reverse=True)


def test_cities_for_country_example_capitals():
    # New York -> USA
    us = {c["name"] for c in cities_for_country("United States", limit=15)}
    assert "New York" in us
    # London -> UK
    uk = {c["name"] for c in cities_for_country("United Kingdom", limit=15)}
    assert "London" in uk
    # Dubai -> UAE
    ae = {c["name"] for c in cities_for_country("United Arab Emirates", limit=15)}
    assert "Dubai" in ae
    # Tokyo -> Japan
    jp = {c["name"] for c in cities_for_country("Japan", limit=15)}
    assert "Tokyo" in jp


def test_limit_caps_pool():
    # USA has far more than 15 cities >= 15k population.
    assert len(cities_for_country("United States", limit=15)) == 15
    assert len(cities_for_country("United States", limit=5)) == 5


def test_fewer_than_limit_country():
    # A small country returns everything it has, never padded.
    cities = cities_for_country("Antigua and Barbuda", limit=15)
    assert 0 < len(cities) <= 15
    assert len(cities) == len(cities_for_country("Antigua and Barbuda", limit=100))


def test_unknown_country_returns_empty():
    assert cities_for_country("Narnia") == []
    assert cities_for_country(None) == []


def test_dataset_rows_have_required_fields():
    """Every candidate must carry the fields the leaderboard needs."""
    for country in ("Pakistan", "United States", "Japan"):
        for c in cities_for_country(country, limit=5):
            assert isinstance(c["name"], str) and c["name"]
            assert isinstance(c["lat"], float)
            assert isinstance(c["lon"], float)
            assert isinstance(c["population"], int)
