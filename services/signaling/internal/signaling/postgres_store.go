package signaling

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	requiredSignalingSchemaVersion  int64 = 1
	requiredSignalingSchemaChecksum       = "755b1da0e06c6cfe59f4d2fe65ddf8c7327e4238ef487355c900118aaf6a97ec"
	authorityReservationPrefix            = "pending-authority-"
	postgresCreateLockID                  = 838433003
	postgresNotifyTimeout                 = 250 * time.Millisecond
	postgresBackgroundTimeout             = 10 * time.Second
	maximumDatabaseClockSkew              = 5 * time.Second
)

type PostgresStore struct {
	pool                    *pgxpool.Pool
	authority               *AuthorityClient
	maxSessions             int
	sessionCreatesPerMinute int
	messagesPerMinute       int
	maxCandidates           int
	maxWaiters              int
	notificationSlots       chan struct{}
	now                     func() time.Time
}

type storedSession struct {
	RequestID   string
	TTLSeconds  int64
	Response    SessionResponse
	HostToken   string
	DeviceToken string
	Invalidated bool
	OfferSent   bool
	AnswerSent  bool
	HostEnded   bool
	DeviceEnded bool
	HostCount   int
	DeviceCount int
}

type waiterLease struct {
	ID               string
	BackendPID       int
	BackendStartedAt time.Time
}

