#!/usr/bin/env python3
"""
ECOES Secure Communications – full-data scraper.

Pulls all threads (Initiated + Recipient), opens each thread, and extracts:
- Thread: Reference, Subject, Escalation Level, From, To, Last Escalation, Owner
- Sender Data Items: Meter Point Number (and any other visible fields)
- Messages: every message in the thread (type, sender, timestamp, content)

Output: one CSV row per message, with thread fields repeated for each message.
Designed so you can filter/reconstruct and run statistics on the ground data.

Usage:
  1. First run: log in manually if needed, then run with HEADLESS=false to capture session.
  2. Or: log in in the browser, then run with ECOES_STORAGE_STATE=ecoes_session.json
        after saving the session (see Playwright docs).
  3. pip install -r requirements.txt && playwright install chromium
  4. python scrape_all_communications.py

  To capture the detail panel DOM (for fixing reference/subject/from/to parsing):
  python scrape_all_communications.py --save-dom debug_detail_panel.html --max-current 1
  Then share debug_detail_panel.html (or the header section) so selectors can be matched.

  Archived pass stops when a thread's last message is in 2025 (config: ARCHIVED_STOP_YEAR).
  Scroll and open are interleaved so we don't load the full archived list unnecessarily.
"""
from __future__ import annotations

import csv
import json
import re
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeout

try:
    from bs4 import BeautifulSoup
except ImportError:
    raise SystemExit(
        "Missing dependency: run 'uv sync' (or 'pip install beautifulsoup4') and run with the same environment, e.g. 'uv run python scrape_all_communications.py'"
    ) from None

import config

# Regex for communication_id from a[data-ajax-url] (same as Original Script)
COMM_ID_RE = re.compile(r"communicationId=(\d+)")

# ECOES message timestamp format e.g. "20 Feb 2026 17:07"
_MSG_TS_FMTS = ("%d %b %Y %H:%M", "%d %b %Y")


def _parse_date_str_to_date(date_str: str) -> datetime | None:
    """Parse ECOES date string to datetime; returns None if unparseable."""
    s = (date_str or "").strip()
    if not s:
        return None
    for fmt in _MSG_TS_FMTS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None

def _date_str_to_iso(date_str: str) -> str:
    """Convert ECOES date string to ISO 8601 for CSV so Metabase (and text sort) orders correctly. Returns original if unparseable."""
    dt = _parse_date_str_to_date(date_str)
    if dt is None:
        return (date_str or "").strip()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _updated_date_year(updated_date_str: str) -> int | None:
    """
    Parse last-edited/updated date from list row (e.g. "20 Feb 2026" or "15 Dec 2024 10:30").
    Returns the year, or None if unparseable. Used to stop archived pass when last edited < 2025.
    """
    dt = _parse_date_str_to_date(updated_date_str)
    return dt.year if dt else None


def _last_message_year(thread_data: dict) -> int | None:
    """
    Return the year of the latest message in the thread, or None if we can't parse.
    Used to stop the archived pass when we reach threads last active in 2025.
    """
    messages = thread_data.get("messages") or []
    if not messages:
        return None
    years = []
    for m in messages:
        ts = (m.get("timestamp") or "").strip()
        if not ts:
            continue
        for fmt in _MSG_TS_FMTS:
            try:
                dt = datetime.strptime(ts, fmt)
                years.append(dt.year)
                break
            except ValueError:
                continue
    return max(years) if years else None


def ensure_filters_include_all(page: Page) -> None:
    """Ensure both Initiated and Recipient are selected so we get all communications.
    Uses force=True because the checkboxes may be in a collapsed/hidden sidebar.
    """
    for checkbox_id in ("#checkBoxSent", "#checkBoxReceived"):
        loc = page.locator(checkbox_id).first
        if loc.count():
            try:
                loc.check(force=True)
            except Exception:
                pass
    page.wait_for_timeout(200)


def _archived_checkbox_checked(page: Page) -> bool | None:
    """Read whether the Archived checkbox is checked (scoped to the folder panel)."""
    try:
        # Checkbox may be inside the archived item; id is unique on page
        el = page.locator(f"#{config.ARCHIVED_CHECKBOX_ID}").first
        if el.count():
            return el.is_checked()
    except Exception:
        pass
    return None


def set_archived(page: Page, want_archived: bool) -> bool:
    """
    Set the Archived folder toggle on or off (Communication Folders left panel).
    Tries click targets first, then JS fallback (ECOES uses custom tick UI).
    """
    try:
        page.wait_for_selector(config.ARCHIVED_ITEM_SEL, state="attached", timeout=10000)
    except Exception:
        print("  ⚠️ Archived panel item not found")
        return False

    if _archived_checkbox_checked(page) == want_archived:
        return True

    # Scroll the left panel so Archived item is visible (panel may be scrollable)
    try:
        page.locator(config.ARCHIVED_ITEM_SEL).first.scroll_into_view_if_needed(timeout=2000)
        page.wait_for_timeout(150)
    except Exception:
        pass

    # Click targets: ECOES often binds to the item or the tick label (same as ecoes_export)
    click_targets = [
        config.ARCHIVED_ITEM_SEL,
        f"{config.ARCHIVED_ITEM_SEL} label.user-tick span.fa-stack",
        f"{config.ARCHIVED_ITEM_SEL} .square-tick-box",
        f"{config.ARCHIVED_ITEM_SEL} label.process-type-label",
        f"{config.ARCHIVED_ITEM_SEL} #{config.ARCHIVED_CHECKBOX_ID}",
    ]
    for sel in click_targets:
        loc = page.locator(sel).first
        if loc.count():
            try:
                loc.click(timeout=2500, force=True, position={"x": 8, "y": 8})
            except Exception:
                try:
                    loc.click(timeout=2500, force=True)
                except Exception:
                    continue
            for _ in range(8):
                page.wait_for_timeout(100)
                if _archived_checkbox_checked(page) == want_archived:
                    break
            if _archived_checkbox_checked(page) == want_archived:
                break

    # JavaScript fallback: set checkbox and fire events so app state updates (like ecoes_export)
    if _archived_checkbox_checked(page) != want_archived:
        try:
            page.evaluate(
                """(desired) => {
                    const cb = document.getElementById('checkBoxShowArchived');
                    if (!cb) return false;
                    cb.checked = !!desired;
                    cb.dispatchEvent(new Event('input',  { bubbles: true }));
                    cb.dispatchEvent(new Event('change', { bubbles: true }));
                    return cb.checked === !!desired;
                }""",
                want_archived,
            )
            page.wait_for_timeout(200)
        except Exception:
            pass

    # Trigger list refresh so results update
    for refresh_sel in (config.SEARCH_BUTTON_SEL, config.CLEAR_FILTER_SEL):
        try:
            if page.locator(refresh_sel).count():
                page.locator(refresh_sel).first.click(timeout=2000, force=True)
                break
        except Exception:
            pass
    page.wait_for_timeout(600)
    return _archived_checkbox_checked(page) == want_archived


