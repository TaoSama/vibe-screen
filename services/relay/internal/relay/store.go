package relay

import (
	"crypto/rand"
	"encoding/hex"
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
	ErrUnknownSession = errors.New("unknown session")
	ErrSessionExists  = errors.New("session already exists")
	ErrDeviceRevoked  = errors.New("device revoked")
)

type UsageEvent struct {
	EventID      string `json:"event_id"`
	DeviceID     string `json:"device_id"`
	SessionID    string `json:"session_id"`
	Kind         string `json:"kind"`
	IngressBytes uint64 `json:"ingress_bytes"`
	EgressBytes  uint64 `json:"egress_bytes"`
}

type deviceUsage struct {
	Day                string          `json:"day"`
	IngressBytes       uint64          `json:"ingress_bytes"`
	EgressBytes        uint64          `json:"egress_bytes"`
	Sessions           map[string]bool `json:"sessions"`
	EventIDs           map[string]bool `json:"event_ids"`
	Revoked            bool            `json:"revoked,omitempty"`
	RevocationID       string          `json:"revocation_id,omitempty"`
	TerminationPending bool            `json:"termination_pending,omitempty"`
}

type persistedState struct {
	Devices map[string]*deviceUsage `json:"devices"`
}

type UsageStore struct {
	mu           sync.Mutex
	path         string
	dailyLimit   uint64
	sessionLimit int
	state        persistedState
}

type pendingTermination struct {
	DeviceID     string
	RevocationID string
}

func NewUsageStore(path string, dailyLimit uint64, sessionLimit int) (*UsageStore, error) {
	s := &UsageStore{path: path, dailyLimit: dailyLimit, sessionLimit: sessionLimit, state: persistedState{Devices: make(map[string]*deviceUsage)}}
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
	}
	return s, nil
}

func (s *UsageStore) Apply(now time.Time, event UsageEvent) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	day := now.UTC().Format(time.DateOnly)
	current := s.state.Devices[event.DeviceID]
	if current != nil && current.Day == day && current.EventIDs[event.EventID] {
		return ErrDuplicateEvent
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
		usage = &deviceUsage{Day: day, Sessions: sessions, EventIDs: make(map[string]bool), Revoked: revoked}
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
		return fmt.Errorf("unsupported event kind %q", event.Kind)
	}
	usage.IngressBytes += event.IngressBytes
	usage.EgressBytes += event.EgressBytes
	usage.EventIDs[event.EventID] = true
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

func (s *UsageStore) Snapshot(now time.Time, deviceID string) (uint64, uint64, int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	usage := s.state.Devices[deviceID]
	if usage == nil {
		return 0, 0, 0
	}
	if usage.Day != now.UTC().Format(time.DateOnly) {
		return 0, 0, len(usage.Sessions)
	}
	return usage.IngressBytes, usage.EgressBytes, len(usage.Sessions)
}

func (s *UsageStore) IsRevoked(deviceID string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	usage := s.state.Devices[deviceID]
	return usage != nil && usage.Revoked
}

func (s *UsageStore) Revoke(deviceID string, now time.Time) (string, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	usage := cloneUsage(s.state.Devices[deviceID])
	if usage == nil {
		usage = &deviceUsage{Day: now.UTC().Format(time.DateOnly), Sessions: make(map[string]bool), EventIDs: make(map[string]bool)}
	}
	if usage.Revoked && !usage.TerminationPending && usage.RevocationID != "" {
		return usage.RevocationID, false, nil
	}
	if usage.RevocationID == "" {
		identifier := make([]byte, 16)
		if _, err := rand.Read(identifier); err != nil {
			return "", false, fmt.Errorf("generate revocation id: %w", err)
		}
		usage.RevocationID = hex.EncodeToString(identifier)
	}
	usage.Revoked = true
	usage.TerminationPending = true
	nextState := persistedState{Devices: make(map[string]*deviceUsage, len(s.state.Devices)+1)}
	for id, existing := range s.state.Devices {
		nextState.Devices[id] = existing
	}
	nextState.Devices[deviceID] = usage
	if err := s.persistLocked(nextState); err != nil {
		return "", false, err
	}
	s.state = nextState
	return usage.RevocationID, true, nil
}

func (s *UsageStore) CompleteTermination(deviceID, revocationID string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	usage := cloneUsage(s.state.Devices[deviceID])
	if usage == nil || !usage.Revoked || usage.RevocationID != revocationID {
		return errors.New("revocation changed before termination completed")
	}
	if !usage.TerminationPending {
		return nil
	}
	usage.TerminationPending = false
	nextState := persistedState{Devices: make(map[string]*deviceUsage, len(s.state.Devices))}
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

func (s *UsageStore) PendingTerminations(limit int) []pendingTermination {
	s.mu.Lock()
	defer s.mu.Unlock()
	pending := make([]pendingTermination, 0)
	for deviceID, usage := range s.state.Devices {
		if usage != nil && usage.Revoked && usage.TerminationPending && usage.RevocationID != "" {
			pending = append(pending, pendingTermination{DeviceID: deviceID, RevocationID: usage.RevocationID})
			if len(pending) == limit {
				break
			}
		}
	}
	return pending
}

func (s *UsageStore) Ready() error {
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

func (s *UsageStore) Totals(now time.Time) (uint64, uint64, int64) {
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
	return ingress, egress, active
}

func cloneUsage(source *deviceUsage) *deviceUsage {
	if source == nil {
		return nil
	}
	copy := &deviceUsage{Day: source.Day, IngressBytes: source.IngressBytes, EgressBytes: source.EgressBytes, Sessions: make(map[string]bool), EventIDs: make(map[string]bool), Revoked: source.Revoked, RevocationID: source.RevocationID, TerminationPending: source.TerminationPending}
	for id, present := range source.Sessions {
		copy.Sessions[id] = present
	}
	for id, present := range source.EventIDs {
		copy.EventIDs[id] = present
	}
	return copy
}

func (s *UsageStore) persistLocked(state persistedState) error {
	if err := os.MkdirAll(filepath.Dir(s.path), 0o750); err != nil {
		return fmt.Errorf("create state directory: %w", err)
	}
	contents, err := json.Marshal(state)
	if err != nil {
		return fmt.Errorf("encode state: %w", err)
	}
	temp, err := os.CreateTemp(filepath.Dir(s.path), ".relay-state-*")
	if err != nil {
		return fmt.Errorf("create temporary state: %w", err)
	}
	tempName := temp.Name()
	defer func() { _ = os.Remove(tempName) }()
	if err := temp.Chmod(0o600); err != nil {
		_ = temp.Close()
		return fmt.Errorf("protect state: %w", err)
	}
	if _, err := temp.Write(contents); err != nil {
		_ = temp.Close()
		return fmt.Errorf("write state: %w", err)
	}
	if err := temp.Sync(); err != nil {
		_ = temp.Close()
		return fmt.Errorf("sync state: %w", err)
	}
	if err := temp.Close(); err != nil {
		return fmt.Errorf("close state: %w", err)
	}
	if err := os.Rename(tempName, s.path); err != nil {
		return fmt.Errorf("replace state: %w", err)
	}
	directory, err := os.Open(filepath.Dir(s.path))
	if err != nil {
		return fmt.Errorf("open state directory for sync: %w", err)
	}
	if err := directory.Sync(); err != nil {
		_ = directory.Close()
		return fmt.Errorf("sync state directory: %w", err)
	}
	if err := directory.Close(); err != nil {
		return fmt.Errorf("close state directory: %w", err)
	}
	return nil
}
