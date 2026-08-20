package authority

import (
	"context"
	"errors"
	"math"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func openIntegrationStore(t *testing.T) (*PostgresStore, Config) {
	t.Helper()
	databaseURL := os.Getenv("VIBE_AUTHORITY_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("VIBE_AUTHORITY_TEST_DATABASE_URL is not set")
	}
	migration, err := os.ReadFile(filepath.Join("..", "..", "migrations", "001_authority.sql"))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	if err := ApplyMigration(ctx, databaseURL, string(migration)); err != nil {
		t.Fatal(err)
	}
	// A second application proves the checksum ledger makes migration retries safe.
	if err := ApplyMigration(ctx, databaseURL, string(migration)); err != nil {
		t.Fatal(err)
	}
	cfg := testAuthorityConfig()
	cfg.DatabaseURL = databaseURL
	store, err := OpenPostgres(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.pool.Exec(ctx, `TRUNCATE authority_coturn_events,authority_relay_allocations,authority_relay_daily_usage,authority_signaling_sessions,authority_devices,authority_accounts,authority_audit_events RESTART IDENTITY CASCADE`); err != nil {
		store.Close()
		t.Fatal(err)
	}
	t.Cleanup(store.Close)
	return store, cfg
}

func TestPostgresDenyWinsAndPersistsRevocation(t *testing.T) {
	store, cfg := openIntegrationStore(t)
	ctx := context.Background()
	if err := store.EnsureAccount(ctx, "account"); err != nil {
		t.Fatal(err)
	}
	for _, deviceID := range []string{"host", "client"} {
		if err := store.RegisterDevice(ctx, "account", deviceID); err != nil {
			t.Fatal(err)
		}
	}
	request := SignalingRequest{RequestID: "request", AccountID: "account", HostDeviceID: "host", ClientDeviceID: "client", SessionEpoch: 1, TTLSeconds: 60}
	start := make(chan struct{})
	var admission SignalingAdmission
	var createErr, revokeErr error
	var wait sync.WaitGroup
	wait.Add(2)
	go func() {
		defer wait.Done()
		<-start
		admission, createErr = store.CreateSignaling(ctx, request, time.Now().UTC())
	}()
	go func() { defer wait.Done(); <-start; revokeErr = store.RevokeDevice(ctx, "client", 1, time.Now().UTC()) }()
	close(start)
	wait.Wait()
	if revokeErr != nil {
		t.Fatal(revokeErr)
	}
	if createErr == nil {
		if _, err := store.AuthorizeSignaling(ctx, admission.SessionID, admission.ClientToken, time.Now().UTC()); !errors.Is(err, ErrRevoked) {
			t.Fatalf("role token authorized after revocation: %v", err)
		}
	} else if !errors.Is(createErr, ErrRevoked) {
		t.Fatalf("unexpected create result: %v", createErr)
	}
	restarted, err := OpenPostgres(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer restarted.Close()
	if _, err := restarted.CreateSignaling(ctx, SignalingRequest{RequestID: "after-restart", AccountID: "account", HostDeviceID: "host", ClientDeviceID: "client", SessionEpoch: 2, TTLSeconds: 60}, time.Now().UTC()); !errors.Is(err, ErrRevoked) {
		t.Fatalf("revocation not durable across restart: %v", err)
	}
}

func TestPostgresSignalingAdmissionReplayIsDurableAndExact(t *testing.T) {
	store, cfg := openIntegrationStore(t)
	ctx := context.Background()
	if err := store.EnsureAccount(ctx, "account"); err != nil {
		t.Fatal(err)
	}
	for _, deviceID := range []string{"host", "client"} {
		if err := store.RegisterDevice(ctx, "account", deviceID); err != nil {
			t.Fatal(err)
		}
	}
	now := time.Now().UTC()
	request := SignalingRequest{RequestID: "durable-request", AccountID: "account", HostDeviceID: "host", ClientDeviceID: "client", SessionEpoch: 3, TTLSeconds: 60}
	created, err := store.CreateSignaling(ctx, request, now)
	if err != nil {
		t.Fatal(err)
	}
	if !created.Created {
		t.Fatal("first admission was not marked created")
	}

	restarted, err := OpenPostgres(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer restarted.Close()
	replayed, err := restarted.CreateSignaling(ctx, request, now.Add(time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if replayed.SessionID != created.SessionID || replayed.HostToken != created.HostToken || replayed.ClientToken != created.ClientToken || replayed.Created {
		t.Fatalf("durable replay changed stable admission fields: replay=%#v created=%#v", replayed, created)
	}
	expiresDelta := replayed.ExpiresAt.Sub(created.ExpiresAt)
	if expiresDelta < 0 {
		expiresDelta = -expiresDelta
	}
	if expiresDelta > time.Microsecond {
		t.Fatalf("durable replay changed expiry beyond database precision: replay=%s created=%s delta=%s", replayed.ExpiresAt, created.ExpiresAt, expiresDelta)
	}

	changed := request
	changed.TTLSeconds = 120
	if _, err := restarted.CreateSignaling(ctx, changed, now.Add(2*time.Second)); !errors.Is(err, ErrConflict) {
		t.Fatalf("changed idempotency replay error=%v, want ErrConflict", err)
	}
	if _, err := restarted.CreateSignaling(ctx, SignalingRequest{RequestID: "host-rollback", AccountID: "account", HostDeviceID: "host", ClientDeviceID: "client", SessionEpoch: 2, TTLSeconds: 60}, now.Add(3*time.Second)); !errors.Is(err, ErrConflict) {
		t.Fatalf("durable host epoch floor error=%v, want ErrConflict", err)
	}
	if err := restarted.RegisterDevice(ctx, "account", "other-host"); err != nil {
		t.Fatal(err)
	}
	if _, err := restarted.CreateSignaling(ctx, SignalingRequest{RequestID: "client-rollback", AccountID: "account", HostDeviceID: "other-host", ClientDeviceID: "client", SessionEpoch: 2, TTLSeconds: 60}, now.Add(4*time.Second)); !errors.Is(err, ErrConflict) {
		t.Fatalf("durable client epoch floor error=%v, want ErrConflict", err)
	}
}

func TestPostgresAllocationLimitIsAtomicAcrossConcurrentConnections(t *testing.T) {
	store, _ := openIntegrationStore(t)
	ctx := context.Background()
	if err := store.EnsureAccount(ctx, "account"); err != nil {
		t.Fatal(err)
	}
	for _, deviceID := range []string{"host", "client"} {
		if err := store.RegisterDevice(ctx, "account", deviceID); err != nil {
			t.Fatal(err)
		}
	}
	session, err := store.CreateSignaling(ctx, SignalingRequest{RequestID: "request", AccountID: "account", HostDeviceID: "host", ClientDeviceID: "client", SessionEpoch: 1, TTLSeconds: 60}, time.Now().UTC())
	if err != nil {
		t.Fatal(err)
	}
	start := make(chan struct{})
	var accepted atomic.Int32
	var wait sync.WaitGroup
	for _, allocationID := range []string{"allocation-one", "allocation-two"} {
		wait.Add(1)
		go func(allocationID string) {
			defer wait.Done()
			<-start
			err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: allocationID, SourceID: "turn-one"}, time.Now().UTC())
			if err == nil {
				accepted.Add(1)
			} else if !errors.Is(err, ErrQuotaExceeded) {
				t.Errorf("unexpected admission error: %v", err)
			}
		}(allocationID)
	}
	close(start)
	wait.Wait()
	if accepted.Load() != 1 {
		t.Fatalf("accepted %d allocations, want one", accepted.Load())
	}
}

func TestPostgresAuthorityReviewContracts(t *testing.T) {
	store, _ := openIntegrationStore(t)
	store.allocationLimit = 5
	ctx := context.Background()
	now := time.Now().UTC()
	if err := store.EnsureAccount(ctx, "account"); err != nil {
		t.Fatal(err)
	}
	for _, deviceID := range []string{"host", "client", "other", "expired-host", "expired-client"} {
		if err := store.RegisterDevice(ctx, "account", deviceID); err != nil {
			t.Fatal(err)
		}
	}
	session, err := store.CreateSignaling(ctx, SignalingRequest{RequestID: "high-water", AccountID: "account", HostDeviceID: "host", ClientDeviceID: "client", SessionEpoch: 10, TTLSeconds: 60}, now)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.CreateSignaling(ctx, SignalingRequest{RequestID: "device-rollback", AccountID: "account", HostDeviceID: "host", ClientDeviceID: "other", SessionEpoch: 9, TTLSeconds: 60}, now); !errors.Is(err, ErrConflict) {
		t.Fatalf("per-device rollback error=%v", err)
	}
	if _, err := store.CreateSignaling(ctx, SignalingRequest{RequestID: "overflow", AccountID: "account", HostDeviceID: "host", ClientDeviceID: "other", SessionEpoch: math.MaxInt64 + 1, TTLSeconds: 60}, now); !errors.Is(err, ErrConflict) {
		t.Fatalf("epoch overflow error=%v", err)
	}
	for name, request := range map[string]RelayAdmissionRequest{
		"missing": {DeviceID: "client", SessionID: "missing", AllocationID: "missing", SourceID: "node"},
		"unbound": {DeviceID: "other", SessionID: session.SessionID, AllocationID: "unbound", SourceID: "node"},
	} {
		if err := store.AdmitRelay(ctx, request, now); !errors.Is(err, ErrNotFound) {
			t.Fatalf("%s relay error=%v", name, err)
		}
	}
	expired, err := store.CreateSignaling(ctx, SignalingRequest{RequestID: "expired", AccountID: "account", HostDeviceID: "expired-host", ClientDeviceID: "expired-client", SessionEpoch: 1, TTLSeconds: 60}, now.Add(-2*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "expired-client", SessionID: expired.SessionID, AllocationID: "expired", SourceID: "node"}, now); !errors.Is(err, ErrRevoked) {
		t.Fatalf("expired relay session error=%v", err)
	}
	for _, allocationID := range []string{"conflict", "valid"} {
		if err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: allocationID, SourceID: "node"}, now); err != nil {
			t.Fatal(err)
		}
	}
	exactRetry := RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: "valid", SourceID: "node"}
	if err := store.AdmitRelay(ctx, exactRetry, now.Add(time.Second)); err != nil {
		t.Fatalf("exact relay retry failed: %v", err)
	}
	otherSource := exactRetry
	otherSource.SourceID = "other-node"
	if err := store.AdmitRelay(ctx, otherSource, now); err != nil {
		t.Fatalf("same allocation id from another source should be independent: %v", err)
	}
	changedRetry := exactRetry
	changedRetry.DeviceID = "host"
	if err := store.AdmitRelay(ctx, changedRetry, now); !errors.Is(err, ErrConflict) {
		t.Fatalf("changed relay retry error=%v", err)
	}
	concurrentRetry := RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: "concurrent-retry", SourceID: "node"}
	start := make(chan struct{})
	results := make(chan error, 2)
	for range 2 {
		go func() {
			<-start
			results <- store.AdmitRelay(ctx, concurrentRetry, now)
		}()
	}
	close(start)
	for range 2 {
		if err := <-results; err != nil {
			t.Fatalf("concurrent exact relay retry failed: %v", err)
		}
	}
	if _, err := store.ApplyCoturnUsage(ctx, CoturnUsage{SourceID: "node", AllocationID: "valid", DeviceID: "client", SessionID: session.SessionID, Sequence: 1, ObservedAt: now}); !errors.Is(err, ErrConflict) {
		t.Fatalf("empty event id error=%v", err)
	}
	result, err := store.Reconcile(ctx, ReconcileRequest{SourceID: "node", ObservedAt: now.Add(time.Second), Allocations: []CoturnUsage{
		{AllocationID: "conflict", DeviceID: "other", SessionID: session.SessionID, Sequence: 1},
		{AllocationID: "unknown", DeviceID: "client", SessionID: session.SessionID, Sequence: 1},
		{AllocationID: "valid", DeviceID: "client", SessionID: session.SessionID, Sequence: 1, IngressBytes: 1},
	}}, time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	if result.Applied != 1 || !slices.Equal(result.ConflictAllocationIDs, []string{"conflict"}) || !slices.Equal(result.UnauthorizedAllocationIDs, []string{"unknown"}) {
		t.Fatalf("reconcile result=%+v", result)
	}
	backward := CoturnUsage{SourceID: "node", EventID: "backward", AllocationID: "valid", DeviceID: "client", SessionID: session.SessionID, Sequence: 2, IngressBytes: 2, ObservedAt: now}
	if _, err := store.ApplyCoturnUsage(ctx, backward); !errors.Is(err, ErrStaleUsage) {
		t.Fatalf("backward observed_at error=%v", err)
	}
	oldAdmission := RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: "old-clock", SourceID: "node"}
	oldObservedAt := now.Add(-48 * time.Hour)
	if err := store.AdmitRelay(ctx, oldAdmission, oldObservedAt); err != nil {
		t.Fatal(err)
	}
	if _, err := store.ApplyCoturnUsage(ctx, CoturnUsage{SourceID: "node", EventID: "old-clock", AllocationID: "old-clock", DeviceID: "client", SessionID: session.SessionID, Sequence: 1, IngressBytes: 7, ObservedAt: now.Add(time.Second)}); err != nil {
		t.Fatal(err)
	}
	var billedToday bool
	if err := store.pool.QueryRow(ctx, `SELECT usage_day=(CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date FROM authority_relay_daily_usage WHERE device_id='client' AND ingress_bytes>=7 ORDER BY usage_day DESC LIMIT 1`).Scan(&billedToday); err != nil {
		t.Fatal(err)
	}
	if !billedToday {
		t.Fatal("usage was not billed to the database UTC ingestion day")
	}
	if err := store.RevokeDevice(ctx, "client", 1, now); err != nil {
		t.Fatal(err)
	}
	finalUsage := CoturnUsage{SourceID: "node", EventID: "final-close", AllocationID: "valid", DeviceID: "client", SessionID: session.SessionID, Sequence: 2, IngressBytes: 3, EgressBytes: 5, Closed: true, ObservedAt: now.Add(2 * time.Second)}
	if _, err := store.ApplyCoturnUsage(ctx, finalUsage); !errors.Is(err, ErrRevoked) {
		t.Fatalf("final usage after revocation error=%v, want ErrRevoked", err)
	}
	if err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: "after-revoke", SourceID: "node"}, now); !errors.Is(err, ErrRevoked) {
		t.Fatalf("relay admission after device revocation error=%v", err)
	}
}