def wait_list_after_scope_change(page: Page, timeout_ms: int = 20000) -> None:
    """After toggling Archived, wait for the list to refresh (spinner then rows)."""
    try:
        if page.locator(".infinite-scroll-load:not(.hide)").count():
            page.locator(".infinite-scroll-load").first.wait_for(state="hidden", timeout=timeout_ms)
    except Exception:
        pass
    page.wait_for_timeout(400)


def wait_list_ready(page: Page, timeout_ms: int = 60000) -> None:
    """Wait until at least one row is visible (same as Original Script)."""
    page.wait_for_selector(config.ROW_SEL, timeout=timeout_ms)


def wait_list_ready_with_feedback(page: Page, timeout_ms: int = 120000) -> bool:
    """
    Wait for the communication list, print progress every 15s, and if we're
    still not on the list page after 30s, try re-navigating once (login often redirects away).
    Returns True if list appeared, False if timeout.
    """
    interval_ms = 15000
    elapsed = 0
    re_navigated = False
    while elapsed < timeout_ms:
        if page.locator(config.ROW_SEL).count() > 0:
            print("List loaded.")
            return True
        if elapsed > 0 and elapsed % interval_ms == 0:
            url = page.url
            print(f"  … still waiting for list ({elapsed // 1000}s) — current page: {url[:80]}…")
            if elapsed >= 30000 and "SecureCommunications" not in url and not re_navigated:
                print("  Re-navigating to Secure Communications (login may have redirected away).")
                page.goto(config.APP_URL, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                re_navigated = True
        page.wait_for_timeout(2000)
        elapsed += 2000
    print(f"Timed out after {timeout_ms // 1000}s. Current URL: {page.url}")
    return False


def scroll_to_load_all_threads(page: Page) -> None:
    """
    Scroll until no new rows load. Aligned with Original: mouse.wheel, wait for
    .infinite-scroll-load to hide, stagnant count 6 or max 250 loops.
    """
    last_count = -1
    stagnant = 0
    for _ in range(config.SCROLL_MAX_LOOPS):
        page.mouse.wheel(0, 8000)
        time.sleep(config.SCROLL_PAUSE_SEC)
        if page.locator(".infinite-scroll-load:not(.hide)").count():
            try:
                page.locator(".infinite-scroll-load").first.wait_for(state="hidden", timeout=10000)
            except Exception:
                pass
        count = page.locator(config.ROW_SEL).count()
        if count == last_count:
            stagnant += 1
        else:
            stagnant, last_count = 0, count
        if stagnant >= config.SCROLL_STAGNANT_MAX:
            break
    print(f"Loaded {last_count} rows.")


def scroll_to_load_more_threads(page: Page, max_steps: int | None = None) -> int:
    """
    Scroll a limited number of steps to load more rows (for archived pass).
    Returns the new row count. Use to interleave scroll with opening threads
    so we don't load the entire list before checking "last message in 2025".
    """
    steps = max_steps or getattr(config, "ARCHIVED_SCROLL_STEPS", 12)
    last_count = page.locator(config.ROW_SEL).count()
    for _ in range(steps):
        page.mouse.wheel(0, 8000)
        time.sleep(config.SCROLL_PAUSE_SEC)
        if page.locator(".infinite-scroll-load:not(.hide)").count():
            try:
                page.locator(".infinite-scroll-load").first.wait_for(state="hidden", timeout=10000)
            except Exception:
                pass
        count = page.locator(config.ROW_SEL).count()
        if count > last_count:
            last_count = count
    return last_count


def get_communication_id_from_row(row_locator) -> str:
    """Extract communication_id from row's a[data-ajax-url] (same as Original parse_row)."""
    try:
        url = row_locator.locator("a[data-ajax-url]").first.get_attribute("data-ajax-url") or ""
        m = COMM_ID_RE.search(url)
        return m.group(1) if m else ""
    except Exception:
        return ""


def _date_from_icon_in_row(row_locator, data_original_title: str) -> str:
    """
    Extract date from the thread list row next to an icon with the given data-original-title.
    Tries parent text, following sibling, then title attribute. Used for both created and updated.
    """
    try:
        icon = row_locator.locator(f'span[data-original-title="{data_original_title}"]').first
        if not icon.count():
            return ""
        parent = icon.locator("xpath=..")
        if parent.count():
            text = (parent.first.inner_text() or "").strip()
            for label in (data_original_title, data_original_title.lower()):
                if label and text.lower().startswith(label.lower()):
                    text = text[len(label) :].strip()
                    break
            if text and re.search(r"\d", text):
                return text
        sibling = icon.locator("xpath=following-sibling::*").first
        if sibling.count():
            text = (sibling.inner_text() or "").strip()
            if text and re.search(r"\d", text):
                return text
        title = (icon.get_attribute("title") or "").strip()
        if title and re.search(r"\d", title):
            return title
    except Exception:
        pass
    return ""


# Match ECOES date in text: "19 Feb 2026" or "19 Feb 2026 14:30"
_DATE_IN_TEXT_RE = re.compile(
    r"\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}(?:\s+\d{1,2}:\d{2})?"
)


def _dates_from_row_by_regex(row_locator) -> list[str]:
    """
    Get all ECOES-format dates from this row only: row_locator.inner_text() is taken from
    the single element (one div.communication-row), then we findall(_DATE_IN_TEXT_RE).
    Returns them in the order they appear. Used as:
      - When 2 dates: position 0 = created_at, position 1 = updated_at.
      - When 3+ dates: position 0 is often subject/preview; we use position 1 = created_at, position 2 = updated_at.
    """
    try:
        text = (row_locator.inner_text() or "").strip()
        if not text:
            return []
        return _DATE_IN_TEXT_RE.findall(text)
    except Exception:
        return []


def _all_dates_from_row_in_order(row_locator) -> list[str]:
    """
    Find all spans in the row with data-original-title (date tooltips) and extract date text
    in DOM order. Each icon should yield one date: we use the icon's following-sibling first
    (so we don't take the same parent text for both). If parent has both dates, we split by
    regex and assign by icon index. Returns list of date strings; first=created, second=updated.
    """
    out: list[str] = []
    try:
        icons = row_locator.locator("span[data-original-title]")
        n = icons.count()
        for i in range(n):
            icon = icons.nth(i)
            text = ""
            # Prefer following-sibling: usually the date for this icon only
            sibling = icon.locator("xpath=following-sibling::*").first
            if sibling.count():
                text = (sibling.inner_text() or "").strip()
            if not text or not re.search(r"\d", text):
                parent = icon.locator("xpath=..")
                if parent.count():
                    text = (parent.first.inner_text() or "").strip()
            if not text or not re.search(r"\d", text):
                text = (icon.get_attribute("title") or "").strip()
            if not text or not re.search(r"\d", text):
                continue
            # Strip label prefixes
            for prefix in ("Updated Date", "Created Date", "Modified Date", "Last Updated", "Updated", "Created", "Modified"):
                if text.lower().startswith(prefix.lower()):
                    text = text[len(prefix) :].strip()
                    break
            # If text has multiple dates (e.g. "19 Feb 2026 24 Feb 2026"), take the i-th one
            dates_in_text = _DATE_IN_TEXT_RE.findall(text)
            if len(dates_in_text) > i:
                out.append(dates_in_text[i])
            elif dates_in_text:
                out.append(dates_in_text[0])
            elif re.search(r"\d", text):
                out.append(text)
    except Exception:
        pass
    return out


def get_created_and_updated_date_from_row(row_locator) -> tuple[str, str, str]:
    """
    Extract created_at and updated_at from this list row. Returns (created_at, updated_at, source).
    source describes what was used so logs/UI can show exactly what was picked off the page.

    - Primary: regex on this row's inner_text(); we take the 1st match as created_at, 2nd as updated_at.
    - Fallback: icon-based (span[data-original-title]) in DOM order.
    """
    # Primary: from this row's text. When 3+ dates, 1st is often subject/preview so use 2nd=created_at, 3rd=updated_at. When 2 dates, use 1st=created_at, 2nd=updated_at.
    by_regex = _dates_from_row_by_regex(row_locator)
    if len(by_regex) >= 3:
        return (by_regex[1], by_regex[2], f"row text: 2nd date={by_regex[1]!r}, 3rd date={by_regex[2]!r} ({len(by_regex)} dates in row, 1st ignored)")
    if len(by_regex) == 2:
        return (by_regex[0], by_regex[1], f"row text: 1st date={by_regex[0]!r}, 2nd date={by_regex[1]!r} (2 dates in row)")
    if len(by_regex) == 1:
        return (by_regex[0], "", f"row text: 1st date={by_regex[0]!r} (only 1 date in row)")

    all_dates = _all_dates_from_row_in_order(row_locator)
    if len(all_dates) >= 2:
        return (all_dates[0], all_dates[1], f"row icons: 1st={all_dates[0]!r}, 2nd={all_dates[1]!r}")
    if len(all_dates) == 1:
        return (all_dates[0], "", "row icons: 1 date")
    # Fallback: try title-based matching
    created = ""
    titles_created = getattr(config, "CREATED_DATE_TITLES", ("Updated Date",))
    for title in titles_created:
        created = _date_from_icon_in_row(row_locator, title)
        if created:
            break
    updated = ""
    if not created:
        return ("", "", "none")
    titles_updated = getattr(config, "UPDATED_DATE_TITLES", ("Modified Date", "Last Updated", "Updated"))
    for title in titles_updated:
        val = _date_from_icon_in_row(row_locator, title)
        if val and val != created:
            updated = val
            break
    return (created, updated, "row icons by title")


def get_thread_rows(page: Page) -> list[dict]:
    """
    Collect all thread rows. Each item: index, locator, communication_id, created_at, updated_at, dates_source.
    dates_source says exactly what was picked (e.g. "row text: 1st date=..., 2nd date=... (2 dates in row)").
    """
    rows = page.locator(config.ROW_SEL)
    n = rows.count()
    out = []
    for i in range(n):
        loc = rows.nth(i)
        comm_id = get_communication_id_from_row(loc)
        created_at, updated_at, dates_source = get_created_and_updated_date_from_row(loc)
        out.append({
            "index": i,
            "locator": loc,
            "communication_id": comm_id,
            "created_at": created_at,
            "updated_at": updated_at,
            "dates_source": dates_source,
        })
    return out


def read_mpxn(page: Page) -> tuple[str, str]:
    """
    Read MPAN/MPRN from the open detail panel. Same logic as Original Script:
    input[placeholder='MPAN'] / input[placeholder='MPRN'], value as digits-only.
    Returns (mpxn_type, mpxn_value) e.g. ('MPAN', '123...') or ('', '').
    """
    for lab in ("MPAN", "MPRN"):
        try:
            loc = page.locator(f'input[placeholder="{lab}"]').first
            if loc.count():
                val = (loc.get_attribute("value") or "").strip()
                if val:
                    return lab, re.sub(r"\D+", "", val)
        except Exception:
            pass
    try:
        html = page.content()
        m = re.search(
            r'span[^>]+data-original-title=["\']\s*(MPAN|MPRN)\s*["\'][^<]{0,400}?<input[^>]+value=["\']([^"\']+)["\']',
            html, re.I | re.S,
        )
        if m:
            return m.group(1).upper(), re.sub(r"\D+", "", m.group(2))
    except Exception:
        pass
    return "", ""


# Regex to find "email" + "date" in content when DOM doesn't separate them (e.g. "user@domain.com20 Feb 2026 17:25")
_EMAIL_DATE_RE = re.compile(
    r"([\w.-]+@[\w.-]+\.\w+)\s*"
    r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\s+\d{1,2}:\d{2})"
)


