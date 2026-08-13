CREATE TABLE IF NOT EXISTS authority_schema_migrations (
    version bigint PRIMARY KEY,
    checksum_sha256 text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS authority_accounts (
    account_id text PRIMARY KEY,
    suspended_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS authority_devices (
    device_id text PRIMARY KEY,
    account_id text NOT NULL REFERENCES authority_accounts(account_id),
    revocation_epoch bigint NOT NULL DEFAULT 0 CHECK (revocation_epoch >= 0),
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS authority_devices_account_idx ON authority_devices(account_id);

CREATE TABLE authority_session_epoch_floors (
    device_id text PRIMARY KEY REFERENCES authority_devices(device_id),
    highest_epoch bigint NOT NULL CHECK (highest_epoch > 0),
    CONSTRAINT authority_session_epoch_floors_epoch_check CHECK (highest_epoch <= 9223372036854775807)
);

CREATE TABLE authority_signaling_sessions (
    session_id text PRIMARY KEY,
    request_id text NOT NULL UNIQUE,
    account_id text NOT NULL REFERENCES authority_accounts(account_id),
    host_device_id text NOT NULL REFERENCES authority_devices(device_id),
    client_device_id text NOT NULL REFERENCES authority_devices(device_id),
    session_epoch bigint NOT NULL CHECK (session_epoch > 0),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (host_device_id, client_device_id, session_epoch)
);
CREATE INDEX IF NOT EXISTS authority_signaling_active_idx
    ON authority_signaling_sessions (client_device_id, expires_at)
    WHERE revoked_at IS NULL;

CREATE TABLE authority_relay_daily_usage (
    device_id text NOT NULL REFERENCES authority_devices(device_id),
    usage_day date NOT NULL,
    ingress_bytes bigint NOT NULL DEFAULT 0 CHECK (ingress_bytes >= 0),
    egress_bytes bigint NOT NULL DEFAULT 0 CHECK (egress_bytes >= 0),
    PRIMARY KEY (device_id, usage_day)
);

CREATE TABLE authority_relay_allocations (
    allocation_id text NOT NULL,
    source_id text NOT NULL,
    device_id text NOT NULL REFERENCES authority_devices(device_id),
    session_id text NOT NULL,
    observed_sequence bigint NOT NULL DEFAULT 0 CHECK (observed_sequence >= 0),
    ingress_bytes bigint NOT NULL DEFAULT 0 CHECK (ingress_bytes >= 0),
    egress_bytes bigint NOT NULL DEFAULT 0 CHECK (egress_bytes >= 0),
    admitted_at timestamptz NOT NULL,
    last_observed_at timestamptz NOT NULL,
    closed_at timestamptz,
    PRIMARY KEY (source_id, allocation_id),
    CONSTRAINT authority_relay_allocations_session_fk FOREIGN KEY (session_id)
        REFERENCES authority_signaling_sessions(session_id)
);
CREATE INDEX IF NOT EXISTS authority_relay_active_device_idx
    ON authority_relay_allocations (device_id)
    WHERE closed_at IS NULL;

CREATE TABLE authority_coturn_events (
    source_id text NOT NULL,
    event_id text NOT NULL CONSTRAINT authority_coturn_events_event_id_check CHECK (event_id <> ''),
    payload_sha256 bytea NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, event_id)
);

CREATE TABLE authority_audit_events (
    audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_type text NOT NULL,
    account_id text,
    device_id text,
    session_id text,
    occurred_at timestamptz NOT NULL DEFAULT now()
);
