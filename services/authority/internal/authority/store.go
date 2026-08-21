package authority

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sort"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Store interface {
	Ready(context.Context) error
	EnsureAccount(context.Context, string) error
	SuspendAccount(context.Context, string, time.Time) error
	RegisterDevice(context.Context, string, string) error
	RevokeDevice(context.Context, string, uint64, time.Time) error
	CreateSignaling(context.Context, SignalingRequest, time.Time) (SignalingAdmission, error)
	AuthorizeSignaling(context.Context, string, string, time.Time) (string, error)
	InvalidateSignaling(context.Context, string, time.Time) error
	AdmitRelay(context.Context, RelayAdmissionRequest, time.Time) error
	ApplyCoturnUsage(context.Context, CoturnUsage) (bool, error)
	Reconcile(context.Context, ReconcileRequest, time.Duration) (ReconcileResult, error)
	Close()
}

type PostgresStore struct {
	pool                     *pgxpool.Pool
	roleSecret               []byte
	dailyLimit               uint64
	allocationLimit          int
	maximumDatabaseClockSkew time.Duration
	now                      func() time.Time
}

const (
	requiredSchemaVersion                  int64 = 1
	requiredSchemaChecksum                       = "5ca4aac8504fc29e0610db61befb467484c42bad2340906beef8626c0a855e1f"
	allocationClosedBySource                     = "source_closed"
	allocationClosedByAccountSuspended           = "account_suspended"
	allocationClosedByDeviceRevoked              = "device_revoked"
	allocationClosedBySignalingInvalidated       = "signaling_invalidated"
	allocationClosedByRelayQuotaExceeded         = "relay_quota_exceeded"
)