func OpenPostgresStore(ctx context.Context, cfg Config, authority *AuthorityClient) (*PostgresStore, error) {
	pool, err := pgxpool.New(ctx, cfg.DatabaseURL)
	if err != nil {
		return nil, fmt.Errorf("open signaling database: %w", err)
	}
	store := &PostgresStore{
		pool:                    pool,
		authority:               authority,
		maxSessions:             cfg.MaxActiveSessions,
		sessionCreatesPerMinute: cfg.SessionCreatesPerMinute,
		messagesPerMinute:       cfg.MessagesPerMinute,
		maxCandidates:           cfg.MaxCandidatesPerRole,
		maxWaiters:              cfg.MaxWaitersPerRole,
		notificationSlots:       make(chan struct{}, notificationSlotLimit(pool.Stat().MaxConns())),
		now:                     time.Now,
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
		return fmt.Errorf("%w: database clock probe: %v", ErrStorage, err)
	}
	hostAfter := s.now().UTC()
	if err := validateDatabaseClock(databaseNow.UTC(), hostBefore, hostAfter, maximumDatabaseClockSkew); err != nil {
		return fmt.Errorf("%w: database clock probe: %v", ErrStorage, err)
	}

	var version int64
	var checksum string
	if err := s.pool.QueryRow(ctx, "SELECT version,checksum_sha256 FROM signaling_schema_migrations ORDER BY version DESC LIMIT 1").Scan(&version, &checksum); err != nil {
		return fmt.Errorf("%w: schema probe: %v", ErrStorage, err)
	}
	if version != requiredSignalingSchemaVersion || checksum != requiredSignalingSchemaChecksum {
		return fmt.Errorf("%w: schema version/checksum mismatch", ErrStorage)
	}
	var complete bool
	if err := s.pool.QueryRow(ctx, "SELECT every(to_regclass(name) IS NOT NULL) FROM unnest($1::text[]) AS name", []string{"signaling_schema_migrations", "signaling_sessions", "signaling_messages", "signaling_role_rates", "signaling_waiter_leases", "signaling_device_action_rates"}).Scan(&complete); err != nil {
		return fmt.Errorf("%w: structure probe: %v", ErrStorage, err)
	}
	if !complete {
		return fmt.Errorf("%w: required signaling relation is missing", ErrStorage)
	}
	if _, err := s.pool.Exec(ctx, "SELECT s.session_id,s.request_id,s.ttl_seconds,s.expires_at,s.host_token,s.device_token,s.invalidated,s.created_at,m.session_id,m.sender_role,m.message_id,m.message_type,m.sdp,m.candidate,m.sequence,m.created_at,r.session_id,r.role,r.window_started_at,r.message_count,w.session_id,w.role,w.lease_id,w.backend_pid,w.backend_started_at,w.registered_at,d.device_id,d.action,d.refilled_at,d.tokens_available FROM signaling_sessions s,signaling_messages m,signaling_role_rates r,signaling_waiter_leases w,signaling_device_action_rates d LIMIT 0"); err != nil {
		return fmt.Errorf("%w: required signaling column is missing: %v", ErrStorage, err)
	}
	requiredConstraints := []string{
		"signaling_schema_migrations_pkey",
		"signaling_sessions_pkey",
		"signaling_sessions_request_id_key",
		"signaling_sessions_ttl_seconds_check",
		"signaling_messages_session_id_fkey",
		"signaling_messages_sender_role_check",
		"signaling_messages_message_type_check",
		"signaling_messages_sequence_check",
		"signaling_messages_pkey",
		"signaling_messages_session_id_sequence_key",
		"signaling_role_rates_session_id_fkey",
		"signaling_role_rates_role_check",
		"signaling_role_rates_message_count_check",
		"signaling_role_rates_pkey",
		"signaling_waiter_leases_session_id_fkey",
		"signaling_waiter_leases_role_check",
		"signaling_waiter_leases_backend_pid_check",
		"signaling_waiter_leases_pkey",
		"signaling_device_action_rates_tokens_available_check",
		"signaling_device_action_rates_pkey",
	}
	var constraints int
	if err := s.pool.QueryRow(ctx, "SELECT count(*) FROM pg_constraint WHERE connamespace=current_schema()::regnamespace AND conname=ANY($1)", requiredConstraints).Scan(&constraints); err != nil || constraints != len(requiredConstraints) {
		return fmt.Errorf("%w: required signaling constraint is missing", ErrStorage)
	}
	tables := []string{
		"signaling_schema_migrations", "signaling_schema_migrations",
		"signaling_sessions", "signaling_sessions", "signaling_sessions", "signaling_sessions", "signaling_sessions", "signaling_sessions", "signaling_sessions",
		"signaling_messages", "signaling_messages", "signaling_messages", "signaling_messages", "signaling_messages", "signaling_messages", "signaling_messages",
		"signaling_role_rates", "signaling_role_rates", "signaling_role_rates", "signaling_role_rates",
		"signaling_waiter_leases", "signaling_waiter_leases", "signaling_waiter_leases", "signaling_waiter_leases", "signaling_waiter_leases", "signaling_waiter_leases",
		"signaling_device_action_rates", "signaling_device_action_rates", "signaling_device_action_rates", "signaling_device_action_rates",
	}
	columns := []string{
		"version", "checksum_sha256",
		"session_id", "request_id", "ttl_seconds", "expires_at", "host_token", "device_token", "invalidated",
		"session_id", "sender_role", "message_id", "message_type", "sdp", "candidate", "sequence",
		"session_id", "role", "window_started_at", "message_count",
		"session_id", "role", "lease_id", "backend_pid", "backend_started_at", "registered_at",
		"device_id", "action", "refilled_at", "tokens_available",
	}
	types := []string{
		"bigint", "text",
		"text", "text", "bigint", "timestamp with time zone", "text", "text", "boolean",
		"text", "text", "text", "text", "text", "jsonb", "bigint",
		"text", "text", "timestamp with time zone", "integer",
		"text", "text", "text", "integer", "timestamp with time zone", "timestamp with time zone",
		"text", "text", "timestamp with time zone", "integer",
	}
	nullable := []string{
		"NO", "NO",
		"NO", "NO", "NO", "NO", "YES", "YES", "NO",
		"NO", "NO", "NO", "NO", "NO", "YES", "NO",
		"NO", "NO", "NO", "NO",
		"NO", "NO", "NO", "NO", "NO", "NO",
		"NO", "NO", "NO", "NO",
	}
	if err := s.pool.QueryRow(ctx, "SELECT count(*)=$5 FROM unnest($1::text[],$2::text[],$3::text[],$4::text[]) AS expected(table_name,column_name,data_type,is_nullable) JOIN information_schema.columns actual ON actual.table_schema=current_schema() AND actual.table_name=expected.table_name AND actual.column_name=expected.column_name AND actual.data_type=expected.data_type AND actual.is_nullable=expected.is_nullable", tables, columns, types, nullable, len(tables)).Scan(&complete); err != nil || !complete {
		return fmt.Errorf("%w: required signaling column signature mismatch", ErrStorage)
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

func (s *PostgresStore) Create(ctx context.Context, request CreateSessionRequest) (SessionResponse, bool, error) {
	if s.authority != nil {
		return s.createAuthority(ctx, request)
	}
	return s.createLocal(ctx, request)
}

func (s *PostgresStore) createLocal(ctx context.Context, request CreateSessionRequest) (SessionResponse, bool, error) {
	response := SessionResponse{}
	created := false
	err := s.createTransaction(ctx, func(tx pgx.Tx) error {
		if err := s.cleanupTx(ctx, tx); err != nil {
			return err
		}
		existing, err := s.sessionByRequestTx(ctx, tx, request.RequestID)
		if err == nil {
			if existing.Invalidated {
				return ErrInvalidated
			}
			if existing.TTLSeconds != int64(request.TTL/time.Second) {
				return ErrConflict
			}
			response = existing.Response
			return nil
		}
		if !errors.Is(err, ErrNotFound) {
			return err
		}
		if err := s.enforceCapacityTx(ctx, tx); err != nil {
			return err
		}
		if err := s.allowCreateTx(ctx, tx, request); err != nil {
			return err
		}
		sessionID, err := randomToken(16)
		if err != nil {
			return fmt.Errorf("generate session ID: %w", err)
		}
		hostToken, err := randomToken(32)
		if err != nil {
			return fmt.Errorf("generate host token: %w", err)
		}
		deviceToken, err := randomToken(32)
		if err != nil {
			return fmt.Errorf("generate device token: %w", err)
		}
		response = SessionResponse{SessionID: sessionID, HostToken: hostToken, DeviceToken: deviceToken}
		if err := tx.QueryRow(ctx, "INSERT INTO signaling_sessions(session_id,request_id,ttl_seconds,expires_at,host_token,device_token,created_at) VALUES ($1,$2,$3,now()+($4::bigint * interval '1 microsecond'),$5,$6,now()) RETURNING expires_at", sessionID, request.RequestID, int64(request.TTL/time.Second), request.TTL.Microseconds(), hostToken, deviceToken).Scan(&response.ExpiresAt); err != nil {
			return err
		}
		created = true
		return nil
	})
	return response, created, err
}

func (s *PostgresStore) createAuthority(ctx context.Context, request CreateSessionRequest) (SessionResponse, bool, error) {
	reservation, reserved, err := s.reserveAuthorityRequest(ctx, request)
	if err != nil {
		return SessionResponse{}, false, err
	}
	admission, err := s.authority.CreateSession(ctx, authoritySignalingRequest{
		RequestID: request.RequestID, AccountID: request.AccountID, HostDeviceID: request.HostDeviceID,
		ClientDeviceID: request.ClientDeviceID, SessionEpoch: request.SessionEpoch, TTLSeconds: int64(request.TTL / time.Second),
	})
	if err != nil {
		if reserved {
			s.cleanupAuthorityReservation(request.RequestID, reservation.Response.SessionID)
		}
		return SessionResponse{}, false, err
	}
	if reserved && !admission.Created {
		s.cleanupAuthorityReservation(request.RequestID, reservation.Response.SessionID)
		return SessionResponse{}, false, ErrInvalidated
	}
	return s.finalizeAuthorityAdmission(ctx, request, admission)
}

func (s *PostgresStore) reserveAuthorityRequest(ctx context.Context, request CreateSessionRequest) (storedSession, bool, error) {
	reservation := storedSession{}
	reserved := false
	err := s.createTransaction(ctx, func(tx pgx.Tx) error {
		if err := s.cleanupTx(ctx, tx); err != nil {
			return err
		}
		existing, err := s.sessionByRequestTx(ctx, tx, request.RequestID)
		if errors.Is(err, ErrExpired) {
			err = ErrNotFound
		}
		if err == nil {
			if existing.Invalidated {
				return ErrInvalidated
			}
			if isAuthorityReservation(existing.Response.SessionID) {
				return ErrConflict
			}
			reservation = existing
			return nil
		}
		if !errors.Is(err, ErrNotFound) {
			return err
		}
		if err := s.enforceCapacityTx(ctx, tx); err != nil {
			return err
		}
		if err := s.allowCreateTx(ctx, tx, request); err != nil {
			return err
		}
		reservationID, err := randomToken(16)
		if err != nil {
			return fmt.Errorf("generate authority reservation ID: %w", err)
		}
		reservationID = authorityReservationPrefix + reservationID
		reservation = storedSession{
			RequestID:   request.RequestID,
			TTLSeconds:  int64(request.TTL / time.Second),
			Response:    SessionResponse{SessionID: reservationID, ExpiresAt: s.now().UTC().Add(request.TTL)},
			Invalidated: false,
		}
		_, err = tx.Exec(ctx, "INSERT INTO signaling_sessions(session_id,request_id,ttl_seconds,expires_at,host_token,device_token,created_at) VALUES ($1,$2,$3,$4,NULL,NULL,$5)", reservationID, request.RequestID, reservation.TTLSeconds, reservation.Response.ExpiresAt, s.now().UTC())
		if err != nil {
			return err
		}
		reserved = true
		return nil
	})
	return reservation, reserved, err
}

func (s *PostgresStore) finalizeAuthorityAdmission(ctx context.Context, request CreateSessionRequest, admission authoritySignalingAdmission) (SessionResponse, bool, error) {
	response := SessionResponse{SessionID: admission.SessionID, HostToken: admission.HostToken, DeviceToken: admission.ClientToken, ExpiresAt: admission.ExpiresAt}
	created := false
	err := s.createTransaction(ctx, func(tx pgx.Tx) error {
		if err := s.cleanupTx(ctx, tx); err != nil {
			return err
		}
		existing, err := s.sessionByRequestTx(ctx, tx, request.RequestID)
		if errors.Is(err, ErrExpired) {
			err = ErrNotFound
		}
		if err == nil {
			if existing.Invalidated {
				return ErrInvalidated
			}
			if isAuthorityReservation(existing.Response.SessionID) {
				if err := s.ensureAuthoritySessionIDAvailableTx(ctx, tx, admission.SessionID); err != nil {
					return err
				}
				if _, err := tx.Exec(ctx, "UPDATE signaling_sessions SET session_id=$2, ttl_seconds=$3, expires_at=$4 WHERE session_id=$1", existing.Response.SessionID, admission.SessionID, int64(request.TTL/time.Second), admission.ExpiresAt); err != nil {
					return err
				}
				created = admission.Created
				return nil
			}
			if existing.Response.SessionID != admission.SessionID {
				return ErrAuthorityUnavailable
			}
			if _, err := tx.Exec(ctx, "UPDATE signaling_sessions SET expires_at=$2 WHERE session_id=$1", admission.SessionID, admission.ExpiresAt); err != nil {
				return err
			}
			if !admission.ExpiresAt.Equal(existing.Response.ExpiresAt) {
				return notifyTx(ctx, tx, admission.SessionID)
			}
			return nil
		}
		if !errors.Is(err, ErrNotFound) {
			return err
		}
		if err := s.enforceCapacityTx(ctx, tx); err != nil {
			return err
		}
		if err := s.ensureAuthoritySessionIDAvailableTx(ctx, tx, admission.SessionID); err != nil {
			return err
		}
		_, err = tx.Exec(ctx, "INSERT INTO signaling_sessions(session_id,request_id,ttl_seconds,expires_at,host_token,device_token,created_at) VALUES ($1,$2,$3,$4,NULL,NULL,$5)", admission.SessionID, request.RequestID, int64(request.TTL/time.Second), admission.ExpiresAt, s.now().UTC())
		if err != nil {
			return err
		}
		created = admission.Created
		return nil
	})
	return response, created, err
}

func (s *PostgresStore) ensureAuthoritySessionIDAvailableTx(ctx context.Context, tx pgx.Tx, sessionID string) error {
	if _, err := s.sessionByIDTx(ctx, tx, sessionID); err == nil {
		return ErrAuthorityUnavailable
	} else if errors.Is(err, ErrExpired) {
		return ErrInvalidated
	} else if !errors.Is(err, ErrNotFound) {
		return err
	}
	return nil
}

func isAuthorityReservation(sessionID string) bool {
	return strings.HasPrefix(sessionID, authorityReservationPrefix)
}

func (s *PostgresStore) cleanupAuthorityReservation(requestID, sessionID string) {
	if !isAuthorityReservation(sessionID) {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), postgresBackgroundTimeout)
	defer cancel()
	_ = s.createTransaction(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, "DELETE FROM signaling_sessions WHERE request_id=$1 AND session_id=$2", requestID, sessionID)
		return err
	})
}

