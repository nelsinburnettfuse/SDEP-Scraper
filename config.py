"""
Configuration for ECOES Secure Communications scraper.
Aligned with Original Script.py (row selector, URL, scroll, open-thread logic).
Override via environment variables or edit here.
"""
import os

# Base URL – must match Original Script (www.ecoes.co.uk)
BASE_URL = os.environ.get("ECOES_BASE_URL", "https://www.ecoes.co.uk")
SECURE_COMMS_PATH = "/SecureCommunications/Index"
APP_URL = BASE_URL + SECURE_COMMS_PATH

# Session: persistent context (like Original) or saved JSON
SESSION_DIR = os.environ.get("ECOES_SESSION_DIR", "ecoes_session/")
STORAGE_STATE_PATH = os.environ.get("ECOES_STORAGE_STATE", "ecoes_session.json")

# Playwright
BROWSER = os.environ.get("ECOES_BROWSER", "chromium")
# Default false so you can see the browser and log in; set to "true" for unattended runs
HEADLESS = os.environ.get("ECOES_HEADLESS", "false").lower() == "true"
USE_PERSISTENT_CONTEXT = os.environ.get("ECOES_USE_PERSISTENT_CONTEXT", "true").lower() == "true"

# Output paths
OUTPUT_CSV = os.environ.get("ECOES_OUTPUT_CSV", "secure_comms_messages.csv")
OUTPUT_RAW_DIR = os.environ.get("ECOES_OUTPUT_RAW_DIR", "raw_threads")

# Scrolling / pacing (aligned with Original)
SCROLL_PAUSE_SEC = 0.25
SCROLL_STAGNANT_MAX = 6
SCROLL_MAX_LOOPS = 250
# Archived pass: scroll in chunks so we can stop when we hit 2025 (don't load entire list at once)
ARCHIVED_SCROLL_STEPS = 12
ARCHIVED_STOP_YEAR = 2026  # stop when we see a thread whose last message is before this year (e.g. 2025)
CLICK_WAIT_MS = 2000
BETWEEN_THREADS_MS = 500
WAIT_MPAN_MPRN_TIMEOUT_MS = 8000
EXPECT_RESPONSE_TIMEOUT_MS = 15000

# Selectors – must match Original Script
ROW_SEL = "div.communication-row"
TEXT_SEL = "div.row-content-text"
SELECTOR_THREAD_ROW = ROW_SEL
SELECTOR_DETAIL_PANEL = "#communication-detail"
# Link that opens thread (Original: a[data-ajax-url] with communicationId=)
SELECTOR_THREAD_LINK = "a[data-ajax-url]"

# Communication Folders (left panel): Archived / Deleted toggles
# Scoped to secure-comms-wrapper to avoid duplicate IDs elsewhere
FILTER_PANEL = "#secure-comms-wrapper .secure-comms-panel"
ARCHIVED_ITEM_SEL = f"{FILTER_PANEL} .sc-panel-item[data-sec-comm-filter-archived]"
ARCHIVED_CHECKBOX_ID = "checkBoxShowArchived"
CLEAR_FILTER_SEL = "a.btn-clear-filter[data-sec-comm-filter-refresh]"
SEARCH_BUTTON_SEL = "#btnCommsSearch"

# Message direction: sender domain in this set => outbound (ours), else inbound
OUTBOUND_EMAIL_DOMAINS = {"fuseenergy.com"}

# List row dates: data-original-title values to find created vs updated (ECOES: pencil = created)
CREATED_DATE_TITLES = ("Updated Date",)  # pencil icon shows created-at
UPDATED_DATE_TITLES = ("Modified Date", "Last Updated", "Updated")  # real last-edited

# Fast mode (e.g. full 2025 scrape): lower waits. Set ECOES_FAST=true or use --fast
FAST_BETWEEN_THREADS_MS = 50
FAST_CLICK_WAIT_MS = 280
FAST_WAIT_MPAN_MPRN_TIMEOUT_MS = 3500
FAST_CLOSE_DETAIL_MS = 50
FAST_SCROLL_PAUSE_SEC = 0.12
FAST_ARCHIVED_SCROLL_STEPS = 8