func TestPostgresSignalingInvalidationClosesRelayAllocationLedgerOnly(t *testing.T) {
	store, _ := openIntegrationStore(t)
	ctx := context.Background()
	now := time.Now().UTC()
	if err := store.EnsureAccount(ctx, "account"); err != nil {
		t.Fatal(err)
	}
	for _, deviceID := range []string{"host", "client"} {
		if err := store.RegisterDevice(ctx, "account", deviceID); err != nil {
			t.Fatal(err)
		}
	}
	session, err := store.CreateSignaling(ctx, SignalingRequest{RequestID: "invalidate-ledger", AccountID: "account", HostDeviceID: "host", ClientDeviceID: "client", SessionEpoch: 1, TTLSeconds: 60}, now)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: "allocation", SourceID: "node"}, now); err != nil {
		t.Fatal(err)
	}
	first := CoturnUsage{SourceID: "node", EventID: "first", AllocationID: "allocation", DeviceID: "client", SessionID: session.SessionID, Sequence: 1, IngressBytes: 3, EgressBytes: 5, ObservedAt: now.Add(time.Second)}
	if _, err := store.ApplyCoturnUsage(ctx, first); err != nil {
		t.Fatal(err)
	}
	if err := store.InvalidateSignaling(ctx, session.SessionID, now.Add(2*time.Second)); err != nil {
		t.Fatal(err)
	}
	if err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: "blocked", SourceID: "node"}, now.Add(3*time.Second)); !errors.Is(err, ErrRevoked) {
		t.Fatalf("invalidated session relay admission error=%v", err)
	}
	final := CoturnUsage{SourceID: "node", EventID: "final", AllocationID: "allocation", DeviceID: "client", SessionID: session.SessionID, Sequence: 2, IngressBytes: 4, EgressBytes: 7, ObservedAt: now.Add(3 * time.Second), Closed: true}
	if _, err := store.ApplyCoturnUsage(ctx, final); !errors.Is(err, ErrRevoked) {
		t.Fatalf("final usage after signaling invalidation error=%v, want ErrRevoked", err)
	}
	var ingress, egress string
	if err := store.pool.QueryRow(ctx, `SELECT ingress_bytes::text,egress_bytes::text FROM authority_relay_daily_usage WHERE device_id=$1`, "client").Scan(&ingress, &egress); err != nil {
		t.Fatal(err)
	}
	if ingress != "3" || egress != "5" {
		t.Fatalf("final invalidated usage mutated ledger to %s/%s", ingress, egress)
	}
	var closedAt *time.Time
	if err := store.pool.QueryRow(ctx, `SELECT closed_at FROM authority_relay_allocations WHERE allocation_id=$1`, "allocation").Scan(&closedAt); err != nil {
		t.Fatal(err)
	}
	wantClosedAt := now.Add(2 * time.Second).Truncate(time.Microsecond)
	if closedAt == nil || !closedAt.UTC().Truncate(time.Microsecond).Equal(wantClosedAt) {
		t.Fatalf("closed_at=%v, want invalidation timestamp %v", closedAt, wantClosedAt)
	}
}

