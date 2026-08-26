package relay

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

var (
	ErrQuotaExceeded  = errors.New("daily byte quota exceeded")
	ErrSessionLimit   = errors.New("concurrent session limit exceeded")
	ErrDuplicateEvent = errors.New("duplicate event")
	ErrConflict       = errors.New("conflict")
	ErrUnknownSession = errors.New("unknown session")
	ErrSessionExists  = errors.New("session already exists")
	ErrDeviceRevoked  = errors.New("device revoked")
	ErrInvalidEvent   = errors.New("invalid usage event")
	ErrStorage        = errors.New("storage unavailable")
)

type Store interface {
	Apply(context.Context, time.Time, UsageEvent) error
	Duplicate(context.Context, time.Time, UsageEvent) (bool, error)
	Snapshot(context.Context, time.Time, string) (uint64, uint64, int, error)
	IsRevoked(context.Context, string) (bool, error)
	Revoke(context.Context, string, time.Time) error
	Ready(context.Context) error
	Totals(context.Context, time.Time) (uint64, uint64, int64, error)
	Close()
}

type UsageEvent struct {
	EventID      string `json:"event_id"`
	DeviceID     string `json:"device_id"`
	SessionID    string `json:"session_id"`
	AllocationID string `json:"allocation_id,omitempty"`
	Kind         string `json:"kind"`
	IngressBytes uint64 `json:"ingress_bytes"`
	EgressBytes  uint64 `json:"egress_bytes"`
}

type deviceUsage struct {
	Day          string            `json:"day"`
	IngressBytes uint64            `json:"ingress_bytes"`
	EgressBytes  uint64            `json:"egress_bytes"`
	Sessions     map[string]bool   `json:"sessions"`
	EventIDs     map[string]bool   `json:"event_ids"`
	EventDigests map[string]string `json:"event_digests,omitempty"`
	Revoked      bool              `json:"revoked,omitempty"`
}

type persistedState struct {
	Devices map[string]*deviceUsage `json:"devices"`
}

type FileStore struct {
	mu           sync.Mutex
	path         string
	dailyLimit   uint64
	sessionLimit int
	state        persistedState
}

type UsageStore = FileStore

func NewUsageStore(path string, dailyLimit uint64, sessionLimit int) (*FileStore, error) {
	s := &FileStore{path: path, dailyLimit: dailyLimit, sessionLimit: sessionLimit, state: persistedState{Devices: make(map[string]*deviceUsage)}}
	contents, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return s, nil
		}
		return nil, fmt.Errorf("read state: %w", err)
	}
	if err := json.Unmarshal(contents, &s.state); err != nil {
		return nil, fmt.Errorf("decode state: %w", err)
	}
	if s.state.Devices == nil {
		s.state.Devices = make(map[string]*deviceUsage)
	}
	for deviceID, usage := range s.state.Devices {
		if usage == nil {
			return nil, fmt.Errorf("decode state: device %q has null usage", deviceID)
		}
		if usage.Sessions == nil {
			usage.Sessions = make(map[string]bool)
		}
		if usage.EventIDs == nil {
			usage.EventIDs = make(map[string]bool)
		}
		if usage.EventDigests == nil {
			usage.EventDigests = make(map[string]string)
		}
	}
	return s, nil
}

