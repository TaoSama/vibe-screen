package relay

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestAllocationRegistryUpsertCreatesAndReusesIdentity(t *testing.T) {
	path := filepath.Join(t.TempDir(), "allocations.json")
	entry := allocationRegistryEntry{
		AllocationID: "allocation-1",
		DeviceID:     "device-1",
		SessionID:    "session-1",
		Username:     "4102444800:device-1",
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
	if got := info.Mode().Perm(); got != 0o640 {
		t.Fatalf("registry mode = %o, want 0640", got)
	}
}

func TestAllocationRegistryAllowsSharedTURNRESTUsernameForSameSecondCredentials(t *testing.T) {
	path := filepath.Join(t.TempDir(), "allocations.json")
	first := allocationRegistryEntry{AllocationID: "allocation-1", DeviceID: "device-1", SessionID: "session-1", Username: "4102444800:device-1"}
	second := allocationRegistryEntry{AllocationID: "allocation-2", DeviceID: "device-1", SessionID: "session-2", Username: "4102444800:device-1"}
	if err := upsertAllocationRegistryEntry(path, first, "turn-prod-1"); err != nil {
		t.Fatal(err)
	}
	if err := upsertAllocationRegistryEntry(path, second, "turn-prod-1"); err != nil {
		t.Fatal(err)
	}
	registry, err := readAllocationRegistry(path, "turn-prod-1")
	if err != nil {
		t.Fatal(err)
	}
	if len(registry.Allocations) != 2 {
		t.Fatalf("registry allocations = %#v", registry.Allocations)
	}
}

func TestAllocationRegistryRejectsConflictingIdentity(t *testing.T) {
	path := filepath.Join(t.TempDir(), "allocations.json")
	entry := allocationRegistryEntry{
		AllocationID: "allocation-1",
		DeviceID:     "device-1",
		SessionID:    "session-1",
		Username:     "4102444800:device-1",
	}
	if err := upsertAllocationRegistryEntry(path, entry, "turn-prod-1"); err != nil {
		t.Fatal(err)
	}
	entry.SessionID = "session-2"
	if err := upsertAllocationRegistryEntry(path, entry, "turn-prod-1"); err == nil {
		t.Fatal("expected conflicting identity rejection")
	}
}

func TestAllocationRegistryRefreshesTURNRESTUsernameForSameAllocation(t *testing.T) {
	path := filepath.Join(t.TempDir(), "allocations.json")
	first := allocationRegistryEntry{
		AllocationID:    "allocation-1",
		DeviceID:        "device-1",
		SessionID:       "session-1",
		Username:        "4102444800:device-1",
		CoturnSessionID: "coturn-old",
	}
	second := allocationRegistryEntry{
		AllocationID: "allocation-1",
		DeviceID:     "device-1",
		SessionID:    "session-1",
		Username:     "4102444860:device-1",
	}
	if err := upsertAllocationRegistryEntry(path, first, "turn-prod-1"); err != nil {
		t.Fatal(err)
	}
	if err := upsertAllocationRegistryEntry(path, second, "turn-prod-1"); err != nil {
		t.Fatal(err)
	}
	registry, err := readAllocationRegistry(path, "turn-prod-1")
	if err != nil {
		t.Fatal(err)
	}
	if len(registry.Allocations) != 1 {
		t.Fatalf("registry allocations = %#v", registry.Allocations)
	}
	if got := registry.Allocations[0]; got.Username != second.Username || got.CoturnSessionID != "" {
		t.Fatalf("registry did not refresh username: %#v", got)
	}
}

func TestAllocationRegistryPreservesBindingForSameTURNRESTUsernameRetry(t *testing.T) {
	path := filepath.Join(t.TempDir(), "allocations.json")
	first := allocationRegistryEntry{
		AllocationID:    "allocation-1",
		DeviceID:        "device-1",
		SessionID:       "session-1",
		Username:        "4102444800:device-1",
		CoturnSessionID: "coturn-bound",
	}
	second := first
	second.CoturnSessionID = ""
	if err := upsertAllocationRegistryEntry(path, first, "turn-prod-1"); err != nil {
		t.Fatal(err)
	}
	if err := upsertAllocationRegistryEntry(path, second, "turn-prod-1"); err != nil {
		t.Fatal(err)
	}
	registry, err := readAllocationRegistry(path, "turn-prod-1")
	if err != nil {
		t.Fatal(err)
	}
	if got := registry.Allocations[0]; got.CoturnSessionID != first.CoturnSessionID {
		t.Fatalf("registry lost same-username binding: %#v", got)
	}
}

func TestAllocationRegistryPrunesExpiredEntries(t *testing.T) {
	now := time.Date(2026, 8, 25, 12, 0, 0, 0, time.UTC)
	entries := []allocationRegistryEntry{
		{AllocationID: "expired", DeviceID: "device-1", SessionID: "session-1", Username: "1700000000:device-1"},
		{AllocationID: "active", DeviceID: "device-2", SessionID: "session-2", Username: "4102444800:device-2"},
	}
	retained := pruneExpiredAllocationRegistryEntries(entries, now)
	if len(retained) != 1 || retained[0].AllocationID != "active" {
		t.Fatalf("retained entries = %#v", retained)
	}
}

func TestAllocationRegistryRemoveCompletedAllocation(t *testing.T) {
	path := filepath.Join(t.TempDir(), "allocations.json")
	for _, entry := range []allocationRegistryEntry{
		{AllocationID: "allocation-1", DeviceID: "device-1", SessionID: "session-1", Username: "4102444800:device-1"},
		{AllocationID: "allocation-2", DeviceID: "device-2", SessionID: "session-2", Username: "4102444800:device-2"},
	} {
		if err := upsertAllocationRegistryEntry(path, entry, "turn-prod-1"); err != nil {
			t.Fatal(err)
		}
	}
	if err := removeAllocationRegistryEntry(path, "allocation-1", "turn-prod-1"); err != nil {
		t.Fatal(err)
	}
	registry, err := readAllocationRegistry(path, "turn-prod-1")
	if err != nil {
		t.Fatal(err)
	}
	if len(registry.Allocations) != 1 || registry.Allocations[0].AllocationID != "allocation-2" {
		t.Fatalf("registry allocations = %#v", registry.Allocations)
	}
}

func TestAllocationRegistryRejectsCorruptDuplicateEntries(t *testing.T) {
	path := filepath.Join(t.TempDir(), "allocations.json")
	contents := []byte(`{
  "source_id": "turn-prod-1",
  "allocations": [
    {"allocation_id":"allocation-1","device_id":"device-1","session_id":"session-1","username":"1800000000:device-1"},
    {"allocation_id":"allocation-1","device_id":"device-1","session_id":"session-1","username":"1800000000:device-1"}
  ]
}`)
	if err := os.WriteFile(path, contents, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := readAllocationRegistry(path, "turn-prod-1"); err == nil {
		t.Fatal("expected duplicate allocation rejection")
	}
}

func TestAllocationRegistryRejectsWrongSource(t *testing.T) {
	path := filepath.Join(t.TempDir(), "allocations.json")
	entry := allocationRegistryEntry{
		AllocationID: "allocation-1",
		DeviceID:     "device-1",
		SessionID:    "session-1",
		Username:     "4102444800:device-1",
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
		Username:     "4102444800:device-2",
	}
	if err := upsertAllocationRegistryEntry(path, entry, "turn-prod-1"); err == nil {
		t.Fatal("expected username/device mismatch rejection")
	}
}