func TestPostgresRevocationClosesRelayAllocationsForLedgerOnly(t *testing.T) {
	store, _ := openIntegrationStore(t)
	store.allocationLimit = 1
	ctx := context.Background()
	now := time.Now().UTC()
	if err := store.EnsureAccount(ctx, "account"); err != nil {
		t.Fatal(err)
	}
	for _, deviceID := range []string{"host", "client", "replacement"} {
		if err := store.RegisterDevice(ctx, "account", deviceID); err != nil {
			t.Fatal(err)
		}
	}
	session, err := store.CreateSignaling(ctx, SignalingRequest{RequestID: "revocation-ledger", AccountID: "account", HostDeviceID: "host", ClientDeviceID: "client", SessionEpoch: 1, TTLSeconds: 60}, now)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: "allocation", SourceID: "node"}, now); err != nil {
		t.Fatal(err)
	}
	if err := store.RevokeDevice(ctx, "client", 1, now.Add(time.Second)); err != nil {
		t.Fatal(err)
	}
	final := CoturnUsage{SourceID: "node", EventID: "final-after-revoke", AllocationID: "allocation", DeviceID: "client", SessionID: session.SessionID, Sequence: 1, IngressBytes: 9, EgressBytes: 4, ObservedAt: now.Add(2 * time.Second), Closed: true}
	if _, err := store.ApplyCoturnUsage(ctx, final); !errors.Is(err, ErrRevoked) {
		t.Fatalf("final usage after device revoke error=%v, want ErrRevoked", err)
	}
	var dailyRows int
	if err := store.pool.QueryRow(ctx, `SELECT count(*) FROM authority_relay_daily_usage WHERE device_id=$1`, "client").Scan(&dailyRows); err != nil {
		t.Fatal(err)
	}
	if dailyRows != 0 {
		t.Fatalf("revoked final usage created %d daily rows", dailyRows)
	}
	var closedAt *time.Time
	if err := store.pool.QueryRow(ctx, `SELECT closed_at FROM authority_relay_allocations WHERE allocation_id=$1`, "allocation").Scan(&closedAt); err != nil {
		t.Fatal(err)
	}
	wantClosedAt := now.Add(time.Second).Truncate(time.Microsecond)
	if closedAt == nil || !closedAt.UTC().Truncate(time.Microsecond).Equal(wantClosedAt) {
		t.Fatalf("closed_at=%v, want revocation timestamp %v", closedAt, wantClosedAt)
	}
	if err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: "blocked", SourceID: "node"}, now.Add(3*time.Second)); !errors.Is(err, ErrRevoked) {
		t.Fatalf("revoked device admission error=%v", err)
	}
	replacement, err := store.CreateSignaling(ctx, SignalingRequest{RequestID: "replacement", AccountID: "account", HostDeviceID: "host", ClientDeviceID: "replacement", SessionEpoch: 2, TTLSeconds: 60}, now.Add(3*time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "replacement", SessionID: replacement.SessionID, AllocationID: "replacement-allocation", SourceID: "node"}, now.Add(3*time.Second)); err != nil {
		t.Fatalf("closed revoked allocation still consumed quota: %v", err)
	}
}