func (s *FileStore) Apply(_ context.Context, now time.Time, event UsageEvent) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	day := now.UTC().Format(time.DateOnly)
	current := s.state.Devices[event.DeviceID]
	if current != nil && current.Day == day && current.EventIDs[event.EventID] {
		duplicate, err := duplicateUsageEvent(current, event)
		if err != nil {
			return err
		}
		if duplicate {
			return ErrDuplicateEvent
		}
	}
	if current != nil && current.Revoked {
		return ErrDeviceRevoked
	}
	usage := cloneUsage(current)
	if usage == nil || usage.Day != day {
		sessions := make(map[string]bool)
		revoked := false
		if usage != nil {
			for sessionID, present := range usage.Sessions {
				sessions[sessionID] = present
			}
			revoked = usage.Revoked
		}
		usage = &deviceUsage{Day: day, Sessions: sessions, EventIDs: make(map[string]bool), EventDigests: make(map[string]string), Revoked: revoked}
	}
	if event.IngressBytes > ^uint64(0)-usage.IngressBytes || event.EgressBytes > ^uint64(0)-usage.EgressBytes {
		return ErrQuotaExceeded
	}
	used := usage.IngressBytes + usage.EgressBytes
	if event.IngressBytes > ^uint64(0)-event.EgressBytes {
		return ErrQuotaExceeded
	}
	eventBytes := event.IngressBytes + event.EgressBytes
	if used > s.dailyLimit || eventBytes > s.dailyLimit-used {
		return ErrQuotaExceeded
	}
	switch event.Kind {
	case "start":
		if usage.Sessions[event.SessionID] {
			return ErrSessionExists
		}
		if len(usage.Sessions) >= s.sessionLimit {
			return ErrSessionLimit
		}
		usage.Sessions[event.SessionID] = true
	case "update":
		if !usage.Sessions[event.SessionID] {
			return ErrUnknownSession
		}
	case "end":
		if !usage.Sessions[event.SessionID] {
			return ErrUnknownSession
		}
		delete(usage.Sessions, event.SessionID)
	default:
		return fmt.Errorf("%w: unsupported event kind %q", ErrInvalidEvent, event.Kind)
	}
	usage.IngressBytes += event.IngressBytes
	usage.EgressBytes += event.EgressBytes
	usage.EventIDs[event.EventID] = true
	payloadDigest, err := usageEventDigest(event)
	if err != nil {
		return fmt.Errorf("%w: %v", ErrInvalidEvent, err)
	}
	usage.EventDigests[event.EventID] = fmt.Sprintf("%x", payloadDigest)
	nextState := persistedState{Devices: make(map[string]*deviceUsage, len(s.state.Devices))}
	for deviceID, existing := range s.state.Devices {
		nextState.Devices[deviceID] = existing
	}
	nextState.Devices[event.DeviceID] = usage
	if err := s.persistLocked(nextState); err != nil {
		return err
	}
	s.state = nextState
	return nil
}

func (s *FileStore) Duplicate(_ context.Context, now time.Time, event UsageEvent) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	current := s.state.Devices[event.DeviceID]
	if current == nil || current.Day != now.UTC().Format(time.DateOnly) || !current.EventIDs[event.EventID] {
		return false, nil
	}
	return duplicateUsageEvent(current, event)
}

func (s *FileStore) Snapshot(_ context.Context, now time.Time, deviceID string) (uint64, uint64, int, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	usage := s.state.Devices[deviceID]
	if usage == nil {
		return 0, 0, 0, nil
	}
	if usage.Day != now.UTC().Format(time.DateOnly) {
		return 0, 0, len(usage.Sessions), nil
	}
	return usage.IngressBytes, usage.EgressBytes, len(usage.Sessions), nil
}

func (s *FileStore) IsRevoked(_ context.Context, deviceID string) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	usage := s.state.Devices[deviceID]
	return usage != nil && usage.Revoked, nil
}

func (s *FileStore) Revoke(_ context.Context, deviceID string, now time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	usage := cloneUsage(s.state.Devices[deviceID])
	if usage == nil {
		usage = &deviceUsage{Day: now.UTC().Format(time.DateOnly), Sessions: make(map[string]bool), EventIDs: make(map[string]bool), EventDigests: make(map[string]string)}
	}
	usage.Revoked = true
	nextState := persistedState{Devices: make(map[string]*deviceUsage, len(s.state.Devices)+1)}
	for id, existing := range s.state.Devices {
		nextState.Devices[id] = existing
	}
	nextState.Devices[deviceID] = usage
	if err := s.persistLocked(nextState); err != nil {
		return err
	}
	s.state = nextState
	return nil
}