func (s *PostgresStore) Invalidate(ctx context.Context, sessionID string) (bool, error) {
	if s.authority != nil {
		if err := s.authority.InvalidateSession(ctx, sessionID); err != nil {
			return false, err
		}
	}
	invalidated := false
	err := s.transaction(ctx, func(tx pgx.Tx) error {
		current, err := s.sessionByIDTx(ctx, tx, sessionID)
		if err != nil {
			if errors.Is(err, ErrNotFound) && s.authority != nil {
				return nil
			}
			return err
		}
		if current.Invalidated {
			return nil
		}
		if _, err := tx.Exec(ctx, "UPDATE signaling_sessions SET invalidated=true, host_token=NULL, device_token=NULL WHERE session_id=$1", sessionID); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, "DELETE FROM signaling_messages WHERE session_id=$1", sessionID); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, "DELETE FROM signaling_role_rates WHERE session_id=$1", sessionID); err != nil {
			return err
		}
		if err := notifyTx(ctx, tx, sessionID); err != nil {
			return err
		}
		invalidated = true
		return nil
	})
	return invalidated, err
}

func (s *PostgresStore) Authorize(ctx context.Context, sessionID, token string) (Role, error) {
	if s.authority != nil {
		authorization, err := s.authority.AuthorizeRole(ctx, sessionID, token)
		if err != nil {
			return "", err
		}
		role, err := roleFromAuthority(authorization.Role)
		if err != nil {
			return "", err
		}
		if err := s.ensureAuthorityRoutingSession(ctx, sessionID, authorization.ExpiresAt); err != nil {
			return "", err
		}
		return role, nil
	}
	current, err := s.loadSession(ctx, sessionID)
	if err != nil {
		return "", err
	}
	if secureEqual(token, current.HostToken) {
		return RoleHost, nil
	}
	if secureEqual(token, current.DeviceToken) {
		return RoleDevice, nil
	}
	return "", ErrUnauthorized
}

