package relay

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

type PostgresStore struct {
	pool                     *pgxpool.Pool
	dailyLimit               uint64
	sessionLimit             int
	maximumDatabaseClockSkew time.Duration
	now                      func() time.Time
}

const (
	requiredSchemaVersion  int64 = 1
	requiredSchemaChecksum       = "26a9dcb3ec632342c543b975a1f778da202f9bb3fad965bf8efe5e80a0e88a21"
)

func OpenPostgres(ctx context.Context, cfg Config) (*PostgresStore, error) {
	pool, err := pgxpool.New(ctx, cfg.DatabaseURL)
	if err != nil {
		return nil, fmt.Errorf("open relay database: %w", err)
	}
	store := &PostgresStore{
		pool:                     pool,
		dailyLimit:               cfg.DailyBytesPerDevice,
		sessionLimit:             cfg.MaxConcurrentSessionsPerDevice,
		maximumDatabaseClockSkew: cfg.MaximumDatabaseClockSkew(),
		now:                      time.Now,
	}
	if err := store.Ready(ctx); err != nil {
		pool.Close()
		return nil, err
	}
	return store, nil
}

func (s *PostgresStore) Close() { s.pool.Close() }

func (s *PostgresStore) Ready(ctx context.Context) error {
	hostBefore := s.now().UTC()
	var databaseNow time.Time
	if err := s.pool.QueryRow(ctx, "SELECT clock_timestamp()").Scan(&databaseNow); err != nil {
		return storageError("database clock probe", err)
	}
	hostAfter := s.now().UTC()
	if err := validateDatabaseClock(databaseNow.UTC(), hostBefore, hostAfter, s.maximumDatabaseClockSkew); err != nil {
		return storageError("database clock probe", err)
	}
	var version int64
	var checksum string
	if err := s.pool.QueryRow(ctx, "SELECT version,checksum_sha256 FROM relay_schema_migrations ORDER BY version DESC LIMIT 1").Scan(&version, &checksum); err != nil {
		return storageError("schema probe", err)
	}
	if version != requiredSchemaVersion || checksum != requiredSchemaChecksum {
		return storageError("schema version/checksum mismatch", errors.New("relay schema drift"))
	}
	var complete bool
	if err := s.pool.QueryRow(ctx, "SELECT every(to_regclass(name) IS NOT NULL) FROM unnest($1::text[]) AS name", []string{"relay_schema_migrations", "relay_devices", "relay_daily_usage", "relay_active_sessions", "relay_usage_events"}).Scan(&complete); err != nil {
		return storageError("structure probe", err)
	}
	if !complete {
		return storageError("required relay relation is missing", errors.New("missing relation"))
	}
	if _, err := s.pool.Exec(ctx, "SELECT m.version,m.checksum_sha256,m.applied_at,d.device_id,d.revoked,d.revoked_at,d.created_at,u.device_id,u.usage_day,u.ingress_bytes,u.egress_bytes,a.device_id,a.session_id,a.opened_at,e.device_id,e.event_day,e.event_id,e.payload_sha256,e.received_at FROM relay_schema_migrations m,relay_devices d,relay_daily_usage u,relay_active_sessions a,relay_usage_events e LIMIT 0"); err != nil {
		return storageError("required relay column is missing", err)
	}
	var constraints int
	requiredConstraints := []string{
		"relay_schema_migrations_pkey",
		"relay_devices_pkey",
		"relay_daily_usage_pkey",
		"relay_daily_usage_device_id_fkey",
		"relay_daily_usage_ingress_bytes_check",
		"relay_daily_usage_egress_bytes_check",
		"relay_active_sessions_pkey",
		"relay_active_sessions_device_id_fkey",
		"relay_usage_events_pkey",
		"relay_usage_events_device_id_fkey",
		"relay_usage_events_event_id_check",
	}
	if err := s.pool.QueryRow(ctx, "SELECT count(*) FROM pg_constraint WHERE connamespace=current_schema()::regnamespace AND conname=ANY($1)", requiredConstraints).Scan(&constraints); err != nil {
		return storageError("required relay constraint is missing", err)
	}
	if constraints != len(requiredConstraints) {
		return storageError("required relay constraint is missing", errors.New("constraint count mismatch"))
	}
	tables := []string{
		"relay_schema_migrations", "relay_schema_migrations",
		"relay_devices", "relay_devices", "relay_devices",
		"relay_daily_usage", "relay_daily_usage", "relay_daily_usage", "relay_daily_usage",
		"relay_active_sessions", "relay_active_sessions", "relay_active_sessions",
		"relay_usage_events", "relay_usage_events", "relay_usage_events", "relay_usage_events",
	}
	columns := []string{
		"version", "checksum_sha256",
		"device_id", "revoked", "revoked_at",
		"device_id", "usage_day", "ingress_bytes", "egress_bytes",
		"device_id", "session_id", "opened_at",
		"device_id", "event_day", "event_id", "payload_sha256",
	}
	types := []string{
		"bigint", "text",
		"text", "boolean", "timestamp with time zone",
		"text", "date", "numeric", "numeric",
		"text", "text", "timestamp with time zone",
		"text", "date", "text", "bytea",
	}
	nullable := []string{
		"NO", "NO",
		"NO", "NO", "YES",
		"NO", "NO", "NO", "NO",
		"NO", "NO", "NO",
		"NO", "NO", "NO", "NO",
	}
	if err := s.pool.QueryRow(ctx, "SELECT count(*)=$5 FROM unnest($1::text[],$2::text[],$3::text[],$4::text[]) AS expected(table_name,column_name,data_type,is_nullable) JOIN information_schema.columns actual ON actual.table_schema=current_schema() AND actual.table_name=expected.table_name AND actual.column_name=expected.column_name AND actual.data_type=expected.data_type AND actual.is_nullable=expected.is_nullable", tables, columns, types, nullable, len(tables)).Scan(&complete); err != nil {
		return storageError("required relay column signature mismatch", err)
	}
	if !complete {
		return storageError("required relay column signature mismatch", errors.New("column signature mismatch"))
	}
	return nil
}

