package signaling

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

func openSignalingIntegrationStore(t *testing.T, cfg Config) (*PostgresStore, Config) {
	t.Helper()
	databaseURL := os.Getenv("VIBE_SIGNALING_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("VIBE_SIGNALING_TEST_DATABASE_URL is not set")
	}
	databaseURL, schema := signalingIntegrationTestDatabaseURL(t, databaseURL)
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
	var currentSchema string
	if err := store.pool.QueryRow(ctx, "SELECT current_schema()").Scan(&currentSchema); err != nil {
		store.Close()
		t.Fatal(err)
	}
	if currentSchema != schema {
		store.Close()
		t.Fatalf("postgres integration schema = %q, want %q", currentSchema, schema)
	}
	if _, err := store.pool.Exec(ctx, "TRUNCATE signaling_waiter_leases,signaling_role_rates,signaling_messages,signaling_sessions RESTART IDENTITY CASCADE"); err != nil {
		store.Close()
		t.Fatal(err)
	}
	t.Cleanup(store.Close)
	return store, cfg
}

func readSignalingMigration(t *testing.T) string {
	t.Helper()
	migration, err := os.ReadFile(filepath.Join("..", "..", "migrations", "001_signaling.sql"))
	if err != nil {
		t.Fatal(err)
	}
	return string(migration)
}

func signalingIntegrationTestDatabaseURL(t *testing.T, databaseURL string) (string, string) {
	t.Helper()
	config, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		t.Fatalf("parse signaling integration database URL: %v", err)
	}
	schema := postgresTestSchemaName(t.Name())
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		t.Fatalf("open signaling integration database for schema setup: %v", err)
	}
	defer pool.Close()
	if _, err := pool.Exec(ctx, "DROP SCHEMA IF EXISTS "+pgx.Identifier{schema}.Sanitize()+" CASCADE"); err != nil {
		t.Fatalf("drop stale signaling integration schema: %v", err)
	}
	if _, err := pool.Exec(ctx, "CREATE SCHEMA "+pgx.Identifier{schema}.Sanitize()); err != nil {
		t.Fatalf("create signaling integration schema: %v", err)
	}
	t.Cleanup(func() {
		cleanupCtx, cleanupCancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer cleanupCancel()
		cleanupPool, err := pgxpool.NewWithConfig(cleanupCtx, config)
		if err != nil {
			t.Fatalf("open signaling integration database for schema cleanup: %v", err)
		}
		defer cleanupPool.Close()
		if _, err := cleanupPool.Exec(cleanupCtx, "DROP SCHEMA IF EXISTS "+pgx.Identifier{schema}.Sanitize()+" CASCADE"); err != nil {
			t.Fatalf("drop signaling integration schema: %v", err)
		}
	})

	isolatedURL, err := databaseURLWithSearchPath(databaseURL, schema)
	if err != nil {
		t.Fatalf("prepare isolated signaling integration database URL: %v", err)
	}
	return isolatedURL, schema
}

func databaseURLWithSearchPath(databaseURL, schema string) (string, error) {
	parsed, err := url.Parse(databaseURL)
	if err != nil {
		return "", err
	}
	query := parsed.Query()
	query.Set("search_path", schema)
	parsed.RawQuery = query.Encode()
	return parsed.String(), nil
}

func postgresTestSchemaName(value string) string {
	const maxIdentifierLength = 63
	const hashLength = 8
	const prefix = "signaling_test_"
	digest := sha256.Sum256([]byte(value))
	suffix := hex.EncodeToString(digest[:])[:hashLength]
	baseLimit := maxIdentifierLength - len(prefix) - hashLength - 1
	base := sanitizePostgresIdentifier(value)
	if len(base) > baseLimit {
		base = base[:baseLimit]
	}
	return prefix + base + "_" + suffix
}

func sanitizePostgresIdentifier(value string) string {
	output := make([]byte, 0, len(value))
	for index := 0; index < len(value); index++ {
		character := value[index]
		if character >= 'a' && character <= 'z' || character >= '0' && character <= '9' {
			output = append(output, character)
			continue
		}
		if character >= 'A' && character <= 'Z' {
			output = append(output, character+'a'-'A')
			continue
		}
		output = append(output, '_')
	}
	if len(output) == 0 || output[0] < 'a' || output[0] > 'z' {
		output = append([]byte("t_"), output...)
	}
	return string(output)
}