func (s *PostgresStore) ensureAuthorityRoutingSession(ctx context.Context, sessionID string, expiresAt time.Time) error {
	return s.createTransaction(ctx, func(tx pgx.Tx) error {
		if err := s.cleanupTx(ctx, tx); err != nil {
			return err
		}
		current, err := s.sessionByIDTx(ctx, tx, sessionID)
		if err == nil {
			if current.Invalidated {
				return ErrNotFound
			}
		} else if !errors.Is(err, ErrNotFound) {
			return err
		} else if err := s.enforceCapacityTx(ctx, tx); err != nil {
			return err
		}
		tag, err := tx.Exec(ctx, "INSERT INTO signaling_sessions(session_id,request_id,ttl_seconds,expires_at,host_token,device_token,created_at) VALUES ($1,$2,0,$3,NULL,NULL,$4) ON CONFLICT (session_id) DO UPDATE SET expires_at=EXCLUDED.expires_at, host_token=NULL, device_token=NULL WHERE signaling_sessions.invalidated=false", sessionID, authoritySessionRequestID(sessionID), expiresAt, s.now().UTC())
		if err != nil {
			return err
		}
		if tag.RowsAffected() == 0 {
			return ErrNotFound
		}
		return nil
	})
}

func (s *PostgresStore) AddMessageAuthorized(ctx context.Context, sessionID string, role Role, request MessageRequest) (Event, bool, error) {
	event := Event{}
	created := false
	err := s.transaction(ctx, func(tx pgx.Tx) error {
		current, err := s.sessionByIDTx(ctx, tx, sessionID)
		if err != nil {
			return err
		}
		if err := validateSessionRole(current, role); err != nil {
			return err
		}
		existing, err := s.messageByIDTx(ctx, tx, sessionID, role, request.MessageID)
		if err == nil {
			if !sameMessage(existing.request, request) {
				return ErrConflict
			}
			event = existing.event
			return nil
		}
		if !errors.Is(err, ErrNotFound) {
			return err
		}
		if err := s.allowRateTx(ctx, tx, sessionID, role); err != nil {
			return err
		}
		if err := s.validateStateTx(ctx, tx, current, role, request); err != nil {
			return err
		}
		var sequence int64
		if err := tx.QueryRow(ctx, "SELECT COALESCE(MAX(sequence),0)+1 FROM signaling_messages WHERE session_id=$1", sessionID).Scan(&sequence); err != nil {
			return err
		}
		if sequence <= 0 {
			return ErrConflict
		}
		event = Event{Sequence: uint64(sequence), MessageID: request.MessageID, Type: request.Type, SenderRole: role, SDP: request.SDP, Candidate: cloneCandidate(request.Candidate), CreatedAt: s.now().UTC()}
		candidate, err := marshalCandidate(request.Candidate)
		if err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, "INSERT INTO signaling_messages(session_id,sender_role,message_id,message_type,sdp,candidate,sequence,created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)", sessionID, role, request.MessageID, request.Type, request.SDP, candidate, sequence, event.CreatedAt); err != nil {
			return err
		}
		if err := notifyTx(ctx, tx, sessionID); err != nil {
			return err
		}
		created = true
		return nil
	})
	return event, created, err
}

func (s *PostgresStore) PollAuthorized(ctx context.Context, sessionID string, role Role, after uint64, wait bool) ([]Event, uint64, error) {
	waiting := false
	var listener *postgresNotificationListener
	var lease waiterLease
	defer func() {
		if listener != nil {
			listener.close()
		}
		if lease.ID != "" {
			releaseCtx, cancel := context.WithTimeout(context.Background(), postgresBackgroundTimeout)
			defer cancel()
			_ = s.releaseWaiter(releaseCtx, sessionID, role, lease.ID)
		}
	}()
	for {
		acquireWaiter := wait && listener != nil && !waiting
		events, next, err := s.pollOnce(ctx, sessionID, role, after, acquireWaiter, lease)
		if err != nil {
			return nil, after, err
		}
		if next > after {
			return events, next, nil
		}
		if !wait {
			return []Event{}, after, nil
		}
		if listener == nil {
			var err error
			listener, err = s.openNotificationListener(ctx)
			if err != nil {
				return nil, after, storageError("open signaling notification listener", err)
			}
			leaseID, err := randomToken(16)
			if err != nil {
				return nil, after, fmt.Errorf("generate waiter lease ID: %w", err)
			}
			lease = waiterLease{ID: leaseID, BackendPID: listener.backendPID, BackendStartedAt: listener.backendStartedAt}
			// Recheck the session after LISTEN is active, then register a lease if
			// there is still nothing to return. This avoids relying on process-local
			// ownership while still letting a crashed listener be reclaimed later.
			continue
		}
		waiting = true
		waitCtx, cancel := context.WithTimeout(ctx, postgresNotifyTimeout)
		waitErr := listener.wait(waitCtx, sessionID)
		cancel()
		if waitErr != nil && !errors.Is(waitErr, context.DeadlineExceeded) && ctx.Err() == nil {
			return nil, after, storageError("wait for signaling notification", waitErr)
		}
		if err := ctx.Err(); err != nil {
			if errors.Is(err, context.DeadlineExceeded) {
				return []Event{}, after, nil
			}
			return nil, after, err
		}
	}
}

