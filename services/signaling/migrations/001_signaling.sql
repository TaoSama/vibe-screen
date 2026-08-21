CREATE TABLE IF NOT EXISTS signaling_schema_migrations (
    version bigint PRIMARY KEY,
    checksum_sha256 text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signaling_sessions (
    session_id text PRIMARY KEY,
    request_id text NOT NULL UNIQUE,
    ttl_seconds bigint NOT NULL CHECK (ttl_seconds >= 0),
    expires_at timestamptz NOT NULL,
    host_token text,
    device_token text,
    invalidated boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS signaling_sessions_expires_idx ON signaling_sessions(expires_at);

CREATE TABLE IF NOT EXISTS signaling_messages (
    session_id text NOT NULL REFERENCES signaling_sessions(session_id) ON DELETE CASCADE,
    sender_role text NOT NULL CHECK (sender_role IN ('host','device')),
    message_id text NOT NULL,
    message_type text NOT NULL CHECK (message_type IN ('offer','answer','ice_candidate','end_of_candidates')),
    sdp text NOT NULL DEFAULT '',
    candidate jsonb,
    sequence bigint NOT NULL CHECK (sequence > 0),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (session_id, sender_role, message_id),
    UNIQUE (session_id, sequence)
);
CREATE INDEX IF NOT EXISTS signaling_messages_poll_idx ON signaling_messages(session_id, sequence);

CREATE TABLE IF NOT EXISTS signaling_role_rates (
    session_id text NOT NULL REFERENCES signaling_sessions(session_id) ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('host','device')),
    window_started_at timestamptz NOT NULL,
    message_count integer NOT NULL CHECK (message_count >= 0),
    PRIMARY KEY (session_id, role)
);

-- Upgrade deploy order: drain or stop instances that still use the legacy
-- signaling_waiters counter schema, apply this migration, then start instances
-- that use signaling_waiter_leases.
DROP TABLE IF EXISTS signaling_waiters;

CREATE TABLE IF NOT EXISTS signaling_waiter_leases (
    session_id text NOT NULL REFERENCES signaling_sessions(session_id) ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('host','device')),
    lease_id text NOT NULL,
    backend_pid integer NOT NULL CHECK (backend_pid > 0),
    backend_started_at timestamptz NOT NULL,
    registered_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, role, lease_id)
);
CREATE INDEX IF NOT EXISTS signaling_waiter_leases_backend_idx
    ON signaling_waiter_leases(backend_pid, backend_started_at);