func OpenPostgres(ctx context.Context, cfg Config) (*PostgresStore, error) {
	pool, err := pgxpool.New(ctx, cfg.DatabaseURL)
	if err != nil {
		return nil, fmt.Errorf("open authority database: %w", err)
	}
	store := &PostgresStore{
		pool:                     pool,
		roleSecret:               []byte(cfg.RoleTokenSecret),
		dailyLimit:               cfg.DailyBytesPerDevice,
		allocationLimit:          cfg.MaximumAllocationsPerDevice,
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
	if err := s.pool.QueryRow(ctx, `SELECT clock_timestamp()`).Scan(&databaseNow); err != nil {
		return fmt.Errorf("%w: database clock probe: %v", ErrStorage, err)
	}
	hostAfter := s.now().UTC()
	if err := validateDatabaseClock(databaseNow.UTC(), hostBefore, hostAfter, s.maximumDatabaseClockSkew); err != nil {
		return fmt.Errorf("%w: database clock probe: %v", ErrStorage, err)
	}

	var version int64
	var checksum string
	if err := s.pool.QueryRow(ctx, `SELECT version,checksum_sha256 FROM authority_schema_migrations ORDER BY version DESC LIMIT 1`).Scan(&version, &checksum); err != nil {
		return fmt.Errorf("%w: schema probe: %v", ErrStorage, err)
	}
	if version != requiredSchemaVersion || checksum != requiredSchemaChecksum {
		return fmt.Errorf("%w: schema version/checksum mismatch", ErrStorage)
	}
	var complete bool
	if err := s.pool.QueryRow(ctx, `SELECT every(to_regclass(name) IS NOT NULL) FROM unnest($1::text[]) AS name`, []string{"authority_schema_migrations", "authority_accounts", "authority_devices", "authority_session_epoch_floors", "authority_signaling_sessions", "authority_relay_daily_usage", "authority_relay_allocations", "authority_coturn_events", "authority_audit_events"}).Scan(&complete); err != nil {
		return fmt.Errorf("%w: structure probe: %v", ErrStorage, err)
	}
	if !complete {
		return fmt.Errorf("%w: required authority relation is missing", ErrStorage)
	}
	if _, err := s.pool.Exec(ctx, `SELECT m.version,m.checksum_sha256,m.applied_at,a.account_id,a.suspended_at,a.created_at,d.device_id,d.account_id,d.revocation_epoch,d.revoked_at,d.created_at,f.device_id,f.highest_epoch,s.session_id,s.request_id,s.account_id,s.host_device_id,s.client_device_id,s.session_epoch,s.expires_at,s.revoked_at,s.created_at,u.device_id,u.usage_day,u.ingress_bytes,u.egress_bytes,r.allocation_id,r.source_id,r.device_id,r.session_id,r.observed_sequence,r.ingress_bytes,r.egress_bytes,r.admitted_at,r.last_observed_at,r.closed_at,r.closure_reason,e.source_id,e.event_id,e.payload_sha256,e.received_at,x.audit_id,x.event_type,x.account_id,x.device_id,x.session_id,x.occurred_at FROM authority_schema_migrations m,authority_accounts a,authority_devices d,authority_session_epoch_floors f,authority_signaling_sessions s,authority_relay_daily_usage u,authority_relay_allocations r,authority_coturn_events e,authority_audit_events x LIMIT 0`); err != nil {
		return fmt.Errorf("%w: required authority column is missing: %v", ErrStorage, err)
	}
	var constraints int
	requiredConstraints := []string{
		"authority_schema_migrations_pkey",
		"authority_accounts_pkey",
		"authority_devices_pkey",
		"authority_devices_account_id_fkey",
		"authority_devices_revocation_epoch_check",
		"authority_session_epoch_floors_pkey",
		"authority_session_epoch_floors_device_id_fkey",
		"authority_session_epoch_floors_highest_epoch_check",
		"authority_session_epoch_floors_epoch_check",
		"authority_signaling_sessions_pkey",
		"authority_signaling_sessions_request_id_key",
		"authority_signaling_sessions_account_id_fkey",
		"authority_signaling_sessions_host_device_id_fkey",
		"authority_signaling_sessions_client_device_id_fkey",
		"authority_signaling_sessions_session_epoch_check",
		"authority_signaling_sessions_host_device_id_client_device_i_key",
		"authority_relay_daily_usage_pkey",
		"authority_relay_daily_usage_device_id_fkey",
		"authority_relay_daily_usage_ingress_bytes_check",
		"authority_relay_daily_usage_egress_bytes_check",
		"authority_relay_allocations_pkey",
		"authority_relay_allocations_device_id_fkey",
		"authority_relay_allocations_observed_sequence_check",
		"authority_relay_allocations_ingress_bytes_check",
		"authority_relay_allocations_egress_bytes_check",
		"authority_relay_allocations_session_fk",
		"authority_relay_allocations_closure_reason_check",
		"authority_coturn_events_pkey",
		"authority_coturn_events_event_id_check",
		"authority_audit_events_pkey",
	}
	if err := s.pool.QueryRow(ctx, `SELECT count(*) FROM pg_constraint WHERE connamespace=current_schema()::regnamespace AND conname=ANY($1)`, requiredConstraints).Scan(&constraints); err != nil || constraints != len(requiredConstraints) {
		return fmt.Errorf("%w: required authority constraint is missing", ErrStorage)
	}
	tables := []string{
		"authority_schema_migrations", "authority_schema_migrations",
		"authority_devices", "authority_devices",
		"authority_session_epoch_floors", "authority_session_epoch_floors",
		"authority_signaling_sessions", "authority_signaling_sessions", "authority_signaling_sessions",
		"authority_relay_daily_usage", "authority_relay_daily_usage", "authority_relay_daily_usage",
		"authority_relay_allocations", "authority_relay_allocations", "authority_relay_allocations", "authority_relay_allocations", "authority_relay_allocations",
		"authority_coturn_events", "authority_coturn_events",
	}
	columns := []string{
		"version", "checksum_sha256",
		"device_id", "revocation_epoch",
		"device_id", "highest_epoch",
		"session_id", "session_epoch", "expires_at",
		"usage_day", "ingress_bytes", "egress_bytes",
		"allocation_id", "session_id", "ingress_bytes", "egress_bytes", "closure_reason",
		"event_id", "payload_sha256",
	}
	types := []string{
		"bigint", "text",
		"text", "bigint",
		"text", "bigint",
		"text", "bigint", "timestamp with time zone",
		"date", "numeric", "numeric",
		"text", "text", "bigint", "bigint", "text",
		"text", "bytea",
	}
	nullable := []string{
		"NO", "NO",
		"NO", "NO",
		"NO", "NO",
		"NO", "NO", "NO",
		"NO", "NO", "NO",
		"NO", "NO", "NO", "NO", "YES",
		"NO", "NO",
	}
	if err := s.pool.QueryRow(ctx, `SELECT count(*)=$5 FROM unnest($1::text[],$2::text[],$3::text[],$4::text[]) AS expected(table_name,column_name,data_type,is_nullable) JOIN information_schema.columns actual ON actual.table_schema=current_schema() AND actual.table_name=expected.table_name AND actual.column_name=expected.column_name AND actual.data_type=expected.data_type AND actual.is_nullable=expected.is_nullable`, tables, columns, types, nullable, len(tables)).Scan(&complete); err != nil || !complete {
		return fmt.Errorf("%w: required authority column signature mismatch", ErrStorage)
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
	// The database timestamp was sampled at an unknown point between the two
	// host samples. Require every possible sample position to stay within the
	// configured bound; excessive query delay is therefore also fail-closed.
	if databaseNow.Before(hostAfter.Add(-maximumSkew)) || databaseNow.After(hostBefore.Add(maximumSkew)) {
		return errors.New("database clock exceeds the configured skew limit")
	}
	return nil
}

func (s *PostgresStore) EnsureAccount(ctx context.Context, accountID string) error {
	_, err := s.pool.Exec(ctx, `INSERT INTO authority_accounts(account_id) VALUES ($1) ON CONFLICT (account_id) DO NOTHING`, accountID)
	return storageError("ensure account", err)
}

func (s *PostgresStore) SuspendAccount(ctx context.Context, accountID string, now time.Time) error {
	return s.transaction(ctx, func(tx pgx.Tx) error {
		var suspendedAt *time.Time
		if err := tx.QueryRow(ctx, `SELECT suspended_at FROM authority_accounts WHERE account_id=$1 FOR UPDATE`, accountID).Scan(&suspendedAt); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return ErrNotFound
			}
			return err
		}
		if suspendedAt != nil {
			return nil
		}
		if _, err := tx.Exec(ctx, `UPDATE authority_accounts SET suspended_at=$2 WHERE account_id=$1`, accountID, now); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `UPDATE authority_signaling_sessions SET revoked_at=COALESCE(revoked_at,$2) WHERE account_id=$1 AND revoked_at IS NULL`, accountID, now); err != nil {
			return err
		}
		// Fail closed: close every relay allocation bound to this account so a
		// suspended account cannot keep consuming TURN bandwidth or advance
		// coturn accounting through a later usage update.
		if _, err := tx.Exec(ctx, `UPDATE authority_relay_allocations SET closed_at=$2,closure_reason=$3 WHERE device_id IN (SELECT device_id FROM authority_devices WHERE account_id=$1) AND closed_at IS NULL`, accountID, now, allocationClosedByAccountSuspended); err != nil {
			return err
		}
		_, err := tx.Exec(ctx, `INSERT INTO authority_audit_events(event_type,account_id,occurred_at) VALUES ('account_suspended',$1,$2)`, accountID, now)
		return err
	})
}

