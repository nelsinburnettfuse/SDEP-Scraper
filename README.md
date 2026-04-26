# ECOES Secure Communications scraper

Scrapes every Secure Communications thread on `www.ecoes.co.uk` (Initiated + Recipient, Current + Archived), opens each thread, and writes one CSV row per message. Built on Playwright + a persistent browser profile so login carries over across runs.

The output is designed to be uploaded straight into an analytics tool (e.g. Metabase) — `bucket`, `direction`, `created_at`, `updated_at` and `message_timestamp` are all populated so backlog / response-rate / agent-activity queries can be written downstream.

## What the script does, end to end

1. **Launches Playwright Chromium** against `https://www.ecoes.co.uk/SecureCommunications/Index` using a persistent browser profile (`ecoes_session/`). First run is interactive (log in once); subsequent runs reuse the profile.
2. **Ensures both inboxes** (`Initiated` + `Recipient`) are selected so all communications are visible.
3. **Pass 1 — Current inbox.** Scrolls the list with mouse-wheel events until `.infinite-scroll-load` clears, then for each `div.communication-row`:
   - reads `communication_id` from `a[data-ajax-url]`,
   - reads `created_at` / `updated_at` from the row icons,
   - clicks to open `#communication-detail`, waits for `GetCommunication`,
   - reads MPAN / MPRN from the panel,
   - parses Reference, Subject, Escalation Level, From, To, and every message in the thread,
   - closes the panel with Escape.
4. **Pass 2 — Archived inbox.** Reloads, toggles the Archived folder, and repeats the above. Stops as soon as a thread's `updated_at` year is below `ARCHIVED_STOP_YEAR` (default `2026`, i.e. stops at 2025) or before `--stop-before YYYY-MM-DD`. Scroll and open are interleaved to avoid loading the entire archive.
5. **Deduplicates** by `(communication_id, message_index)`.
6. **Incremental merge** (if `--incremental`): only scrapes threads updated since the last run (with a 2-day safety buffer), verifies that threads in the day-2 → day-1 buffer zone match the previous CSV (consistency check; warns if not), then merges new rows over old ones in `secure_comms_messages.csv`.
7. **Thread manifest** (`manifests/latest_manifest.json`): records the full set of `communication_id`s for this run and prints a diff against the previous manifest (new threads, disappeared threads). Previous manifest is archived locally as `manifests/manifest_<timestamp>.json` for audit (gitignored).
8. **Data quality report** (`dq_report.json`, gitignored): runs structured checks and prints a summary. Flags include:
   - `empty_detail` — thread has no messages (panel likely failed to load)
   - `missing_metadata` — no `inbox_title` or `reference`
   - `missing_mpxn` — no MPAN/MPRN
   - `date_inversion` — `created_at > updated_at`
   - `dual_bucket` — same thread appears in both Current and Archived
   - `empty_content` — message row with empty body
   - `missing_sender` — message row with no sender email
9. **Writes the CSV** (`secure_comms_messages.csv`), or splits it into `*_001.csv`, `*_002.csv`, … chunks with `--max-rows-per-csv` (handy for Metabase upload limits).
10. **Stamps `last_run.json`** with the run timestamp + output path so the next `--incremental` run knows where to pick up.

## Repo layout

| File | Role |
|------|------|
| `scrape_all_communications.py` | Main scraper (Playwright). All the orchestration, scrolling, parsing, dedup, merging. |
| `config.py` | URLs, selectors, pacing, fast-mode constants, env-var overrides. |
| `data_quality.py` | Post-scrape consistency checks → `dq_report.json`. Also runnable standalone on any CSV. |
| `thread_manifest.py` | Cross-run consistency: persists thread IDs and diffs vs previous run. |
| `login_and_save_session.py` | Optional one-off helper to save a `storage_state` JSON instead of using the persistent profile. |
| `pyproject.toml` / `requirements.txt` / `uv.lock` | Dependencies (`playwright`, `beautifulsoup4`). |
| `manifests/latest_manifest.json` | Source of truth for the new-vs-disappeared-thread diff. |

Generated at runtime, gitignored: `secure_comms_messages*.csv`, `raw_threads/`, `ecoes_session/`, `dq_report.json`, `last_run.json`, archived `manifests/manifest_*.json`.

## Setup

With **uv** (recommended):

```bash
uv sync
uv run playwright install chromium
```

With **pip**:

```bash
pip install -r requirements.txt
playwright install chromium
```

## First-time login

The site requires auth. The default flow is a persistent browser profile (`ecoes_session/`):

```bash
ECOES_HEADLESS=false uv run python scrape_all_communications.py --max-current 2
```

Log in when the window opens. Once the list appears, the run continues. Future runs reuse the same profile and stay logged in (run them headless if you like).

To use a saved JSON session instead of a persistent profile, run `python login_and_save_session.py` once and then set `ECOES_USE_PERSISTENT_CONTEXT=false`.

## Running