func (s *FileStore) Ready(_ context.Context) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := os.MkdirAll(filepath.Dir(s.path), 0o750); err != nil {
		return fmt.Errorf("create state directory: %w", err)
	}
	test, err := os.CreateTemp(filepath.Dir(s.path), ".ready-*")
	if err != nil {
		return fmt.Errorf("test state directory: %w", err)
	}
	name := test.Name()
	if err := test.Close(); err != nil {
		_ = os.Remove(name)
		return fmt.Errorf("close readiness file: %w", err)
	}
	if err := os.Remove(name); err != nil {
		return fmt.Errorf("remove readiness file: %w", err)
	}
	return nil
}

func (s *FileStore) Totals(_ context.Context, now time.Time) (uint64, uint64, int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	day := now.UTC().Format(time.DateOnly)
	var ingress, egress uint64
	var active int64
	for _, usage := range s.state.Devices {
		if usage.Day == day {
			ingress += usage.IngressBytes
			egress += usage.EgressBytes
		}
		active += int64(len(usage.Sessions))
	}
	return ingress, egress, active, nil
}

func (s *FileStore) Close() {}

func cloneUsage(source *deviceUsage) *deviceUsage {
	if source == nil {
		return nil
	}
	copy := &deviceUsage{Day: source.Day, IngressBytes: source.IngressBytes, EgressBytes: source.EgressBytes, Sessions: make(map[string]bool), EventIDs: make(map[string]bool), EventDigests: make(map[string]string), Revoked: source.Revoked}
	for id, present := range source.Sessions {
		copy.Sessions[id] = present
	}
	for id, present := range source.EventIDs {
		copy.EventIDs[id] = present
	}
	for id, digest := range source.EventDigests {
		copy.EventDigests[id] = digest
	}
	return copy
}

func duplicateUsageEvent(current *deviceUsage, event UsageEvent) (bool, error) {
	existingDigest, hasDigest := current.EventDigests[event.EventID]
	if !hasDigest {
		return true, nil
	}
	payloadDigest, err := usageEventDigest(event)
	if err != nil {
		return false, fmt.Errorf("%w: %v", ErrInvalidEvent, err)
	}
	if existingDigest != fmt.Sprintf("%x", payloadDigest) {
		return false, ErrInvalidEvent
	}
	return true, nil
}

func (s *FileStore) persistLocked(state persistedState) error {
	if err := os.MkdirAll(filepath.Dir(s.path), 0o750); err != nil {
		return fmt.Errorf("%w: create state directory: %v", ErrStorage, err)
	}
	contents, err := json.Marshal(state)
	if err != nil {
		return fmt.Errorf("%w: encode state: %v", ErrStorage, err)
	}
	temp, err := os.CreateTemp(filepath.Dir(s.path), ".relay-state-*")
	if err != nil {
		return fmt.Errorf("%w: create temporary state: %v", ErrStorage, err)
	}
	tempName := temp.Name()
	defer func() { _ = os.Remove(tempName) }()
	if err := temp.Chmod(0o600); err != nil {
		_ = temp.Close()
		return fmt.Errorf("%w: protect state: %v", ErrStorage, err)
	}
	if _, err := temp.Write(contents); err != nil {
		_ = temp.Close()
		return fmt.Errorf("%w: write state: %v", ErrStorage, err)
	}
	if err := temp.Sync(); err != nil {
		_ = temp.Close()
		return fmt.Errorf("%w: sync state: %v", ErrStorage, err)
	}
	if err := temp.Close(); err != nil {
		return fmt.Errorf("%w: close state: %v", ErrStorage, err)
	}
	if err := os.Rename(tempName, s.path); err != nil {
		return fmt.Errorf("%w: replace state: %v", ErrStorage, err)
	}
	directory, err := os.Open(filepath.Dir(s.path))
	if err != nil {
		return fmt.Errorf("%w: open state directory for sync: %v", ErrStorage, err)
	}
	if err := directory.Sync(); err != nil {
		_ = directory.Close()
		return fmt.Errorf("%w: sync state directory: %v", ErrStorage, err)
	}
	if err := directory.Close(); err != nil {
		return fmt.Errorf("%w: close state directory: %v", ErrStorage, err)
	}
	return nil
}