def _split_content_into_messages(blob: str) -> list[dict]:
    """
    When sender_email/timestamp are empty but content has "email + date" blocks,
    split into one message per block. Returns list of {"sender_email", "timestamp", "content"}.
    """
    blob = (blob or "").strip()
    if not blob or "@" not in blob:
        return []
    parts = _EMAIL_DATE_RE.split(blob)
    # split with 2 groups gives: [preamble, email1, date1, body1, email2, date2, body2, ...]
    if len(parts) < 3:
        return []
    out = []
    for i in range(1, len(parts), 3):
        email = (parts[i] or "").strip()
        ts = (parts[i + 1] or "").strip()
        body = (parts[i + 2] or "").strip() if i + 2 < len(parts) else ""
        if email or ts or body:
            out.append({
                "sender_email": email,
                "timestamp": ts,
                "content": body[:2000],
            })
    return out


def _strip_trailing_meta(text: str, sender: str, ts: str) -> str:
    """Remove sender and timestamp from the end of message content (they appear below body in the DOM)."""
    if not text:
        return text
    text = text.strip()
    # Remove in either order, with optional whitespace between/after
    for _ in range(4):  # allow date then email, or email then date, plus extra newlines
        orig = text
        if ts and text.endswith(ts):
            text = text[: -len(ts)].strip()
        if sender and text.endswith(sender):
            text = text[: -len(sender)].strip()
        # combined with newline or space
        if ts and sender:
            for sep in ("\n", " ", "\n\n"):
                suffix = (ts + sep + sender).strip()
                if suffix and text.endswith(suffix):
                    text = text[: -len(suffix)].strip()
                suffix = (sender + sep + ts).strip()
                if suffix and text.endswith(suffix):
                    text = text[: -len(suffix)].strip()
        if text == orig:
            break
    return text


