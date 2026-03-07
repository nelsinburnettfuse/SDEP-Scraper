-- Drill-down: underlying messages for any Sankey segment.
-- Use with metabase_sankey_et_messages.sql (aggregated Sankey, stays under 2000-row limit).
--
-- Setup: Create a Metabase question from this SQL. Add variables: source (Text), target (Text).
-- Link as Drill-through from the Sankey card: map source/target from the clicked segment.
-- Or add to the same dashboard; users can filter by source/target to see messages for a segment.
--
-- Parameters (optional): {{source}}, {{target}} – filter to messages for that link.
--
-- Table names: replace with your upload / dbt model versions.

WITH all_sdeps AS (
  SELECT message_type
  FROM analytics.upload_msg_ecoes_messages_full_20251027233420
),

base_et AS (
  SELECT
    m.message_type,
    m.mpxn_value,
    et.current_status AS et_current_status
  FROM analytics.upload_msg_ecoes_messages_full_20251027233420 m
  LEFT JOIN fuse_supply.supply_definition sd ON m.mpxn_value = sd.identifier
  LEFT JOIN dbt_ops_switching.erroneous_transfer et ON sd.fid = et.supply_fid
  WHERE m.message_type IN (
    '[Elec]Erroneous Transfer -Escalation',
    '[Elec]Erroneous Transfer General Query',
    '[Elec]Erroneous Transfer Re-registration - Escalation',
    '[Gas]Erroneous Transfer - Escalation'
  )
),

with_has_et AS (
  SELECT
    message_type,
    mpxn_value,
    CASE WHEN et_current_status IS NOT NULL THEN 'Has ET' ELSE 'No ET' END AS has_et,
    COALESCE(et_current_status, 'ET: N/A') AS status_display
  FROM base_et
),

latest_dispute_per_supply_reg AS (
  SELECT supply_fid, registration_date_uk, message_status,
    ROW_NUMBER() OVER (PARTITION BY supply_fid, registration_date_uk ORDER BY updated_at DESC) AS rn
  FROM dbt_ops_readings.disputed_missing_read
),
latest_dispute AS (
  SELECT supply_fid, registration_date_uk, message_status
  FROM latest_dispute_per_supply_reg
  WHERE rn = 1
),

base_dispute AS (
  SELECT
    m._mb_row_id,
    m.message_type,
    m.mpxn_value,
    ld.supply_fid AS dispute_supply_fid,
    ld.message_status AS dispute_message_status
  FROM analytics.upload_msg_ecoes_messages_full_20251027233420 m
  LEFT JOIN fuse_supply.supply_definition sd ON m.mpxn_value = sd.identifier
  LEFT JOIN latest_dispute ld ON sd.fid = ld.supply_fid
  WHERE m.message_type IN (
    '[Elec]Disputed meter readings - Escalation',
    '[Elec]Disputed meter readings - General Query',
    '[Elec]Missing read - Escalation',
    '[Elec]Missing read - General Query',
    '[Gas]Disputed Meter reading - Escalation',
    '[Gas]Disputed meter reading - General Query',
    '[Gas]Missing read - General Query'
  )
),

with_has_dispute AS (
  SELECT
    _mb_row_id,
    message_type,
    mpxn_value,
    CASE WHEN dispute_supply_fid IS NOT NULL THEN 'Has dispute' ELSE 'No dispute' END AS has_dispute,
    COALESCE(dispute_message_status, 'Dispute: N/A') AS dispute_status_display
  FROM base_dispute
),

-- Drill rows: one per message per link. Use _mb_row_id where we have it.
-- Cast to VARCHAR for RedShift UNION compatibility (table types may be bigint/varchar).
drill_rows AS (
  -- Level 0→1 from ET branch (has mpxn, use message_type as proxy for row)
  SELECT 'SDEP messages' AS source, 'ET messages' AS target, CAST(NULL AS VARCHAR) AS _mb_row_id, CAST(mpxn_value AS VARCHAR) AS mpxn_value, message_type
  FROM base_et
  UNION ALL
  -- Level 0→1 from Dispute branch
  SELECT 'SDEP messages' AS source, 'Dispute messages' AS target, CAST(_mb_row_id AS VARCHAR) AS _mb_row_id, CAST(mpxn_value AS VARCHAR) AS mpxn_value, message_type
  FROM base_dispute
  UNION ALL
  -- Level 0→1 Other: all_sdeps minus ET and Dispute
  SELECT 'SDEP messages' AS source, 'Other' AS target, CAST(NULL AS VARCHAR) AS _mb_row_id, CAST(NULL AS VARCHAR) AS mpxn_value, message_type
  FROM all_sdeps
  WHERE message_type NOT IN (
    '[Elec]Erroneous Transfer -Escalation',
    '[Elec]Erroneous Transfer General Query',
    '[Elec]Erroneous Transfer Re-registration - Escalation',
    '[Gas]Erroneous Transfer - Escalation',
    '[Elec]Disputed meter readings - Escalation',
    '[Elec]Disputed meter readings - General Query',
    '[Elec]Missing read - Escalation',
    '[Elec]Missing read - General Query',
    '[Gas]Disputed Meter reading - Escalation',
    '[Gas]Disputed meter reading - General Query',
    '[Gas]Missing read - General Query'
  )
  UNION ALL
  -- ET: ET messages → message_type
  SELECT 'ET messages' AS source, message_type AS target, CAST(NULL AS VARCHAR) AS _mb_row_id, CAST(mpxn_value AS VARCHAR) AS mpxn_value, message_type
  FROM base_et
  UNION ALL
  -- ET: message_type → Has ET
  SELECT message_type AS source, has_et AS target, CAST(NULL AS VARCHAR) AS _mb_row_id, CAST(mpxn_value AS VARCHAR) AS mpxn_value, message_type
  FROM with_has_et
  UNION ALL
  -- ET: Has ET → status
  SELECT has_et AS source, status_display AS target, CAST(NULL AS VARCHAR) AS _mb_row_id, CAST(mpxn_value AS VARCHAR) AS mpxn_value, message_type
  FROM with_has_et
  UNION ALL
  -- Dispute: Dispute messages → message_type
  SELECT 'Dispute messages' AS source, message_type AS target, CAST(_mb_row_id AS VARCHAR) AS _mb_row_id, CAST(mpxn_value AS VARCHAR) AS mpxn_value, message_type
  FROM base_dispute
  UNION ALL
  -- Dispute: message_type → Has dispute
  SELECT message_type AS source, has_dispute AS target, CAST(_mb_row_id AS VARCHAR) AS _mb_row_id, CAST(mpxn_value AS VARCHAR) AS mpxn_value, message_type
  FROM with_has_dispute
  UNION ALL
  -- Dispute: Has dispute → status
  SELECT has_dispute AS source, dispute_status_display AS target, CAST(_mb_row_id AS VARCHAR) AS _mb_row_id, CAST(mpxn_value AS VARCHAR) AS mpxn_value, message_type
  FROM with_has_dispute
)
SELECT DISTINCT
  source,
  target,
  _mb_row_id,
  mpxn_value,
  message_type
FROM drill_rows
WHERE 1=1
  [[AND source = {{source}}]]
  [[AND target = {{target}}]]
ORDER BY source, target, _mb_row_id NULLS LAST, mpxn_value, message_type;
