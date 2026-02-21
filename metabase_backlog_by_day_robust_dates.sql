-- Same as metabase_backlog_by_day.sql but with Redshift-safe date parsing when
-- message_timestamp is varchar (e.g. "20 Feb 2026 14:14") or numeric (epoch sec/ms).
-- Use this if the simple query fails with cast errors; you may need admin to allow
-- this question (DOUBLE PRECISION / SIMILAR TO can trigger permission blocks).

WITH msg_dates AS (
  SELECT
    communication_id,
    message_timestamp,
    CASE
      WHEN CAST(message_timestamp AS VARCHAR(256)) SIMILAR TO '%[A-Za-z]%'
      THEN CAST(CAST(message_timestamp AS TIMESTAMP) AS DATE)
      ELSE CAST(
        DATEADD(
          second,
          CAST(
            CASE
              WHEN CAST(message_timestamp AS DOUBLE PRECISION) > 1e12
              THEN CAST(message_timestamp AS DOUBLE PRECISION) / 1000
              ELSE CAST(message_timestamp AS DOUBLE PRECISION)
            END AS BIGINT
          ),
          '1970-01-01'::timestamp
        ) AS DATE
      )
    END AS msg_date,
    direction,
    escalation_level
  FROM "analytics"."upload_secure_comms_messages_20260220190513"
  WHERE message_timestamp IS NOT NULL
),
ordered_messages AS (
  SELECT
    communication_id,
    message_timestamp,
    msg_date,
    direction,
    escalation_level,
    LEAD(msg_date) OVER (
      PARTITION BY communication_id
      ORDER BY message_timestamp
    ) AS next_msg_date
  FROM msg_dates
),
max_date AS (
  SELECT MAX(msg_date) AS d
  FROM msg_dates
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
  SELECT DISTINCT msg_date AS day_at_midnight
  FROM msg_dates
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
  COUNT(DISTINCT communication_id) AS thread_count
FROM exploded
GROUP BY day_at_midnight, escalation_level
ORDER BY day_at_midnight, escalation_level;