func (s *PostgresStore) pollOnce(ctx context.Context, sessionID string, role Role, after uint64, acquireWaiter bool, lease waiterLease) ([]Event, uint64, error) {
	var events []Event
	next := after
	err := s.transaction(ctx, func(tx pgx.Tx) error {
		current, err := s.sessionByIDTx(ctx, tx, sessionID)
		if err != nil {
			return err
		}
		if err := validateSessionRole(current, role); err != nil {
			return err
		}
		events, next, err = s.eventsAfterTx(ctx, tx, sessionID, role, after)
		if err != nil || next > after || !acquireWaiter {
			return err
		}
		if err := s.lockWaiterRegistrationTx(ctx, tx, sessionID, role); err != nil {
			return err
		}
		waiters, err := s.waitersTx(ctx, tx, sessionID, role, lease.ID)
		if err != nil {
			return err
		}
		if waiters >= s.maxWaiters {
			return ErrTooManyWaiters
		}
		_, err = tx.Exec(ctx, "INSERT INTO signaling_waiter_leases(session_id,role,lease_id,backend_pid,backend_started_at,registered_at) VALUES ($1,$2,$3,$4,$5,now()) ON CONFLICT (session_id,role,lease_id) DO NOTHING", sessionID, role, lease.ID, lease.BackendPID, lease.BackendStartedAt)
		return err
	})
	return events, next, err
}

func (s *PostgresStore) Stats() StoreStats {
	ctx, cancel := context.WithTimeout(context.Background(), postgresBackgroundTimeout)
	defer cancel()
	stats, err := s.stats(ctx)
	if err != nil {
		return StoreStats{}
	}
	return stats
}

func (s *PostgresStore) Cleanup() int {
	removed := 0
	ctx, cancel := context.WithTimeout(context.Background(), postgresBackgroundTimeout)
	defer cancel()
	_ = s.createTransaction(ctx, func(tx pgx.Tx) error {
		var err error
		removed, err = s.cleanupTxCount(ctx, tx)
		return err
	})
	return removed
}

func (s *PostgresStore) stats(ctx context.Context) (StoreStats, error) {
	var stats StoreStats
	err := s.createTransaction(ctx, func(tx pgx.Tx) error {
		if _, err := s.cleanupExpiredSessionsTx(ctx, tx); err != nil {
			return err
		}
		if err := tx.QueryRow(ctx, "SELECT COUNT(*) FILTER (WHERE NOT invalidated), COUNT(*) FILTER (WHERE invalidated), COUNT(*) FROM signaling_sessions").Scan(&stats.ActiveSessions, &stats.Tombstones, &stats.ReservedRecords); err != nil {
			return err
		}
		return tx.QueryRow(ctx, "SELECT COUNT(*) FROM signaling_waiter_leases").Scan(&stats.BlockedWaiters)
	})
	return stats, err
}

func (s *PostgresStore) loadSession(ctx context.Context, sessionID string) (storedSession, error) {
	var current storedSession
	var expired bool
	err := s.pool.QueryRow(ctx, "SELECT session_id,request_id,ttl_seconds,expires_at,COALESCE(host_token,''),COALESCE(device_token,''),invalidated,expires_at<=now() FROM signaling_sessions WHERE session_id=$1", sessionID).Scan(&current.Response.SessionID, &current.RequestID, &current.TTLSeconds, &current.Response.ExpiresAt, &current.HostToken, &current.DeviceToken, &current.Invalidated, &expired)
	if errors.Is(err, pgx.ErrNoRows) {
		return storedSession{}, ErrNotFound
	}
	if err != nil {
		return storedSession{}, storageError("load signaling session", err)
	}
	if current.Invalidated {
		return storedSession{}, ErrNotFound
	}
	if expired {
		return storedSession{}, ErrExpired
	}
	return current, nil
}

func (s *PostgresStore) sessionByRequestTx(ctx context.Context, tx pgx.Tx, requestID string) (storedSession, error) {
	return s.scanSession(ctx, tx, "WHERE request_id=$1", requestID)
}

func (s *PostgresStore) sessionByIDTx(ctx context.Context, tx pgx.Tx, sessionID string) (storedSession, error) {
	return s.scanSession(ctx, tx, "WHERE session_id=$1", sessionID)
}

func (s *PostgresStore) scanSession(ctx context.Context, tx pgx.Tx, predicate string, arg string) (storedSession, error) {
	query := "SELECT session_id,request_id,ttl_seconds,expires_at,COALESCE(host_token,''),COALESCE(device_token,''),invalidated,expires_at<=now() FROM signaling_sessions " + predicate + " FOR UPDATE"
	var current storedSession
	var expired bool
	err := tx.QueryRow(ctx, query, arg).Scan(&current.Response.SessionID, &current.RequestID, &current.TTLSeconds, &current.Response.ExpiresAt, &current.HostToken, &current.DeviceToken, &current.Invalidated, &expired)
	if errors.Is(err, pgx.ErrNoRows) {
		return storedSession{}, ErrNotFound
	}
	if err != nil {
		return storedSession{}, err
	}
	current.Response.HostToken = current.HostToken
	current.Response.DeviceToken = current.DeviceToken
	if current.Invalidated {
		return current, nil
	}
	if expired {
		return storedSession{}, ErrExpired
	}
	if err := s.populateStateTx(ctx, tx, &current); err != nil {
		return storedSession{}, err
	}
	return current, nil
}

