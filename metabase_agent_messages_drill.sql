-- Drill-down: one row per message for the selected date/agent (from Agent messages summary).
-- Use as a separate Metabase question; link it as "Drill-through" from the Agent messages card.
--
-- Metabase: Create a question from this SQL. Add variables: start_date, end_date (Date),
-- agent (Text), message_date (Date), drill_agent (Text). Then on the Agent messages card:
-- Click "..." → "Drill-through" → "Go to a custom destination" (or "See this record" if
-- you use a model). Map: message_date ← clicked row's message_date, drill_agent ← sender_email.
--
-- Parameters (all optional; pass from dashboard or from clicked row):
--   start_date, end_date, agent  – same as summary (narrow by period / agent).
--   message_date                  – from clicked row: CAST(message_timestamp AS DATE).
--   drill_agent                    – from clicked row: sender_email.
-- If you only pass message_date and drill_agent, you see all messages for that day and agent.
--
-- Table: analytics.upload_secure_comms_messages_20260220190513 (replace if different).
-- "from" / "to" are quoted because they are reserved words.

SELECT
  communication_id,
  reference,
  subject,
  escalation_level,
  "from",
  "to",
  bucket,
  mpxn_type,
  mpxn_value,
  meter_point_number,
  created_at,
  updated_at,
  message_index,
  message_type,
  sender_email,
  message_timestamp,
  message_content,
  direction
FROM "analytics"."upload_secure_comms_messages_20260220190513"
WHERE message_timestamp IS NOT NULL
  AND direction = 'outbound'
  [[AND CAST(message_timestamp AS DATE) >= {{start_date}}]]
  [[AND CAST(message_timestamp AS DATE) <= {{end_date}}]]
  [[AND sender_email = {{agent}}]]
  [[AND CAST(message_timestamp AS DATE) = {{message_date}}]]
  [[AND sender_email = {{drill_agent}}]]
ORDER BY message_timestamp DESC, communication_id, message_index;