func (s *PostgresStore) RegisterDevice(ctx context.Context, accountID, deviceID string) error {
	return s.transaction(ctx, func(tx pgx.Tx) error {
		var accountMarker int
		if err := tx.QueryRow(ctx, `SELECT 1 FROM authority_accounts WHERE account_id=$1 FOR UPDATE`, accountID).Scan(&accountMarker); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return ErrNotFound
			}
			return err
		}
		tag, err := tx.Exec(ctx, `INSERT INTO authority_devices(device_id, account_id) VALUES ($1,$2) ON CONFLICT (device_id) DO UPDATE SET account_id=EXCLUDED.account_id WHERE authority_devices.account_id=EXCLUDED.account_id`, deviceID, accountID)
		if err != nil {
			return err
		}
		if tag.RowsAffected() == 0 {
			return ErrConflict
		}
		return nil
	})
}

func (s *PostgresStore) RevokeDevice(ctx context.Context, deviceID string, epoch uint64, now time.Time) error {
	if epoch == 0 || epoch > math.MaxInt64 {
		return ErrConflict
	}
	return s.transaction(ctx, func(tx pgx.Tx) error {
		var accountID string
		if err := tx.QueryRow(ctx, `SELECT account_id FROM authority_devices WHERE device_id=$1`, deviceID).Scan(&accountID); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return ErrNotFound
			}
			return err
		}
		var accountMarker int
		if err := tx.QueryRow(ctx, `SELECT 1 FROM authority_accounts WHERE account_id=$1 FOR UPDATE`, accountID).Scan(&accountMarker); err != nil {
			return err
		}
		var current int64
		if err := tx.QueryRow(ctx, `SELECT revocation_epoch FROM authority_devices WHERE device_id=$1 FOR UPDATE`, deviceID).Scan(&current); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return ErrNotFound
			}
			return err
		}
		if epoch < uint64(current) {
			return ErrConflict
		}
		if epoch == uint64(current) {
			return nil
		}
		if _, err := tx.Exec(ctx, `UPDATE authority_devices SET revocation_epoch=$2, revoked_at=$3 WHERE device_id=$1`, deviceID, int64(epoch), now); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `UPDATE authority_signaling_sessions SET revoked_at=COALESCE(revoked_at,$2) WHERE (host_device_id=$1 OR client_device_id=$1) AND revoked_at IS NULL`, deviceID, now); err != nil {
			return err
		}
		// Fail closed: close every relay allocation bound to this device so a
		// revoked device cannot keep consuming TURN bandwidth or advance
		// coturn accounting through a later usage update.
		if _, err := tx.Exec(ctx, `UPDATE authority_relay_allocations SET closed_at=$2,closure_reason=$3 WHERE device_id=$1 AND closed_at IS NULL`, deviceID, now, allocationClosedByDeviceRevoked); err != nil {
			return err
		}
		_, err := tx.Exec(ctx, `INSERT INTO authority_audit_events(event_type,device_id,occurred_at) VALUES ('device_revoked',$1,$2)`, deviceID, now)
		return err
	})
}