func (s *PostgresStore) populateStateTx(ctx context.Context, tx pgx.Tx, current *storedSession) error {
	if err := tx.QueryRow(ctx, "SELECT EXISTS (SELECT 1 FROM signaling_messages WHERE session_id=$1 AND sender_role='host' AND message_type='offer'), EXISTS (SELECT 1 FROM signaling_messages WHERE session_id=$1 AND sender_role='device' AND message_type='answer')", current.Response.SessionID).Scan(&current.OfferSent, &current.AnswerSent); err != nil {
		return err
	}
	rows, err := tx.Query(ctx, "SELECT sender_role, message_type, COUNT(*) FROM signaling_messages WHERE session_id=$1 GROUP BY sender_role,message_type", current.Response.SessionID)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var role Role
		var messageType MessageType
		var count int
		if err := rows.Scan(&role, &messageType, &count); err != nil {
			return err
		}
		switch {
		case messageType == MessageEndOfCandidates && role == RoleHost:
			current.HostEnded = true
		case messageType == MessageEndOfCandidates && role == RoleDevice:
			current.DeviceEnded = true
		case messageType == MessageICECandidate && role == RoleHost:
			current.HostCount = count
		case messageType == MessageICECandidate && role == RoleDevice:
			current.DeviceCount = count
		}
	}
	return rows.Err()
}

type storedMessage struct {
	event   Event
	request MessageRequest
}

func (s *PostgresStore) messageByIDTx(ctx context.Context, tx pgx.Tx, sessionID string, role Role, messageID string) (storedMessage, error) {
	var item storedMessage
	var candidate []byte
	var sequence int64
	err := tx.QueryRow(ctx, "SELECT message_type,sdp,candidate,sequence,created_at FROM signaling_messages WHERE session_id=$1 AND sender_role=$2 AND message_id=$3", sessionID, role, messageID).Scan(&item.event.Type, &item.event.SDP, &candidate, &sequence, &item.event.CreatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return storedMessage{}, ErrNotFound
	}
	if err != nil {
		return storedMessage{}, err
	}
	if candidate != nil {
		var parsed ICECandidate
		if err := json.Unmarshal(candidate, &parsed); err != nil {
			return storedMessage{}, err
		}
		item.event.Candidate = &parsed
	}
	item.event.Sequence = uint64(sequence)
	item.event.MessageID = messageID
	item.event.SenderRole = role
	item.request = MessageRequest{MessageID: messageID, Type: item.event.Type, SDP: item.event.SDP, Candidate: cloneCandidate(item.event.Candidate)}
	return item, nil
}

func (s *PostgresStore) allowRateTx(ctx context.Context, tx pgx.Tx, sessionID string, role Role) error {
	now := s.now().UTC()
	var started time.Time
	var count int
	err := tx.QueryRow(ctx, "SELECT window_started_at,message_count FROM signaling_role_rates WHERE session_id=$1 AND role=$2 FOR UPDATE", sessionID, role).Scan(&started, &count)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return err
	}
	if errors.Is(err, pgx.ErrNoRows) || now.Sub(started) >= time.Minute {
		_, err = tx.Exec(ctx, "INSERT INTO signaling_role_rates(session_id,role,window_started_at,message_count) VALUES ($1,$2,$3,1) ON CONFLICT (session_id,role) DO UPDATE SET window_started_at=EXCLUDED.window_started_at,message_count=1", sessionID, role, now)
		return err
	}
	if count >= s.messagesPerMinute {
		return ErrRateLimited
	}
	_, err = tx.Exec(ctx, "UPDATE signaling_role_rates SET message_count=message_count+1 WHERE session_id=$1 AND role=$2", sessionID, role)
	return err
}

func (s *PostgresStore) allowCreateTx(ctx context.Context, tx pgx.Tx, request CreateSessionRequest) error {
	for _, deviceID := range createRateDeviceIDs(request) {
		if err := s.allowDeviceActionTx(ctx, tx, deviceID, createSessionAction, s.sessionCreatesPerMinute); err != nil {
			return err
		}
	}
	return nil
}

func (s *PostgresStore) allowDeviceActionTx(ctx context.Context, tx pgx.Tx, deviceID, action string, limit int) error {
	now := s.now().UTC()
	bucket := tokenBucket{}
	err := tx.QueryRow(ctx, "SELECT refilled_at,tokens_available FROM signaling_device_action_rates WHERE device_id=$1 AND action=$2 FOR UPDATE", deviceID, action).Scan(&bucket.refilledAt, &bucket.tokensAvailable)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return err
	}
	if errors.Is(err, pgx.ErrNoRows) {
		if !consumeTokenBucket(&bucket, now, limit) {
			return ErrRateLimited
		}
		_, err = tx.Exec(ctx, "INSERT INTO signaling_device_action_rates(device_id,action,refilled_at,tokens_available) VALUES ($1,$2,$3,$4)", deviceID, action, bucket.refilledAt, bucket.tokensAvailable)
		return err
	}
	if !consumeTokenBucket(&bucket, now, limit) {
		return ErrRateLimited
	}
	_, err = tx.Exec(ctx, "UPDATE signaling_device_action_rates SET refilled_at=$3,tokens_available=$4 WHERE device_id=$1 AND action=$2", deviceID, action, bucket.refilledAt, bucket.tokensAvailable)
	return err
}