def parse_detail_panel_html(html: str) -> dict:
    """
    Parse the #communication-detail inner HTML into structured fields.
    Returns dict with thread-level fields and a list of messages.
    """
    soup = BeautifulSoup(html, "html.parser")

    def text_of(sel: str) -> str:
        el = soup.select_one(sel)
        return (el.get_text(strip=True) or "").strip() if el else ""

    def label_value(label_text: str) -> str:
        # Find a label (e.g. "Reference:") and return the following value
        for tag in soup.find_all(string=re.compile(re.escape(label_text), re.I)):
            parent = tag.parent
            if not parent:
                continue
            # Next sibling or same block
            next_ = parent.find_next_sibling()
            if next_:
                return next_.get_text(strip=True) or ""
            # Sometimes value is in same element after colon
            full = parent.get_text(strip=True) or ""
            if ":" in full:
                return full.split(":", 1)[-1].strip()
        return ""

    # Inbox/thread title at top of detail (e.g. "PT0033 - Disputed Meter Readings (Gas.) - Escalation")
    # ECOES uses <h4 class=""> for this title; exclude label-like lines (Last Escalated, Owner, Reference, etc.)
    _reject_title = re.compile(
        r"^(Reference|Subject|Escalation Level|From|To|Last Escalated|Owner\s*\(.*\)):\s*",
        re.I,
    )
    inbox_title = ""
    for sel in ("h4", "h1", "h2", "h3", ".panel-title", ".detail-title", ".sec-comms-detail-header h4", ".sec-comms-detail-header h1", ".sec-comms-detail-header h2"):
        el = soup.select_one(sel)
        if el:
            t = (el.get_text(strip=True) or "").strip()
            if t and len(t) > 2 and not _reject_title.match(t):
                inbox_title = t
                break
    if not inbox_title:
        for p in soup.select(".sec-comms-detail-header p"):
            full = (p.get_text(strip=True) or "").strip()
            if full and not _reject_title.match(full):
                inbox_title = full
                break

    # Detail header: same logic as escalation – .sec-comms-detail-header p, get_text(strip=True), regex "Label:\s*(.+)$"
    ref = subject = from_ = to_ = escalation = ""
    for p in soup.select(".sec-comms-detail-header p"):
        full = (p.get_text(strip=True) or "").strip()
        if not full:
            continue
        m = re.search(r"Reference:\s*(.+)$", full, re.I)
        if m:
            ref = m.group(1).strip()
            continue
        m = re.search(r"Subject:\s*(.+)$", full, re.I)
        if m:
            subject = m.group(1).strip()
            continue
        m = re.search(r"From:\s*(.+)$", full, re.I)
        if m:
            from_ = " ".join(m.group(1).strip().split())
            continue
        m = re.search(r"To:\s*(.+)$", full, re.I)
        if m:
            to_ = " ".join(m.group(1).strip().split())
            continue
        m = re.search(r"Escalation Level:\s*(.+)$", full, re.I)
        if m:
            escalation = m.group(1).strip()
            continue

    ref = ref or label_value("Reference") or text_of("[data-field='reference']")
    subject = subject or label_value("Subject") or text_of("[data-field='subject']")
    escalation = escalation or label_value("Escalation Level") or text_of("[data-field='escalation']")
    from_ = from_ or label_value("From") or text_of("[data-field='from']")
    to_ = to_ or label_value("To") or text_of("[data-field='to']")

    # Sender Data Items: look for a long numeric value (Meter Point Number)
    meter_point = ""
    for inp in soup.select("input[readonly], .form-control.readonly, [readonly]"):
        val = inp.get("value") or ""
        if val.isdigit() and len(val) >= 10:
            meter_point = val
            break
    if not meter_point:
        for div in soup.select(".sender-data-item, .data-item, [data-sender-item]"):
            t = div.get_text(strip=True) or ""
            if t.isdigit() and len(t) >= 10:
                meter_point = t
                break

    # Messages: use same DOM structure as ecoes_export.py (works reliably)
    # ECOES uses #cd-timeline .cd-timeline-block per message; within each: .cd-little (sender), .cd-date (time), .cd-timeline-content for body
    messages = []
    msg_containers = soup.select("#cd-timeline .cd-timeline-block")
    if not msg_containers:
        msg_containers = soup.select(".cd-timeline-block")
    if not msg_containers:
        msg_containers = soup.select(".message-item, .timeline-item, [data-message], .message-content, .comm-message")
    for mc in msg_containers:
        def t(sel):
            el = mc.select_one(sel)
            return (el.get_text(strip=True) or "").strip() if el else ""

        # Sender and date: same selectors as ecoes_export.py
        sender = mc.get("data-sender") or t(".cd-little") or t(".sender-email") or t("[data-sender]") or ""
        ts = mc.get("data-timestamp") or t(".cd-date") or t(".message-date") or t(".timestamp") or ""

        # Body: ecoes_export uses .cd-timeline-content > div span; fallbacks for other layouts
        body = (
            t(".cd-timeline-content div span")
            or t(".cd-timeline-content > div span")
            or t(".cd-timeline-content")
            or t(".message-body")
            or t(".message-text")
            or (mc.get_text(strip=True) or "")
            or ""
        )
        # Strip trailing sender and timestamp so they don't appear in content (they're in cd-little / cd-date below the body)
        if body and (sender or ts):
            body = _strip_trailing_meta(body, sender.strip(), ts.strip())

        # Infer message type from icon if present (same as ecoes_export: fa-envelope = message, fa-paperclip = attachment)
        msg_type = mc.get("data-type") or t(".message-type") or ""
        if not msg_type and mc.select_one(".cd-timeline-img i.fa-envelope"):
            msg_type = "message"
        if not msg_type and mc.select_one(".cd-timeline-img i.fa-paperclip"):
            msg_type = "attachment"
        if not msg_type and mc.select_one(".cd-timeline-img i.fa-exclamation"):
            msg_type = "system"
        if not msg_type:
            msg_type = "message"

        if not sender and not body and not ts:
            continue
        messages.append({
            "message_type": msg_type.strip(),
            "sender_email": sender.strip(),
            "timestamp": ts.strip(),
            "content": body[:2000],
        })

    # Fallback: any block that looks like "reply" / "escalation" with email and date
    if not messages:
        for block in soup.select(".panel, .bubble, .message, [class*='message']"):
            text = block.get_text(strip=True) or ""
            if "@" in text and re.search(r"\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}", text):
                messages.append({
                    "message_type": "reply" if "reply" in text.lower() else "other",
                    "sender_email": "",
                    "timestamp": "",
                    "content": text[:2000],
                })

    # When DOM didn't separate sender/timestamp, content can be a blob of "body + email + date" repeated.
    # Split any such message into one row per email+date block.
    expanded = []
    for m in messages:
        if not m.get("sender_email") and not m.get("timestamp") and m.get("content"):
            split_msgs = _split_content_into_messages(m["content"])
            if split_msgs:
                for sm in split_msgs:
                    expanded.append({
                        "message_type": m.get("message_type", ""),
                        "sender_email": sm.get("sender_email", ""),
                        "timestamp": sm.get("timestamp", ""),
                        "content": (sm.get("content") or "")[:2000],
                    })
                continue
        expanded.append(m)
    messages = expanded

    return {
        "inbox_title": inbox_title,
        "reference": ref,
        "subject": subject,
        "escalation_level": escalation,
        "from": from_,
        "to": to_,
        "meter_point_number": meter_point,
        "messages": messages,
    }


