package relay

import (
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
	if err := store.Apply(now, start); err != nil {
		t.Fatal(err)
	}
	tooLarge := UsageEvent{EventID: "two", DeviceID: "device", SessionID: "session", Kind: "update", EgressBytes: 41}
	if err := store.Apply(now, tooLarge); !errors.Is(err, ErrQuotaExceeded) {
		t.Fatalf("error = %v", err)
	}
	_, egress, sessions := store.Snapshot(now, "device")
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
	if err := store.Apply(dayOne, UsageEvent{EventID: "one", DeviceID: "device", SessionID: "session", Kind: "start", EgressBytes: 100}); err != nil {
		t.Fatal(err)
	}
	dayTwo := dayOne.Add(24 * time.Hour)
	if err := store.Apply(dayTwo, UsageEvent{EventID: "two", DeviceID: "device", SessionID: "session", Kind: "update", EgressBytes: 10}); err != nil {
		t.Fatal(err)
	}
	_, egress, sessions := store.Snapshot(dayTwo, "device")
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
	if err := store.Apply(now, UsageEvent{EventID: "start-before-revoke", DeviceID: "device", SessionID: "session", Kind: "start", EgressBytes: 10}); err != nil {
		t.Fatal(err)
	}
	if _, _, err := store.Revoke("device", now); err != nil {
		t.Fatal(err)
	}
	accepted := UsageEvent{EventID: "start-before-revoke", DeviceID: "device", SessionID: "session", Kind: "start", EgressBytes: 10}
	if err := store.Apply(now, accepted); !errors.Is(err, ErrDuplicateEvent) {
		t.Fatalf("accepted event retry error = %v", err)
	}

	for _, event := range []UsageEvent{
		{EventID: "start-after-revoke", DeviceID: "device", SessionID: "new-session", Kind: "start", EgressBytes: 1},
		{EventID: "update-after-revoke", DeviceID: "device", SessionID: "session", Kind: "update", EgressBytes: 1},
		{EventID: "end-after-revoke", DeviceID: "device", SessionID: "session", Kind: "end"},
	} {
		if err := store.Apply(now, event); !errors.Is(err, ErrDeviceRevoked) {
			t.Fatalf("%s error = %v", event.Kind, err)
		}
	}
	if err := store.Apply(now.Add(24*time.Hour), accepted); !errors.Is(err, ErrDeviceRevoked) {
		t.Fatalf("prior-day event retry error = %v", err)
	}

	_, egress, sessions := store.Snapshot(now, "device")
	if egress != 10 || sessions != 1 {
		t.Fatalf("state mutated after revoked usage: %d/%d", egress, sessions)
	}
}