func (s *PostgresStore) CreateSignaling(ctx context.Context, request SignalingRequest, now time.Time) (SignalingAdmission, error) {
	if request.SessionEpoch == 0 || request.SessionEpoch > math.MaxInt64 {
		return SignalingAdmission{}, ErrConflict
	}
	var result SignalingAdmission
	err := s.transaction(ctx, func(tx pgx.Tx) error {
		var suspendedAt *time.Time
		if err := tx.QueryRow(ctx, `SELECT suspended_at FROM authority_accounts WHERE account_id=$1 FOR UPDATE`, request.AccountID).Scan(&suspendedAt); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return ErrNotFound
			}
			return err
		}
		if suspendedAt != nil {
			return ErrRevoked
		}
		devices := []string{request.HostDeviceID, request.ClientDeviceID}
		sort.Strings(devices)
		rows, err := tx.Query(ctx, `SELECT device_id,account_id,revoked_at FROM authority_devices WHERE device_id=ANY($1) ORDER BY device_id FOR UPDATE`, devices)
		if err != nil {
			return err
		}
		defer rows.Close()
		seen := 0
		for rows.Next() {
			var deviceID, accountID string
			var revokedAt *time.Time
			if err := rows.Scan(&deviceID, &accountID, &revokedAt); err != nil {
				return err
			}
			if accountID != request.AccountID || revokedAt != nil {
				return ErrRevoked
			}
			seen++
		}
		if err := rows.Err(); err != nil {
			return err
		}
		if seen != len(uniqueStrings(devices)) {
			return ErrNotFound
		}
		var existingRequest SignalingRequest
		var sessionID string
		var expiresAt time.Time
		err = tx.QueryRow(ctx, `SELECT session_id,account_id,host_device_id,client_device_id,session_epoch,extract(epoch from expires_at-created_at)::bigint,expires_at FROM authority_signaling_sessions WHERE request_id=$1`, request.RequestID).Scan(&sessionID, &existingRequest.AccountID, &existingRequest.HostDeviceID, &existingRequest.ClientDeviceID, &existingRequest.SessionEpoch, &existingRequest.TTLSeconds, &expiresAt)
		if err == nil {
			if existingRequest.AccountID != request.AccountID || existingRequest.HostDeviceID != request.HostDeviceID || existingRequest.ClientDeviceID != request.ClientDeviceID || existingRequest.SessionEpoch != request.SessionEpoch || existingRequest.TTLSeconds != request.TTLSeconds {
				return ErrConflict
			}
			result = s.admission(sessionID, expiresAt, false)
			return nil
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		floorDevices := uniqueStrings(devices)
		floorRows, err := tx.Query(ctx, `SELECT device_id,highest_epoch FROM authority_session_epoch_floors WHERE device_id=ANY($1) ORDER BY device_id FOR UPDATE`, floorDevices)
		if err != nil {
			return err
		}
		for floorRows.Next() {
			var deviceID string
			var highestEpoch int64
			if err := floorRows.Scan(&deviceID, &highestEpoch); err != nil {
				floorRows.Close()
				return err
			}
			if request.SessionEpoch <= uint64(highestEpoch) {
				floorRows.Close()
				return ErrConflict
			}
		}
		if err := floorRows.Err(); err != nil {
			floorRows.Close()
			return err
		}
		floorRows.Close()
		if _, err = tx.Exec(ctx, `INSERT INTO authority_session_epoch_floors(device_id,highest_epoch) SELECT unnest($1::text[]),$2 ON CONFLICT (device_id) DO UPDATE SET highest_epoch=EXCLUDED.highest_epoch WHERE authority_session_epoch_floors.highest_epoch<EXCLUDED.highest_epoch`, floorDevices, int64(request.SessionEpoch)); err != nil {
			return err
		}
		sessionID, err = randomIdentifier()
		if err != nil {
			return err
		}
		expiresAt = now.Add(time.Duration(request.TTLSeconds) * time.Second)
		_, err = tx.Exec(ctx, `INSERT INTO authority_signaling_sessions(session_id,request_id,account_id,host_device_id,client_device_id,session_epoch,expires_at,created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)`, sessionID, request.RequestID, request.AccountID, request.HostDeviceID, request.ClientDeviceID, int64(request.SessionEpoch), expiresAt, now)
		if err != nil {
			return err
		}
		result = s.admission(sessionID, expiresAt, true)
		return nil
	})
	return result, err
}

