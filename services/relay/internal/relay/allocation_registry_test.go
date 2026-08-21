package relay

import (
	"os"
	"path/filepath"
	"testing"
)

func TestAllocationRegistryUpsertCreatesAndReusesIdentity(t *testing.T) {
	path := filepath.Join(t.TempDir(), "allocations.json")
	entry := allocationRegistryEntry{
		AllocationID: "allocation-1",
		DeviceID:     "device-1",
		SessionID:    "session-1",
		Username:     "1800000000:device-1",
	}
	if err := upsertAllocationRegistryEntry(path, entry, "turn-prod-1"); err != nil {
		t.Fatal(err)
	}
	if err := upsertAllocationRegistryEntry(path, entry, "turn-prod-1"); err != nil {
		t.Fatal(err)
	}
	registry, err := readAllocationRegistry(path, "turn-prod-1")
	if err != nil {
		t.Fatal(err)
	}
	if registry.SourceID != "turn-prod-1" || len(registry.Allocations) != 1 || registry.Allocations[0] != entry {
		t.Fatalf("registry = %#v", registry)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("registry path was not materialized: %v", err)
	}
	if got := info.Mode().Perm(); got != 0o644 {
		t.Fatalf("registry mode = %o, want 0644 for shared reconciler reads", got)
	}
}

func TestAllocationRegistryRejectsConflictingIdentity(t *testing.T) {
	path := filepath.Join(t.TempDir(), "allocations.json")
	entry := allocationRegistryEntry{
		AllocationID: "allocation-1",
		DeviceID:     "device-1",
		SessionID:    "session-1",
		Username:     "1800000000:device-1",
	}
	if err := upsertAllocationRegistryEntry(path, entry, "turn-prod-1"); err != nil {
		t.Fatal(err)
	}
	entry.SessionID = "session-2"
	if err := upsertAllocationRegistryEntry(path, entry, "turn-prod-1"); err == nil {
		t.Fatal("expected conflicting identity rejection")
	}
}

func TestAllocationRegistryRejectsAmbiguousTURNRESTUsername(t *testing.T) {
	path := filepath.Join(t.TempDir(), "allocations.json")
	entry := allocationRegistryEntry{
		AllocationID: "allocation-1",
		DeviceID:     "device-1",
		SessionID:    "session-1",
		Username:     "1800000000:device-1",
	}
	if err := upsertAllocationRegistryEntry(path, entry, "turn-prod-1"); err != nil {
		t.Fatal(err)
	}
	entry.AllocationID = "allocation-2"
	entry.SessionID = "session-2"
	if err := upsertAllocationRegistryEntry(path, entry, "turn-prod-1"); err == nil {
		t.Fatal("expected ambiguous TURN REST username rejection")
	}
}

func TestAllocationRegistryRejectsCorruptDuplicateEntries(t *testing.T) {
	path := filepath.Join(t.TempDir(), "allocations.json")
	contents := []byte(`{
  "source_id": "turn-prod-1",
  "allocations": [
    {"allocation_id":"allocation-1","device_id":"device-1","session_id":"session-1","username":"1800000000:device-1"},
    {"allocation_id":"allocation-2","device_id":"device-1","session_id":"session-2","username":"1800000000:device-1"}
  ]
}`)
	if err := os.WriteFile(path, contents, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := readAllocationRegistry(path, "turn-prod-1"); err == nil {
		t.Fatal("expected duplicate TURN REST username rejection")
	}
}

func TestAllocationRegistryRejectsWrongSource(t *testing.T) {
	path := filepath.Join(t.TempDir(), "allocations.json")
	entry := allocationRegistryEntry{
		AllocationID: "allocation-1",
		DeviceID:     "device-1",
		SessionID:    "session-1",
		Username:     "1800000000:device-1",
	}
	if err := upsertAllocationRegistryEntry(path, entry, "turn-prod-1"); err != nil {
		t.Fatal(err)
	}
	if _, err := readAllocationRegistry(path, "turn-prod-2"); err == nil {
		t.Fatal("expected source mismatch rejection")
	}
}

func TestAllocationRegistryRejectsUsernameForDifferentDevice(t *testing.T) {
	path := filepath.Join(t.TempDir(), "allocations.json")
	entry := allocationRegistryEntry{
		AllocationID: "allocation-1",
		DeviceID:     "device-1",
		SessionID:    "session-1",
		Username:     "1800000000:device-2",
	}
	if err := upsertAllocationRegistryEntry(path, entry, "turn-prod-1"); err == nil {
		t.Fatal("expected username/device mismatch rejection")
	}
}
