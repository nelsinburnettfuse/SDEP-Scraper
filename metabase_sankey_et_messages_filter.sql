-- Filterable list: SDEP messages that contribute to the Sankey.
-- One row per message. Add dashboard filters on branch, message_type, has_dispute, dispute_status
-- (or has_et, et_status for ET branch) to narrow down progressively.
--
-- Example filters for Dispute branch:
--   1. branch = 'Dispute messages'
--   2. message_type = '[Elec]Missing read - General Query'
--   3. has_dispute = 'Has dispute'
--   4. dispute_status = 'closed'
--
-- Use with metabase_sankey_et_messages.sql on the same dashboard.

WITH base_et AS (
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

base_dispute_raw AS (
  SELECT
    m._mb_row_id,
    m.message_type,
    m.mpxn_value,
    ld.supply_fid AS dispute_supply_fid,
    ld.message_status AS dispute_message_status,
    ld.registration_date_uk
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
base_dispute AS (
  SELECT _mb_row_id, message_type, mpxn_value, dispute_supply_fid, dispute_message_status
  FROM (
    SELECT *,
      ROW_NUMBER() OVER (
        PARTITION BY COALESCE(CAST(_mb_row_id AS VARCHAR), CAST(mpxn_value AS VARCHAR) || '-' || message_type)
        ORDER BY registration_date_uk DESC NULLS LAST
      ) AS rn
    FROM base_dispute_raw
  ) sub
  WHERE rn = 1
),

base_other AS (
  SELECT _mb_row_id, message_type, mpxn_value
  FROM analytics.upload_msg_ecoes_messages_full_20251027233420
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
),

-- One row per message per branch; dedupe ET (join fan-out) via ROW_NUMBER for RedShift
et_deduped AS (
  SELECT _mb_row_id, mpxn_value, message_type, et_current_status,
    ROW_NUMBER() OVER (PARTITION BY COALESCE(CAST(_mb_row_id AS VARCHAR), CAST(mpxn_value AS VARCHAR) || '-' || message_type) ORDER BY et_current_status NULLS LAST) AS rn
  FROM base_et
),
et_messages AS (
  SELECT
    CAST(_mb_row_id AS VARCHAR) AS _mb_row_id,
    CAST(mpxn_value AS VARCHAR) AS mpxn_value,
    message_type,
    'ET messages' AS branch,
    CASE WHEN et_current_status IS NOT NULL THEN 'Has ET' ELSE 'No ET' END AS has_et,
    COALESCE(et_current_status, 'ET: N/A') AS et_status,
    NULL::VARCHAR AS has_dispute,
    NULL::VARCHAR AS dispute_status
  FROM et_deduped
  WHERE rn = 1
),
dispute_messages AS (
  SELECT
    CAST(_mb_row_id AS VARCHAR) AS _mb_row_id,
    CAST(mpxn_value AS VARCHAR) AS mpxn_value,
    message_type,
    'Dispute messages' AS branch,
    NULL::VARCHAR AS has_et,
    NULL::VARCHAR AS et_status,
    CASE WHEN dispute_supply_fid IS NOT NULL THEN 'Has dispute' ELSE 'No dispute' END AS has_dispute,
    COALESCE(dispute_message_status, 'Dispute: N/A') AS dispute_status
  FROM base_dispute
),
other_messages AS (
  SELECT
    CAST(_mb_row_id AS VARCHAR) AS _mb_row_id,
    CAST(mpxn_value AS VARCHAR) AS mpxn_value,
    message_type,
    'Other' AS branch,
    NULL::VARCHAR AS has_et,
    NULL::VARCHAR AS et_status,
    NULL::VARCHAR AS has_dispute,
    NULL::VARCHAR AS dispute_status
  FROM base_other
)
SELECT * FROM et_messages
UNION ALL
SELECT * FROM dispute_messages
UNION ALL
SELECT * FROM other_messages
ORDER BY branch, message_type, _mb_row_id, mpxn_value;