func (s *PostgresStore) AuthorizeSignaling(ctx context.Context, sessionID, token string, now time.Time) (string, error) {
	var revokedAt, accountSuspended, hostRevoked, clientRevoked *time.Time
	var expiresAt time.Time
	err := s.pool.QueryRow(ctx, `SELECT s.expires_at,s.revoked_at,a.suspended_at,h.revoked_at,c.revoked_at FROM authority_signaling_sessions s JOIN authority_accounts a ON a.account_id=s.account_id JOIN authority_devices h ON h.device_id=s.host_device_id JOIN authority_devices c ON c.device_id=s.client_device_id WHERE s.session_id=$1`, sessionID).Scan(&expiresAt, &revokedAt, &accountSuspended, &hostRevoked, &clientRevoked)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", ErrNotFound
	}
	if err != nil {
		return "", storageError("authorize signaling", err)
	}
	if revokedAt != nil || accountSuspended != nil || hostRevoked != nil || clientRevoked != nil || !now.Before(expiresAt) {
		return "", ErrRevoked
	}
	for _, role := range []string{"host", "client"} {
		if hmac.Equal([]byte(token), []byte(s.roleToken(sessionID, role))) {
			return role, nil
		}
	}
	return "", ErrNotFound
}

func (s *PostgresStore) InvalidateSignaling(ctx context.Context, sessionID string, now time.Time) error {
	return s.transaction(ctx, func(tx pgx.Tx) error {
		tag, err := tx.Exec(ctx, `UPDATE authority_signaling_sessions SET revoked_at=COALESCE(revoked_at,$2) WHERE session_id=$1`, sessionID, now)
		if err != nil {
			return err
		}
		if tag.RowsAffected() == 0 {
			return ErrNotFound
		}
		// Fail closed: close every relay allocation bound to this session so
		// invalidating a signaling admission also blocks later coturn usage
		// updates for the authority ledger.
		if _, err := tx.Exec(ctx, `UPDATE authority_relay_allocations SET closed_at=$2,closure_reason=$3 WHERE session_id=$1 AND closed_at IS NULL`, sessionID, now, allocationClosedBySignalingInvalidated); err != nil {
			return err
		}
		return nil
	})
}

func (s *PostgresStore) AdmitRelay(ctx context.Context, request RelayAdmissionRequest, now time.Time) error {
	return s.transaction(ctx, func(tx pgx.Tx) error {
		var existingDeviceID, existingSessionID string
		err := tx.QueryRow(ctx, `SELECT device_id,session_id FROM authority_relay_allocations WHERE source_id=$1 AND allocation_id=$2 FOR UPDATE`, request.SourceID, request.AllocationID).Scan(&existingDeviceID, &existingSessionID)
		if err == nil {
			if existingDeviceID == request.DeviceID && existingSessionID == request.SessionID {
				return nil
			}
			return ErrConflict
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		if err := lockActiveDevice(ctx, tx, request.DeviceID); err != nil {
			return err
		}
		var sessionRevokedAt *time.Time
		var sessionExpiresAt time.Time
		if err := tx.QueryRow(ctx, `SELECT revoked_at,expires_at FROM authority_signaling_sessions WHERE session_id=$1 AND (host_device_id=$2 OR client_device_id=$2) FOR UPDATE`, request.SessionID, request.DeviceID).Scan(&sessionRevokedAt, &sessionExpiresAt); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return ErrNotFound
			}
			return err
		}
		if sessionRevokedAt != nil || !now.Before(sessionExpiresAt) {
			return ErrRevoked
		}
		var quotaExceeded bool
		if err := tx.QueryRow(ctx, `SELECT COALESCE(ingress_bytes+egress_bytes,0)>=$1::numeric FROM authority_relay_daily_usage WHERE device_id=$2 AND usage_day=(CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date`, strconv.FormatUint(s.dailyLimit, 10), request.DeviceID).Scan(&quotaExceeded); err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		if quotaExceeded {
			return ErrQuotaExceeded
		}
		var active int
		if err := tx.QueryRow(ctx, `SELECT count(*) FROM authority_relay_allocations WHERE device_id=$1 AND closed_at IS NULL`, request.DeviceID).Scan(&active); err != nil {
			return err
		}
		if active >= s.allocationLimit {
			return ErrQuotaExceeded
		}
		_, err = tx.Exec(ctx, `INSERT INTO authority_relay_allocations(allocation_id,source_id,device_id,session_id,admitted_at,last_observed_at) VALUES ($1,$2,$3,$4,$5,$5)`, request.AllocationID, request.SourceID, request.DeviceID, request.SessionID, now)
		return err
	})
}

