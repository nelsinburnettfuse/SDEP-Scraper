# Secure Comms – Metabase queries recap

## Queries you wanted

| Goal | File | What it does |
|------|------|----------------|
| **Backlog over time (cumulative)** | `metabase_backlog_by_day.sql` | As of each day at midnight, how many threads have their latest message inbound (by escalation). Drillable to communication_id. |
| **Backlog right now** | `metabase_backlog_current.sql` | Threads whose latest message is inbound (point-in-time). Returns one row per thread; aggregate in Metabase for a single “current backlog” count or by escalation. |
| **Day-by-day response rate** | `metabase_response_rate_by_day.sql` | **Per inbound message**: did we send a following outbound the same day, a later day, or never? One row per inbound with `message_date`, `communication_id`, `escalation_level`, `response_type` (same_day / later / never). In Metabase, summarize by `message_date` (and optionally `escalation_level`) to get counts for “received that day” and how many got same_day / later / never response. |
| **Agent messages in a time period** | `metabase_agent_messages.sql` | Per day and per sender_email (agent): count of outbound messages. In Metabase, add a **date filter** on `message_date` to restrict to your time period. |

All of these use the same table (replace the table name in the SQL if your upload has a different one). Date handling is simple `CAST(message_timestamp AS DATE)`; for mixed types use the robust-dates version where it exists.

---

## Archived chats and agent credit

- **Backlog** (current and by day) uses all threads in the table (Current + Archived) so the count reflects full history in your snapshot.
- **Response rate and agent messages** explicitly include **all** outbound messages (no filter on `bucket`), so:
  - Agents get credit for every response they sent, even if the thread was later archived.
  - Loading more archived chats increases both the backlog history and the counts of agent/response activity.

So when you load archived chats, you’re not just filling backlog history; you’re also making sure “messages sent” and “response-rate (same_day / later / never per inbound message)” include those sends. The queries are written to include Current + Archived for that reason.

---

## Loading archived more carefully

You mentioned wanting to “load archived chats more carefully” while still giving agents credit. Things to consider:

1. **Scope of “current backlog”**  
   If “backlog currently” should only mean *non-archived* threads waiting on us, we can add `WHERE bucket = 'Current'` to `metabase_backlog_current.sql`. Right now it counts all threads in the table whose last message is inbound (Current + Archived).

2. **Scope of agent/response metrics**  
   Agent message counts and response rate are intentionally **not** filtered by bucket, so archived threads still contribute. No change needed unless you want a separate “Current only” metric.

3. **Scraper**  
   `ARCHIVED_STOP_YEAR` and `--max-archived` already limit how far back you scrape. You can tighten or relax those (e.g. scrape more archived to improve agent metrics, or cap to reduce run time).

If you want “backlog currently” to mean only Current inbox, say so and we can add the bucket filter to that query only.
