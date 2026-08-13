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
	"sort"
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
	pool            *pgxpool.Pool
	roleSecret      []byte
	dailyLimit      uint64
	allocationLimit int
}

const requiredSchemaVersion int64 = 1

func OpenPostgres(ctx context.Context, cfg Config) (*PostgresStore, error) {
	pool, err := pgxpool.New(ctx, cfg.DatabaseURL)
	if err != nil {
		return nil, fmt.Errorf("open authority database: %w", err)
	}
	store := &PostgresStore{pool: pool, roleSecret: []byte(cfg.RoleTokenSecret), dailyLimit: cfg.DailyBytesPerDevice, allocationLimit: cfg.MaximumAllocationsPerDevice}
	if err := store.Ready(ctx); err != nil {
		pool.Close()
		return nil, err
	}
	return store, nil
}

func (s *PostgresStore) Close() { s.pool.Close() }

func (s *PostgresStore) Ready(ctx context.Context) error {
	var version int64
	if err := s.pool.QueryRow(ctx, `SELECT max(version) FROM authority_schema_migrations`).Scan(&version); err != nil {
		return fmt.Errorf("%w: schema probe: %v", ErrStorage, err)
	}
	if version != requiredSchemaVersion {
		return fmt.Errorf("%w: schema version %d, require %d", ErrStorage, version, requiredSchemaVersion)
	}
	var complete bool
	if err := s.pool.QueryRow(ctx, `SELECT every(to_regclass(name) IS NOT NULL) FROM unnest($1::text[]) AS name`, []string{"authority_accounts", "authority_devices", "authority_session_epoch_floors", "authority_signaling_sessions", "authority_relay_daily_usage", "authority_relay_allocations", "authority_coturn_events"}).Scan(&complete); err != nil {
		return fmt.Errorf("%w: structure probe: %v", ErrStorage, err)
	}
	if !complete {
		return fmt.Errorf("%w: required authority relation is missing", ErrStorage)
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
		_, err := tx.Exec(ctx, `INSERT INTO authority_audit_events(event_type,account_id,occurred_at) VALUES ('account_suspended',$1,$2)`, accountID, now)
		return err
	})
}

func (s *PostgresStore) RegisterDevice(ctx context.Context, accountID, deviceID string) error {
	tag, err := s.pool.Exec(ctx, `INSERT INTO authority_devices(device_id, account_id) VALUES ($1,$2) ON CONFLICT (device_id) DO UPDATE SET account_id=EXCLUDED.account_id WHERE authority_devices.account_id=EXCLUDED.account_id`, deviceID, accountID)
	if err != nil {
		return storageError("register device", err)
	}
	if tag.RowsAffected() == 0 {
		return ErrConflict
	}
	return nil
}

func (s *PostgresStore) RevokeDevice(ctx context.Context, deviceID string, epoch uint64, now time.Time) error {
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
		_, err := tx.Exec(ctx, `INSERT INTO authority_audit_events(event_type,device_id,occurred_at) VALUES ('device_revoked',$1,$2)`, deviceID, now)
		return err
	})
}

