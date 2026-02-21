# Metabase "You don't have permission to see the result"

If the backlog question returns that message, the block is usually from **Metabase or Redshift permissions**, not the SQL itself.

## 1. Minimal table test (run in Metabase → New question → Native query)

Use the same database and run:

```sql
SELECT COUNT(*) AS row_count
FROM "analytics"."upload_secure_comms_messages_20260220190513"
WHERE 1=1;
```

- **If this also says "no permission"**  
  You’re not allowed to run native SQL on this DB and/or don’t have `SELECT` on this table. An admin needs to fix that.

- **If this returns a number**  
  You can read the table. Try the tests below to narrow it down.

## 2. Is it the saved question or the SQL?

- **Run the full backlog SQL in a new native question** (New question → Native query → paste the full backlog SQL → Run). Don’t save it.
  - If you **see results** → the block is on the **saved question** (e.g. only creator can view). Fix: admin gives your group “View” permission on that question, or the creator shares it / changes “Who can see this”.
  - If you **still get “no permission”** → the block is likely on this **query shape** or **result**. Try the one-row backlog test next.

## 3. One-row backlog test (same logic, single number)

Run this; it uses the same logic as the backlog query but returns one row (total backlog as of latest date). Replace the table name if yours is different.

```sql
WITH msg_dates AS (
  SELECT
    communication_id,
    message_timestamp,
    CASE
      WHEN CAST(message_timestamp AS VARCHAR(256)) SIMILAR TO '%[A-Za-z]%'
      THEN CAST(CAST(message_timestamp AS TIMESTAMP) AS DATE)
      ELSE CAST(DATEADD(second, CAST(CASE WHEN CAST(message_timestamp AS DOUBLE PRECISION) > 1e12 THEN CAST(message_timestamp AS DOUBLE PRECISION) / 1000 ELSE CAST(message_timestamp AS DOUBLE PRECISION) END AS BIGINT), '1970-01-01'::timestamp) AS DATE)
    END AS msg_date,
    direction,
    escalation_level
  FROM "analytics"."upload_secure_comms_messages_20260220190513"
  WHERE message_timestamp IS NOT NULL
),
ordered_messages AS (
  SELECT communication_id, msg_date, direction,
    LEAD(msg_date) OVER (PARTITION BY communication_id ORDER BY message_timestamp) AS next_msg_date
  FROM msg_dates
),
max_date AS (SELECT MAX(msg_date) AS d FROM msg_dates),
date_ranges AS (
  SELECT communication_id, msg_date,
    COALESCE(DATEADD(day, -1, next_msg_date), (SELECT d FROM max_date)) AS end_date,
    direction
  FROM ordered_messages
),
last_date AS (SELECT MAX(msg_date) AS d FROM msg_dates),
backlog_as_of_last AS (
  SELECT dr.communication_id
  FROM date_ranges dr
  CROSS JOIN last_date ld
  WHERE dr.direction = 'inbound'
    AND dr.msg_date <= ld.d
    AND (dr.end_date >= ld.d OR dr.end_date IS NULL)
)
SELECT COUNT(DISTINCT communication_id) AS total_backlog
FROM backlog_as_of_last;
```

- **If this works** → the blocker may be **many rows** or **certain columns** in the full result. An admin can check sandboxing/limits.
- **If this also says "no permission"** → the block is likely on **any non-trivial query** on this table, or your group’s native/SQL permissions. Admin should check group permissions and data sandboxing.

## 4. What an admin should check

- **Metabase**
  - Database: "Can users run native (SQL) questions?" and that your group is allowed.
  - Group permissions: "Native query editing" and "View data" (or "Create queries") for this database.
  - The **saved question**: "Can non-creators view this question?" and that your group can "View" it.
  - Data sandboxing: if the table (or a related one) is sandboxed, ensure your user/group gets at least read access to the rows needed for the backlog query.

- **Redshift**
  - Your user (or the Metabase DB user, if queries run as that) has `SELECT` on `analytics.upload_secure_comms_messages_20260220190513` (and on `analytics` if required).
  - No RLS (row-level security) that denies all rows for your user.

## 5. Table name

If your table has a different name (e.g. a new upload), replace  
`"analytics"."upload_secure_comms_messages_20260220190513"`  
in both the minimal test and `metabase_backlog_by_day.sql` with the actual schema and table name.