func validateDatabaseClock(databaseNow, hostBefore, hostAfter time.Time, maximumSkew time.Duration) error {
	if databaseNow.IsZero() || hostBefore.IsZero() || hostAfter.IsZero() || maximumSkew <= 0 {
		return errors.New("invalid clock sample")
	}
	if hostAfter.Before(hostBefore) {
		return errors.New("host clock moved backwards during probe")
	}
	if databaseNow.Before(hostAfter.Add(-maximumSkew)) || databaseNow.After(hostBefore.Add(maximumSkew)) {
		return errors.New("database clock exceeds the configured skew limit")
	}
	return nil
}

func (s *PostgresStore) Apply(ctx context.Context, now time.Time, event UsageEvent) error {
	day := now.UTC().Format(time.DateOnly)
	payloadDigest, err := usageEventDigest(event)
	if err != nil {
		return fmt.Errorf("%w: %v", ErrInvalidEvent, err)
	}
	return s.transaction(ctx, func(tx pgx.Tx) error {
		if err := ensureDevice(ctx, tx, event.DeviceID); err != nil {
			return err
		}
		var existing []byte
		err := tx.QueryRow(ctx, "SELECT payload_sha256 FROM relay_usage_events WHERE device_id=$1 AND event_day=$2 AND event_id=$3", event.DeviceID, day, event.EventID).Scan(&existing)
		if err == nil {
			if !hmac.Equal(existing, payloadDigest) {
				return ErrInvalidEvent
			}
			return ErrDuplicateEvent
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		var revoked bool
		if err := tx.QueryRow(ctx, "SELECT revoked FROM relay_devices WHERE device_id=$1 FOR UPDATE", event.DeviceID).Scan(&revoked); err != nil {
			return err
		}
		if revoked {
			return ErrDeviceRevoked
		}
		tag, err := tx.Exec(ctx, "INSERT INTO relay_usage_events(device_id,event_day,event_id,payload_sha256) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING", event.DeviceID, day, event.EventID, payloadDigest)
		if err != nil {
			return err
		}
		if tag.RowsAffected() == 0 {
			if err := tx.QueryRow(ctx, "SELECT payload_sha256 FROM relay_usage_events WHERE device_id=$1 AND event_day=$2 AND event_id=$3", event.DeviceID, day, event.EventID).Scan(&existing); err != nil {
				return err
			}
			if !hmac.Equal(existing, payloadDigest) {
				return ErrInvalidEvent
			}
			return ErrDuplicateEvent
		}
		ingress, egress, err := dailyUsage(ctx, tx, event.DeviceID, day)
		if err != nil {
			return err
		}
		if event.IngressBytes > ^uint64(0)-ingress || event.EgressBytes > ^uint64(0)-egress {
			return ErrQuotaExceeded
		}
		if event.IngressBytes > ^uint64(0)-event.EgressBytes {
			return ErrQuotaExceeded
		}
		used := ingress + egress
		eventBytes := event.IngressBytes + event.EgressBytes
		if used > s.dailyLimit || eventBytes > s.dailyLimit-used {
			return ErrQuotaExceeded
		}
		switch event.Kind {
		case "start":
			if err := s.startSession(ctx, tx, event.DeviceID, event.SessionID, now); err != nil {
				return err
			}
		case "update":
			if err := requireSession(ctx, tx, event.DeviceID, event.SessionID); err != nil {
				return err
			}
		case "end":
			if err := endSession(ctx, tx, event.DeviceID, event.SessionID); err != nil {
				return err
			}
		default:
			return fmt.Errorf("%w: unsupported event kind %q", ErrInvalidEvent, event.Kind)
		}
		_, err = tx.Exec(ctx, "INSERT INTO relay_daily_usage(device_id,usage_day,ingress_bytes,egress_bytes) VALUES ($1,$2,$3::numeric,$4::numeric) ON CONFLICT (device_id,usage_day) DO UPDATE SET ingress_bytes=relay_daily_usage.ingress_bytes+EXCLUDED.ingress_bytes,egress_bytes=relay_daily_usage.egress_bytes+EXCLUDED.egress_bytes", event.DeviceID, day, strconv.FormatUint(event.IngressBytes, 10), strconv.FormatUint(event.EgressBytes, 10))
		return err
	})
}

func (s *PostgresStore) Snapshot(ctx context.Context, now time.Time, deviceID string) (uint64, uint64, int, error) {
	day := now.UTC().Format(time.DateOnly)
	var ingress, egress string
	err := s.pool.QueryRow(ctx, "SELECT ingress_bytes::text,egress_bytes::text FROM relay_daily_usage WHERE device_id=$1 AND usage_day=$2", deviceID, day).Scan(&ingress, &egress)
	if errors.Is(err, pgx.ErrNoRows) {
		ingress, egress = "0", "0"
	} else if err != nil {
		return 0, 0, 0, storageError("snapshot usage", err)
	}
	ingressBytes, err := parseUint64(ingress)
	if err != nil {
		return 0, 0, 0, err
	}
	egressBytes, err := parseUint64(egress)
	if err != nil {
		return 0, 0, 0, err
	}
	var sessions int
	if err := s.pool.QueryRow(ctx, "SELECT count(*) FROM relay_active_sessions WHERE device_id=$1", deviceID).Scan(&sessions); err != nil {
		return 0, 0, 0, storageError("snapshot active sessions", err)
	}
	return ingressBytes, egressBytes, sessions, nil
}

func (s *PostgresStore) IsRevoked(ctx context.Context, deviceID string) (bool, error) {
	var revoked bool
	err := s.pool.QueryRow(ctx, "SELECT revoked FROM relay_devices WHERE device_id=$1", deviceID).Scan(&revoked)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, storageError("read revocation", err)
	}
	return revoked, nil
}