func (s *PostgresStore) ApplyCoturnUsage(ctx context.Context, usage CoturnUsage) (bool, error) {
	if !validIdentifier(usage.EventID) || usage.Sequence == 0 || usage.Sequence > math.MaxInt64 || usage.IngressBytes > math.MaxInt64 || usage.EgressBytes > math.MaxInt64 {
		return false, ErrConflict
	}
	duplicate := false
	err := s.transaction(ctx, func(tx pgx.Tx) error {
		encoded, err := json.Marshal(usage)
		if err != nil {
			return fmt.Errorf("encode usage digest: %w", err)
		}
		digest := sha256.Sum256(encoded)
		tag, err := tx.Exec(ctx, `INSERT INTO authority_coturn_events(source_id,event_id,payload_sha256) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING`, usage.SourceID, usage.EventID, digest[:])
		if err != nil {
			return err
		}
		if tag.RowsAffected() == 0 {
			var existing []byte
			if err := tx.QueryRow(ctx, `SELECT payload_sha256 FROM authority_coturn_events WHERE source_id=$1 AND event_id=$2`, usage.SourceID, usage.EventID).Scan(&existing); err != nil {
				return err
			}
			if !hmac.Equal(existing, digest[:]) {
				return ErrConflict
			}
			duplicate = true
			return nil
		}
		duplicate = false
		var sourceID, deviceID, sessionID string
		var sequence, ingress, egress int64
		var closedAt *time.Time
		var lastObservedAt time.Time
		if err := tx.QueryRow(ctx, `SELECT source_id,device_id,session_id,observed_sequence,ingress_bytes,egress_bytes,last_observed_at,closed_at FROM authority_relay_allocations WHERE source_id=$1 AND allocation_id=$2 FOR UPDATE`, usage.SourceID, usage.AllocationID).Scan(&sourceID, &deviceID, &sessionID, &sequence, &ingress, &egress, &lastObservedAt, &closedAt); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return ErrNotFound
			}
			return err
		}
		if sourceID != usage.SourceID || deviceID != usage.DeviceID || sessionID != usage.SessionID || usage.Sequence <= uint64(sequence) || usage.IngressBytes < uint64(ingress) || usage.EgressBytes < uint64(egress) || usage.ObservedAt.Before(lastObservedAt) {
			return ErrStaleUsage
		}
		if err := lockActiveDevice(ctx, tx, deviceID); err != nil {
			return err
		}
		var sessionRevokedAt *time.Time
		var sessionExpiresAt time.Time
		if err := tx.QueryRow(ctx, `SELECT revoked_at,expires_at FROM authority_signaling_sessions WHERE session_id=$1 AND (host_device_id=$2 OR client_device_id=$2) FOR UPDATE`, sessionID, deviceID).Scan(&sessionRevokedAt, &sessionExpiresAt); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return ErrNotFound
			}
			return err
		}
		if sessionRevokedAt != nil || !usage.ObservedAt.Before(sessionExpiresAt) {
			return ErrRevoked
		}
		if closedAt != nil {
			return ErrStaleUsage
		}
		deltaIngress := usage.IngressBytes - uint64(ingress)
		deltaEgress := usage.EgressBytes - uint64(egress)
		var quotaExceeded bool
		err = tx.QueryRow(ctx, `INSERT INTO authority_relay_daily_usage(device_id,usage_day,ingress_bytes,egress_bytes) VALUES ($1,(CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date,$2::numeric,$3::numeric) ON CONFLICT (device_id,usage_day) DO UPDATE SET ingress_bytes=authority_relay_daily_usage.ingress_bytes+EXCLUDED.ingress_bytes,egress_bytes=authority_relay_daily_usage.egress_bytes+EXCLUDED.egress_bytes RETURNING (ingress_bytes+egress_bytes)>$4::numeric`, deviceID, strconv.FormatUint(deltaIngress, 10), strconv.FormatUint(deltaEgress, 10), strconv.FormatUint(s.dailyLimit, 10)).Scan(&quotaExceeded)
		if err != nil {
			return err
		}
		if quotaExceeded {
			if err := revokeDeviceForRelayQuotaExceeded(ctx, tx, deviceID); err != nil {
				return err
			}
		}
		_, err = tx.Exec(ctx, `UPDATE authority_relay_allocations SET observed_sequence=$3,ingress_bytes=$4,egress_bytes=$5,last_observed_at=$6::timestamptz,closed_at=CASE WHEN closed_at IS NOT NULL THEN closed_at WHEN $7 THEN $6::timestamptz ELSE NULL END,closure_reason=CASE WHEN closure_reason IS NOT NULL THEN closure_reason WHEN $7 THEN $8 ELSE NULL END WHERE source_id=$1 AND allocation_id=$2`, usage.SourceID, usage.AllocationID, int64(usage.Sequence), int64(usage.IngressBytes), int64(usage.EgressBytes), usage.ObservedAt, usage.Closed, allocationClosedBySource)
		return err
	})
	return duplicate, err
}

