package relay

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

type allocationRegistry struct {
	SourceID    string                    `json:"source_id"`
	Allocations []allocationRegistryEntry `json:"allocations"`
}

type allocationRegistryEntry struct {
	AllocationID    string `json:"allocation_id"`
	DeviceID        string `json:"device_id"`
	SessionID       string `json:"session_id"`
	Username        string `json:"username"`
	CoturnSessionID string `json:"coturn_session_id,omitempty"`
}

func upsertAllocationRegistryEntry(path string, entry allocationRegistryEntry, sourceID string) error {
	if path == "" {
		return errors.New("allocation registry path is required")
	}
	if !validAllocationRegistryEntry(entry, sourceID) {
		return errors.New("allocation registry entry contains invalid identifiers")
	}
	registry, err := readAllocationRegistry(path, sourceID)
	if err != nil {
		return err
	}
	found := false
	for index := range registry.Allocations {
		current := registry.Allocations[index]
		if current.AllocationID != entry.AllocationID {
			continue
		}
		if current.DeviceID != entry.DeviceID || current.SessionID != entry.SessionID || current.Username != entry.Username {
			return errors.New("allocation registry contains conflicting allocation identity")
		}
		found = true
		break
	}
	if !found {
		registry.Allocations = append(registry.Allocations, entry)
	}
	return writeAllocationRegistry(path, registry)
}

func readAllocationRegistry(path string, sourceID string) (allocationRegistry, error) {
	contents, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return allocationRegistry{SourceID: sourceID, Allocations: []allocationRegistryEntry{}}, nil
	}
	if err != nil {
		return allocationRegistry{}, fmt.Errorf("read allocation registry: %w", err)
	}
	var registry allocationRegistry
	decoder := json.NewDecoder(bytes.NewReader(contents))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&registry); err != nil {
		return allocationRegistry{}, fmt.Errorf("decode allocation registry: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); err == nil {
		return allocationRegistry{}, errors.New("decode allocation registry: trailing content")
	} else if !errors.Is(err, io.EOF) {
		return allocationRegistry{}, fmt.Errorf("decode allocation registry: %w", err)
	}
	if registry.SourceID != sourceID {
		return allocationRegistry{}, errors.New("allocation registry source_id mismatch")
	}
	seenAllocations := make(map[string]struct{}, len(registry.Allocations))
	seenCoturnSessions := make(map[string]struct{}, len(registry.Allocations))
	for index, entry := range registry.Allocations {
		if !validAllocationRegistryEntry(entry, sourceID) {
			return allocationRegistry{}, fmt.Errorf("allocation registry entry %d is invalid", index)
		}
		if _, exists := seenAllocations[entry.AllocationID]; exists {
			return allocationRegistry{}, fmt.Errorf("allocation registry entry %d repeats allocation_id", index)
		}
		seenAllocations[entry.AllocationID] = struct{}{}
		if entry.CoturnSessionID == "" {
			continue
		}
		if _, exists := seenCoturnSessions[entry.CoturnSessionID]; exists {
			return allocationRegistry{}, fmt.Errorf("allocation registry entry %d repeats coturn_session_id", index)
		}
		seenCoturnSessions[entry.CoturnSessionID] = struct{}{}
	}
	return registry, nil
}

func checkAllocationRegistryReady(path string, sourceID string) error {
	if path == "" {
		return errors.New("allocation registry path is required")
	}
	if !validIdentifier(sourceID) {
		return errors.New("allocation registry source id is invalid")
	}
	if _, err := readAllocationRegistry(path, sourceID); err != nil {
		return err
	}
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o750); err != nil {
		return fmt.Errorf("create allocation registry directory: %w", err)
	}
	temp, err := os.CreateTemp(dir, filepath.Base(path)+".ready.*.tmp")
	if err != nil {
		return fmt.Errorf("create allocation registry readiness temp file: %w", err)
	}
	tempName := temp.Name()
	defer os.Remove(tempName)
	if _, err := temp.WriteString("{}\n"); err != nil {
		temp.Close()
		return fmt.Errorf("write allocation registry readiness temp file: %w", err)
	}
	if err := temp.Close(); err != nil {
		return fmt.Errorf("close allocation registry readiness temp file: %w", err)
	}
	return nil
}

func validAllocationRegistryEntry(entry allocationRegistryEntry, sourceID string) bool {
	if !validIdentifier(sourceID) || !validIdentifier(entry.AllocationID) || !validIdentifier(entry.DeviceID) || !validIdentifier(entry.SessionID) || !validTurnRESTUsername(entry.Username, entry.DeviceID) {
		return false
	}
	return entry.CoturnSessionID == "" || validIdentifier(entry.CoturnSessionID)
}

func validTurnRESTUsername(username string, deviceID string) bool {
	expiryRaw, principal, ok := strings.Cut(username, ":")
	if !ok || principal != deviceID || !validIdentifier(principal) {
		return false
	}
	expiry, err := strconv.ParseInt(expiryRaw, 10, 64)
	return err == nil && expiry > 0
}

func writeAllocationRegistry(path string, registry allocationRegistry) error {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o750); err != nil {
		return fmt.Errorf("create allocation registry directory: %w", err)
	}
	temp, err := os.CreateTemp(dir, filepath.Base(path)+".*.tmp")
	if err != nil {
		return fmt.Errorf("create allocation registry temp file: %w", err)
	}
	tempName := temp.Name()
	defer os.Remove(tempName)
	encoder := json.NewEncoder(temp)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(registry); err != nil {
		temp.Close()
		return fmt.Errorf("encode allocation registry: %w", err)
	}
	if err := temp.Sync(); err != nil {
		temp.Close()
		return fmt.Errorf("sync allocation registry: %w", err)
	}
	if err := temp.Close(); err != nil {
		return fmt.Errorf("close allocation registry: %w", err)
	}
	if err := os.Rename(tempName, path); err != nil {
		return fmt.Errorf("replace allocation registry: %w", err)
	}
	if err := os.Chmod(path, 0o640); err != nil {
		return fmt.Errorf("chmod allocation registry: %w", err)
	}
	if dirHandle, err := os.Open(dir); err == nil {
		_ = dirHandle.Sync()
		_ = dirHandle.Close()
	}
	return nil
}