func (s *PostgresStore) Revoke(ctx context.Context, deviceID string, now time.Time) error {
	return s.transaction(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, "INSERT INTO relay_devices(device_id,revoked,revoked_at) VALUES ($1,true,$2) ON CONFLICT (device_id) DO UPDATE SET revoked=true,revoked_at=COALESCE(relay_devices.revoked_at,EXCLUDED.revoked_at)", deviceID, now)
		return err
	})
}

func (s *PostgresStore) Totals(ctx context.Context, now time.Time) (uint64, uint64, int64, error) {
	day := now.UTC().Format(time.DateOnly)
	var ingress, egress string
	if err := s.pool.QueryRow(ctx, "SELECT COALESCE(sum(ingress_bytes),0)::text,COALESCE(sum(egress_bytes),0)::text FROM relay_daily_usage WHERE usage_day=$1", day).Scan(&ingress, &egress); err != nil {
		return 0, 0, 0, storageError("read totals", err)
	}
	ingressBytes, err := parseUint64(ingress)
	if err != nil {
		return 0, 0, 0, err
	}
	egressBytes, err := parseUint64(egress)
	if err != nil {
		return 0, 0, 0, err
	}
	var active int64
	if err := s.pool.QueryRow(ctx, "SELECT count(*) FROM relay_active_sessions").Scan(&active); err != nil {
		return 0, 0, 0, storageError("read active totals", err)
	}
	return ingressBytes, egressBytes, active, nil
}

