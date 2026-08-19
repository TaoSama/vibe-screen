package signaling

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

func openSignalingIntegrationStore(t *testing.T, cfg Config) (*PostgresStore, Config) {
	t.Helper()
	databaseURL := os.Getenv("VIBE_SIGNALING_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("VIBE_SIGNALING_TEST_DATABASE_URL is not set")
	}
	migration, err := os.ReadFile(filepath.Join("..", "..", "migrations", "001_signaling.sql"))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	if err := ApplyMigration(ctx, databaseURL, string(migration)); err != nil {
		t.Fatal(err)
	}
	if err := ApplyMigration(ctx, databaseURL, string(migration)); err != nil {
		t.Fatal(err)
	}
	cfg.StoreBackend = StoreBackendPostgres
	cfg.DatabaseURL = databaseURL
	store, err := OpenPostgresStore(ctx, cfg, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.pool.Exec(ctx, "TRUNCATE signaling_waiters,signaling_role_rates,signaling_messages,signaling_sessions RESTART IDENTITY CASCADE"); err != nil {
		store.Close()
		t.Fatal(err)
	}
	t.Cleanup(store.Close)
	return store, cfg
}

func TestPostgresAuthorityReplayRebuildsMissingLocalReservation(t *testing.T) {
	expiresAt := time.Now().Add(time.Hour).UTC().Round(time.Microsecond)
	var calls atomic.Int32
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		created := calls.Add(1) == 1
		w.Header().Set("Content-Type", "application/json")
		if created {
			w.WriteHeader(http.StatusCreated)
		} else {
			w.WriteHeader(http.StatusOK)
		}
		_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
			SessionID:   "authority-session-1",
			HostToken:   "host-token-1",
			ClientToken: "client-token-1",
			ExpiresAt:   expiresAt,
			Created:     created,
		})
	}))
	defer authorityServer.Close()

	cfg := testAuthorityConfig(authorityServer.URL)
	store, _ := openSignalingIntegrationStore(t, cfg)
	authority, err := NewAuthorityClient(cfg.AuthorityURL, cfg.AuthorityToken)
	if err != nil {
		t.Fatal(err)
	}
	store.authority = authority
	ctx := context.Background()

	request := CreateSessionRequest{
		RequestID: "authority-replay", TTL: time.Minute,
		AccountID: "acct-1", HostDeviceID: "host-1",
		ClientDeviceID: "device-1", SessionEpoch: 1,
	}
	created, wasCreated, err := store.Create(ctx, request)
	if err != nil || !wasCreated || created.SessionID != "authority-session-1" {
		t.Fatalf("initial authority create response=%#v created=%t err=%v", created, wasCreated, err)
	}
	if _, err := store.pool.Exec(ctx, "TRUNCATE signaling_waiters,signaling_role_rates,signaling_messages,signaling_sessions RESTART IDENTITY CASCADE"); err != nil {
		t.Fatal(err)
	}

	replayed, wasCreated, err := store.Create(ctx, request)
	if err != nil || wasCreated {
		t.Fatalf("replay response=%#v created=%t err=%v", replayed, wasCreated, err)
	}
	if replayed.SessionID != "authority-session-1" || replayed.HostToken != "host-token-1" || replayed.DeviceToken != "client-token-1" {
		t.Fatalf("unexpected replay response: %#v", replayed)
	}
	if stats := store.Stats(); stats.ActiveSessions != 1 || stats.ReservedRecords != 1 {
		t.Fatalf("replay did not rebuild local reservation: %#v", stats)
	}
}