func (s *PostgresStore) validateStateTx(ctx context.Context, tx pgx.Tx, current storedSession, role Role, request MessageRequest) error {
	switch request.Type {
	case MessageOffer:
		if role != RoleHost || current.OfferSent {
			return ErrConflict
		}
	case MessageAnswer:
		if role != RoleDevice || !current.OfferSent || current.AnswerSent {
			return ErrConflict
		}
	case MessageICECandidate:
		if endedForRole(current, role) {
			return ErrConflict
		}
		if countForRole(current, role) >= s.maxCandidates {
			return ErrCandidateLimit
		}
	case MessageEndOfCandidates:
		if endedForRole(current, role) {
			return ErrConflict
		}
	default:
		return ErrConflict
	}
	return nil
}

func (s *PostgresStore) eventsAfterTx(ctx context.Context, tx pgx.Tx, sessionID string, receiver Role, after uint64) ([]Event, uint64, error) {
	if after > math.MaxInt64 {
		return nil, after, ErrConflict
	}
	rows, err := tx.Query(ctx, "SELECT sequence,message_id,message_type,sender_role,sdp,candidate,created_at FROM signaling_messages WHERE session_id=$1 AND sequence>$2 ORDER BY sequence", sessionID, int64(after))
	if err != nil {
		return nil, after, err
	}
	defer rows.Close()
	events := make([]Event, 0)
	next := after
	for rows.Next() {
		var event Event
		var sequence int64
		var candidate []byte
		if err := rows.Scan(&sequence, &event.MessageID, &event.Type, &event.SenderRole, &event.SDP, &candidate, &event.CreatedAt); err != nil {
			return nil, after, err
		}
		event.Sequence = uint64(sequence)
		next = event.Sequence
		if candidate != nil {
			var parsed ICECandidate
			if err := json.Unmarshal(candidate, &parsed); err != nil {
				return nil, after, err
			}
			event.Candidate = &parsed
		}
		if event.SenderRole != receiver {
			events = append(events, event)
		}
	}
	return events, next, rows.Err()
}

func (s *PostgresStore) waitersTx(ctx context.Context, tx pgx.Tx, sessionID string, role Role, leaseID string) (int, error) {
	var waiters int
	if _, err := tx.Exec(ctx, "DELETE FROM signaling_waiter_leases l WHERE l.session_id=$1 AND l.role=$2 AND NOT EXISTS (SELECT 1 FROM pg_stat_activity a WHERE a.pid=l.backend_pid AND a.backend_start=l.backend_started_at)", sessionID, role); err != nil {
		return 0, err
	}
	err := tx.QueryRow(ctx, "SELECT COUNT(*) FROM signaling_waiter_leases WHERE session_id=$1 AND role=$2 AND lease_id<>$3", sessionID, role, leaseID).Scan(&waiters)
	return waiters, err
}

func (s *PostgresStore) lockWaiterRegistrationTx(ctx context.Context, tx pgx.Tx, sessionID string, role Role) error {
	_, err := tx.Exec(ctx, "SELECT pg_advisory_xact_lock(hashtext($1), hashtext($2))", sessionID, string(role))
	return err
}

func (s *PostgresStore) releaseWaiter(ctx context.Context, sessionID string, role Role, leaseID string) error {
	if leaseID == "" {
		return nil
	}
	_, err := s.pool.Exec(ctx, "DELETE FROM signaling_waiter_leases WHERE session_id=$1 AND role=$2 AND lease_id=$3", sessionID, role, leaseID)
	return err
}

type postgresNotificationListener struct {
	connection       *pgxpool.Conn
	release          func()
	backendPID       int
	backendStartedAt time.Time
}

func (s *PostgresStore) openNotificationListener(ctx context.Context) (*postgresNotificationListener, error) {
	if s.notificationSlots != nil {
		select {
		case s.notificationSlots <- struct{}{}:
			// Slot is released by postgresNotificationListener.close.
		case <-ctx.Done():
			return nil, ctx.Err()
		default:
			return nil, ErrTooManyWaiters
		}
	}
	connection, err := s.pool.Acquire(ctx)
	if err != nil {
		s.releaseNotificationSlot()
		return nil, err
	}
	if _, err := connection.Exec(ctx, "LISTEN signaling_events"); err != nil {
		connection.Release()
		s.releaseNotificationSlot()
		return nil, err
	}
	var backendPID int
	var backendStartedAt time.Time
	if err := connection.QueryRow(ctx, "SELECT pg_backend_pid(), backend_start FROM pg_stat_activity WHERE pid=pg_backend_pid()").Scan(&backendPID, &backendStartedAt); err != nil {
		_, _ = connection.Exec(context.Background(), "UNLISTEN signaling_events")
		connection.Release()
		s.releaseNotificationSlot()
		return nil, err
	}
	return &postgresNotificationListener{
		connection:       connection,
		release:          s.releaseNotificationSlot,
		backendPID:       backendPID,
		backendStartedAt: backendStartedAt,
	}, nil
}

func (l *postgresNotificationListener) wait(ctx context.Context, sessionID string) error {
	for {
		notification, err := l.connection.Conn().WaitForNotification(ctx)
		if err != nil {
			return err
		}
		if notification.Payload == sessionID {
			return nil
		}
	}
}

func (l *postgresNotificationListener) close() {
	cleanupCtx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	_, _ = l.connection.Exec(cleanupCtx, "UNLISTEN signaling_events")
	l.connection.Release()
	l.release()
}

func (s *PostgresStore) releaseNotificationSlot() {
	if s.notificationSlots != nil {
		<-s.notificationSlots
	}
}

func notificationSlotLimit(maxConns int32) int {
	if maxConns <= 1 {
		return 0
	}
	return int(maxConns - 1)
}

