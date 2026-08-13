package authority

import (
	"context"
	"errors"
	"os"
	"path/filepath"
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