func TestPostgresAuthorityCreateDoesNotHoldDatabaseLockDuringHTTP(t *testing.T) {
	firstEntered := make(chan struct{})
	secondEntered := make(chan struct{})
	releaseFirst := make(chan struct{})
	defer close(releaseFirst)
	var calls atomic.Int32
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var request authoritySignalingRequest
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Errorf("decode authority request: %v", err)
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		call := calls.Add(1)
		if call == 1 {
			close(firstEntered)
			<-releaseFirst
		} else if call == 2 {
			close(secondEntered)
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
			SessionID:   "authority-" + request.RequestID,
			HostToken:   "host-token-" + request.RequestID,
			ClientToken: "client-token-" + request.RequestID,
			ExpiresAt:   time.Now().Add(time.Hour).UTC(),
			Created:     true,
		})
	}))
	defer authorityServer.Close()

	cfg := testAuthorityConfig(authorityServer.URL)
	cfg.MaxActiveSessions = 2
	store, _ := openSignalingIntegrationStore(t, cfg)
	authority, err := NewAuthorityClient(cfg.AuthorityURL, cfg.AuthorityToken)
	if err != nil {
		t.Fatal(err)
	}
	store.authority = authority

	createErr := make(chan error, 2)
	go func() {
		_, _, err := store.Create(context.Background(), CreateSessionRequest{
			RequestID: "req-1", TTL: time.Minute,
			AccountID: "acct-1", HostDeviceID: "host-1",
			ClientDeviceID: "device-1", SessionEpoch: 1,
		})
		createErr <- err
	}()
	select {
	case <-firstEntered:
	case <-time.After(time.Second):
		t.Fatal("first create did not reach the authority")
	}

	go func() {
		_, _, err := store.Create(context.Background(), CreateSessionRequest{
			RequestID: "req-2", TTL: time.Minute,
			AccountID: "acct-1", HostDeviceID: "host-1",
			ClientDeviceID: "device-1", SessionEpoch: 2,
		})
		createErr <- err
	}()
	select {
	case <-secondEntered:
	case <-time.After(250 * time.Millisecond):
		t.Fatal("second create was blocked by the first authority HTTP call")
	}

	releaseFirst <- struct{}{}
	for i := 0; i < 2; i++ {
		if err := <-createErr; err != nil {
			t.Fatalf("create %d error: %v", i+1, err)
		}
	}
}

