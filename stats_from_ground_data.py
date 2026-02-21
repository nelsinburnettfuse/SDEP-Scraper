#!/usr/bin/env python3
"""
Statistics and analyses on the scraped ground data (message-level CSV).

Backlog is defined here, on top of the extracted data (not in the scraper):
  Backlog = conversations where we are NOT the last person to respond
  (i.e. the last message in the thread is from another party).

Assumes CSV columns: communication_id, reference, subject, escalation_level,
message_index, sender_email, message_timestamp, message_content; optional: bucket.

Run after scrape_all_communications.py has produced secure_comms_messages.csv.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Collection

import pandas as pd


def load_messages(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    # Parse timestamps for time-based stats
    ts_col = "message_timestamp"
    if ts_col in df.columns and df[ts_col].notna().any():
        df["msg_dt"] = pd.to_datetime(df[ts_col], errors="coerce")
    if "last_escalation" in df.columns:
        df["last_esc_dt"] = pd.to_datetime(df["last_escalation"], errors="coerce")
    return df


def _is_our_sender(email: str, our_domains: Collection[str]) -> bool:
    """True if sender email's domain is in our_domains (e.g. fuseenergy.com)."""
    if pd.isna(email) or not str(email).strip() or "@" not in str(email):
        return False
    domain = str(email).strip().lower().split("@", 1)[-1]
    return domain in {d.lower() for d in our_domains}


def last_message_per_thread(
    df: pd.DataFrame,
    our_domains: Collection[str] = ("fuseenergy.com",),
) -> pd.DataFrame:
    """
    One row per thread: last message info and whether we sent it.
    Thread is in backlog iff the last message is not from us.
    """
    if "communication_id" not in df.columns or "sender_email" not in df.columns:
        return pd.DataFrame()
    id_col = "communication_id"
    if "msg_dt" in df.columns and df["msg_dt"].notna().any():
        idx = df.groupby(id_col)["msg_dt"].idxmax()
    else:
        idx = df.groupby(id_col)["message_index"].idxmax()
    last_rows = df.loc[idx].copy()
    last_rows["we_sent_last"] = last_rows["sender_email"].map(
        lambda e: _is_our_sender(e, our_domains)
    )
    last_rows["in_backlog"] = ~last_rows["we_sent_last"]
    return last_rows


def backlog_by_escalation(
    df: pd.DataFrame,
    our_domains: Collection[str] = ("fuseenergy.com",),
    bucket_col: str | None = "bucket",
) -> pd.DataFrame:
    """
    Backlog = conversations where we are not the last to respond.
    Returns counts of threads in backlog by escalation_level (and optionally by bucket).
    """
    threads = last_message_per_thread(df, our_domains=our_domains)
    if threads.empty or "in_backlog" not in threads.columns:
        return pd.DataFrame()
    backlog = threads[threads["in_backlog"]]
    group_cols = []
    if "escalation_level" in backlog.columns:
        group_cols.append("escalation_level")
    if bucket_col and bucket_col in backlog.columns:
        group_cols.append(bucket_col)
    if not group_cols:
        return pd.DataFrame({"backlog_count": [len(backlog)]})
    return backlog.groupby(group_cols, dropna=False).size().reset_index(name="backlog_count")


def responses_per_day(df: pd.DataFrame, our_domain: str = "fuseenergy.com") -> pd.Series:
    """
    Count how many responses we send per day (messages where sender is from our domain).
    """
    if "sender_email" not in df.columns:
        return pd.Series(dtype=int)
    ours = df[df["sender_email"].astype(str).str.lower().str.contains(our_domain, na=False)]
    if "msg_dt" not in ours.columns:
        return pd.Series(dtype=int)
    return ours.set_index("msg_dt").resample("D").size()


def agent_response_counts(df: pd.DataFrame, email_col: str = "sender_email") -> pd.Series:
    """
    Count how many messages each agent (sender email) sent.
    Use message_content or message_type to restrict to "reply" only if desired.
    """
    if email_col not in df.columns:
        return pd.Series(dtype=int)
    return df[email_col].value_counts()


def run_examples(
    csv_path: str,
    our_domains: Collection[str] = ("fuseenergy.com",),
) -> None:
    df = load_messages(csv_path)
    if df.empty:
        print("No data in CSV.")
        return
    our_domain = our_domains[0] if our_domains else "fuseenergy.com"
    print("--- Backlog by escalation (we are not last responder) ---")
    backlog = backlog_by_escalation(df, our_domains=our_domains)
    if not backlog.empty:
        print(backlog.to_string(index=False))
    else:
        print("(no data or missing communication_id/sender_email)")
    print("\n--- Responses per day (our domain: %s) ---" % our_domain)
    rpd = responses_per_day(df, our_domain=our_domain)
    print(rpd.tail(14))
    print("\n--- Top senders (agent activity) ---")
    print(agent_response_counts(df).head(20))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Stats on scraped ECOES messages. Backlog = threads where we are not the last responder."
    )
    parser.add_argument("csv", nargs="?", default="secure_comms_messages.csv", help="Message-level CSV path")
    parser.add_argument(
        "--our-domain",
        action="append",
        default=None,
        dest="our_domains",
        help="Domain(s) that count as 'us' for backlog (default: fuseenergy.com). Repeatable.",
    )
    parser.add_argument(
        "--backlog-only",
        action="store_true",
        help="Only print backlog-by-escalation table (for piping/dashboards).",
    )
    args = parser.parse_args()
    our_domains = tuple(args.our_domains) if args.our_domains else ("fuseenergy.com",)
    if args.backlog_only:
        df = load_messages(args.csv)
        if not df.empty:
            out = backlog_by_escalation(df, our_domains=our_domains)
            print(out.to_string(index=False) if not out.empty else "no_backlog_data")
        else:
            print("no_data")
    else:
        run_examples(args.csv, our_domains=our_domains)