func TestPostgresAuthorityReplayWithoutLocalStateFailsClosed(t *testing.T) {
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
	if _, err := store.pool.Exec(ctx, "TRUNCATE signaling_waiter_leases,signaling_role_rates,signaling_messages,signaling_sessions RESTART IDENTITY CASCADE"); err != nil {
		t.Fatal(err)
	}

	if replayed, wasCreated, err := store.Create(ctx, request); !errors.Is(err, ErrInvalidated) || wasCreated || replayed.SessionID != "" {
		t.Fatalf("replay response=%#v created=%t err=%v", replayed, wasCreated, err)
	}
	if stats := store.Stats(); stats.ActiveSessions != 0 || stats.ReservedRecords != 0 {
		t.Fatalf("fail-closed replay left local state: %#v", stats)
	}
}

func TestPostgresAuthorityPendingReservationRejectsConflictingReplay(t *testing.T) {
	firstEntered := make(chan struct{})
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
		if calls.Add(1) != 1 {
			t.Errorf("pending replay unexpectedly reached authority: %#v", request)
			w.WriteHeader(http.StatusConflict)
			return
		}
		close(firstEntered)
		<-releaseFirst
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
			SessionID:   "authority-same-request",
			HostToken:   "host-token-same-request",
			ClientToken: "client-token-same-request",
			ExpiresAt:   time.Now().Add(time.Hour).UTC(),
			Created:     true,
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

	firstErr := make(chan error, 1)
	go func() {
		_, _, err := store.Create(context.Background(), CreateSessionRequest{
			RequestID: "same-request", TTL: time.Minute,
			AccountID: "acct-1", HostDeviceID: "host-1",
			ClientDeviceID: "device-1", SessionEpoch: 1,
		})
		firstErr <- err
	}()
	select {
	case <-firstEntered:
	case <-time.After(time.Second):
		t.Fatal("first create did not reach the authority")
	}

	_, _, err = store.Create(context.Background(), CreateSessionRequest{
		RequestID: "same-request", TTL: time.Minute,
		AccountID: "acct-2", HostDeviceID: "host-2",
		ClientDeviceID: "device-2", SessionEpoch: 2,
	})
	if !errors.Is(err, ErrConflict) {
		t.Fatalf("pending conflicting replay error=%v", err)
	}

	releaseFirst <- struct{}{}
	if err := <-firstErr; err != nil {
		t.Fatalf("first create error: %v", err)
	}
	if got := calls.Load(); got != 1 {
		t.Fatalf("authority calls=%d, want 1", got)
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

func TestPostgresStoreSharesRoutingAcrossInstances(t *testing.T) {
	cfg := testConfig()
	cfg.MaxCandidatesPerRole = 1
	creator, cfg := openSignalingIntegrationStore(t, cfg)
	ctx := context.Background()

	follower, err := OpenPostgresStore(ctx, cfg, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer follower.Close()

	created, wasCreated, err := creator.Create(ctx, CreateSessionRequest{RequestID: "shared-routing", TTL: time.Minute})
	if err != nil || !wasCreated {
		t.Fatalf("create: created=%t err=%v", wasCreated, err)
	}
	if role, err := follower.Authorize(ctx, created.SessionID, created.DeviceToken); err != nil || role != RoleDevice {
		t.Fatalf("second store did not authorize device role=%q err=%v", role, err)
	}

	type pollResult struct {
		events []Event
		err    error
	}
	result := make(chan pollResult, 1)
	waitCtx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	go func() {
		events, _, pollErr := follower.PollAuthorized(waitCtx, created.SessionID, RoleDevice, 0, true)
		result <- pollResult{events: events, err: pollErr}
	}()
	waitForPostgresWaiter(t, follower, created.SessionID, RoleDevice, 1)

	if _, _, err := creator.AddMessageAuthorized(ctx, created.SessionID, RoleHost, MessageRequest{
		MessageID: "offer-from-peer-instance", Type: MessageOffer, SDP: "v=0",
	}); err != nil {
		t.Fatal(err)
	}
	select {
	case polled := <-result:
		if polled.err != nil || len(polled.events) != 1 || polled.events[0].MessageID != "offer-from-peer-instance" {
			t.Fatalf("cross-instance poll result=%#v", polled)
		}
	case <-time.After(time.Second):
		t.Fatal("cross-instance long poll did not wake")
	}
	if _, _, err := follower.AddMessageAuthorized(ctx, created.SessionID, RoleDevice, MessageRequest{
		MessageID: "answer-from-peer-instance", Type: MessageAnswer, SDP: "v=0",
	}); err != nil {
		t.Fatal(err)
	}
	hostEvents, next, err := creator.PollAuthorized(ctx, created.SessionID, RoleHost, 1, false)
	if err != nil || len(hostEvents) != 1 || hostEvents[0].MessageID != "answer-from-peer-instance" || next != 2 {
		t.Fatalf("cross-instance host poll events=%#v next=%d err=%v", hostEvents, next, err)
	}

	invalidated, err := follower.Invalidate(ctx, created.SessionID)
	if err != nil || !invalidated {
		t.Fatalf("cross-instance invalidate invalidated=%t err=%v", invalidated, err)
	}
	if _, err := creator.Authorize(ctx, created.SessionID, created.HostToken); !errors.Is(err, ErrNotFound) {
		t.Fatalf("originating store authorized invalidated token: %v", err)
	}
	if _, _, err := creator.Create(ctx, CreateSessionRequest{RequestID: "shared-routing", TTL: time.Minute}); !errors.Is(err, ErrInvalidated) {
		t.Fatalf("cross-instance tombstone replay error=%v", err)
	}
}

func TestPostgresWaiterLeaseReleasedAfterBackendDisconnect(t *testing.T) {
	cfg := testConfig()
	store, _ := openSignalingIntegrationStore(t, cfg)
	ctx := context.Background()
	created, _, err := store.Create(ctx, CreateSessionRequest{RequestID: "waiter-lease", TTL: time.Minute})
	if err != nil {
		t.Fatal(err)
	}

	listener, err := store.openNotificationListener(ctx)
	if err != nil {
		t.Fatal(err)
	}
	lease := waiterLease{ID: "stale-lease", BackendPID: listener.backendPID, BackendStartedAt: listener.backendStartedAt}
	if _, _, err := store.pollOnce(ctx, created.SessionID, RoleDevice, 0, true, lease); err != nil {
		listener.close()
		t.Fatal(err)
	}
	waitForPostgresWaiter(t, store, created.SessionID, RoleDevice, 1)
	closePostgresListenerConnection(t, listener)
	waitForPostgresBackendGone(t, store, lease.BackendPID, lease.BackendStartedAt)

	secondListener, err := store.openNotificationListener(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer secondListener.close()
	secondLease := waiterLease{ID: "replacement-lease", BackendPID: secondListener.backendPID, BackendStartedAt: secondListener.backendStartedAt}
	if _, _, err := store.pollOnce(ctx, created.SessionID, RoleDevice, 0, true, secondLease); err != nil {
		t.Fatalf("replacement waiter after backend disconnect: %v", err)
	}
	waitForPostgresWaiter(t, store, created.SessionID, RoleDevice, 1)
	if err := store.releaseWaiter(ctx, created.SessionID, RoleDevice, secondLease.ID); err != nil {
		t.Fatal(err)
	}
}

func TestPostgresWaiterLeaseRegistrationIsAtomic(t *testing.T) {
	cfg := testConfig()
	cfg.MaxWaitersPerRole = 1
	store, cfg := openSignalingIntegrationStore(t, cfg)
	ctx := context.Background()
	peer, err := OpenPostgresStore(ctx, cfg, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer peer.Close()
	created, _, err := store.Create(ctx, CreateSessionRequest{RequestID: "waiter-lease-atomic", TTL: time.Minute})
	if err != nil {
		t.Fatal(err)
	}

	stores := []*PostgresStore{store, peer}
	listeners := make([]*postgresNotificationListener, 0, len(stores))
	for _, owner := range stores {
		listener, err := owner.openNotificationListener(ctx)
		if err != nil {
			t.Fatal(err)
		}
		defer listener.close()
		listeners = append(listeners, listener)
	}

	start := make(chan struct{})
	errs := make(chan error, len(listeners))
	var wait sync.WaitGroup
	for i, owner := range stores {
		listener := listeners[i]
		wait.Add(1)
		go func(i int, owner *PostgresStore, listener *postgresNotificationListener) {
			defer wait.Done()
			<-start
			lease := waiterLease{ID: fmt.Sprintf("atomic-lease-%d", i), BackendPID: listener.backendPID, BackendStartedAt: listener.backendStartedAt}
			_, _, err := owner.pollOnce(ctx, created.SessionID, RoleDevice, 0, true, lease)
			errs <- err
		}(i, owner, listener)
	}
	close(start)
	wait.Wait()
	close(errs)

	var accepted, rejected int
	for err := range errs {
		switch {
		case err == nil:
			accepted++
		case errors.Is(err, ErrTooManyWaiters):
			rejected++
		default:
			t.Fatalf("waiter registration error=%v", err)
		}
	}
	if accepted != 1 || rejected != 1 {
		t.Fatalf("accepted=%d rejected=%d, want one accepted and one rejected", accepted, rejected)
	}
	waitForPostgresWaiter(t, store, created.SessionID, RoleDevice, 1)
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
	tag, err := store.pool.Exec(ctx, "UPDATE signaling_sessions SET expires_at=now()-interval '1 second' WHERE session_id=$1", created.SessionID)
	if err != nil {
		t.Fatal(err)
	}
	if tag.RowsAffected() != 1 {
		t.Fatalf("expired session update affected %d rows, want 1", tag.RowsAffected())
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
	if _, err := store.pool.Exec(ctx, "ALTER TABLE signaling_waiter_leases DROP CONSTRAINT signaling_waiter_leases_backend_pid_check"); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, err := store.pool.Exec(context.Background(), "ALTER TABLE signaling_waiter_leases ADD CONSTRAINT signaling_waiter_leases_backend_pid_check CHECK (backend_pid > 0)"); err != nil {
			t.Fatalf("restore signaling_waiter_leases constraint: %v", err)
		}
	})
	if err := store.Ready(ctx); !errors.Is(err, ErrStorage) {
		t.Fatalf("readiness schema drift error=%v, want ErrStorage", err)
	}
}

func TestSignalingMigrationUpgradesWaiterCountSchema(t *testing.T) {
	databaseURL := os.Getenv("VIBE_SIGNALING_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("VIBE_SIGNALING_TEST_DATABASE_URL is not set")
	}
	databaseURL, _ = signalingIntegrationTestDatabaseURL(t, databaseURL)
	currentMigration := readSignalingMigration(t)
	oldMigration := strings.Replace(currentMigration, newWaiterLeaseSchemaForTest, oldWaiterCountSchemaForTest, 1)
	if oldMigration == currentMigration {
		t.Fatal("newWaiterLeaseSchemaForTest no longer matches the migration source")
	}
	oldDigest := sha256.Sum256([]byte(oldMigration))
	if hex.EncodeToString(oldDigest[:]) != previousWaiterCountSchemaChecksum {
		t.Fatal("old migration fixture no longer matches previous checksum")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	if err := ApplyMigration(ctx, databaseURL, oldMigration); err != nil {
		t.Fatal(err)
	}
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	if _, err := pool.Exec(ctx, "INSERT INTO signaling_sessions(session_id,request_id,ttl_seconds,expires_at,created_at) VALUES ('session-with-stale-waiter','request-with-stale-waiter',60,now()+interval '1 minute',now())"); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, "INSERT INTO signaling_waiters(session_id,role,waiter_count) VALUES ('session-with-stale-waiter','device',1)"); err != nil {
		t.Fatal(err)
	}

	if err := ApplyMigration(ctx, databaseURL, readSignalingMigration(t)); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, "SELECT session_id,role,lease_id,backend_pid,backend_started_at,registered_at FROM signaling_waiter_leases LIMIT 0"); err != nil {
		t.Fatal(err)
	}
	var oldTableExists bool
	if err := pool.QueryRow(ctx, "SELECT to_regclass('signaling_waiters') IS NOT NULL").Scan(&oldTableExists); err != nil {
		t.Fatal(err)
	}
	if oldTableExists {
		t.Fatal("old waiter count table survived migration")
	}
	var recorded string
	if err := pool.QueryRow(ctx, "SELECT checksum_sha256 FROM signaling_schema_migrations WHERE version=1").Scan(&recorded); err != nil {
		t.Fatal(err)
	}
	if recorded != requiredSignalingSchemaChecksum {
		t.Fatalf("recorded checksum = %q, want %q", recorded, requiredSignalingSchemaChecksum)
	}
	if err := ApplyMigration(ctx, databaseURL, readSignalingMigration(t)); err != nil {
		t.Fatalf("reapply upgraded migration: %v", err)
	}
}

const newWaiterLeaseSchemaForTest = "-- Upgrade deploy order: drain or stop instances that still use the legacy\n" +
	"-- signaling_waiters counter schema, apply this migration, then start instances\n" +
	"-- that use signaling_waiter_leases.\n" +
	"DROP TABLE IF EXISTS signaling_waiters;\n\n" +
	"CREATE TABLE IF NOT EXISTS signaling_waiter_leases (\n" +
	"    session_id text NOT NULL REFERENCES signaling_sessions(session_id) ON DELETE CASCADE,\n" +
	"    role text NOT NULL CHECK (role IN ('host','device')),\n" +
	"    lease_id text NOT NULL,\n" +
	"    backend_pid integer NOT NULL CHECK (backend_pid > 0),\n" +
	"    backend_started_at timestamptz NOT NULL,\n" +
	"    registered_at timestamptz NOT NULL DEFAULT now(),\n" +
	"    PRIMARY KEY (session_id, role, lease_id)\n" +
	");\n" +
	"CREATE INDEX IF NOT EXISTS signaling_waiter_leases_backend_idx\n" +
	"    ON signaling_waiter_leases(backend_pid, backend_started_at);"

const oldWaiterCountSchemaForTest = "CREATE TABLE IF NOT EXISTS signaling_waiters (\n" +
	"    session_id text NOT NULL REFERENCES signaling_sessions(session_id) ON DELETE CASCADE,\n" +
	"    role text NOT NULL CHECK (role IN ('host','device')),\n" +
	"    waiter_count integer NOT NULL CHECK (waiter_count >= 0),\n" +
	"    PRIMARY KEY (session_id, role)\n" +
	");"

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
		if err := store.pool.QueryRow(context.Background(), "SELECT COUNT(*) FROM signaling_waiter_leases WHERE session_id=$1 AND role=$2", sessionID, role).Scan(&waiters); err != nil {
			t.Fatal(err)
		}
		if waiters == want {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("waiter count did not reach %d", want)
}

func closePostgresListenerConnection(t *testing.T, listener *postgresNotificationListener) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if err := listener.connection.Conn().Close(ctx); err != nil {
		t.Fatalf("close listener connection: %v", err)
	}
	listener.connection.Release()
	listener.release()
}

func waitForPostgresBackendGone(t *testing.T, store *PostgresStore, backendPID int, backendStartedAt time.Time) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		var exists bool
		if err := store.pool.QueryRow(context.Background(), "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE pid=$1 AND backend_start=$2)", backendPID, backendStartedAt).Scan(&exists); err != nil {
			t.Fatal(err)
		}
		if !exists {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("postgres backend %d did not disconnect", backendPID)
}

func TestPostgresReadinessMapsStorageError(t *testing.T) {
	databaseURL := os.Getenv("VIBE_SIGNALING_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("VIBE_SIGNALING_TEST_DATABASE_URL is not set")
	}
	databaseURL, _ = signalingIntegrationTestDatabaseURL(t, databaseURL)
	migration, err := os.ReadFile(filepath.Join("..", "..", "migrations", "001_signaling.sql"))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	if err := ApplyMigration(ctx, databaseURL, string(migration)); err != nil {
		t.Fatal(err)
	}
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	if _, err := pool.Exec(ctx, "DROP TABLE IF EXISTS signaling_schema_migrations CASCADE"); err != nil {
		t.Fatal(err)
	}
	store := &PostgresStore{pool: pool, now: time.Now}
	if err := store.Ready(ctx); !errors.Is(err, ErrStorage) {
		t.Fatalf("missing schema error=%v, want ErrStorage", err)
	}
}