func revokeDeviceForRelayQuotaExceeded(ctx context.Context, tx pgx.Tx, deviceID string) error {
	var accountID string
	if err := tx.QueryRow(ctx, `SELECT account_id FROM authority_devices WHERE device_id=$1`, deviceID).Scan(&accountID); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return ErrNotFound
		}
		return err
	}
	var accountMarker int
	if err := tx.QueryRow(ctx, `SELECT 1 FROM authority_accounts WHERE account_id=$1 FOR UPDATE`, accountID).Scan(&accountMarker); err != nil {
		return err
	}
	tag, err := tx.Exec(ctx, `UPDATE authority_devices SET revocation_epoch=CASE WHEN revocation_epoch<$2 THEN revocation_epoch+1 ELSE revocation_epoch END,revoked_at=CURRENT_TIMESTAMP WHERE device_id=$1 AND revoked_at IS NULL`, deviceID, int64(math.MaxInt64))
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		var revokedAt *time.Time
		if err := tx.QueryRow(ctx, `SELECT revoked_at FROM authority_devices WHERE device_id=$1`, deviceID).Scan(&revokedAt); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return ErrNotFound
			}
			return err
		}
		return nil
	}
	if _, err := tx.Exec(ctx, `UPDATE authority_signaling_sessions SET revoked_at=COALESCE(revoked_at,CURRENT_TIMESTAMP) WHERE (host_device_id=$1 OR client_device_id=$1) AND revoked_at IS NULL`, deviceID); err != nil {
		return err
	}
	if _, err := tx.Exec(ctx, `UPDATE authority_relay_allocations SET closed_at=CURRENT_TIMESTAMP,closure_reason=$2 WHERE device_id=$1 AND closed_at IS NULL`, deviceID, allocationClosedByRelayQuotaExceeded); err != nil {
		return err
	}
	_, err = tx.Exec(ctx, `INSERT INTO authority_audit_events(event_type,device_id) VALUES ('relay_quota_exceeded',$1)`, deviceID)
	return err
}

func (s *PostgresStore) Reconcile(ctx context.Context, request ReconcileRequest, grace time.Duration) (ReconcileResult, error) {
	result := ReconcileResult{MissingAllocationIDs: []string{}, UnauthorizedAllocationIDs: []string{}, ConflictAllocationIDs: []string{}, RevokedAllocationIDs: []string{}}
	seen := make(map[string]bool, len(request.Allocations))
	for index, usage := range request.Allocations {
		usage.SourceID = request.SourceID
		usage.EventID = reconciliationEventID(request.SourceID, request.ObservedAt, usage.AllocationID)
		usage.ObservedAt = request.ObservedAt
		duplicate, err := s.ApplyCoturnUsage(ctx, usage)
		if err != nil {
			if errors.Is(err, ErrNotFound) {
				result.UnauthorizedAllocationIDs = append(result.UnauthorizedAllocationIDs, usage.AllocationID)
				continue
			}
			if errors.Is(err, ErrStaleUsage) {
				var sourceID, deviceID, sessionID string
				var sequence, ingress, egress int64
				var closureReason *string
				queryErr := s.pool.QueryRow(ctx, `SELECT source_id,device_id,session_id,observed_sequence,ingress_bytes,egress_bytes,closure_reason FROM authority_relay_allocations WHERE source_id=$1 AND allocation_id=$2`, usage.SourceID, usage.AllocationID).Scan(&sourceID, &deviceID, &sessionID, &sequence, &ingress, &egress, &closureReason)
				if queryErr == nil && isAuthorityClosure(closureReason) && sourceID == usage.SourceID && deviceID == usage.DeviceID && sessionID == usage.SessionID {
					result.RevokedAllocationIDs = append(result.RevokedAllocationIDs, usage.AllocationID)
					seen[request.Allocations[index].AllocationID] = true
					continue
				}
				if queryErr == nil && sourceID == usage.SourceID && deviceID == usage.DeviceID && sessionID == usage.SessionID && uint64(sequence) >= usage.Sequence && uint64(ingress) >= usage.IngressBytes && uint64(egress) >= usage.EgressBytes {
					result.AlreadyAhead++
					seen[request.Allocations[index].AllocationID] = true
					continue
				}
				result.ConflictAllocationIDs = append(result.ConflictAllocationIDs, usage.AllocationID)
				seen[request.Allocations[index].AllocationID] = true
				continue
			}
			if errors.Is(err, ErrConflict) {
				result.ConflictAllocationIDs = append(result.ConflictAllocationIDs, usage.AllocationID)
				seen[request.Allocations[index].AllocationID] = true
				continue
			}
			if errors.Is(err, ErrRevoked) {
				result.RevokedAllocationIDs = append(result.RevokedAllocationIDs, usage.AllocationID)
				seen[request.Allocations[index].AllocationID] = true
				continue
			}
			return result, err
		}
		if duplicate {
			result.Duplicate++
		} else {
			result.Applied++
		}
		seen[request.Allocations[index].AllocationID] = true
	}
	sort.Strings(result.UnauthorizedAllocationIDs)
	sort.Strings(result.ConflictAllocationIDs)
	sort.Strings(result.RevokedAllocationIDs)
	rows, err := s.pool.Query(ctx, `SELECT allocation_id FROM authority_relay_allocations WHERE source_id=$1 AND closed_at IS NULL AND last_observed_at<$2 ORDER BY allocation_id`, request.SourceID, request.ObservedAt.Add(-grace))
	if err != nil {
		return result, storageError("reconcile allocations", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return result, err
		}
		if !seen[id] {
			result.MissingAllocationIDs = append(result.MissingAllocationIDs, id)
		}
	}
	return result, rows.Err()
}

