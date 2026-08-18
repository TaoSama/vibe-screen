CREATE TABLE IF NOT EXISTS relay_schema_migrations (
    version bigint PRIMARY KEY,
    checksum_sha256 text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE relay_devices (
    device_id text PRIMARY KEY,
    revoked boolean NOT NULL DEFAULT false,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE relay_daily_usage (
    device_id text NOT NULL REFERENCES relay_devices(device_id),
    usage_day date NOT NULL,
    ingress_bytes numeric NOT NULL DEFAULT 0 CHECK (ingress_bytes >= 0),
    egress_bytes numeric NOT NULL DEFAULT 0 CHECK (egress_bytes >= 0),
    PRIMARY KEY (device_id, usage_day)
);

CREATE TABLE relay_active_sessions (
    device_id text NOT NULL REFERENCES relay_devices(device_id),
    session_id text NOT NULL,
    opened_at timestamptz NOT NULL,
    PRIMARY KEY (device_id, session_id)
);

CREATE TABLE relay_usage_events (
    device_id text NOT NULL REFERENCES relay_devices(device_id),
    event_day date NOT NULL,
    event_id text NOT NULL CONSTRAINT relay_usage_events_event_id_check CHECK (event_id <> ''),
    payload_sha256 bytea NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (device_id, event_day, event_id)
);
