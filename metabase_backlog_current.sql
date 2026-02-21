-- Backlog right now: count of threads whose latest message (in the dataset) is inbound.
-- "Currently" = as of the latest message_timestamp in the table (or filter by date in Metabase).
-- Drillable: returns one row per thread in backlog (communication_id, escalation_level).
-- Include Current + Archived so backlog count is across all loaded threads.
--
-- Table: analytics.upload_secure_comms_messages_20260220190513 (replace if different).
-- Simple date: CAST(message_timestamp AS DATE). For robust date parsing see robust_dates file.

WITH last_message_per_thread AS (
  SELECT
    communication_id,
    direction,
    escalation_level,
    ROW_NUMBER() OVER (
      PARTITION BY communication_id
      ORDER BY message_timestamp DESC
    ) AS rn
  FROM "analytics"."upload_secure_comms_messages_20260220190513"
  WHERE message_timestamp IS NOT NULL
),
backlog_threads AS (
  SELECT
    communication_id,
    COALESCE(NULLIF(TRIM(escalation_level), ''), 'Unknown') AS escalation_level
  FROM last_message_per_thread
  WHERE rn = 1
    AND direction = 'inbound'
)
SELECT
  communication_id,
  escalation_level
FROM backlog_threads
ORDER BY escalation_level, communication_id;
