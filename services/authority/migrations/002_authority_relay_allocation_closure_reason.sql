ALTER TABLE authority_relay_allocations
    ADD COLUMN IF NOT EXISTS closure_reason text;

UPDATE authority_relay_allocations
SET closure_reason = 'source_closed'
WHERE closed_at IS NOT NULL
  AND closure_reason IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE connamespace = current_schema()::regnamespace
          AND conname = 'authority_relay_allocations_closure_reason_check'
    ) THEN
        ALTER TABLE authority_relay_allocations
            ADD CONSTRAINT authority_relay_allocations_closure_reason_check CHECK (
                (closed_at IS NULL AND closure_reason IS NULL)
                OR (closed_at IS NOT NULL AND closure_reason IN (
                    'source_closed',
                    'account_suspended',
                    'device_revoked',
                    'signaling_invalidated',
                    'relay_quota_exceeded'
                ))
            );
    END IF;
END $$;
