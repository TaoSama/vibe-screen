package relay

import (
	"context"
	"errors"
	"math"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func openRelayIntegrationStore(t *testing.T) (*PostgresStore, Config) {
	t.Helper()
	databaseURL := os.Getenv("VIBE_RELAY_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("VIBE_RELAY_TEST_DATABASE_URL is not set")
	}
	migration, err := os.ReadFile(filepath.Join("..", "..", "migrations", "001_relay.sql"))
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
	cfg := testConfig(t)
	cfg.StorageBackend = storageBackendPostgres
	cfg.StateFile = ""
	cfg.DatabaseURL = databaseURL
	cfg.MaximumDatabaseClockSkewSeconds = defaultMaximumDatabaseClockSkewSeconds
	store, err := OpenPostgres(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.pool.Exec(ctx, "TRUNCATE relay_usage_events,relay_active_sessions,relay_daily_usage,relay_devices RESTART IDENTITY CASCADE"); err != nil {
		store.Close()
		t.Fatal(err)
	}
	t.Cleanup(store.Close)
	return store, cfg
}

func TestPostgresStoreMatchesFileStoreContracts(t *testing.T) {
	store, cfg := openRelayIntegrationStore(t)
	store.sessionLimit = 2
	ctx := context.Background()
	now := time.Date(2026, 8, 19, 10, 0, 0, 0, time.UTC)
	start := UsageEvent{EventID: "event-1", DeviceID: "device", SessionID: "session-1", Kind: "start", IngressBytes: 10, EgressBytes: 20}
	if err := store.Apply(ctx, now, start); err != nil {
		t.Fatal(err)
	}
	if err := store.Apply(ctx, now, start); !errors.Is(err, ErrDuplicateEvent) {
		t.Fatalf("duplicate error=%v", err)
	}
	changed := start
	changed.EgressBytes = 21
	if err := store.Apply(ctx, now, changed); !errors.Is(err, ErrInvalidEvent) {
		t.Fatalf("changed duplicate error=%v", err)
	}
	if err := store.Apply(ctx, now, UsageEvent{EventID: "event-2", DeviceID: "device", SessionID: "session-1", Kind: "update", EgressBytes: cfg.DailyBytesPerDevice}); !errors.Is(err, ErrQuotaExceeded) {
		t.Fatalf("quota error=%v", err)
	}
	if err := store.Apply(ctx, now, UsageEvent{EventID: "event-unknown", DeviceID: "device", SessionID: "missing", Kind: "update"}); !errors.Is(err, ErrUnknownSession) {
		t.Fatalf("unknown session error=%v", err)
	}
	if err := store.Apply(ctx, now, UsageEvent{EventID: "event-duplicate-start", DeviceID: "device", SessionID: "session-1", Kind: "start"}); !errors.Is(err, ErrSessionExists) {
		t.Fatalf("duplicate start error=%v", err)
	}
	ingress, egress, sessions, err := store.Snapshot(ctx, now, "device")
	if err != nil {
		t.Fatal(err)
	}
	if ingress != 10 || egress != 20 || sessions != 1 {
		t.Fatalf("snapshot=%d/%d/%d", ingress, egress, sessions)
	}
	dayTwo := now.Add(24 * time.Hour)
	if err := store.Apply(ctx, dayTwo, UsageEvent{EventID: "event-3", DeviceID: "device", SessionID: "session-1", Kind: "update", EgressBytes: 7}); err != nil {
		t.Fatal(err)
	}
	if err := store.Apply(ctx, dayTwo, UsageEvent{EventID: "event-end", DeviceID: "device", SessionID: "session-1", Kind: "end"}); err != nil {
		t.Fatal(err)
	}
	_, egress, sessions, err = store.Snapshot(ctx, dayTwo, "device")
	if err != nil {
		t.Fatal(err)
	}
	if egress != 7 || sessions != 0 {
		t.Fatalf("day two snapshot=%d/%d", egress, sessions)
	}
	if err := store.Revoke(ctx, "device", dayTwo); err != nil {
		t.Fatal(err)
	}
	if err := store.Apply(ctx, dayTwo, UsageEvent{EventID: "event-4", DeviceID: "device", SessionID: "session-2", Kind: "start"}); !errors.Is(err, ErrDeviceRevoked) {
		t.Fatalf("revoked start error=%v", err)
	}
	restarted, err := OpenPostgres(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer restarted.Close()
	revoked, err := restarted.IsRevoked(ctx, "device")
	if err != nil {
		t.Fatal(err)
	}
	if !revoked {
		t.Fatal("revocation did not persist")
	}
}

func TestPostgresQuotaRejectionRollsBackEventAndUsage(t *testing.T) {
	store, _ := openRelayIntegrationStore(t)
	ctx := context.Background()
	now := time.Date(2026, 8, 19, 10, 0, 0, 0, time.UTC)
	if err := store.Apply(ctx, now, UsageEvent{EventID: "event-start", DeviceID: "device", SessionID: "session", Kind: "start", EgressBytes: 60}); err != nil {
		t.Fatal(err)
	}
	tooLarge := UsageEvent{EventID: "event-too-large", DeviceID: "device", SessionID: "session", Kind: "update", EgressBytes: 941}
	if err := store.Apply(ctx, now, tooLarge); !errors.Is(err, ErrQuotaExceeded) {
		t.Fatalf("quota error=%v", err)
	}
	_, egress, sessions, err := store.Snapshot(ctx, now, "device")
	if err != nil {
		t.Fatal(err)
	}
	if egress != 60 || sessions != 1 {
		t.Fatalf("state mutated after quota rejection: %d/%d", egress, sessions)
	}
	tooLarge.EgressBytes = 1
	if err := store.Apply(ctx, now, tooLarge); err != nil {
		t.Fatalf("event id was recorded before rejected transaction rolled back: %v", err)
	}
}

func TestPostgresDailyQuotaIsAtomicAcrossConcurrentUpdates(t *testing.T) {
	store, _ := openRelayIntegrationStore(t)
	ctx := context.Background()
	now := time.Date(2026, 8, 19, 10, 0, 0, 0, time.UTC)
	if err := store.Apply(ctx, now, UsageEvent{EventID: "event-start", DeviceID: "device", SessionID: "session", Kind: "start", EgressBytes: 900}); err != nil {
		t.Fatal(err)
	}
	start := make(chan struct{})
	var accepted atomic.Int32
	var wait sync.WaitGroup
	for _, eventID := range []string{"event-update-1", "event-update-2"} {
		wait.Add(1)
		go func(eventID string) {
			defer wait.Done()
			<-start
			err := store.Apply(ctx, now, UsageEvent{EventID: eventID, DeviceID: "device", SessionID: "session", Kind: "update", EgressBytes: 100})
			if err == nil {
				accepted.Add(1)
			} else if !errors.Is(err, ErrQuotaExceeded) {
				t.Errorf("unexpected update error: %v", err)
			}
		}(eventID)
	}
	close(start)
	wait.Wait()
	if accepted.Load() != 1 {
		t.Fatalf("accepted %d updates, want one", accepted.Load())
	}
	_, egress, _, err := store.Snapshot(ctx, now, "device")
	if err != nil {
		t.Fatal(err)
	}
	if egress != 1000 {
		t.Fatalf("egress=%d, want exact quota", egress)
	}
}

func TestPostgresSessionLimitIsAtomicAcrossConcurrentStarts(t *testing.T) {
	store, _ := openRelayIntegrationStore(t)
	ctx := context.Background()
	now := time.Date(2026, 8, 19, 10, 0, 0, 0, time.UTC)
	start := make(chan struct{})
	var accepted atomic.Int32
	var wait sync.WaitGroup
	for _, sessionID := range []string{"session-1", "session-2"} {
		wait.Add(1)
		go func(sessionID string) {
			defer wait.Done()
			<-start
			err := store.Apply(ctx, now, UsageEvent{EventID: "event-" + sessionID, DeviceID: "device", SessionID: sessionID, Kind: "start"})
			if err == nil {
				accepted.Add(1)
			} else if !errors.Is(err, ErrSessionLimit) {
				t.Errorf("unexpected start error: %v", err)
			}
		}(sessionID)
	}
	close(start)
	wait.Wait()
	if accepted.Load() != 1 {
		t.Fatalf("accepted %d sessions, want one", accepted.Load())
	}
}

func TestPostgresReadinessRejectsSchemaAndClockDrift(t *testing.T) {
	store, _ := openRelayIntegrationStore(t)
	ctx := context.Background()
	if _, err := store.pool.Exec(ctx, "UPDATE relay_schema_migrations SET checksum_sha256='wrong' WHERE version=$1", requiredSchemaVersion); err != nil {
		t.Fatal(err)
	}
	if err := store.Ready(ctx); !errors.Is(err, ErrStorage) {
		t.Fatalf("checksum readiness error=%v", err)
	}
	if _, err := store.pool.Exec(ctx, "UPDATE relay_schema_migrations SET checksum_sha256=$1 WHERE version=$2", requiredSchemaChecksum, requiredSchemaVersion); err != nil {
		t.Fatal(err)
	}
	originalNow := store.now
	store.now = func() time.Time { return originalNow().Add(2 * store.maximumDatabaseClockSkew) }
	if err := store.Ready(ctx); !errors.Is(err, ErrStorage) {
		t.Fatalf("clock readiness error=%v", err)
	}
	store.now = originalNow
	if err := store.Ready(ctx); err != nil {
		t.Fatalf("readiness did not recover: %v", err)
	}
}

func TestPostgresDailyUsageExceedsInt64WithoutLosingPrecision(t *testing.T) {
	store, _ := openRelayIntegrationStore(t)
	store.dailyLimit = uint64(math.MaxInt64) + 1
	store.sessionLimit = 2
	ctx := context.Background()
	now := time.Date(2026, 8, 19, 10, 0, 0, 0, time.UTC)
	if err := store.Apply(ctx, now, UsageEvent{EventID: "event-max", DeviceID: "device", SessionID: "session-1", Kind: "start", IngressBytes: math.MaxInt64}); err != nil {
		t.Fatal(err)
	}
	if err := store.Apply(ctx, now, UsageEvent{EventID: "event-one", DeviceID: "device", SessionID: "session-2", Kind: "start", IngressBytes: 1}); err != nil {
		t.Fatal(err)
	}
	var total string
	if err := store.pool.QueryRow(ctx, "SELECT (ingress_bytes+egress_bytes)::text FROM relay_daily_usage WHERE device_id=$1 AND usage_day=$2", "device", now.UTC().Format(time.DateOnly)).Scan(&total); err != nil {
		t.Fatal(err)
	}
	want := strconv.FormatUint(uint64(math.MaxInt64)+1, 10)
	if total != want {
		t.Fatalf("daily usage=%s, want exact %s", total, want)
	}
	if err := store.Apply(ctx, now, UsageEvent{EventID: "event-blocked", DeviceID: "device", SessionID: "session-1", Kind: "update", IngressBytes: 1}); !errors.Is(err, ErrQuotaExceeded) {
		t.Fatalf("quota after exact limit error=%v", err)
	}
}
