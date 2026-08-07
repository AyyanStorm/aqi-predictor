"""
model_registry.py — Day 14: the Model Registry.

Serialisation, versioning, metadata and promotion logic — the piece that
turns "I trained a model" into "the system serves a model, and can
safely upgrade or undo that decision".

Why a registry exists (the Day 14 lesson):
    A trained model is not a deliverable; a DEPLOYED, REPRODUCIBLE model
    is. When you retrain daily (roadmap Days 21-22), a new model shows up
    every morning. Without a registry you have a pile of joblib files and
    no idea which one is in production, why it won, or how to go back if
    it quietly gets worse. The registry answers three questions about
    every artifact:

      1. WHAT is this?    name, version, params, features, training window
      2. HOW GOOD is it?  honest walk-forward metrics (rmse/mae/r2 per horizon)
      3. WHERE is it?     status: candidate -> production (or archived)

    And it gives you ROLLBACK: production is a pointer, not a file. If
    v3 performs worse on live data than v2, pointing production back at
    v2 is one call — no retraining, no archaeology.

Design (100% serverless, roadmap Section 6 — no MLflow, no Docker):
    data/models/registry/
        registry.json     — the index: every version + its metadata + the
                            production pointer (single source of truth)
        artifacts/        — one joblib file per version:
                            {name}_v{version}.joblib -> {horizon: model}

    Why joblib and not pickle: joblib is pickle specialised for large
    numpy arrays — the same format scikit-learn and LightGBM use, safe
    for trees, and it compresses big models. It is the ecosystem default
    for model serialisation.

    Why JSON and not a database: the registry is read once per inference
    call and written once per training run. A small JSON file is simpler,
    diff-able, and needs zero infrastructure. (data/ is gitignored, so on
    GitHub Actions the registry is rebuilt by the training workflow —
    roadmap Day 22.)

What this module provides:
    1. ModelRegistry class — register / promote / rollback / load / list.
    2. promote_if_better()  — the AUTOMATED promotion rule: a candidate is
                              promoted only if its mean walk-forward RMSE
                              beats the current production model's.
    3. CLI — python -m src.training.model_registry
             list | status | info <name> [<version>]
             promote <name> <version> | rollback <name>
"""

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import joblib

from src.config import FORECAST_HORIZONS, MODELS_DIR
from src.utils.logger import get_logger

logger = get_logger(__name__)

# The registry lives in its own subfolder so the artifacts and the index
# stay together and can never be confused with raw training outputs.
REGISTRY_DIR = MODELS_DIR / "registry"
ARTIFACTS_DIR = REGISTRY_DIR / "artifacts"
INDEX_FILE = REGISTRY_DIR / "registry.json"

# Statuses a version can be in. "archived" = was production once, kept
# for rollback; "candidate" = registered but never promoted.
STATUS_PRODUCTION = "production"
STATUS_CANDIDATE = "candidate"
STATUS_ARCHIVED = "archived"


# =========================================================
# 1. THE REGISTRY
# =========================================================