def open_thread_and_parse(page: Page, row_info: dict) -> dict | None:
    """
    Open thread via a[data-ajax-url] (same as Original), wait for detail,
    read MPxN from page, parse #communication-detail HTML. Close with Escape.
    """
    loc = row_info["locator"]
    comm_id = row_info.get("communication_id") or ""
    link = loc.locator("a[data-ajax-url]").first
    if not link.count():
        return None
    try:
        if comm_id:
            with page.expect_response(
                lambda r: ("GetCommunication" in r.url) and (f"communicationId={comm_id}" in r.url),
                timeout=config.EXPECT_RESPONSE_TIMEOUT_MS,
            ) as resp_wait:
                link.click(timeout=2000)
            _ = resp_wait.value
        else:
            link.click(timeout=2000)
    except Exception:
        try:
            link.evaluate("el => el.click()")
        except Exception:
            try:
                loc.click(force=True, timeout=1000)
            except Exception:
                return None
    try:
        page.wait_for_selector(
            "input[placeholder='MPAN'], input[placeholder='MPRN']",
            timeout=config.WAIT_MPAN_MPRN_TIMEOUT_MS,
        )
    except Exception:
        pass
    page.wait_for_timeout(config.CLICK_WAIT_MS)
    mpxn_type, mpxn_value = read_mpxn(page)
    detail = page.locator(config.SELECTOR_DETAIL_PANEL).first
    if not detail.count():
        _close_detail(page)
        return _thread_data_from_row_only(row_info, mpxn_type, mpxn_value)
    html = detail.inner_html()
    # Optional: save detail panel HTML for debugging (e.g. to fix reference/subject/from/to parsing)
    save_dom_path = getattr(open_thread_and_parse, "_debug_save_dom_path", None)
    if save_dom_path:
        Path(save_dom_path).write_text(html, encoding="utf-8")
        print(f"  [debug] Wrote detail panel DOM to {save_dom_path}")
    _close_detail(page)
    if not html or len(html) < 50:
        return _thread_data_from_row_only(row_info, mpxn_type, mpxn_value)
    data = parse_detail_panel_html(html)
    data["communication_id"] = comm_id
    data["mpxn_type"] = mpxn_type
    data["mpxn_value"] = mpxn_value
    data["meter_point_number"] = mpxn_value or data.get("meter_point_number", "")
    data["created_at"] = row_info.get("created_at", "")
    data["updated_at"] = row_info.get("updated_at", "")
    return data


def _close_detail(page: Page) -> None:
    """Close detail panel (Original uses Escape). Uses CLOSE_DETAIL_MS from config when set (e.g. in fast mode)."""
    try:
        page.keyboard.press("Escape")
        wait_ms = getattr(config, "CLOSE_DETAIL_MS", 200)
        page.wait_for_timeout(wait_ms)
    except Exception:
        pass


def _thread_data_from_row_only(row_info: dict, mpxn_type: str, mpxn_value: str) -> dict:
    """Minimal thread data when detail HTML cannot be parsed."""
    return {
        "communication_id": row_info.get("communication_id", ""),
        "inbox_title": "",
        "reference": "",
        "subject": "",
        "escalation_level": "",
        "from": "",
        "to": "",
        "meter_point_number": mpxn_value,
        "mpxn_type": mpxn_type,
        "mpxn_value": mpxn_value,
        "created_at": row_info.get("created_at", ""),
        "updated_at": row_info.get("updated_at", ""),
        "messages": [],
    }


