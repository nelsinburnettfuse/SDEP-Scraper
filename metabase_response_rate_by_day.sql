-- Response rate at message level: for each inbound message, did we send a following
-- outbound on the same day, on a later day, or never? One row per inbound message.
--
-- On a given day: how many messages we received (inbound), and of those how many got
-- same_day / later / never response. Summarize in Metabase by message_date (and
-- optionally escalation_level) to get counts; keep communication_id for drilling.
-- Includes Current + Archived.
--
-- Table: analytics.upload_secure_comms_messages_20260220190513 (replace if different).
-- Simple date: CAST(message_timestamp AS DATE).

WITH inbounds AS (
  SELECT
    communication_id,
    message_timestamp,
    CAST(message_timestamp AS DATE) AS inbound_date,
    COALESCE(NULLIF(TRIM(escalation_level), ''), 'Unknown') AS escalation_level
  FROM "analytics"."upload_secure_comms_messages_20260220190513"
  WHERE message_timestamp IS NOT NULL
    AND direction = 'inbound'
),
outbounds AS (
  SELECT
    communication_id,
    message_timestamp,
    CAST(message_timestamp AS DATE) AS outbound_date
  FROM "analytics"."upload_secure_comms_messages_20260220190513"
  WHERE message_timestamp IS NOT NULL
    AND direction = 'outbound'
),
first_response AS (
  SELECT
    i.communication_id,
    i.message_timestamp,
    i.inbound_date,
    i.escalation_level,
    MIN(o.outbound_date) AS first_outbound_date
  FROM inbounds i
  LEFT JOIN outbounds o
    ON o.communication_id = i.communication_id
   AND o.message_timestamp > i.message_timestamp
  GROUP BY i.communication_id, i.message_timestamp, i.inbound_date, i.escalation_level
)
SELECT
  inbound_date AS message_date,
  communication_id,
  escalation_level,
  CASE
    WHEN first_outbound_date IS NULL THEN 'never'
    WHEN first_outbound_date = inbound_date THEN 'same_day'
    ELSE 'later'
  END AS response_type
FROM first_response
ORDER BY message_date, communication_id, message_timestamp;
