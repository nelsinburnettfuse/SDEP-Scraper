"""
Thread manifest: persist and compare thread IDs across scraper runs.

Stores a JSON manifest after each run. On subsequent runs, loads the
previous manifest and reports new / disappeared threads — a lightweight
consistency check for web-scraped data.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_LATEST = "latest_manifest.json"


def _manifest_path(directory: str) -> Path:
    return Path(directory) / MANIFEST_LATEST


def load_previous_manifest(directory: str) -> dict | None:
    """Load the most recent manifest, or None if this is the first run."""
    path = _manifest_path(directory)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(thread_ids: set[str], directory: str) -> Path:
    """Save current run's thread IDs as the new manifest.

    Archives the previous manifest (timestamped) before overwriting.
    """
    Path(directory).mkdir(parents=True, exist_ok=True)
    path = _manifest_path(directory)

    if path.exists():
        prev = json.loads(path.read_text(encoding="utf-8"))
        ts = prev.get("scraped_at", "unknown").replace(":", "-")
        archive = Path(directory) / f"manifest_{ts}.json"
        path.rename(archive)

    manifest = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "thread_count": len(thread_ids),
        "thread_ids": sorted(thread_ids),
    }
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def compare_manifests(current_ids: set[str], previous: dict | None) -> dict:
    """Compare current thread IDs against the previous manifest."""
    if previous is None:
        return {
            "first_run": True,
            "current_count": len(current_ids),
            "new_threads": sorted(current_ids),
            "disappeared_threads": [],
            "new_count": len(current_ids),
            "disappeared_count": 0,
        }

    prev_ids = set(previous.get("thread_ids", []))
    new = current_ids - prev_ids
    disappeared = prev_ids - current_ids

    return {
        "first_run": False,
        "previous_scraped_at": previous.get("scraped_at"),
        "previous_count": len(prev_ids),
        "current_count": len(current_ids),
        "new_threads": sorted(new),
        "disappeared_threads": sorted(disappeared),
        "new_count": len(new),
        "disappeared_count": len(disappeared),
    }