func TestPostgresLocalStoreLifecycleAndRestart(t *testing.T) {
	cfg := testConfig()
	cfg.MaxCandidatesPerRole = 1
	store, cfg := openSignalingIntegrationStore(t, cfg)
	ctx := context.Background()

	created, wasCreated, err := store.Create(ctx, CreateSessionRequest{RequestID: "request-one", TTL: time.Minute})
	if err != nil || !wasCreated {
		t.Fatalf("create: created=%t err=%v", wasCreated, err)
	}
	if _, wasCreated, err := store.Create(ctx, CreateSessionRequest{RequestID: "request-one", TTL: time.Minute}); err != nil || wasCreated {
		t.Fatalf("exact replay: created=%t err=%v", wasCreated, err)
	}
	if _, _, err := store.Create(ctx, CreateSessionRequest{RequestID: "request-one", TTL: 2 * time.Minute}); !errors.Is(err, ErrConflict) {
		t.Fatalf("changed TTL replay error=%v", err)
	}
	if role, err := store.Authorize(ctx, created.SessionID, created.HostToken); err != nil || role != RoleHost {
		t.Fatalf("authorize host role=%q err=%v", role, err)
	}

	offer, createdMessage, err := store.AddMessageAuthorized(ctx, created.SessionID, RoleHost, MessageRequest{MessageID: "offer", Type: MessageOffer, SDP: "v=0"})
	if err != nil || !createdMessage || offer.Sequence != 1 {
		t.Fatalf("offer event=%#v created=%t err=%v", offer, createdMessage, err)
	}
	if _, createdMessage, err := store.AddMessageAuthorized(ctx, created.SessionID, RoleHost, MessageRequest{MessageID: "offer", Type: MessageOffer, SDP: "v=0"}); err != nil || createdMessage {
		t.Fatalf("offer replay created=%t err=%v", createdMessage, err)
	}
	if _, _, err := store.AddMessageAuthorized(ctx, created.SessionID, RoleHost, MessageRequest{MessageID: "offer", Type: MessageOffer, SDP: "v=1"}); !errors.Is(err, ErrConflict) {
		t.Fatalf("conflicting offer replay error=%v", err)
	}
	deviceEvents, next, err := store.PollAuthorized(ctx, created.SessionID, RoleDevice, 0, false)
	if err != nil || len(deviceEvents) != 1 || deviceEvents[0].MessageID != "offer" || next != 1 {
		t.Fatalf("device poll events=%#v next=%d err=%v", deviceEvents, next, err)
	}
	if _, _, err := store.AddMessageAuthorized(ctx, created.SessionID, RoleDevice, MessageRequest{MessageID: "answer", Type: MessageAnswer, SDP: "v=0"}); err != nil {
		t.Fatalf("answer: %v", err)
	}
	if _, _, err := store.AddMessageAuthorized(ctx, created.SessionID, RoleHost, MessageRequest{MessageID: "candidate-one", Type: MessageICECandidate, Candidate: &ICECandidate{Candidate: "candidate:one"}}); err != nil {
		t.Fatalf("candidate one: %v", err)
	}
	if _, _, err := store.AddMessageAuthorized(ctx, created.SessionID, RoleHost, MessageRequest{MessageID: "candidate-two", Type: MessageICECandidate, Candidate: &ICECandidate{Candidate: "candidate:two"}}); !errors.Is(err, ErrCandidateLimit) {
		t.Fatalf("candidate limit error=%v", err)
	}
	if stats := store.Stats(); stats.ActiveSessions != 1 || stats.ReservedRecords != 1 {
		t.Fatalf("stats before restart=%#v", stats)
	}

	restarted, err := OpenPostgresStore(ctx, cfg, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer restarted.Close()
	hostEvents, next, err := restarted.PollAuthorized(ctx, created.SessionID, RoleHost, 1, false)
	if err != nil || len(hostEvents) != 1 || hostEvents[0].Type != MessageAnswer || next != 3 {
		t.Fatalf("restarted host poll events=%#v next=%d err=%v", hostEvents, next, err)
	}
	invalidated, err := restarted.Invalidate(ctx, created.SessionID)
	if err != nil || !invalidated {
		t.Fatalf("invalidate invalidated=%t err=%v", invalidated, err)
	}
	if _, err := restarted.Authorize(ctx, created.SessionID, created.HostToken); !errors.Is(err, ErrNotFound) {
		t.Fatalf("authorize after invalidate error=%v", err)
	}
	if _, _, err := restarted.Create(ctx, CreateSessionRequest{RequestID: "request-one", TTL: time.Minute}); !errors.Is(err, ErrInvalidated) {
		t.Fatalf("invalidated request replay error=%v", err)
	}
}

func TestPostgresLocalStoreLongPollAndExpiry(t *testing.T) {
	store, _ := openSignalingIntegrationStore(t, testConfig())
	ctx := context.Background()
	created, _, err := store.Create(ctx, CreateSessionRequest{RequestID: "poll", TTL: 2 * time.Second})
	if err != nil {
		t.Fatal(err)
	}

	longPollCtx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	type pollResult struct {
		events []Event
		err    error
	}
	result := make(chan pollResult, 1)
	go func() {
		events, _, pollErr := store.PollAuthorized(longPollCtx, created.SessionID, RoleDevice, 0, true)
		result <- pollResult{events: events, err: pollErr}
	}()
	waitForPostgresWaiter(t, store, created.SessionID, RoleDevice, 1)
	if _, _, err := store.PollAuthorized(ctx, created.SessionID, RoleDevice, 0, true); !errors.Is(err, ErrTooManyWaiters) {
		t.Fatalf("second waiter error=%v", err)
	}
	if _, _, err := store.AddMessageAuthorized(ctx, created.SessionID, RoleHost, MessageRequest{MessageID: "wake", Type: MessageOffer, SDP: "v=0"}); err != nil {
		t.Fatal(err)
	}
	select {
	case polled := <-result:
		if polled.err != nil || len(polled.events) != 1 || polled.events[0].MessageID != "wake" {
			t.Fatalf("poll result=%#v", polled)
		}
	case <-time.After(time.Second):
		t.Fatal("long poll did not wake")
	}
	waitForPostgresWaiter(t, store, created.SessionID, RoleDevice, 0)
	if _, err := store.pool.Exec(ctx, "UPDATE signaling_sessions SET expires_at=now()-interval '1 second' WHERE session_id=$1", created.SessionID); err != nil {
		t.Fatal(err)
	}
	if _, err := store.Authorize(ctx, created.SessionID, created.HostToken); !errors.Is(err, ErrExpired) && !errors.Is(err, ErrNotFound) {
		t.Fatalf("authorize after expiry error=%v", err)
	}
	removed := store.Cleanup()
	if stats := store.Stats(); removed != 1 || stats.ReservedRecords != 0 {
		t.Fatalf("cleanup removed=%d stats=%#v", removed, stats)
	}
}

func TestPostgresLocalCreateCapacityIsAtomic(t *testing.T) {
	cfg := testConfig()
	cfg.MaxActiveSessions = 1
	store, _ := openSignalingIntegrationStore(t, cfg)
	ctx := context.Background()
	start := make(chan struct{})
	var accepted atomic.Int32
	var wait sync.WaitGroup
	for _, requestID := range []string{"first", "second"} {
		wait.Add(1)
		go func(requestID string) {
			defer wait.Done()
			<-start
			_, _, err := store.Create(ctx, CreateSessionRequest{RequestID: requestID, TTL: time.Minute})
			if err == nil {
				accepted.Add(1)
			} else if !errors.Is(err, ErrCapacity) {
				t.Errorf("create %s error=%v", requestID, err)
			}
		}(requestID)
	}
	close(start)
	wait.Wait()
	if accepted.Load() != 1 {
		t.Fatalf("accepted creates=%d, want one", accepted.Load())
	}
}

func TestPostgresReadyFailsClosedOnSchemaDrift(t *testing.T) {
	store, _ := openSignalingIntegrationStore(t, testConfig())
	ctx := context.Background()
	if _, err := store.pool.Exec(ctx, "ALTER TABLE signaling_waiters DROP CONSTRAINT signaling_waiters_waiter_count_check"); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, err := store.pool.Exec(context.Background(), "ALTER TABLE signaling_waiters ADD CONSTRAINT signaling_waiters_waiter_count_check CHECK (waiter_count >= 0)"); err != nil {
			t.Fatalf("restore signaling_waiters constraint: %v", err)
		}
	})
	if err := store.Ready(ctx); !errors.Is(err, ErrStorage) {
		t.Fatalf("readiness schema drift error=%v, want ErrStorage", err)
	}
}