func reconciliationEventID(sourceID string, observedAt time.Time, allocationID string) string {
	digest := sha256.Sum256([]byte(sourceID + "\x00" + observedAt.UTC().Format(time.RFC3339Nano) + "\x00" + allocationID))
	return fmt.Sprintf("reconcile-%x", digest)
}

func isAuthorityClosure(reason *string) bool {
	if reason == nil {
		return false
	}
	return isAuthorityClosureString(*reason)
}

func isAuthorityClosureString(reason string) bool {
	switch reason {
	case allocationClosedByAccountSuspended, allocationClosedByDeviceRevoked, allocationClosedBySignalingInvalidated, allocationClosedByRelayQuotaExceeded:
		return true
	default:
		return false
	}
}

func (s *PostgresStore) transaction(ctx context.Context, operation func(pgx.Tx) error) error {
	const maximumAttempts = 3
	var last error
	for attempt := 0; attempt < maximumAttempts; attempt++ {
		last = s.transactionOnce(ctx, operation)
		if last == nil || !retryableTransactionError(last) {
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
		return err
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

func lockActiveDevice(ctx context.Context, tx pgx.Tx, deviceID string) error {
	var accountID string
	if err := tx.QueryRow(ctx, `SELECT account_id FROM authority_devices WHERE device_id=$1`, deviceID).Scan(&accountID); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return ErrNotFound
		}
		return err
	}
	var suspendedAt *time.Time
	if err := tx.QueryRow(ctx, `SELECT suspended_at FROM authority_accounts WHERE account_id=$1 FOR UPDATE`, accountID).Scan(&suspendedAt); err != nil {
		return err
	}
	var revokedAt *time.Time
	if err := tx.QueryRow(ctx, `SELECT revoked_at FROM authority_devices WHERE device_id=$1 AND account_id=$2 FOR UPDATE`, deviceID, accountID).Scan(&revokedAt); err != nil {
		return err
	}
	if revokedAt != nil || suspendedAt != nil {
		return ErrRevoked
	}
	return nil
}

func (s *PostgresStore) admission(sessionID string, expiresAt time.Time, created bool) SignalingAdmission {
	return SignalingAdmission{SessionID: sessionID, HostToken: s.roleToken(sessionID, "host"), ClientToken: s.roleToken(sessionID, "client"), ExpiresAt: expiresAt, Created: created}
}

func (s *PostgresStore) roleToken(sessionID, role string) string {
	mac := hmac.New(sha256.New, s.roleSecret)
	_, _ = mac.Write([]byte(sessionID + "\x00" + role))
	return base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}

func randomIdentifier() (string, error) {
	value := make([]byte, 18)
	if _, err := rand.Read(value); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(value), nil
}
func uniqueStrings(values []string) []string {
	result := make([]string, 0, len(values))
	for _, v := range values {
		if len(result) == 0 || result[len(result)-1] != v {
			result = append(result, v)
		}
	}
	return result
}
func storageError(operation string, err error) error {
	if err == nil {
		return nil
	}
	return fmt.Errorf("%w: %s: %v", ErrStorage, operation, err)
}