def _message_direction(sender_email: str, outbound_domains: set[str] | None = None) -> str:
    """Return 'outbound' if sender's domain is in outbound_domains (e.g. fuseenergy.com), else 'inbound'."""
    domains = outbound_domains or getattr(config, "OUTBOUND_EMAIL_DOMAINS", {"fuseenergy.com"})
    if not sender_email or not isinstance(sender_email, str) or "@" not in sender_email:
        return "inbound"
    domain = sender_email.strip().lower().split("@", 1)[-1]
    return "outbound" if domain in {d.lower() for d in domains} else "inbound"


def _base_row(thread_data: dict) -> dict:
    """One message row's thread-level fields (including communication_id, mpxn, created_at, updated_at)."""
    return {
        "communication_id": thread_data.get("communication_id", ""),
        "inbox_title": thread_data.get("inbox_title", ""),
        "reference": thread_data.get("reference", ""),
        "subject": thread_data.get("subject", ""),
        "escalation_level": thread_data.get("escalation_level", ""),
        "from": thread_data.get("from", ""),
        "to": thread_data.get("to", ""),
        "bucket": thread_data.get("bucket", ""),
        "mpxn_type": thread_data.get("mpxn_type", ""),
        "mpxn_value": thread_data.get("mpxn_value", ""),
        "meter_point_number": thread_data.get("meter_point_number", "") or thread_data.get("mpxn_value", ""),
        "created_at": _date_str_to_iso(thread_data.get("created_at", "")),
        "updated_at": _date_str_to_iso(thread_data.get("updated_at", "")),
    }


def message_rows_from_thread(thread_data: dict) -> list[dict]:
    """Expand thread data into one row per message (thread fields repeated). Each row has direction: outbound if sender is our domain, else inbound."""
    base = _base_row(thread_data)
    outbound_domains = getattr(config, "OUTBOUND_EMAIL_DOMAINS", {"fuseenergy.com"})
    rows = []
    for i, msg in enumerate(thread_data.get("messages") or []):
        sender = msg.get("sender_email", "")
        rows.append({
            **base,
            "message_index": i + 1,
            "message_type": msg.get("message_type", ""),
            "sender_email": sender,
            "message_timestamp": _date_str_to_iso(msg.get("timestamp", "")),
            "message_content": msg.get("content", ""),
            "direction": _message_direction(sender, outbound_domains),
        })
    if not rows:
        rows.append({
            **base,
            "message_index": 0,
            "message_type": "",
            "sender_email": "",
            "message_timestamp": "",
            "message_content": "",
            "direction": "inbound",
        })
    return rows


def _scrape_scope(
    page: Page,
    bucket: str,
    max_threads: int | None,
    save_raw_dir: str | None,
    save_dom_path: str | None,
    all_rows: list[dict],
) -> None:
    """Scroll list, collect thread rows, open each and append message rows with bucket set."""
    scroll_to_load_all_threads(page)
    thread_rows = get_thread_rows(page)
    total = len(thread_rows)
    if max_threads is not None:
        thread_rows = thread_rows[:max_threads]
    for i, row_info in enumerate(thread_rows):
        if not row_info.get("communication_id"):
            print(f"  [{bucket}] Thread {i + 1}/{len(thread_rows)} ⏭️ Skip (no communication_id)")
            continue
        print(f"  [{bucket}] Thread {i + 1}/{len(thread_rows)} (of {total} total) id={row_info['communication_id']}")
        if save_dom_path:
            open_thread_and_parse._debug_save_dom_path = save_dom_path
        data = open_thread_and_parse(page, row_info)
        if save_dom_path:
            open_thread_and_parse._debug_save_dom_path = None
        if data:
            data["bucket"] = bucket
            title = data.get("inbox_title") or ""
            if title:
                print(f"    → {title}")
            for row in message_rows_from_thread(data):
                all_rows.append(row)
            if save_raw_dir:
                ref = (data.get("reference") or data.get("communication_id") or "unknown").strip()
                safe_ref = re.sub(r"[^\w\-]", "_", ref)[:80]
                Path(save_raw_dir).mkdir(parents=True, exist_ok=True)
                Path(save_raw_dir).joinpath(f"{safe_ref}.json").write_text(
                    json.dumps(data, indent=2), encoding="utf-8"
                )
        page.wait_for_timeout(config.BETWEEN_THREADS_MS)