```bash
# Default: Current then Archived, stopping when archived hits 2025
uv run python scrape_all_communications.py

# Smoke test: only the first 5 Current threads
uv run python scrape_all_communications.py --max-current 5

# Only the Archived pass
uv run python scrape_all_communications.py --archived-only

# Fast pacing for a full scrape (lower per-thread waits)
uv run python scrape_all_communications.py --fast

# Incremental: only scrape what's changed since last run, merge into previous CSV
uv run python scrape_all_communications.py --incremental

# Cap archived depth + custom stop boundary
uv run python scrape_all_communications.py --max-archived 200 --stop-before 2025-12-31

# Split output for Metabase upload limits
uv run python scrape_all_communications.py --max-rows-per-csv 2000

# Debugging selectors
uv run python scrape_all_communications.py --save-dom debug_panel.html --max-current 1
uv run python scrape_all_communications.py --save-row-dom debug_row.html --archived-only
```

All flags:

| Flag | Purpose |
|------|---------|
| `--no-session` | Don't use saved session (fresh login). |
| `--max-current N` | Cap threads opened in the Current pass. |
| `--max-archived N` | Cap threads opened in the Archived pass. |
| `--archived-only` | Skip Current; scrape only Archived. |
| `--incremental` | Only re-scrape threads updated since the last run (2-day buffer) and merge. |
| `--fast` | Use `FAST_*` config values for lower per-thread waits. |
| `--stop-year YYYY` | Archived: stop when `updated_at` year < YYYY. |
| `--stop-before YYYY-MM-DD` | Archived: stop when `updated_at` ≤ this date. |
| `--output PATH` | Output CSV path (base name when chunking). |
| `--max-rows-per-csv N` | Split output into `_001.csv`, `_002.csv`, … with at most N rows each. |
| `--save-raw DIR` | Save per-thread JSON dumps under `DIR/`. |
| `--save-dom FILE` | Dump the first thread's `#communication-detail` HTML for debugging. |
| `--save-row-dom FILE` | Dump the first list row's HTML for debugging date selectors. |

## Configuration (env vars / `config.py`)

| Variable | Default | What it does |
|----------|---------|--------------|
| `ECOES_BASE_URL` | `https://www.ecoes.co.uk` | Site base URL. |
| `ECOES_HEADLESS` | `false` | `true` for unattended runs. |
| `ECOES_BROWSER` | `chromium` | Playwright browser. |
| `ECOES_SESSION_DIR` | `ecoes_session/` | Persistent browser profile dir. |
| `ECOES_USE_PERSISTENT_CONTEXT` | `true` | Set `false` to use a `storage_state` JSON instead. |
| `ECOES_STORAGE_STATE` | `ecoes_session.json` | JSON session file when not using persistent context. |
| `ECOES_OUTPUT_CSV` | `secure_comms_messages.csv` | Output path. |
| `ECOES_OUTPUT_RAW_DIR` | `raw_threads` | Per-thread JSON dump dir. |
| `ECOES_MANIFEST_DIR` | `manifests` | Where thread manifests are stored. |
| `ECOES_LAST_RUN_FILE` | `last_run.json` | Tracks last-run timestamp for `--incremental`. |
| `ECOES_DQ_REPORT_FILE` | `dq_report.json` | Where the data-quality report is written. |

Pacing (`SCROLL_PAUSE_SEC`, `BETWEEN_THREADS_MS`, `CLICK_WAIT_MS`, `WAIT_MPAN_MPRN_TIMEOUT_MS`, …) and selectors (`ROW_SEL`, `SELECTOR_DETAIL_PANEL`, `SELECTOR_THREAD_LINK`, `ARCHIVED_*`) live in `config.py` — adjust there when ECOES changes its DOM.

## Output CSV columns

| Column | Description |
|--------|-------------|
| `communication_id` | From row link `data-ajax-url` (`communicationId=...`). |
| `inbox_title` | `Initiated` / `Recipient` from the inbox header. |
| `reference` | Thread reference (e.g. `SC01706124`). |
| `subject` | Thread subject. |
| `escalation_level` | E.g. `Final Escalation`. |
| `from`, `to` | Sender / recipient parties. |
| `bucket` | `Current` or `Archived` — which pass scraped this row. |
| `mpxn_type`, `mpxn_value` | `MPAN` / `MPRN` and digits-only meter number. |
| `meter_point_number` | Same as `mpxn_value`, kept for downstream compatibility. |
| `created_at`, `updated_at` | ISO datetimes parsed from the row's pencil/clock icons. |
| `message_index` | 1-based index of the message within the thread. |
| `message_type` | E.g. `reply`, `escalation`. |
| `sender_email` | Sender email for this message. |
| `message_timestamp` | ISO datetime of the message. |
| `message_content` | Body text (truncated for very long messages). |
| `direction` | `outbound` if `sender_email` domain ∈ `OUTBOUND_EMAIL_DOMAINS` (default `fuseenergy.com`), else `inbound`. |

## Consistency checks (built into every run)

- **Dedup** by `(communication_id, message_index)`.
- **Buffer-zone verification** (`--incremental` only): threads in the day-2 → day-1 window are re-scraped and compared message-for-message with the previous CSV; mismatches print a warning telling you to widen the buffer.
- **Thread manifest diff** (`manifests/latest_manifest.json`): new and disappeared `communication_id`s vs the previous run.
- **Data quality report** (`dq_report.json`): `empty_detail`, `missing_metadata`, `missing_mpxn`, `date_inversion`, `dual_bucket`, `empty_content`, `missing_sender`.

To re-run the data quality checks against an existing CSV without scraping:

```bash
uv run python data_quality.py secure_comms_messages.csv --output dq_report.json
```
