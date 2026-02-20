#!/usr/bin/env python3
"""Build static GitHub Pages data from output/ run directories.

Reads each output/{timestamp}/result.json, extracts lightweight fields,
and writes:
  docs/data/runs.json        – sorted index manifest
  docs/data/runs/{id}.json   – per-run detail (report_text, narration, etc.)

Usage:
    python scripts/build_pages.py
"""

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
DATA_DIR = ROOT / "docs" / "data"
RUNS_DIR = DATA_DIR / "runs"

TIMESTAMP_RE = re.compile(r"^\d{8}T\d{6}Z$")


def parse_timestamp(dir_name: str) -> str:
    """Convert '20260219T161123Z' → '2026-02-19 16:11 UTC'."""
    m = re.match(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z", dir_name)
    if not m:
        return dir_name
    y, mo, d, h, mi, _s = m.groups()
    return f"{y}-{mo}-{d} {h}:{mi} UTC"


def extract_run(run_dir: Path):
    """Read result.json and return extracted data, or None on failure."""
    result_path = run_dir / "result.json"
    if not result_path.exists():
        return None

    try:
        with open(result_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  Warning: skipping {run_dir.name} — {e}", file=sys.stderr)
        return None

    flagged = data.get("flagged", [])
    if not isinstance(flagged, list):
        flagged = []

    run_id = run_dir.name

    # Index-level summary (lightweight)
    summary = {
        "id": run_id,
        "query": data.get("query", ""),
        "mode": data.get("mode", "unknown"),
        "status": data.get("status", "unknown"),
        "turns": data.get("turns", 0),
        "provider_count": data.get("provider_count", 0),
        "flags": len(flagged),
        "timestamp": parse_timestamp(run_id),
    }

    # Per-run detail (fetched on demand by report page)
    detail = {
        "id": run_id,
        "query": data.get("query", ""),
        "mode": data.get("mode", "unknown"),
        "status": data.get("status", "unknown"),
        "turns": data.get("turns", 0),
        "provider_count": data.get("provider_count", 0),
        "timestamp": parse_timestamp(run_id),
        "report_text": data.get("report_text", ""),
        "narration": data.get("narration", ""),
        "flagged": flagged,
    }

    return {"summary": summary, "detail": detail}


def main() -> None:
    if not OUTPUT_DIR.exists():
        print(f"Error: {OUTPUT_DIR} does not exist.", file=sys.stderr)
        sys.exit(1)

    # Ensure output directories exist
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    # Scan for timestamped run directories
    run_dirs = sorted(
        (d for d in OUTPUT_DIR.iterdir() if d.is_dir() and TIMESTAMP_RE.match(d.name)),
        key=lambda d: d.name,
        reverse=True,  # newest first
    )

    if not run_dirs:
        print("No timestamped run directories found in output/.")
        sys.exit(0)

    summaries = []
    for run_dir in run_dirs:
        print(f"  Processing {run_dir.name}...")
        result = extract_run(run_dir)
        if result is None:
            continue
        summaries.append(result["summary"])

        # Write per-run detail
        detail_path = RUNS_DIR / f"{run_dir.name}.json"
        with open(detail_path, "w", encoding="utf-8") as f:
            json.dump(result["detail"], f, ensure_ascii=False)
        size_kb = detail_path.stat().st_size / 1024
        print(f"    → {detail_path.name} ({size_kb:.0f} KB)")

    # Write index manifest
    manifest_path = DATA_DIR / "runs.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(summaries, f, ensure_ascii=False, indent=2)

    print(f"\nDone: {len(summaries)} runs → {manifest_path}")


if __name__ == "__main__":
    main()