def _scrape_archived_until_new_year(
    page: Page,
    max_archived: int | None,
    save_raw_dir: str | None,
    all_rows: list[dict],
    stop_year: int | None = None,
    stop_before_date: str | None = None,
) -> None:
    """
    Archived pass: scroll to load list, open each thread. Stop when:
    - updated_at year <= stop_year (e.g. stop_year=2025 → stop when we hit a thread updated in 2025 or earlier), or
    - updated_at date is on or before stop_before_date (e.g. "2025-12-31").
    Uses updated_at from the list row; falls back to created_at if updated_at is missing.
    """
    stop_year = stop_year if stop_year is not None else getattr(config, "ARCHIVED_STOP_YEAR", 2026)
    stop_before_dt: datetime | None = None
    if stop_before_date:
        try:
            stop_before_dt = datetime.strptime(stop_before_date.strip()[:10], "%Y-%m-%d")
        except ValueError:
            pass

    processed_ids: set[str] = set()
    prev_count = 0

    while True:
        thread_rows = get_thread_rows(page)
        to_process = [r for r in thread_rows if r.get("communication_id") and r["communication_id"] not in processed_ids]
        if not to_process:
            # Load more rows (infinite scroll)
            new_count = scroll_to_load_more_threads(page)
            if new_count <= prev_count:
                break
            prev_count = new_count
            page.wait_for_timeout(200)
            continue
        prev_count = len(thread_rows)

        for row_info in to_process:
            comm_id = row_info.get("communication_id", "")
            updated_at = row_info.get("updated_at", "").strip()
            created_at = row_info.get("created_at", "").strip()
            date_for_stop = updated_at or created_at

            if max_archived is not None and len(processed_ids) >= max_archived:
                print(f"  [Archived] Reached --max-archived={max_archived}; stopping.")
                return
            if not comm_id or comm_id in processed_ids:
                continue

            # Stop when updated_at (or created_at fallback) meets a stop condition
            should_stop = False
            reason = ""
            if date_for_stop:
                edited_year = _updated_date_year(date_for_stop)
                # stop_year: stop when year < stop_year (e.g. 2026 → process 2026, stop at 2025)
                if stop_year is not None and edited_year is not None and edited_year < stop_year:
                    should_stop = True
                    reason = f"updated_at year {edited_year} < stop_year {stop_year}"
                if not should_stop and stop_before_dt is not None:
                    row_dt = _parse_date_str_to_date(date_for_stop)
                    if row_dt is not None and row_dt.date() <= stop_before_dt.date():
                        should_stop = True
                        reason = f"updated_at {date_for_stop!r} is on or before {stop_before_date}"
            if should_stop:
                print(f"  [Archived] Stopping: {reason}")
                return

            dates_source = row_info.get("dates_source", "")
            print(f"  [Archived] Thread id={comm_id} | created_at={created_at or '(none)'} | updated_at={updated_at or '(none)'} | picked: {dates_source} | (processed {len(processed_ids) + 1} so far)")
            data = open_thread_and_parse(page, row_info)
            processed_ids.add(comm_id)
            if data:
                data["bucket"] = "Archived"
                title = data.get("inbox_title") or ""
                if title:
                    print(f"    → {title}")
                for row in message_rows_from_thread(data):
                    all_rows.append(row)
                if save_raw_dir:
                    ref = (data.get("reference") or data.get("communication_id") or "unknown").strip()
                    safe_ref = re.sub(r"[^\w\-]", "_", ref)[:80]
                    Path(save_raw_dir).mkdir(parents=True, exist_ok=True)
                    Path(save_raw_dir).joinpath(f"{safe_ref}.json").write_text(
                        json.dumps(data, indent=2), encoding="utf-8"
                    )
            page.wait_for_timeout(config.BETWEEN_THREADS_MS)

        # Load more rows for next iteration (infinite scroll)
        scroll_to_load_more_threads(page)
        page.wait_for_timeout(400)