func (s *PostgresStore) enforceCapacityTx(ctx context.Context, tx pgx.Tx) error {
	var count int
	if err := tx.QueryRow(ctx, "SELECT COUNT(*) FROM signaling_sessions").Scan(&count); err != nil {
		return err
	}
	if count >= s.maxSessions {
		return ErrCapacity
	}
	return nil
}

func (s *PostgresStore) cleanupTx(ctx context.Context, tx pgx.Tx) error {
	_, err := s.cleanupExpiredSessionsTx(ctx, tx)
	return err
}

func (s *PostgresStore) cleanupTxCount(ctx context.Context, tx pgx.Tx) (int, error) {
	if _, err := tx.Exec(ctx, "DELETE FROM signaling_waiter_leases l WHERE NOT EXISTS (SELECT 1 FROM pg_stat_activity a WHERE a.pid=l.backend_pid AND a.backend_start=l.backend_started_at)"); err != nil {
		return 0, err
	}
	if _, err := tx.Exec(ctx, "DELETE FROM signaling_device_action_rates WHERE ctid IN (SELECT ctid FROM signaling_device_action_rates WHERE refilled_at<=$1 LIMIT $2)", s.now().UTC().Add(-rateLimitIdleRetention), postgresRateCleanupLimit); err != nil {
		return 0, err
	}
	return s.cleanupExpiredSessionsTx(ctx, tx)
}

func (s *PostgresStore) cleanupExpiredSessionsTx(ctx context.Context, tx pgx.Tx) (int, error) {
	tag, err := tx.Exec(ctx, "DELETE FROM signaling_sessions WHERE expires_at<=now()")
	if err != nil {
		return 0, err
	}
	return int(tag.RowsAffected()), nil
}

func (s *PostgresStore) transaction(ctx context.Context, operation func(pgx.Tx) error) error {
	const maximumAttempts = 3
	var last error
	for attempt := 0; attempt < maximumAttempts; attempt++ {
		last = s.transactionOnce(ctx, operation)
		if last == nil || !retryableTransactionError(last) {
			return storageError("signaling transaction", last)
		}
		if err := ctx.Err(); err != nil {
			return storageError("signaling transaction canceled", err)
		}
	}
	return storageError("signaling transaction retry exhausted", last)
}

func (s *PostgresStore) createTransaction(ctx context.Context, operation func(pgx.Tx) error) error {
	connection, err := s.pool.Acquire(ctx)
	if err != nil {
		return storageError("acquire signaling create lock connection", err)
	}
	defer connection.Release()
	if _, err := connection.Exec(ctx, "SELECT pg_advisory_lock($1)", postgresCreateLockID); err != nil {
		return storageError("lock signaling create", err)
	}
	defer func() {
		unlockCtx, cancel := context.WithTimeout(context.Background(), postgresBackgroundTimeout)
		defer cancel()
		_, _ = connection.Exec(unlockCtx, "SELECT pg_advisory_unlock($1)", postgresCreateLockID)
	}()

	const maximumAttempts = 3
	var last error
	for attempt := 0; attempt < maximumAttempts; attempt++ {
		last = s.transactionOnceOnConnection(ctx, connection, operation)
		if last == nil || !retryableTransactionError(last) {
			return storageError("signaling create transaction", last)
		}
		if err := ctx.Err(); err != nil {
			return storageError("signaling create transaction canceled", err)
		}
	}
	return storageError("signaling create transaction retry exhausted", last)
}

func (s *PostgresStore) transactionOnce(ctx context.Context, operation func(pgx.Tx) error) error {
	return s.transactionOnceOnConnection(ctx, s.pool, operation)
}

func (s *PostgresStore) transactionOnceOnConnection(ctx context.Context, connection interface {
	BeginTx(context.Context, pgx.TxOptions) (pgx.Tx, error)
}, operation func(pgx.Tx) error) error {
	tx, err := connection.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.Serializable})
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

func notifyTx(ctx context.Context, tx pgx.Tx, sessionID string) error {
	_, err := tx.Exec(ctx, "SELECT pg_notify('signaling_events',$1)", sessionID)
	return err
}

func validateSessionRole(current storedSession, role Role) error {
	if role != RoleHost && role != RoleDevice {
		return ErrUnauthorized
	}
	if current.Invalidated {
		return ErrNotFound
	}
	return nil
}

func countForRole(current storedSession, role Role) int {
	if role == RoleHost {
		return current.HostCount
	}
	return current.DeviceCount
}

func endedForRole(current storedSession, role Role) bool {
	if role == RoleHost {
		return current.HostEnded
	}
	return current.DeviceEnded
}

func marshalCandidate(candidate *ICECandidate) ([]byte, error) {
	if candidate == nil {
		return nil, nil
	}
	return json.Marshal(candidate)
}

func sameMessage(left, right MessageRequest) bool {
	leftCandidate, leftErr := marshalCandidate(left.Candidate)
	rightCandidate, rightErr := marshalCandidate(right.Candidate)
	return leftErr == nil && rightErr == nil && left.MessageID == right.MessageID && left.Type == right.Type && left.SDP == right.SDP && string(leftCandidate) == string(rightCandidate)
}

func storageError(operation string, err error) error {
	if err == nil {
		return nil
	}
	if errors.Is(err, ErrNotFound) || errors.Is(err, ErrExpired) || errors.Is(err, ErrInvalidated) || errors.Is(err, ErrUnauthorized) || errors.Is(err, ErrConflict) || errors.Is(err, ErrRateLimited) || errors.Is(err, ErrCapacity) || errors.Is(err, ErrCandidateLimit) || errors.Is(err, ErrTooManyWaiters) || errors.Is(err, ErrAuthorityUnavailable) || errors.Is(err, ErrStorage) {
		return err
	}
	return fmt.Errorf("%w: %s: %v", ErrStorage, operation, err)
}