func TestPostgresCoturnUsageAndReconcileStaySourceScoped(t *testing.T) {
	store, _ := openIntegrationStore(t)
	store.allocationLimit = 6
	ctx := context.Background()
	now := time.Now().UTC()
	if err := store.EnsureAccount(ctx, "account"); err != nil {
		t.Fatal(err)
	}
	for _, deviceID := range []string{"host", "client"} {
		if err := store.RegisterDevice(ctx, "account", deviceID); err != nil {
			t.Fatal(err)
		}
	}
	session, err := store.CreateSignaling(ctx, SignalingRequest{RequestID: "source-scope", AccountID: "account", HostDeviceID: "host", ClientDeviceID: "client", SessionEpoch: 1, TTLSeconds: 60}, now)
	if err != nil {
		t.Fatal(err)
	}
	for _, sourceID := range []string{"turn-a", "turn-b"} {
		for _, allocationID := range []string{"shared", "stale-" + sourceID} {
			request := RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: allocationID, SourceID: sourceID}
			if err := store.AdmitRelay(ctx, request, now); err != nil {
				t.Fatalf("admit %s/%s: %v", sourceID, allocationID, err)
			}
		}
	}
	for _, usage := range []CoturnUsage{
		{SourceID: "turn-a", EventID: "event-a", AllocationID: "shared", DeviceID: "client", SessionID: session.SessionID, Sequence: 1, IngressBytes: 10, EgressBytes: 1, ObservedAt: now.Add(time.Second)},
		{SourceID: "turn-b", EventID: "event-b", AllocationID: "shared", DeviceID: "client", SessionID: session.SessionID, Sequence: 1, IngressBytes: 20, EgressBytes: 2, ObservedAt: now.Add(time.Second)},
	} {
		if _, err := store.ApplyCoturnUsage(ctx, usage); err != nil {
			t.Fatalf("usage %s: %v", usage.SourceID, err)
		}
	}
	var firstIngress, secondIngress int64
	if err := store.pool.QueryRow(ctx, "SELECT ingress_bytes FROM authority_relay_allocations WHERE source_id='turn-a' AND allocation_id='shared'").Scan(&firstIngress); err != nil {
		t.Fatal(err)
	}
	if err := store.pool.QueryRow(ctx, "SELECT ingress_bytes FROM authority_relay_allocations WHERE source_id='turn-b' AND allocation_id='shared'").Scan(&secondIngress); err != nil {
		t.Fatal(err)
	}
	if firstIngress != 10 || secondIngress != 20 {
		t.Fatalf("shared allocation usage crossed sources: turn-a=%d turn-b=%d", firstIngress, secondIngress)
	}
	first, err := store.Reconcile(ctx, ReconcileRequest{SourceID: "turn-a", ObservedAt: now.Add(2 * time.Second), Allocations: []CoturnUsage{
		{AllocationID: "shared", DeviceID: "client", SessionID: session.SessionID, Sequence: 2, IngressBytes: 11, EgressBytes: 1},
	}}, 500*time.Millisecond)
	if err != nil {
		t.Fatal(err)
	}
	if first.Applied != 1 || !slices.Equal(first.MissingAllocationIDs, []string{"stale-turn-a"}) {
		t.Fatalf("turn-a reconcile result=%+v", first)
	}
	second, err := store.Reconcile(ctx, ReconcileRequest{SourceID: "turn-b", ObservedAt: now.Add(3 * time.Second), Allocations: []CoturnUsage{
		{AllocationID: "shared", DeviceID: "client", SessionID: session.SessionID, Sequence: 2, IngressBytes: 21, EgressBytes: 2},
	}}, 500*time.Millisecond)
	if err != nil {
		t.Fatal(err)
	}
	if second.Applied != 1 || !slices.Equal(second.MissingAllocationIDs, []string{"stale-turn-b"}) {
		t.Fatalf("turn-b reconcile result=%+v", second)
	}
}