def run_scraper(
    use_storage_state: bool = True,
    max_current: int | None = None,
    max_archived: int | None = None,
    archived_only: bool = False,
    fast: bool = False,
    stop_year: int | None = None,
    stop_before_date: str | None = None,
    output_csv: str | None = None,
    max_rows_per_csv: int | None = None,
    save_raw_dir: str | None = None,
    save_dom_path: str | None = None,
    save_row_dom_path: str | None = None,
) -> str:
    """
    Run the full scrape: first Current (non-archived) inbox, then Archived inbox.
    Each row gets a "bucket" column: "Current" or "Archived".
    With archived_only=True, skip Current and scrape only the Archived inbox.
    Archived: we stop when we hit a thread whose last message is before ARCHIVED_STOP_YEAR
    (default 2026, i.e. last message in 2025), and we interleave scroll with opening threads.
    If max_rows_per_csv is set (e.g. 2000), output is split into multiple CSV files
    (e.g. base_001.csv, base_002.csv) so each can be uploaded to Metabase separately.
    """
    output_csv = output_csv or config.OUTPUT_CSV
    save_raw_dir = save_raw_dir or config.OUTPUT_RAW_DIR
    if save_raw_dir:
        Path(save_raw_dir).mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []
    fieldnames = [
        "communication_id", "inbox_title", "reference", "subject", "escalation_level", "from", "to",
        "bucket", "mpxn_type", "mpxn_value", "meter_point_number", "created_at", "updated_at",
        "message_index", "message_type", "sender_email", "message_timestamp", "message_content",
        "direction",
    ]

    browser = None
    try:
        with sync_playwright() as p:
            if config.USE_PERSISTENT_CONTEXT and config.SESSION_DIR:
                Path(config.SESSION_DIR).mkdir(parents=True, exist_ok=True)
                context = p.chromium.launch_persistent_context(
                    user_data_dir=config.SESSION_DIR,
                    headless=config.HEADLESS,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                page = context.new_page()
            else:
                browser = p[config.BROWSER].launch(headless=config.HEADLESS)
                context_options = {}
                if use_storage_state and Path(config.STORAGE_STATE_PATH).exists():
                    context_options["storage_state"] = config.STORAGE_STATE_PATH
                context = browser.new_context(**context_options)
                page = context.new_page()
            page.set_default_timeout(30000)

            try:
                page.goto(config.APP_URL, wait_until="domcontentloaded")
                if not config.HEADLESS:
                    print("A browser window should have opened. Log in there if you see a login page.")
                else:
                    print("Running headless (no window). To log in, run with: ECOES_HEADLESS=false")
                print("Waiting for the communication list to load (up to 2 minutes). Make sure you're on the Secure Communications list view (Processes → Secure Communications).")
                if not wait_list_ready_with_feedback(page, timeout_ms=120000):
                    print("The list did not appear. Check that you're logged in and on the Secure Communications page with the list of threads visible.")
                    context.close()
                    if browser is not None:
                        try:
                            browser.close()
                        except Exception:
                            pass
                    print("No data saved.")
                    return output_csv
                ensure_filters_include_all(page)
                page.wait_for_timeout(1000)

                # Save first list row HTML (for debugging created_at / updated_at selectors)
                if save_row_dom_path:
                    set_archived(page, archived_only)
                    page.wait_for_timeout(200)
                    if archived_only:
                        wait_list_after_scope_change(page)
                    first_row = page.locator(config.ROW_SEL).first
                    if first_row.count():
                        Path(save_row_dom_path).write_text(first_row.evaluate("el => el.outerHTML"), encoding="utf-8")
                        print(f"  [debug] Wrote first list row DOM to {save_row_dom_path}")
                    else:
                        print("  [debug] No row found for --save-row-dom")

                # Apply fast pacing for full scrapes (e.g. all of 2025)
                if fast:
                    config.BETWEEN_THREADS_MS = getattr(config, "FAST_BETWEEN_THREADS_MS", 80)
                    config.CLICK_WAIT_MS = getattr(config, "FAST_CLICK_WAIT_MS", 400)
                    config.WAIT_MPAN_MPRN_TIMEOUT_MS = getattr(config, "FAST_WAIT_MPAN_MPRN_TIMEOUT_MS", 4000)
                    config.CLOSE_DETAIL_MS = getattr(config, "FAST_CLOSE_DETAIL_MS", 80)
                    config.SCROLL_PAUSE_SEC = getattr(config, "FAST_SCROLL_PAUSE_SEC", 0.12)
                    config.ARCHIVED_SCROLL_STEPS = getattr(config, "FAST_ARCHIVED_SCROLL_STEPS", 8)
                    print("  ⚡ Fast mode: reduced waits (between threads, after open, close, panel timeout).")

                if not archived_only:
                    # Pass 1: Current (non-archived) inbox
                    print("\n📥 Current inbox (non-archived)")
                    set_archived(page, False)
                    page.wait_for_timeout(200)
                    _scrape_scope(page, "Current", max_current, save_raw_dir, save_dom_path, all_rows)

                # Pass 2: Archived inbox (stop by stop_year and/or stop_before_date)
                stop_yr = stop_year if stop_year is not None else getattr(config, "ARCHIVED_STOP_YEAR", 2026)
                msg = f"\n📦 Archived inbox (stop when updated_at year < {stop_yr}"
                if stop_before_date:
                    msg += f" or on/before {stop_before_date}"
                msg += ")"
                print(msg)
                if set_archived(page, True):
                    wait_list_after_scope_change(page)
                    _scrape_archived_until_new_year(
                        page, max_archived, save_raw_dir, all_rows,
                        stop_year=stop_year,
                        stop_before_date=stop_before_date,
                    )
                else:
                    print("  ⚠️ Could not switch to Archived; skipping archived pass.")
            finally:
                context.close()
                if browser is not None:
                    try:
                        browser.close()
                    except Exception:
                        pass
    except KeyboardInterrupt:
        print("\n\nInterrupted (Ctrl+C). Saving scraped data so far...")

    # Deduplicate by (communication_id, message_index) – same message in same thread = duplicate
    seen: set[tuple[str, str | int]] = set()
    deduped: list[dict] = []
    dup_count = 0
    for row in all_rows:
        key = (str(row.get("communication_id", "")), row.get("message_index", ""))
        if key in seen:
            dup_count += 1
            continue
        seen.add(key)
        deduped.append(row)
    if dup_count:
        print(f"Skipped {dup_count} duplicate message(s) (same communication_id + message_index).")

    path = Path(output_csv)
    path.parent.mkdir(parents=True, exist_ok=True)
    chunk_size = max_rows_per_csv if max_rows_per_csv is not None and max_rows_per_csv > 0 else None

    if chunk_size is None:
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(deduped)
        print(f"Wrote {len(deduped)} message rows to {output_csv}")
        return output_csv

    # Split into multiple CSVs (e.g. base_001.csv, base_002.csv) for Metabase upload
    stem, suffix = path.stem, path.suffix
    if not suffix or suffix.lower() != ".csv":
        suffix = ".csv"
    written: list[str] = []
    for i in range(0, len(deduped), chunk_size):
        chunk = deduped[i : i + chunk_size]
        part = (path.parent / f"{stem}_{(i // chunk_size) + 1:03d}{suffix}").as_posix()
        with open(part, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(chunk)
        written.append(part)
        print(f"Wrote {len(chunk)} rows to {part}")
    print(f"Wrote {len(deduped)} message rows total in {len(written)} file(s).")
    return written[0] if written else output_csv


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Scrape ECOES Secure Communications: Current inbox then Archived inbox. Each row has a 'bucket' column (Current | Archived)."
    )
    parser.add_argument("--no-session", action="store_true", help="Do not use saved session (fresh login)")
    parser.add_argument(
        "--max-current",
        type=int,
        default=None,
        metavar="N",
        help="Max threads to open from the Current (non-archived) inbox (default: all). Use for testing.",
    )
    parser.add_argument(
        "--max-archived",
        type=int,
        default=None,
        metavar="N",
        help="Hard cap on archived threads to open. Archived pass also stops when a thread's last message is in 2025.",
    )
    parser.add_argument(
        "--archived-only",
        action="store_true",
        help="Skip Current inbox and scrape only the Archived inbox.",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Faster pacing (lower waits) for full scrapes e.g. all of 2025. Uses config FAST_* values.",
    )
    parser.add_argument(
        "--stop-year",
        type=int,
        default=None,
        metavar="YYYY",
        help="Archived: stop when updated_at year < YYYY (e.g. 2026 → process 2026, stop at 2025). Default from config ARCHIVED_STOP_YEAR.",
    )
    parser.add_argument(
        "--stop-before",
        type=str,
        default=None,
        metavar="YYYY-MM-DD",
        help="Archived: stop when updated_at is on or before this date (e.g. 2025-12-31).",
    )
    parser.add_argument("--output", default=None, help="Output CSV path (base name when using --max-rows-per-csv)")
    parser.add_argument(
        "--max-rows-per-csv",
        type=int,
        default=None,
        metavar="N",
        help="Split output into multiple CSV files with at most N rows each (e.g. 2000 for Metabase).",
    )
    parser.add_argument("--save-raw", default=None, help="Directory to save per-thread JSON")
    parser.add_argument(
        "--save-dom",
        metavar="FILE",
        default=None,
        help="Save the first thread's detail panel HTML to FILE (for debugging reference/subject/from/to parsing).",
    )
    parser.add_argument(
        "--save-row-dom",
        metavar="FILE",
        default=None,
        help="Save the first list row's HTML to FILE (for debugging created_at/updated_at selectors). Use with --archived-only to capture an archived row.",
    )
    args = parser.parse_args()
    run_scraper(
        use_storage_state=not args.no_session,
        max_current=args.max_current,
        max_archived=args.max_archived,
        archived_only=args.archived_only,
        fast=args.fast,
        stop_year=args.stop_year,
        stop_before_date=args.stop_before,
        output_csv=args.output,
        max_rows_per_csv=args.max_rows_per_csv,
        save_raw_dir=args.save_raw,
        save_dom_path=args.save_dom,
        save_row_dom_path=args.save_row_dom,
    )