class ModelRegistry:
    """
    A file-based model registry with versioning and promotion.

    The index (registry.json) is the single source of truth: it lists
    every registered version with its metadata and points to the current
    production version. Artifacts are joblib files named
    {name}_v{version}.joblib, each holding a dict {horizon: model} —
    one trained model per forecast horizon (the roadmap's three-target
    design: y_24, y_48, y_72).

    Every write is atomic: the index is written to a temp file and
    renamed over the old one, so a crash mid-write can never leave a
    half-written registry (the training pipeline on Day 22 will run this
    unattended — corruption there would be invisible and fatal).

    The registry is deliberately a plain class, not a singleton: tests
    can point it at a temp directory, production uses the default one.
    """

    def __init__(self, registry_dir=None):
        self.registry_dir = Path(registry_dir) if registry_dir else REGISTRY_DIR
        self.artifacts_dir = self.registry_dir / "artifacts"
        self.index_file = self.registry_dir / "registry.json"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_file.exists():
            self._write_index({"versions": [], "production": None,
                               "promotion_history": []})

    # -------------------------------------------------
    # Index I/O
    # -------------------------------------------------

    def _read_index(self):
        """Load the index JSON. Returns the parsed dict."""
        with open(self.index_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_index(self, index):
        """Atomically persist the index: temp file + rename."""
        fd, tmp_path = tempfile.mkstemp(
            dir=self.registry_dir, suffix=".tmp"
        )
        try:
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(index, f, indent=2, sort_keys=True)
                f.write("\n")
            shutil.move(tmp_path, self.index_file)  # atomic on same fs
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise

    # -------------------------------------------------
    # Versioning
    # -------------------------------------------------

    def _next_version(self, index, name):
        """v1, v2, v3... — one counter per model name."""
        versions = [
            v["version"]
            for v in index["versions"]
            if v["name"] == name
        ]
        return max(versions, default=0) + 1

    @staticmethod
    def _artifact_filename(name, version):
        return f"{name}_v{version}.joblib"

    # -------------------------------------------------
    # Registration
    # -------------------------------------------------

    def register(self, name, models, metrics, feature_cols, params=None,
                 n_train_rows=None, train_window=None, notes=""):
        """
        Save a trained model set to the registry as a new version.

        Parameters
        ----------
        name : str
            Model family name, e.g. "lgbm", "rf", "ridge". Versions are
            numbered per name, so lgbm_v1, lgbm_v2, ...
        models : dict[int, model]
            {horizon: fitted model} — one per forecast horizon.
        metrics : dict[int, dict]
            {horizon: {"rmse": .., "mae": .., "r2": ..}} — the honest
            walk-forward numbers (evaluate.py), NOT training-set scores.
        feature_cols : list[str]
            The exact feature list the models were trained on. Stored so
            inference (Day 16) can verify it feeds the same columns.
        params : dict | None
            Hyperparameters used (alpha / n_estimators / learning_rate...).
        n_train_rows : int | None
            Number of training rows (for the report's "data" section).
        train_window : dict | None
            {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} of the training
            data, so a reviewer can see what period each version saw.
        notes : str
            Free text (e.g. "grid-searched on Day 13").

        Returns
        -------
        int
            The new version number.
        """
        index = self._read_index()
        version = self._next_version(index, name)
        artifact_path = self.artifacts_dir / self._artifact_filename(name, version)

        # Serialise first, then record — never the other way round. If
        # joblib fails we abort with the index untouched.
        joblib.dump(models, artifact_path)

        entry = {
            "name": name,
            "version": version,
            "artifact": artifact_path.name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": STATUS_CANDIDATE,
            "promoted_at": None,
            "metrics": {str(h): m for h, m in metrics.items()},
            "mean_rmse": round(
                sum(metrics[h]["rmse"] for h in FORECAST_HORIZONS)
                / len(FORECAST_HORIZONS),
                4,
            ),
            "feature_cols": list(feature_cols),
            "params": params or {},
            "n_train_rows": n_train_rows,
            "train_window": train_window or {},
            "notes": notes,
        }
        index["versions"].append(entry)
        self._write_index(index)
        logger.info(
            f"Registered {name}_v{version} "
            f"(mean walk-forward RMSE {entry['mean_rmse']:.2f})"
        )
        return version

    # -------------------------------------------------
    # Promotion / rollback
    # -------------------------------------------------

    def _find(self, index, name, version=None):
        """Return the version dict; the production one by default."""
        for v in index["versions"]:
            if v["name"] == name and (
                version is None or v["version"] == version
            ):
                if version is None and v["status"] != STATUS_PRODUCTION:
                    continue
                return v
        return None

    def promote(self, name, version):
        """
        Manually promote a version to production.

        The previous production version is demoted to 'archived' (kept on
        disk — rollback target), and the promotion is recorded in history
        so rollback() can undo it.
        """
        index = self._read_index()
        target = self._find(index, name, version)
        if target is None:
            raise KeyError(f"No version {name}_v{version} in the registry")

        # Demote whoever currently holds the production slot for this name.
        for v in index["versions"]:
            if v["name"] == name and v["status"] == STATUS_PRODUCTION:
                v["status"] = STATUS_ARCHIVED

        target["status"] = STATUS_PRODUCTION
        target["promoted_at"] = datetime.now(timezone.utc).isoformat()
        index["promotion_history"].append(
            {
                "name": name,
                "version": version,
                "promoted_at": target["promoted_at"],
                "reason": "manual promote",
            }
        )
        self._write_index(index)
        logger.info(f"Promoted {name}_v{version} to production")

    def promote_if_better(self, name, version, force=False):
        """
        The AUTOMATED promotion rule (used by the Day 22 training cron).

        A candidate is promoted only if its mean walk-forward RMSE is
        LOWER than the current production version's (lower = better).
        This is what makes daily retraining safe: a bad day's model is
        registered but never served. With force=True it always promotes —
        useful for the very first deployment or manual overrides.

        Returns
        -------
        bool
            True if the candidate was promoted.
        """
        index = self._read_index()
        candidate = self._find(index, name, version)
        if candidate is None:
            raise KeyError(f"No version {name}_v{version} in the registry")
        current = self._find(index, name)  # the production version, if any

        if current is None or force:
            self.promote(name, version)
            return True

        if candidate["mean_rmse"] < current["mean_rmse"]:
            self.promote(name, version)
            logger.info(
                f"Auto-promoted {name}_v{version} "
                f"(RMSE {candidate['mean_rmse']:.2f} < "
                f"{current['mean_rmse']:.2f})"
            )
            return True

        logger.info(
            f"Kept {name}_v{current['version']} as production: candidate "
            f"v{version} RMSE {candidate['mean_rmse']:.2f} is not better "
            f"than {current['mean_rmse']:.2f}"
        )
        return False

    def rollback(self, name):
        """
        Undo the last promotion for a model name.

        Production moves back to the version that held the slot before
        the most recent promotion (the archived one). One call, no
        retraining — the whole point of keeping old artifacts around.
        """
        index = self._read_index()
        history = [
            h for h in index["promotion_history"] if h["name"] == name
        ]
        if len(history) < 2:
            raise ValueError(
                f"Cannot rollback '{name}': no previous production version "
                f"in the promotion history"
            )

        # The promotion BEFORE the latest one is the version to restore.
        previous = history[-2]["version"]
        self.promote(name, previous)
        logger.info(f"Rolled back {name} to v{previous}")

    # -------------------------------------------------
    # Loading (used by inference, Day 16)
    # -------------------------------------------------

    def load(self, name, version=None):
        """
        Load a registered model set from disk.

        version=None loads the CURRENT PRODUCTION model for `name` —
        exactly what the inference pipeline (Day 16) calls. Returns the
        {horizon: model} dict the artifact was saved as.
        """
        index = self._read_index()
        entry = self._find(index, name, version)
        if entry is None:
            raise KeyError(
                f"No production model '{name}' in the registry — "
                f"train and promote one first."
            )
        artifact_path = self.artifacts_dir / entry["artifact"]
        if not artifact_path.exists():
            raise FileNotFoundError(
                f"Artifact {artifact_path} missing — registry index and "
                f"artifacts are out of sync"
            )
        return joblib.load(artifact_path), entry

    # -------------------------------------------------
    # Introspection
    # -------------------------------------------------

    def list_versions(self, name=None):
        """All registered versions, newest first. Optionally filtered by name."""
        index = self._read_index()
        versions = sorted(
            index["versions"], key=lambda v: v["created_at"], reverse=True
        )
        if name is not None:
            versions = [v for v in versions if v["name"] == name]
        return versions

    def production(self, name):
        """Metadata for the current production version of a model name."""
        index = self._read_index()
        entry = self._find(index, name)
        if entry is None:
            return None
        return entry

    def status(self):
        """Human-readable registry status: every version + production."""
        index = self._read_index()
        lines = []
        for v in sorted(index["versions"],
                        key=lambda v: (v["name"], v["version"])):
            flag = "  <-- PRODUCTION" if v["status"] == STATUS_PRODUCTION else ""
            lines.append(
                f"  {v['name']}_v{v['version']}  [{v['status']}]  "
                f"mean RMSE {v['mean_rmse']:.2f}  "
                f"({v['created_at'][:10]}){flag}"
            )
        return "\n".join(lines) if lines else "  (registry is empty)"


# =========================================================
# 2. CLI
# =========================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Day 14 Model Registry — versioning, promotion, rollback."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List all registered versions")
    sub.add_parser("status", help="Show registry status with production flags")

    p_info = sub.add_parser("info", help="Show metadata for a model")
    p_info.add_argument("name")
    p_info.add_argument("version", nargs="?", type=int, default=None)

    p_promote = sub.add_parser("promote", help="Promote a version to production")
    p_promote.add_argument("name")
    p_promote.add_argument("version", type=int)

    p_rollback = sub.add_parser("rollback", help="Undo the last promotion")
    p_rollback.add_argument("name")

    args = parser.parse_args()
    reg = ModelRegistry()

    if args.command == "list":
        versions = reg.list_versions()
        if not versions:
            print("(registry is empty — run training with --register to add models)")
        for v in versions:
            print(f"  {v['name']}_v{v['version']}  [{v['status']}]  "
                  f"mean RMSE {v['mean_rmse']:.2f}  ({v['created_at'][:10]})")
    elif args.command == "status":
        print(reg.status())
    elif args.command == "info":
        entry = None
        if args.version is not None:
            entry = next(
                (v for v in reg.list_versions(args.name)
                 if v["version"] == args.version), None
            )
        else:
            entry = reg.production(args.name)
        if entry is None:
            raise SystemExit(f"No version found: {args.name}_v{args.version or 'production'}")
        print(json.dumps(entry, indent=2, sort_keys=True))
    elif args.command == "promote":
        reg.promote(args.name, args.version)
        print(reg.status())
    elif args.command == "rollback":
        reg.rollback(args.name)
        print(reg.status())


if __name__ == "__main__":
    main()