func (s *PostgresStore) startSession(ctx context.Context, tx pgx.Tx, deviceID, sessionID string, now time.Time) error {
	var exists bool
	if err := tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM relay_active_sessions WHERE device_id=$1 AND session_id=$2)", deviceID, sessionID).Scan(&exists); err != nil {
		return err
	}
	if exists {
		return ErrSessionExists
	}
	var active int
	if err := tx.QueryRow(ctx, "SELECT count(*) FROM relay_active_sessions WHERE device_id=$1", deviceID).Scan(&active); err != nil {
		return err
	}
	if active >= s.sessionLimit {
		return ErrSessionLimit
	}
	_, err := tx.Exec(ctx, "INSERT INTO relay_active_sessions(device_id,session_id,opened_at) VALUES ($1,$2,$3)", deviceID, sessionID, now)
	return err
}

func (s *PostgresStore) transaction(ctx context.Context, operation func(pgx.Tx) error) error {
	const maximumAttempts = 3
	var last error
	for attempt := 0; attempt < maximumAttempts; attempt++ {
		last = s.transactionOnce(ctx, operation)
		if last == nil || errors.Is(last, ErrDuplicateEvent) || errors.Is(last, ErrQuotaExceeded) || errors.Is(last, ErrSessionLimit) || errors.Is(last, ErrSessionExists) || errors.Is(last, ErrUnknownSession) || errors.Is(last, ErrDeviceRevoked) || errors.Is(last, ErrInvalidEvent) || !retryableTransactionError(last) {
			return last
		}
		if err := ctx.Err(); err != nil {
			return storageError("transaction canceled", err)
		}
	}
	return storageError("transaction retry exhausted", last)
}

func (s *PostgresStore) transactionOnce(ctx context.Context, operation func(pgx.Tx) error) error {
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.Serializable})
	if err != nil {
		return storageError("begin transaction", err)
	}
	if err := operation(tx); err != nil {
		_ = tx.Rollback(ctx)
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		_ = tx.Rollback(ctx)
		return err
	}
	return nil
}

func retryableTransactionError(err error) bool {
	var postgresError *pgconn.PgError
	if !errors.As(err, &postgresError) {
		return false
	}
	return postgresError.Code == "40001" || postgresError.Code == "40P01" || postgresError.Code == "23505"
}

func usageEventDigest(event UsageEvent) ([]byte, error) {
	encoded, err := json.Marshal(event)
	if err != nil {
		return nil, err
	}
	digest := sha256.Sum256(encoded)
	return digest[:], nil
}

func ensureDevice(ctx context.Context, tx pgx.Tx, deviceID string) error {
	_, err := tx.Exec(ctx, "INSERT INTO relay_devices(device_id) VALUES ($1) ON CONFLICT (device_id) DO NOTHING", deviceID)
	return err
}

func dailyUsage(ctx context.Context, tx pgx.Tx, deviceID, day string) (uint64, uint64, error) {
	var ingress, egress string
	err := tx.QueryRow(ctx, "SELECT ingress_bytes::text,egress_bytes::text FROM relay_daily_usage WHERE device_id=$1 AND usage_day=$2 FOR UPDATE", deviceID, day).Scan(&ingress, &egress)
	if errors.Is(err, pgx.ErrNoRows) {
		return 0, 0, nil
	}
	if err != nil {
		return 0, 0, err
	}
	ingressBytes, err := parseUint64(ingress)
	if err != nil {
		return 0, 0, err
	}
	egressBytes, err := parseUint64(egress)
	if err != nil {
		return 0, 0, err
	}
	return ingressBytes, egressBytes, nil
}

func requireSession(ctx context.Context, tx pgx.Tx, deviceID, sessionID string) error {
	var marker int
	err := tx.QueryRow(ctx, "SELECT 1 FROM relay_active_sessions WHERE device_id=$1 AND session_id=$2 FOR UPDATE", deviceID, sessionID).Scan(&marker)
	if errors.Is(err, pgx.ErrNoRows) {
		return ErrUnknownSession
	}
	return err
}

func endSession(ctx context.Context, tx pgx.Tx, deviceID, sessionID string) error {
	tag, err := tx.Exec(ctx, "DELETE FROM relay_active_sessions WHERE device_id=$1 AND session_id=$2", deviceID, sessionID)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return ErrUnknownSession
	}
	return nil
}

func parseUint64(value string) (uint64, error) {
	parsed, err := strconv.ParseUint(value, 10, 64)
	if err != nil {
		return 0, storageError("parse stored uint64", err)
	}
	return parsed, nil
}

func storageError(operation string, err error) error {
	if err == nil {
		return nil
	}
	return fmt.Errorf("%w: %s: %v", ErrStorage, operation, err)
}