func TestPostgresReadinessRejectsChecksumMismatch(t *testing.T) {
	store, _ := openIntegrationStore(t)
	ctx := context.Background()
	if _, err := store.pool.Exec(ctx, `UPDATE authority_schema_migrations SET checksum_sha256='wrong' WHERE version=$1`, requiredSchemaVersion); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_, _ = store.pool.Exec(context.Background(), `UPDATE authority_schema_migrations SET checksum_sha256=$1 WHERE version=$2`, requiredSchemaChecksum, requiredSchemaVersion)
	})
	if err := store.Ready(ctx); !errors.Is(err, ErrStorage) {
		t.Fatalf("readiness checksum error=%v", err)
	}
}

func TestPostgresReadinessRejectsCriticalConstraintDrift(t *testing.T) {
	store, _ := openIntegrationStore(t)
	ctx := context.Background()
	if _, err := store.pool.Exec(ctx, `ALTER TABLE authority_coturn_events DROP CONSTRAINT authority_coturn_events_pkey`); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_, _ = store.pool.Exec(context.Background(), `ALTER TABLE authority_coturn_events ADD CONSTRAINT authority_coturn_events_pkey PRIMARY KEY (source_id,event_id)`)
	})
	if err := store.Ready(ctx); !errors.Is(err, ErrStorage) {
		t.Fatalf("readiness constraint drift error=%v", err)
	}
}

