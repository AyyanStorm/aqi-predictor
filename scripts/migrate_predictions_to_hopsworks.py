#!/usr/bin/env python3
"""
Migration script: copy local Parquet predictions to Hopsworks.

Run on Render (where HOPSWORKS_API_KEY / HOPSWORKS_PROJECT are set)
as a one-off job, or locally after exporting the same env vars.

Usage:
    HOPSWORKS_API_KEY=... HOPSWORKS_PROJECT=... python scripts/migrate_predictions_to_hopsworks.py
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tracking.store import ParquetPredictionStore, HopsworksPredictionStore
from src.utils.logger import get_logger

logger = get_logger(__name__)


def main():
    # Verify Hopsworks creds are available
    if not os.getenv("HOPSWORKS_API_KEY") or not os.getenv("HOPSWORKS_PROJECT"):
        print("ERROR: HOPSWORKS_API_KEY and HOPSWORKS_PROJECT must be set")
        sys.exit(1)

    print("Loading local Parquet predictions...")
    local_store = ParquetPredictionStore()
    local_records = local_store.load_all()

    if local_records.empty:
        print("No local predictions to migrate.")
        return

    print(f"Found {len(local_records)} local predictions")

    print("Connecting to Hopsworks...")
    hopsworks_store = HopsworksPredictionStore()

    # Check what's already in Hopsworks (avoid duplicates)
    existing = hopsworks_store.load_all()
    existing_ids = set(existing["prediction_id"].tolist()) if not existing.empty else set()
    print(f"Hopsworks already has {len(existing_ids)} predictions")

    # Migrate missing ones
    migrated = 0
    skipped = 0
    for _, row in local_records.iterrows():
        record = row.to_dict()
        pred_id = record.get("prediction_id")
        if pred_id in existing_ids:
            skipped += 1
            continue
        try:
            hopsworks_store.save(record)
            migrated += 1
            if migrated % 10 == 0:
                print(f"  Migrated {migrated}...")
        except Exception as e:
            logger.error(f"Failed to migrate {pred_id}: {e}")

    print(f"\nDone. Migrated: {migrated}, Skipped (already exist): {skipped}")

    # Verify
    final = hopsworks_store.load_all()
    print(f"Hopsworks now has {len(final)} total predictions")


if __name__ == "__main__":
    main()