package authority

import (
	"context"
	"errors"
	"math"
	"os"
	"path/filepath"
	"slices"
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
	store.allocationLimit = 3
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
	if err := store.InvalidateSignaling(ctx, session.SessionID, now); err != nil {
		t.Fatal(err)
	}
	if err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: "revoked", SourceID: "node"}, now); !errors.Is(err, ErrRevoked) {
		t.Fatalf("revoked relay session error=%v", err)
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
