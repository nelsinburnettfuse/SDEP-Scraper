-- Backlog that cumulates over time: as of each day at midnight, how many threads
-- have their latest message (so far) inbound, by escalation level.
--
-- Definition: "Backlog on date D" = threads where the chronologically latest
-- message in the thread (with timestamp <= end of D) is inbound (waiting on us).
-- That count can grow or shrink day-to-day as we reply or new inbound arrives.
--
-- Single snapshot: This query assumes one table with full message history. The
-- result is correct for every day in the data range. For ongoing use with
-- periodic uploads, point the table to your latest upload or add a snapshot_date
-- and filter to the snapshot current as of each day if you need true history.
-- Redshift-compatible (no generate_series). all_dates = days that appear in data.
-- Drillable: returns one row per (day, escalation, communication_id). In Metabase,
-- add a visualization that summarizes (e.g. Count of communication_id by day_at_midnight
-- and escalation_level); drill-through / "View details" will show the underlying threads.
-- Uses table: analytics.upload_secure_comms_messages_20260220190513
--
-- Simple date handling (CAST to DATE only). If you get cast errors, see
-- metabase_backlog_by_day_robust_dates.sql.

WITH ordered_messages AS (
  SELECT
    communication_id,
    message_timestamp,
    CAST(message_timestamp AS DATE) AS msg_date,
    direction,
    escalation_level,
    LEAD(CAST(message_timestamp AS DATE)) OVER (
      PARTITION BY communication_id
      ORDER BY message_timestamp
    ) AS next_msg_date
  FROM "analytics"."upload_secure_comms_messages_20260220190513"
  WHERE message_timestamp IS NOT NULL
),
max_date AS (
  SELECT MAX(CAST(message_timestamp AS DATE)) AS d
  FROM "analytics"."upload_secure_comms_messages_20260220190513"
  WHERE message_timestamp IS NOT NULL
),
date_ranges AS (
  SELECT
    communication_id,
    msg_date,
    COALESCE(DATEADD(day, -1, next_msg_date), (SELECT d FROM max_date)) AS end_date,
    direction,
    escalation_level
  FROM ordered_messages
),
all_dates AS (
  SELECT DISTINCT CAST(message_timestamp AS DATE) AS day_at_midnight
  FROM "analytics"."upload_secure_comms_messages_20260220190513"
  WHERE message_timestamp IS NOT NULL
),
exploded AS (
  SELECT
    ad.day_at_midnight,
    COALESCE(NULLIF(TRIM(dr.escalation_level), ''), 'Unknown') AS escalation_level,
    dr.communication_id
  FROM date_ranges dr
  INNER JOIN all_dates ad
    ON ad.day_at_midnight >= dr.msg_date
   AND ad.day_at_midnight <= dr.end_date
  WHERE dr.direction = 'inbound'
)
SELECT
  day_at_midnight,
  escalation_level,
  communication_id
FROM exploded
ORDER BY day_at_midnight, escalation_level, communication_id;
