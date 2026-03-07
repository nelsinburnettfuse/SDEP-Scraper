# ECOES Secure Communications – full-data scraper

Scrapes **all** Secure Communications threads (Initiated + Recipient), opens each thread, and extracts every message plus thread-level fields. Output is one CSV row per message so you can filter and run statistics on the ground data.

**Logic is aligned with Original Script.py:** same URL (`www.ecoes.co.uk`), row selector (`div.communication-row`), scroll behaviour (mouse wheel + `.infinite-scroll-load`), opening threads via `a[data-ajax-url]` and `GetCommunication` response, `communication_id` from the link, and MPAN/MPRN read from `input[placeholder='MPAN']` / `input[placeholder='MPRN']` (digits-only, same as Original). Session uses a **persistent browser context** (`ecoes_session/`) by default so you log in once like the Original.

## What it does

1. Opens the Secure Communications index page (`https://www.ecoes.co.uk/SecureCommunications/Index`).
2. Waits for the list (`div.communication-row`), then ensures **Initiated** and **Recipient** are selected.
3. Scrolls with mouse wheel until the list is fully loaded (waits for `.infinite-scroll-load` to hide, same as Original).
4. For each row: gets `communication_id` from `a[data-ajax-url]`, clicks that link, waits for the detail panel (and optionally the GetCommunication response), reads **MPAN/MPRN** from the page (same as Original), parses `#communication-detail` for Reference, Subject, From, To, messages, etc., then closes the panel with Escape.
5. Writes a CSV with **one row per message** and optional per-thread JSON under `raw_threads/`.

## Setup

Using **uv** (recommended):

```bash
cd ecoes_secure_comms_scraper
uv sync
uv run playwright install chromium
```

Or with **pip**:

```bash
cd ecoes_secure_comms_scraper
pip install -r requirements.txt
playwright install chromium
```

- `uv sync` creates a virtual environment (if needed), installs dependencies from `pyproject.toml`, and locks them. Run the scraper with `uv run python scrape_all_communications.py` so it uses that environment.
- To install from `requirements.txt` with uv instead: `uv pip install -r requirements.txt`, then `uv run python scrape_all_communications.py`.

## Login (required)

The site requires authentication. By default the scraper uses a **persistent context** (browser profile in `ecoes_session/`), same as Original Script:

1. Run with the browser visible so you can log in the first time:
   ```bash
   ECOES_HEADLESS=false uv run python scrape_all_communications.py --max-threads 2
   ```
   (Omit `uv run` if you're using pip and an activated venv.)
2. Log in when prompted. Once the list appears, the run continues; future runs will reuse the same profile and stay logged in.

To use a saved JSON session instead (e.g. from `login_and_save_session.py`), set `ECOES_USE_PERSISTENT_CONTEXT=false` and ensure `ecoes_session.json` exists.

## Running the scraper

If you used **uv** for setup, prefix with `uv run`:

```bash
# Use persistent context (ecoes_session/) and scrape all threads
uv run python scrape_all_communications.py

# Limit to 10 threads (e.g. for testing)
uv run python scrape_all_communications.py --max-threads 10

# Custom output and raw JSON directory
uv run python scrape_all_communications.py --output my_export.csv --save-raw ./raw_threads

# Fresh run without saved session
uv run python scrape_all_communications.py --no-session
```

With **pip** and an activated venv, run the same commands without `uv run` (e.g. `python scrape_all_communications.py`).

## Configuration

Edit `config.py` or use environment variables:

- `ECOES_BASE_URL` – base URL (default `https://www.ecoes.co.uk`, same as Original)
- `ECOES_HEADLESS` – `true` / `false`
- `ECOES_SESSION_DIR` – persistent context directory (default `ecoes_session/`)
- `ECOES_USE_PERSISTENT_CONTEXT` – `true` to use persistent context (default), `false` to use storage_state JSON
- `ECOES_STORAGE_STATE` – path to saved session JSON when not using persistent context
- `ECOES_OUTPUT_CSV`, `ECOES_OUTPUT_RAW_DIR` – output paths

## Selectors (aligned with Original Script)

- **Row:** `div.communication-row` (`config.ROW_SEL`)
- **Open thread:** `a[data-ajax-url]` on each row (URL contains `communicationId=`)
- **Detail panel:** `#communication-detail`
- **MPAN/MPRN:** `input[placeholder='MPAN']`, `input[placeholder='MPRN']` in the open panel

Parsing of the detail panel (Reference, Subject, messages, etc.) is in `parse_detail_panel_html()`. If the site’s HTML structure changes, adjust the `label_value()` calls and message selectors there.

## Output CSV columns

| Column | Description |
|--------|-------------|
| communication_id | From row link `data-ajax-url` (same as Original) |
| reference | Thread reference (e.g. SC01706124) |
| subject | Thread subject |
| escalation_level | e.g. Final Escalation |
| from | Sender party |
| to | Recipient party |
| last_escalation | Last escalated date |
| owner | Owner (FUSE) if present |
| mpxn_type | MPAN or MPRN (same as Original, text) |
| mpxn_value | Digits-only meter number (same as Original) |
| meter_point_number | Same as mpxn_value for compatibility |
| message_index | 1-based index of message in thread |
| message_type | e.g. reply, escalation |
| sender_email | Sender email for this message |
| message_timestamp | Message date/time |
| message_content | Message body (truncated if very long) |

## Statistics on the ground data

Use the message-level CSV for:

- **Responses per day** – count rows where `sender_email` is your domain (e.g. `@fuseenergy.com`) and group by date.
- **Backlog over time** – define “open” threads (e.g. no reply from us after `last_escalation`) and count by day.
- **Agent activity** – group by `sender_email` or `owner` to see who is replying most.

Example script:

```bash
python stats_from_ground_data.py secure_comms_messages.csv --our-domain fuseenergy.com
```

You can extend `stats_from_ground_data.py` with pandas to add more metrics (e.g. escalation level distribution, time-to-reply per thread).

## Hosting on GitHub

1. **Create a new repository** on GitHub (e.g. `ecoes_secure_comms_scraper`). Do *not* add a README, .gitignore, or license yet if you want to push this existing repo.

2. **Add the remote and push** (replace `YOUR_USERNAME` and `REPO_NAME` with your GitHub user and repo name):

   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/REPO_NAME.git
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git push -u origin main
   ```

3. **Session and secrets**: `.gitignore` is set so `ecoes_session/`, `ecoes_session.json`, `*.csv`, and `raw_threads/` are not committed. Never add real session files or credentials to the repo.