func TestValidateDatabaseClock(t *testing.T) {
	now := time.Date(2026, time.August, 19, 4, 0, 0, 0, time.UTC)
	if err := validateDatabaseClock(now, now.Add(-time.Millisecond), now.Add(time.Millisecond), time.Second); err != nil {
		t.Fatalf("valid clock sample: %v", err)
	}
	if err := validateDatabaseClock(now.Add(2*time.Second), now, now.Add(time.Millisecond), time.Second); err == nil {
		t.Fatal("future database clock was accepted")
	}
	if err := validateDatabaseClock(now.Add(-2*time.Second), now, now.Add(time.Millisecond), time.Second); err == nil {
		t.Fatal("past database clock was accepted")
	}
}

func waitForPostgresWaiter(t *testing.T, store *PostgresStore, sessionID string, role Role, want int) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		var waiters int
		if err := store.pool.QueryRow(context.Background(), "SELECT COALESCE((SELECT waiter_count FROM signaling_waiters WHERE session_id=$1 AND role=$2),0)", sessionID, role).Scan(&waiters); err != nil {
			t.Fatal(err)
		}
		if waiters == want {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("waiter count did not reach %d", want)
}

func TestPostgresReadinessMapsStorageError(t *testing.T) {
	databaseURL := os.Getenv("VIBE_SIGNALING_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("VIBE_SIGNALING_TEST_DATABASE_URL is not set")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	if _, err := pool.Exec(ctx, "DROP TABLE IF EXISTS signaling_schema_migrations CASCADE"); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		migration, err := os.ReadFile(filepath.Join("..", "..", "migrations", "001_signaling.sql"))
		if err != nil {
			t.Fatalf("read migration after missing-schema test: %v", err)
		}
		if err := ApplyMigration(context.Background(), databaseURL, string(migration)); err != nil {
			t.Fatalf("restore signaling migration ledger: %v", err)
		}
	})
	store := &PostgresStore{pool: pool, now: time.Now}
	if err := store.Ready(ctx); !errors.Is(err, ErrStorage) {
		t.Fatalf("missing schema error=%v, want ErrStorage", err)
	}
}