func TestPostgresCoturnUsageOverDailyLimitRevokesAfterLedgerUpdate(t *testing.T) {
	store, _ := openIntegrationStore(t)
	store.allocationLimit = 3
	store.dailyLimit = 40
	ctx := context.Background()
	now := time.Now().UTC()
	if err := store.EnsureAccount(ctx, "account"); err != nil {
		t.Fatal(err)
	}
	for _, deviceID := range []string{"host", "client"} {
		if err := store.RegisterDevice(ctx, "account", deviceID); err != nil {
			t.Fatal(err)
		}
	}
	session, err := store.CreateSignaling(ctx, SignalingRequest{RequestID: "request", AccountID: "account", HostDeviceID: "host", ClientDeviceID: "client", SessionEpoch: 1, TTLSeconds: 60}, now)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: "allocation", SourceID: "node"}, now); err != nil {
		t.Fatal(err)
	}
	exactLimit := CoturnUsage{SourceID: "node", EventID: "event-1", AllocationID: "allocation", DeviceID: "client", SessionID: session.SessionID, Sequence: 1, IngressBytes: 30, EgressBytes: 10, ObservedAt: now}
	if duplicate, err := store.ApplyCoturnUsage(ctx, exactLimit); err != nil || duplicate {
		t.Fatalf("exact-limit usage=%v/%v", duplicate, err)
	}
	var billedToday bool
	if err := store.pool.QueryRow(ctx, "SELECT usage_day=(CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date FROM authority_relay_daily_usage WHERE device_id=$1", "client").Scan(&billedToday); err != nil {
		t.Fatal(err)
	}
	if !billedToday {
		t.Fatal("usage was not billed to the database UTC ingestion day")
	}
	if err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: "at-quota", SourceID: "node"}, now); !errors.Is(err, ErrQuotaExceeded) {
		t.Fatalf("admission at exact quota error=%v, want ErrQuotaExceeded", err)
	}
	overage := exactLimit
	overage.EventID = "event-2"
	overage.Sequence = 2
	overage.IngressBytes = 31
	overage.ObservedAt = now.Add(time.Second)
	if duplicate, err := store.ApplyCoturnUsage(ctx, overage); err != nil || duplicate {
		t.Fatalf("overage usage=%v/%v", duplicate, err)
	}
	var total, revocationEpoch string
	var revokedAt *time.Time
	if err := store.pool.QueryRow(ctx, "SELECT (u.ingress_bytes+u.egress_bytes)::text,d.revocation_epoch::text,d.revoked_at FROM authority_relay_daily_usage u JOIN authority_devices d ON d.device_id=u.device_id WHERE u.device_id=$1", "client").Scan(&total, &revocationEpoch, &revokedAt); err != nil {
		t.Fatal(err)
	}
	if total != "41" || revocationEpoch != "1" || revokedAt == nil {
		t.Fatalf("overage ledger/revocation total=%s epoch=%s revokedAt=%v", total, revocationEpoch, revokedAt)
	}
	if _, err := store.AuthorizeSignaling(ctx, session.SessionID, session.ClientToken, now.Add(2*time.Second)); !errors.Is(err, ErrRevoked) {
		t.Fatalf("session authorized after over-quota revoke: %v", err)
	}
	if duplicate, err := store.ApplyCoturnUsage(ctx, overage); err != nil || !duplicate {
		t.Fatalf("duplicate overage retry=%v/%v", duplicate, err)
	}
	var auditCount int
	if err := store.pool.QueryRow(ctx, "SELECT count(*) FROM authority_audit_events WHERE event_type='relay_quota_exceeded' AND device_id=$1", "client").Scan(&auditCount); err != nil {
		t.Fatal(err)
	}
	if auditCount != 1 {
		t.Fatalf("quota audit count=%d, want 1", auditCount)
	}
	if err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: "after-overage", SourceID: "node"}, now); !errors.Is(err, ErrRevoked) {
		t.Fatalf("relay admission after over-quota revoke error=%v, want ErrRevoked", err)
	}
}

