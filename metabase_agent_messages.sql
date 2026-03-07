-- Agent messages: for a given time period, how many messages each agent sent.
-- Dashboard: add a filter and link it to "start_date" and/or "end_date" (Date) and "agent" (Text or Dropdown).
-- Optional: leave date or agent blank to see all. Includes Current + Archived.
--
-- Table: analytics.upload_secure_comms_messages_20260220190513 (replace if different).
-- Simple date: CAST(message_timestamp AS DATE).

SELECT
  CAST(message_timestamp AS DATE) AS message_date,
  sender_email,
  COUNT(*) AS message_count
FROM "analytics"."upload_secure_comms_messages_20260220190513"
WHERE message_timestamp IS NOT NULL
  AND direction = 'outbound'
  [[AND CAST(message_timestamp AS DATE) >= {{start_date}}]]
  [[AND CAST(message_timestamp AS DATE) <= {{end_date}}]]
  [[AND sender_email = {{agent}}]]
GROUP BY CAST(message_timestamp AS DATE), sender_email
ORDER BY message_date, message_count DESC, sender_email;
