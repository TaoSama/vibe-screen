package relay

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"
)

func TestStoreRejectsQuotaWithoutMutatingState(t *testing.T) {
	store, err := NewUsageStore(filepath.Join(t.TempDir(), "state.json"), 100, 1)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 8, 4, 0, 0, 0, 0, time.UTC)
	start := UsageEvent{EventID: "one", DeviceID: "device", SessionID: "session", Kind: "start", EgressBytes: 60}
	ctx := context.Background()
	if err := store.Apply(ctx, now, start); err != nil {
		t.Fatal(err)
	}
	tooLarge := UsageEvent{EventID: "two", DeviceID: "device", SessionID: "session", Kind: "update", EgressBytes: 41}
	if err := store.Apply(ctx, now, tooLarge); !errors.Is(err, ErrQuotaExceeded) {
		t.Fatalf("error = %v", err)
	}
	_, egress, sessions, err := store.Snapshot(ctx, now, "device")
	if err != nil {
		t.Fatal(err)
	}
	if egress != 60 || sessions != 1 {
		t.Fatalf("state mutated after rejection: %d/%d", egress, sessions)
	}
}

func TestStoreResetsDailyUsage(t *testing.T) {
	store, err := NewUsageStore(filepath.Join(t.TempDir(), "state.json"), 100, 1)
	if err != nil {
		t.Fatal(err)
	}
	dayOne := time.Date(2026, 8, 4, 0, 0, 0, 0, time.UTC)
	ctx := context.Background()
	if err := store.Apply(ctx, dayOne, UsageEvent{EventID: "one", DeviceID: "device", SessionID: "session", Kind: "start", EgressBytes: 100}); err != nil {
		t.Fatal(err)
	}
	dayTwo := dayOne.Add(24 * time.Hour)
	if err := store.Apply(ctx, dayTwo, UsageEvent{EventID: "two", DeviceID: "device", SessionID: "session", Kind: "update", EgressBytes: 10}); err != nil {
		t.Fatal(err)
	}
	_, egress, sessions, err := store.Snapshot(ctx, dayTwo, "device")
	if err != nil {
		t.Fatal(err)
	}
	if egress != 10 || sessions != 1 {
		t.Fatalf("day two = %d/%d", egress, sessions)
	}
}

func TestStoreRejectsUsageAfterRevocationWithoutMutatingState(t *testing.T) {
	store, err := NewUsageStore(filepath.Join(t.TempDir(), "state.json"), 100, 2)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 8, 4, 0, 0, 0, 0, time.UTC)
	ctx := context.Background()
	if err := store.Apply(ctx, now, UsageEvent{EventID: "start-before-revoke", DeviceID: "device", SessionID: "session", Kind: "start", EgressBytes: 10}); err != nil {
		t.Fatal(err)
	}
	if err := store.Revoke(ctx, "device", now); err != nil {
		t.Fatal(err)
	}
	accepted := UsageEvent{EventID: "start-before-revoke", DeviceID: "device", SessionID: "session", Kind: "start", EgressBytes: 10}
	if err := store.Apply(ctx, now, accepted); !errors.Is(err, ErrDuplicateEvent) {
		t.Fatalf("accepted event retry error = %v", err)
	}

	for _, event := range []UsageEvent{
		{EventID: "start-after-revoke", DeviceID: "device", SessionID: "new-session", Kind: "start", EgressBytes: 1},
		{EventID: "update-after-revoke", DeviceID: "device", SessionID: "session", Kind: "update", EgressBytes: 1},
		{EventID: "end-after-revoke", DeviceID: "device", SessionID: "session", Kind: "end"},
	} {
		if err := store.Apply(ctx, now, event); !errors.Is(err, ErrDeviceRevoked) {
			t.Fatalf("%s error = %v", event.Kind, err)
		}
	}
	if err := store.Apply(ctx, now.Add(24*time.Hour), accepted); !errors.Is(err, ErrDeviceRevoked) {
		t.Fatalf("prior-day event retry error = %v", err)
	}

	_, egress, sessions, err := store.Snapshot(ctx, now, "device")
	if err != nil {
		t.Fatal(err)
	}
	if egress != 10 || sessions != 1 {
		t.Fatalf("state mutated after revoked usage: %d/%d", egress, sessions)
	}
}
