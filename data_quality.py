"""
Post-scrape data quality checks for ECOES Secure Communications.

Flags anomalies in the CSV output so they can be investigated or re-scraped.
Runs automatically at the end of each scrape, or standalone:

    python data_quality.py secure_comms_messages.csv
    python data_quality.py secure_comms_messages.csv --output dq_report.json
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def _parse_iso(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def run_quality_checks(rows: list[dict]) -> dict:
    """
    Analyse scraped rows and return a structured report of anomalies.

    Each check produces a list of flagged communication_ids with a reason.
    The report also includes aggregate stats for quick triage.
    """
    flags: list[dict] = []
    threads: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        cid = r.get("communication_id", "")
        if cid:
            threads[cid].append(r)

    # -- 1. Empty detail panel (no messages extracted) -------------------------
    for cid, thread_rows in threads.items():
        if all(str(r.get("message_index", "")) in ("0", "") for r in thread_rows):
            sample = thread_rows[0]
            flags.append({
                "check": "empty_detail",
                "severity": "high",
                "communication_id": cid,
                "detail": "Thread has no messages — detail panel likely failed to load",
                "bucket": sample.get("bucket", ""),
                "created_at": sample.get("created_at", ""),
                "updated_at": sample.get("updated_at", ""),
            })

    # -- 2. Missing metadata (inbox_title / reference) -------------------------
    for cid, thread_rows in threads.items():
        sample = thread_rows[0]
        missing = []
        if not (sample.get("inbox_title") or "").strip():
            missing.append("inbox_title")
        if not (sample.get("reference") or "").strip():
            missing.append("reference")
        if missing:
            flags.append({
                "check": "missing_metadata",
                "severity": "high",
                "communication_id": cid,
                "detail": f"Missing: {', '.join(missing)}",
                "bucket": sample.get("bucket", ""),
            })

    # -- 3. Missing MPXN -------------------------------------------------------
    for cid, thread_rows in threads.items():
        sample = thread_rows[0]
        if not (sample.get("mpxn_value") or "").strip():
            flags.append({
                "check": "missing_mpxn",
                "severity": "medium",
                "communication_id": cid,
                "detail": "No MPAN/MPRN value",
                "inbox_title": sample.get("inbox_title", ""),
                "bucket": sample.get("bucket", ""),
            })

    # -- 4. created_at > updated_at --------------------------------------------
    for cid, thread_rows in threads.items():
        sample = thread_rows[0]
        created = _parse_iso(sample.get("created_at", ""))
        updated = _parse_iso(sample.get("updated_at", ""))
        if created and updated and created > updated:
            flags.append({
                "check": "date_inversion",
                "severity": "medium",
                "communication_id": cid,
                "detail": f"created_at ({sample['created_at']}) > updated_at ({sample['updated_at']})",
                "bucket": sample.get("bucket", ""),
            })

    # -- 5. Dual-bucket (thread in both Current and Archived) ------------------
    for cid, thread_rows in threads.items():
        buckets = {r.get("bucket", "") for r in thread_rows}
        if len(buckets) > 1:
            flags.append({
                "check": "dual_bucket",
                "severity": "low",
                "communication_id": cid,
                "detail": f"Thread appears in multiple buckets: {', '.join(sorted(buckets))}",
            })

    # -- 6. Empty message content on non-zero message_index --------------------
    for cid, thread_rows in threads.items():
        for r in thread_rows:
            idx = str(r.get("message_index", ""))
            if idx not in ("0", "") and not (r.get("message_content") or "").strip():
                flags.append({
                    "check": "empty_content",
                    "severity": "medium",
                    "communication_id": cid,
                    "detail": f"message_index {idx} has no content",
                    "bucket": r.get("bucket", ""),
                })

    # -- 7. Missing sender_email on non-zero message_index ---------------------
    for cid, thread_rows in threads.items():
        for r in thread_rows:
            idx = str(r.get("message_index", ""))
            if idx not in ("0", "") and not (r.get("sender_email") or "").strip():
                flags.append({
                    "check": "missing_sender",
                    "severity": "medium",
                    "communication_id": cid,
                    "detail": f"message_index {idx} has no sender_email",
                    "bucket": r.get("bucket", ""),
                })

    # -- Summary stats ---------------------------------------------------------
    check_counts = Counter(f["check"] for f in flags)
    severity_counts = Counter(f["severity"] for f in flags)
    flagged_threads = sorted({f["communication_id"] for f in flags})

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_rows": len(rows),
        "total_threads": len(threads),
        "flagged_thread_count": len(flagged_threads),
        "flagged_threads": flagged_threads,
        "summary": {
            "by_check": dict(check_counts.most_common()),
            "by_severity": dict(severity_counts.most_common()),
        },
        "flags": flags,
    }


def print_report(report: dict) -> None:
    """Print a human-readable summary to stdout."""
    total = report["total_threads"]
    flagged = report["flagged_thread_count"]
    pct = (flagged / total * 100) if total else 0

    print(f"\n🔍 Data quality report ({report['total_rows']} rows, {total} threads)")
    print(f"   Flagged threads: {flagged}/{total} ({pct:.1f}%)")

    by_check = report["summary"]["by_check"]
    if not by_check:
        print("   No anomalies found.")
        return

    print()
    labels = {
        "empty_detail": "Empty detail panel (no messages)",
        "missing_metadata": "Missing inbox_title / reference",
        "missing_mpxn": "Missing MPAN/MPRN",
        "date_inversion": "created_at > updated_at",
        "dual_bucket": "Thread in both Current & Archived",
        "empty_content": "Message with empty content",
        "missing_sender": "Message with no sender_email",
    }
    severity_icon = {"high": "🔴", "medium": "🟡", "low": "🔵"}

    high_flags = [f for f in report["flags"] if f["severity"] == "high"]
    medium_flags = [f for f in report["flags"] if f["severity"] == "medium"]
    low_flags = [f for f in report["flags"] if f["severity"] == "low"]

    for severity, flag_list in [("high", high_flags), ("medium", medium_flags), ("low", low_flags)]:
        if not flag_list:
            continue
        icon = severity_icon[severity]
        grouped = Counter(f["check"] for f in flag_list)
        for check, count in grouped.most_common():
            label = labels.get(check, check)
            ids = sorted({f["communication_id"] for f in flag_list if f["check"] == check})
            print(f"   {icon} {label}: {count} flag(s) across {len(ids)} thread(s)")
            preview = ids[:5]
            print(f"      IDs: {', '.join(preview)}{'...' if len(ids) > 5 else ''}")


def save_report(report: dict, path: str) -> None:
    """Write the full report to JSON."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(report, indent=2), encoding="utf-8")


def check_csv(csv_path: str, report_path: str | None = None) -> dict:
    """Load a CSV and run all quality checks. Optionally save the JSON report."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    report = run_quality_checks(rows)
    print_report(report)
    if report_path:
        save_report(report, report_path)
        print(f"\n   Full report saved to {report_path}")
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run data quality checks on scraped ECOES Secure Communications CSV.")
    parser.add_argument("csv_path", help="Path to the CSV file to check")
    parser.add_argument("--output", "-o", default=None, help="Path to save the JSON report (default: dq_report.json alongside CSV)")
    args = parser.parse_args()

    report_path = args.output or str(Path(args.csv_path).with_name("dq_report.json"))
    check_csv(args.csv_path, report_path)