func TestPostgresRevocationRejectsExistingAllocationUsage(t *testing.T) {
	store, _ := openIntegrationStore(t)
	store.allocationLimit = 3
	ctx := context.Background()
	now := time.Now().UTC()
	if err := store.EnsureAccount(ctx, "account"); err != nil {
		t.Fatal(err)
	}
	for _, deviceID := range []string{"host", "client", "other-host", "other-client"} {
		if err := store.RegisterDevice(ctx, "account", deviceID); err != nil {
			t.Fatal(err)
		}
	}
	session, err := store.CreateSignaling(ctx, SignalingRequest{RequestID: "request", AccountID: "account", HostDeviceID: "host", ClientDeviceID: "client", SessionEpoch: 1, TTLSeconds: 60}, now)
	if err != nil {
		t.Fatal(err)
	}
	activeSession, err := store.CreateSignaling(ctx, SignalingRequest{RequestID: "active-request", AccountID: "account", HostDeviceID: "other-host", ClientDeviceID: "other-client", SessionEpoch: 1, TTLSeconds: 60}, now)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "other-client", SessionID: activeSession.SessionID, AllocationID: "active-before-revoked", SourceID: "node"}, now); err != nil {
		t.Fatal(err)
	}
	for _, allocationID := range []string{"allocation", "already-applied", "after-revoked"} {
		if err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: allocationID, SourceID: "node"}, now); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := store.ApplyCoturnUsage(ctx, CoturnUsage{SourceID: "node", EventID: "before-revoke", AllocationID: "allocation", DeviceID: "client", SessionID: session.SessionID, Sequence: 1, IngressBytes: 10, EgressBytes: 20, ObservedAt: now}); err != nil {
		t.Fatal(err)
	}
	if _, err := store.ApplyCoturnUsage(ctx, CoturnUsage{SourceID: "node", EventID: "already-applied", AllocationID: "already-applied", DeviceID: "client", SessionID: session.SessionID, Sequence: 1, IngressBytes: 3, ObservedAt: now}); err != nil {
		t.Fatal(err)
	}
	if err := store.RevokeDevice(ctx, "client", 1, now.Add(time.Second)); err != nil {
		t.Fatal(err)
	}
	if _, err := store.ApplyCoturnUsage(ctx, CoturnUsage{SourceID: "node", EventID: "after-revoke", AllocationID: "allocation", DeviceID: "client", SessionID: session.SessionID, Sequence: 2, IngressBytes: 11, EgressBytes: 21, ObservedAt: now.Add(2 * time.Second)}); !errors.Is(err, ErrRevoked) {
		t.Fatalf("usage after device revoke error=%v, want ErrRevoked", err)
	}
	result, err := store.Reconcile(ctx, ReconcileRequest{SourceID: "node", ObservedAt: now.Add(3 * time.Second), Allocations: []CoturnUsage{
		{AllocationID: "active-before-revoked", DeviceID: "other-client", SessionID: activeSession.SessionID, Sequence: 1, IngressBytes: 5},
		{AllocationID: "already-applied", DeviceID: "client", SessionID: session.SessionID, Sequence: 1, IngressBytes: 3},
		{AllocationID: "allocation", DeviceID: "client", SessionID: session.SessionID, Sequence: 2, IngressBytes: 11, EgressBytes: 21},
		{AllocationID: "after-revoked", DeviceID: "client", SessionID: session.SessionID, Sequence: 1, IngressBytes: 99},
	}}, time.Minute)
	if !errors.Is(err, ErrRevoked) {
		t.Fatalf("reconcile after device revoke error=%v, want ErrRevoked", err)
	}
	if result.Applied != 1 || result.AlreadyAhead != 1 || result.Duplicate != 0 || len(result.MissingAllocationIDs) != 0 {
		t.Fatalf("partial reconcile result before fail-closed stop=%+v", result)
	}
	var ingress, egress string
	if err := store.pool.QueryRow(ctx, "SELECT ingress_bytes::text,egress_bytes::text FROM authority_relay_daily_usage WHERE device_id=$1", "client").Scan(&ingress, &egress); err != nil {
		t.Fatal(err)
	}
	if ingress != "13" || egress != "20" {
		t.Fatalf("usage after revoke mutated ledger to %s/%s", ingress, egress)
	}
	var activeIngress string
	if err := store.pool.QueryRow(ctx, "SELECT ingress_bytes::text FROM authority_relay_daily_usage WHERE device_id=$1", "other-client").Scan(&activeIngress); err != nil {
		t.Fatal(err)
	}
	if activeIngress != "5" {
		t.Fatalf("active allocation before revoked entry was not committed: ingress=%s", activeIngress)
	}
}

func TestPostgresConcurrentCoturnEventRetryDebitsAndRevokesOnce(t *testing.T) {
	store, _ := openIntegrationStore(t)
	store.dailyLimit = 100
	ctx := context.Background()
	now := time.Now().UTC()
	if err := store.EnsureAccount(ctx, "account"); err != nil {
		t.Fatal(err)
	}
	for _, deviceID := range []string{"host", "client"} {
		if err := store.RegisterDevice(ctx, "account", deviceID); err != nil {
			t.Fatal(err)
		}
	}
	session, err := store.CreateSignaling(ctx, SignalingRequest{RequestID: "request", AccountID: "account", HostDeviceID: "host", ClientDeviceID: "client", SessionEpoch: 1, TTLSeconds: 60}, now)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: "allocation", SourceID: "node"}, now); err != nil {
		t.Fatal(err)
	}
	usage := CoturnUsage{SourceID: "node", EventID: "event", AllocationID: "allocation", DeviceID: "client", SessionID: session.SessionID, Sequence: 1, IngressBytes: 70, EgressBytes: 31, ObservedAt: now}
	start := make(chan struct{})
	results := make(chan struct {
		duplicate bool
		err       error
	}, 8)
	var wait sync.WaitGroup
	for range 8 {
		wait.Add(1)
		go func() {
			defer wait.Done()
			<-start
			duplicate, err := store.ApplyCoturnUsage(ctx, usage)
			results <- struct {
				duplicate bool
				err       error
			}{duplicate: duplicate, err: err}
		}()
	}
	close(start)
	wait.Wait()
	close(results)
	applied := 0
	duplicates := 0
	for result := range results {
		if result.err != nil {
			t.Fatalf("usage retry error=%v", result.err)
		}
		if result.duplicate {
			duplicates++
		} else {
			applied++
		}
	}
	if applied != 1 || duplicates != 7 {
		t.Fatalf("applied=%d duplicates=%d, want 1/7", applied, duplicates)
	}
	var total, revocationEpoch string
	var auditCount int
	if err := store.pool.QueryRow(ctx, "SELECT (u.ingress_bytes+u.egress_bytes)::text,d.revocation_epoch::text,(SELECT count(*) FROM authority_audit_events WHERE event_type='relay_quota_exceeded' AND device_id='client') FROM authority_relay_daily_usage u JOIN authority_devices d ON d.device_id=u.device_id WHERE u.device_id='client'").Scan(&total, &revocationEpoch, &auditCount); err != nil {
		t.Fatal(err)
	}
	if total != "101" || revocationEpoch != "1" || auditCount != 1 {
		t.Fatalf("total=%s revocationEpoch=%s auditCount=%d, want 101/1/1", total, revocationEpoch, auditCount)
	}
}