func (s *PostgresStore) CreateSignaling(ctx context.Context, request SignalingRequest, now time.Time) (SignalingAdmission, error) {
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
		var highestEpoch int64
		err = tx.QueryRow(ctx, `SELECT highest_epoch FROM authority_session_epoch_floors WHERE host_device_id=$1 AND client_device_id=$2 FOR UPDATE`, request.HostDeviceID, request.ClientDeviceID).Scan(&highestEpoch)
		if err == nil && request.SessionEpoch <= uint64(highestEpoch) {
			return ErrConflict
		}
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		if _, err = tx.Exec(ctx, `INSERT INTO authority_session_epoch_floors(host_device_id,client_device_id,highest_epoch) VALUES ($1,$2,$3) ON CONFLICT (host_device_id,client_device_id) DO UPDATE SET highest_epoch=EXCLUDED.highest_epoch WHERE authority_session_epoch_floors.highest_epoch<EXCLUDED.highest_epoch`, request.HostDeviceID, request.ClientDeviceID, int64(request.SessionEpoch)); err != nil {
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
	tag, err := s.pool.Exec(ctx, `UPDATE authority_signaling_sessions SET revoked_at=COALESCE(revoked_at,$2) WHERE session_id=$1`, sessionID, now)
	if err != nil {
		return storageError("invalidate signaling", err)
	}
	if tag.RowsAffected() == 0 {
		return ErrNotFound
	}
	return nil
}

func (s *PostgresStore) AdmitRelay(ctx context.Context, request RelayAdmissionRequest, now time.Time) error {
	return s.transaction(ctx, func(tx pgx.Tx) error {
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
		var bytes uint64
		if err := tx.QueryRow(ctx, `SELECT COALESCE(ingress_bytes+egress_bytes,0) FROM authority_relay_daily_usage WHERE device_id=$1 AND usage_day=$2`, request.DeviceID, now.UTC().Format(time.DateOnly)).Scan(&bytes); err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		if bytes >= s.dailyLimit {
			return ErrQuotaExceeded
		}
		var active int
		if err := tx.QueryRow(ctx, `SELECT count(*) FROM authority_relay_allocations WHERE device_id=$1 AND closed_at IS NULL`, request.DeviceID).Scan(&active); err != nil {
			return err
		}
		if active >= s.allocationLimit {
			return ErrQuotaExceeded
		}
		_, err := tx.Exec(ctx, `INSERT INTO authority_relay_allocations(allocation_id,source_id,device_id,session_id,admitted_at,last_observed_at) VALUES ($1,$2,$3,$4,$5,$5)`, request.AllocationID, request.SourceID, request.DeviceID, request.SessionID, now)
		if err != nil {
			return ErrConflict
		}
		return nil
	})
}

func (s *PostgresStore) ApplyCoturnUsage(ctx context.Context, usage CoturnUsage) (bool, error) {
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
		var sourceID, deviceID, sessionID string
		var sequence, ingress, egress int64
		var closedAt *time.Time
		if err := tx.QueryRow(ctx, `SELECT source_id,device_id,session_id,observed_sequence,ingress_bytes,egress_bytes,closed_at FROM authority_relay_allocations WHERE source_id=$1 AND allocation_id=$2 FOR UPDATE`, usage.SourceID, usage.AllocationID).Scan(&sourceID, &deviceID, &sessionID, &sequence, &ingress, &egress, &closedAt); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return ErrNotFound
			}
			return err
		}
		if sourceID != usage.SourceID || deviceID != usage.DeviceID || sessionID != usage.SessionID || usage.Sequence <= uint64(sequence) || usage.IngressBytes < uint64(ingress) || usage.EgressBytes < uint64(egress) || closedAt != nil {
			return ErrStaleUsage
		}
		deltaIngress := usage.IngressBytes - uint64(ingress)
		deltaEgress := usage.EgressBytes - uint64(egress)
		day := usage.ObservedAt.UTC().Format(time.DateOnly)
		_, err = tx.Exec(ctx, `INSERT INTO authority_relay_daily_usage(device_id,usage_day,ingress_bytes,egress_bytes) VALUES ($1,$2,$3,$4) ON CONFLICT (device_id,usage_day) DO UPDATE SET ingress_bytes=authority_relay_daily_usage.ingress_bytes+EXCLUDED.ingress_bytes,egress_bytes=authority_relay_daily_usage.egress_bytes+EXCLUDED.egress_bytes`, deviceID, day, int64(deltaIngress), int64(deltaEgress))
		if err != nil {
			return err
		}
		_, err = tx.Exec(ctx, `UPDATE authority_relay_allocations SET observed_sequence=$3,ingress_bytes=$4,egress_bytes=$5,last_observed_at=$6,closed_at=CASE WHEN $7 THEN $6 ELSE NULL END WHERE source_id=$1 AND allocation_id=$2`, usage.SourceID, usage.AllocationID, int64(usage.Sequence), int64(usage.IngressBytes), int64(usage.EgressBytes), usage.ObservedAt, usage.Closed)
		return err
	})
	return duplicate, err
}

func (s *PostgresStore) Reconcile(ctx context.Context, request ReconcileRequest, grace time.Duration) (ReconcileResult, error) {
	result := ReconcileResult{}
	seen := make(map[string]bool, len(request.Allocations))
	for index, usage := range request.Allocations {
		usage.SourceID = request.SourceID
		usage.EventID = fmt.Sprintf("reconcile-%d-%s", request.ObservedAt.UnixNano(), usage.AllocationID)
		usage.ObservedAt = request.ObservedAt
		duplicate, err := s.ApplyCoturnUsage(ctx, usage)
		if err != nil {
			if errors.Is(err, ErrNotFound) {
				result.SourceOnlyAllocationIDs = append(result.SourceOnlyAllocationIDs, usage.AllocationID)
				continue
			}
			if errors.Is(err, ErrStaleUsage) {
				var sourceID, deviceID, sessionID string
				var sequence, ingress, egress int64
				queryErr := s.pool.QueryRow(ctx, `SELECT source_id,device_id,session_id,observed_sequence,ingress_bytes,egress_bytes FROM authority_relay_allocations WHERE source_id=$1 AND allocation_id=$2`, usage.SourceID, usage.AllocationID).Scan(&sourceID, &deviceID, &sessionID, &sequence, &ingress, &egress)
				if queryErr == nil && sourceID == usage.SourceID && deviceID == usage.DeviceID && sessionID == usage.SessionID && uint64(sequence) >= usage.Sequence && uint64(ingress) >= usage.IngressBytes && uint64(egress) >= usage.EgressBytes {
					result.AlreadyAhead++
					seen[request.Allocations[index].AllocationID] = true
					continue
				}
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
	sort.Strings(result.SourceOnlyAllocationIDs)
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
