-- Sankey: SDEP messages → ET messages | Dispute messages | Other
-- ET branch: message_type → Has ET → Current Status
-- Dispute branch: message_type → Has dispute → (status if applicable)
--
-- Aggregated output (~50 rows) to stay under Metabase Sankey 2000-row limit.
-- For filtering underlying messages: use metabase_sankey_et_messages_filter.sql on the same
-- dashboard. Add filters on branch, message_type, has_dispute, dispute_status to narrow down.

WITH all_sdeps AS (
  SELECT message_type
  FROM analytics.upload_msg_ecoes_messages_full_20251027233420
),

-- ET branch: supply_definition → erroneous_transfer
base_et AS (
  SELECT
    m._mb_row_id,
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
    _mb_row_id,
    message_type,
    CASE WHEN et_current_status IS NOT NULL THEN 'Has ET' ELSE 'No ET' END AS has_et,
    COALESCE(et_current_status, 'ET: N/A') AS status_display
  FROM base_et
),

-- Latest dispute per (supply_fid, registration_date_uk): use status of the most recent one
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

-- Dispute branch: supply_definition → latest dispute per (supply_fid, registration_date_uk)
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
    mpxn_value,
    message_type,
    CASE WHEN dispute_supply_fid IS NOT NULL THEN 'Has dispute' ELSE 'No dispute' END AS has_dispute,
    COALESCE(dispute_message_status, 'Dispute: N/A') AS dispute_status_display
  FROM base_dispute
)

-- Level 0 → Level 1: SDEP messages → ET | Dispute | Other
SELECT
  'SDEP messages' AS source,
  CASE
    WHEN message_type IN (
      '[Elec]Erroneous Transfer -Escalation',
      '[Elec]Erroneous Transfer General Query',
      '[Elec]Erroneous Transfer Re-registration - Escalation',
      '[Gas]Erroneous Transfer - Escalation'
    ) THEN 'ET messages'
    WHEN message_type IN (
      '[Elec]Disputed meter readings - Escalation',
      '[Elec]Disputed meter readings - General Query',
      '[Elec]Missing read - Escalation',
      '[Elec]Missing read - General Query',
      '[Gas]Disputed Meter reading - Escalation',
      '[Gas]Disputed meter reading - General Query',
      '[Gas]Missing read - General Query'
    ) THEN 'Dispute messages'
    ELSE 'Other'
  END AS target,
  COUNT(*) AS value
FROM all_sdeps
GROUP BY 2

UNION ALL

-- ET: ET messages → message_type (COUNT DISTINCT to match filter, avoid join fan-out)
SELECT 'ET messages' AS source, message_type AS target, COUNT(DISTINCT COALESCE(CAST(_mb_row_id AS VARCHAR), CAST(mpxn_value AS VARCHAR) || '|' || message_type)) AS value
FROM base_et
GROUP BY 2

UNION ALL

-- ET: message_type → Has ET
SELECT message_type AS source, has_et AS target, COUNT(DISTINCT COALESCE(CAST(_mb_row_id AS VARCHAR), CAST(mpxn_value AS VARCHAR) || '|' || message_type)) AS value
FROM with_has_et
GROUP BY 1, 2

UNION ALL

-- ET: Has ET → Current Status
SELECT has_et AS source, status_display AS target, COUNT(DISTINCT COALESCE(CAST(_mb_row_id AS VARCHAR), CAST(mpxn_value AS VARCHAR) || '|' || message_type)) AS value
FROM with_has_et
GROUP BY 1, 2

UNION ALL

-- Dispute: Dispute messages → message_type (COUNT DISTINCT to avoid join fan-out; surrogate for NULL _mb_row_id)
SELECT 'Dispute messages' AS source, message_type AS target, COUNT(DISTINCT COALESCE(CAST(_mb_row_id AS VARCHAR), CAST(mpxn_value AS VARCHAR) || '|' || message_type)) AS value
FROM base_dispute
GROUP BY 2

UNION ALL

-- Dispute: message_type → Has dispute
SELECT message_type AS source, has_dispute AS target, COUNT(DISTINCT COALESCE(CAST(_mb_row_id AS VARCHAR), CAST(mpxn_value AS VARCHAR) || '|' || message_type)) AS value
FROM with_has_dispute
GROUP BY 1, 2

UNION ALL

-- Dispute: Has dispute → message_status (inbound, closed, outbound, flagged, or Dispute: N/A)
SELECT has_dispute AS source, dispute_status_display AS target, COUNT(DISTINCT COALESCE(CAST(_mb_row_id AS VARCHAR), CAST(mpxn_value AS VARCHAR) || '|' || message_type)) AS value
FROM with_has_dispute
GROUP BY 1, 2

ORDER BY source, target;