func TestPostgresReadinessRejectsDatabaseClockSkewInEitherDirection(t *testing.T) {
	store, _ := openIntegrationStore(t)
	originalNow := store.now
	t.Cleanup(func() { store.now = originalNow })
	offset := 2 * store.maximumDatabaseClockSkew

	for _, test := range []struct {
		name   string
		offset time.Duration
	}{
		{name: "database ahead", offset: -offset},
		{name: "database behind", offset: offset},
	} {
		t.Run(test.name, func(t *testing.T) {
			store.now = func() time.Time { return originalNow().Add(test.offset) }
			if err := store.Ready(context.Background()); !errors.Is(err, ErrStorage) {
				t.Fatalf("readiness clock skew error=%v, want ErrStorage", err)
			}
		})
	}

	store.now = originalNow
	if err := store.Ready(context.Background()); err != nil {
		t.Fatalf("readiness did not recover after restoring host clock: %v", err)
	}
}

func TestPostgresReadinessFailsClosedWhenClockProbeIsCanceled(t *testing.T) {
	store, _ := openIntegrationStore(t)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := store.Ready(ctx); !errors.Is(err, ErrStorage) {
		t.Fatalf("canceled readiness clock probe error=%v, want ErrStorage", err)
	}
}

func TestPostgresRegisterDeviceMissingAccountReturnsNotFound(t *testing.T) {
	store, _ := openIntegrationStore(t)
	ctx := context.Background()
	if err := store.RegisterDevice(ctx, "missing-account", "device"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("register device for missing account error=%v, want ErrNotFound", err)
	}
}

func TestPostgresDailyUsageExceedsInt64WithoutLosingPrecision(t *testing.T) {
	store, _ := openIntegrationStore(t)
	store.allocationLimit = 4
	store.dailyLimit = uint64(math.MaxInt64) + 1
	ctx := context.Background()
	now := time.Now().UTC()
	if err := store.EnsureAccount(ctx, "account"); err != nil {
		t.Fatal(err)
	}
	for _, deviceID := range []string{"host", "client"} {
		if err := store.RegisterDevice(ctx, "account", deviceID); err != nil {
			t.Fatal(err)
		}
	}
	session, err := store.CreateSignaling(ctx, SignalingRequest{RequestID: "request", AccountID: "account", HostDeviceID: "host", ClientDeviceID: "client", SessionEpoch: 1, TTLSeconds: 60}, now)
	if err != nil {
		t.Fatal(err)
	}
	for _, allocationID := range []string{"allocation-max", "allocation-one"} {
		if err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: allocationID, SourceID: "node"}, now); err != nil {
			t.Fatal(err)
		}
	}
	usage := []CoturnUsage{
		{SourceID: "node", EventID: "event-max", AllocationID: "allocation-max", DeviceID: "client", SessionID: session.SessionID, Sequence: 1, IngressBytes: math.MaxInt64, ObservedAt: now},
		{SourceID: "node", EventID: "event-one", AllocationID: "allocation-one", DeviceID: "client", SessionID: session.SessionID, Sequence: 1, IngressBytes: 1, ObservedAt: now},
	}
	for _, update := range usage {
		if _, err := store.ApplyCoturnUsage(ctx, update); err != nil {
			t.Fatal(err)
		}
	}
	var total string
	if err := store.pool.QueryRow(ctx, "SELECT (ingress_bytes+egress_bytes)::text FROM authority_relay_daily_usage WHERE device_id=$1 AND usage_day=(CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date", "client").Scan(&total); err != nil {
		t.Fatal(err)
	}
	want := strconv.FormatUint(uint64(math.MaxInt64)+1, 10)
	if total != want {
		t.Fatalf("daily usage=%s, want exact %s", total, want)
	}
	if err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: "allocation-blocked", SourceID: "node"}, now); !errors.Is(err, ErrQuotaExceeded) {
		t.Fatalf("admission after exact quota error=%v, want ErrQuotaExceeded", err)
	}
}
