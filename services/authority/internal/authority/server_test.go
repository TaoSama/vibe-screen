package authority

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

const testSecretSuffix = "-token-with-more-than-thirty-two-bytes"

type memorySession struct {
	request   SignalingRequest
	admission SignalingAdmission
	revoked   bool
}
type memoryAllocation struct {
	request                   RelayAdmissionRequest
	sequence, ingress, egress uint64
	closed                    bool
	observed                  time.Time
}
type memoryStore struct {
	mu              sync.Mutex
	accounts        map[string]bool
	devices         map[string]string
	revoked         map[string]uint64
	sessions        map[string]*memorySession
	requests        map[string]string
	allocations     map[string]*memoryAllocation
	events          map[string][sha256.Size]byte
	daily           map[string]uint64
	epochFloors     map[string]uint64
	allocationLimit int
	dailyLimit      uint64
}

func newMemoryStore() *memoryStore {
	return &memoryStore{accounts: map[string]bool{}, devices: map[string]string{}, revoked: map[string]uint64{}, sessions: map[string]*memorySession{}, requests: map[string]string{}, allocations: map[string]*memoryAllocation{}, events: map[string][sha256.Size]byte{}, daily: map[string]uint64{}, epochFloors: map[string]uint64{}, allocationLimit: 1, dailyLimit: 100}
}
func (s *memoryStore) Close()                      {}
func (s *memoryStore) Ready(context.Context) error { return nil }
func (s *memoryStore) EnsureAccount(_ context.Context, id string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.accounts[id]; !ok {
		s.accounts[id] = false
	}
	return nil
}
func (s *memoryStore) SuspendAccount(_ context.Context, id string, _ time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.accounts[id]; !ok {
		return ErrNotFound
	}
	s.accounts[id] = true
	for _, session := range s.sessions {
		if session.request.AccountID == id {
			session.revoked = true
		}
	}
	return nil
}
func (s *memoryStore) RegisterDevice(_ context.Context, accountID, deviceID string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.accounts[accountID]; !ok {
		return ErrNotFound
	}
	if existing, ok := s.devices[deviceID]; ok && existing != accountID {
		return ErrConflict
	}
	s.devices[deviceID] = accountID
	return nil
}
func (s *memoryStore) RevokeDevice(_ context.Context, id string, epoch uint64, _ time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.devices[id]; !ok {
		return ErrNotFound
	}
	if epoch <= s.revoked[id] {
		return ErrConflict
	}
	s.revoked[id] = epoch
	for _, session := range s.sessions {
		if session.request.HostDeviceID == id || session.request.ClientDeviceID == id {
			session.revoked = true
		}
	}
	return nil
}
func (s *memoryStore) CreateSignaling(_ context.Context, request SignalingRequest, now time.Time) (SignalingAdmission, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.accounts[request.AccountID] || s.revoked[request.HostDeviceID] > 0 || s.revoked[request.ClientDeviceID] > 0 {
		return SignalingAdmission{}, ErrRevoked
	}
	if s.devices[request.HostDeviceID] != request.AccountID || s.devices[request.ClientDeviceID] != request.AccountID {
		return SignalingAdmission{}, ErrNotFound
	}
	if id, ok := s.requests[request.RequestID]; ok {
		session := s.sessions[id]
		if session.request != request {
			return SignalingAdmission{}, ErrConflict
		}
		result := session.admission
		result.Created = false
		return result, nil
	}
	if request.SessionEpoch == 0 || request.SessionEpoch > math.MaxInt64 || request.SessionEpoch <= s.epochFloors[request.HostDeviceID] || request.SessionEpoch <= s.epochFloors[request.ClientDeviceID] {
		return SignalingAdmission{}, ErrConflict
	}
	s.epochFloors[request.HostDeviceID] = request.SessionEpoch
	s.epochFloors[request.ClientDeviceID] = request.SessionEpoch
	id := "session-" + request.RequestID
	result := SignalingAdmission{SessionID: id, HostToken: "host-" + id, ClientToken: "client-" + id, ExpiresAt: now.Add(time.Duration(request.TTLSeconds) * time.Second), Created: true}
	s.sessions[id] = &memorySession{request: request, admission: result}
	s.requests[request.RequestID] = id
	return result, nil
}
func (s *memoryStore) AuthorizeSignaling(_ context.Context, id, token string, now time.Time) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	session := s.sessions[id]
	if session == nil {
		return "", ErrNotFound
	}
	if session.revoked || !now.Before(session.admission.ExpiresAt) || s.accounts[session.request.AccountID] || s.revoked[session.request.HostDeviceID] > 0 || s.revoked[session.request.ClientDeviceID] > 0 {
		return "", ErrRevoked
	}
	if token == session.admission.HostToken {
		return "host", nil
	}
	if token == session.admission.ClientToken {
		return "client", nil
	}
	return "", ErrNotFound
}
func (s *memoryStore) InvalidateSignaling(_ context.Context, id string, _ time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.sessions[id] == nil {
		return ErrNotFound
	}
	s.sessions[id].revoked = true
	return nil
}
func (s *memoryStore) AdmitRelay(_ context.Context, request RelayAdmissionRequest, now time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if existing := s.allocations[request.AllocationID]; existing != nil {
		if existing.request == request {
			return nil
		}
		return ErrConflict
	}
	if s.revoked[request.DeviceID] > 0 || s.accounts[s.devices[request.DeviceID]] {
		return ErrRevoked
	}
	session := s.sessions[request.SessionID]
	if session == nil {
		return ErrNotFound
	}
	if session.request.HostDeviceID != request.DeviceID && session.request.ClientDeviceID != request.DeviceID {
		return ErrNotFound
	}
	if session.revoked || !now.Before(session.admission.ExpiresAt) {
		return ErrRevoked
	}
	if s.daily[request.DeviceID] >= s.dailyLimit {
		return ErrQuotaExceeded
	}
	active := 0
	for _, allocation := range s.allocations {
		if allocation.request.DeviceID == request.DeviceID && !allocation.closed {
			active++
		}
	}
	if active >= s.allocationLimit {
		return ErrQuotaExceeded
	}
	s.allocations[request.AllocationID] = &memoryAllocation{request: request, observed: now}
	return nil
}
func (s *memoryStore) ApplyCoturnUsage(_ context.Context, usage CoturnUsage) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !validIdentifier(usage.EventID) {
		return false, ErrConflict
	}
	key := usage.SourceID + "/" + usage.EventID
	encoded, err := json.Marshal(usage)
	if err != nil {
		return false, err
	}
	digest := sha256.Sum256(encoded)
	if existing, ok := s.events[key]; ok {
		if existing != digest {
			return false, ErrConflict
		}
		return true, nil
	}
	allocation := s.allocations[usage.AllocationID]
	if allocation == nil {
		return false, ErrNotFound
	}
	if allocation.request.SourceID != usage.SourceID || allocation.request.DeviceID != usage.DeviceID || allocation.request.SessionID != usage.SessionID || usage.Sequence <= allocation.sequence || usage.IngressBytes < allocation.ingress || usage.EgressBytes < allocation.egress || usage.ObservedAt.Before(allocation.observed) || allocation.closed {
		return false, ErrStaleUsage
	}
	s.events[key] = digest
	s.daily[usage.DeviceID] += usage.IngressBytes - allocation.ingress + usage.EgressBytes - allocation.egress
	allocation.sequence, allocation.ingress, allocation.egress, allocation.closed, allocation.observed = usage.Sequence, usage.IngressBytes, usage.EgressBytes, usage.Closed, usage.ObservedAt
	return false, nil
}
func (s *memoryStore) Reconcile(ctx context.Context, request ReconcileRequest, grace time.Duration) (ReconcileResult, error) {
	result := ReconcileResult{MissingAllocationIDs: []string{}, UnauthorizedAllocationIDs: []string{}, ConflictAllocationIDs: []string{}}
	seen := map[string]bool{}
	for index, usage := range request.Allocations {
		usage.SourceID = request.SourceID
		usage.EventID = reconciliationEventID(request.SourceID, request.ObservedAt, usage.AllocationID)
		usage.ObservedAt = request.ObservedAt
		duplicate, err := s.ApplyCoturnUsage(ctx, usage)
		if err != nil {
			if errors.Is(err, ErrNotFound) {
				result.UnauthorizedAllocationIDs = append(result.UnauthorizedAllocationIDs, usage.AllocationID)
				continue
			}
			if errors.Is(err, ErrStaleUsage) {
				s.mu.Lock()
				allocation := s.allocations[usage.AllocationID]
				ahead := allocation != nil && allocation.request.SourceID == usage.SourceID && allocation.request.DeviceID == usage.DeviceID && allocation.request.SessionID == usage.SessionID && allocation.sequence >= usage.Sequence && allocation.ingress >= usage.IngressBytes && allocation.egress >= usage.EgressBytes
				s.mu.Unlock()
				if ahead {
					result.AlreadyAhead++
					seen[request.Allocations[index].AllocationID] = true
					continue
				}
				result.ConflictAllocationIDs = append(result.ConflictAllocationIDs, usage.AllocationID)
				seen[request.Allocations[index].AllocationID] = true
				continue
			}
			if errors.Is(err, ErrConflict) {
				result.ConflictAllocationIDs = append(result.ConflictAllocationIDs, usage.AllocationID)
				seen[request.Allocations[index].AllocationID] = true
				continue
			}
			return result, err
		}
		if duplicate {
			result.Duplicate++
		} else {
			result.Applied++
		}
		seen[request.Allocations[index].AllocationID] = true
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	for id, allocation := range s.allocations {
		if allocation.request.SourceID == request.SourceID && !allocation.closed && allocation.observed.Before(request.ObservedAt.Add(-grace)) && !seen[id] {
			result.MissingAllocationIDs = append(result.MissingAllocationIDs, id)
		}
	}
	sort.Strings(result.MissingAllocationIDs)
	sort.Strings(result.UnauthorizedAllocationIDs)
	sort.Strings(result.ConflictAllocationIDs)
	return result, nil
}

func testAuthorityConfig() Config {
	return Config{ListenAddress: "127.0.0.1:0", DatabaseURL: "postgres://unused", AdminToken: "admin" + testSecretSuffix, SignalingToken: "signaling" + testSecretSuffix, RelayToken: "relay" + testSecretSuffix, CoturnToken: "coturn" + testSecretSuffix, RoleTokenSecret: "role" + testSecretSuffix, MaximumSessionTTLSeconds: 900, DailyBytesPerDevice: 100, MaximumAllocationsPerDevice: 1, ReconciliationGraceSeconds: 10}
}

func TestRequiredSchemaChecksumMatchesMigration(t *testing.T) {
	contents, err := os.ReadFile(filepath.Join("..", "..", "migrations", "001_authority.sql"))
	if err != nil {
		t.Fatal(err)
	}
	if checksum := fmt.Sprintf("%x", sha256.Sum256(contents)); checksum != requiredSchemaChecksum {
		t.Fatalf("migration checksum=%s, readiness requires %s", checksum, requiredSchemaChecksum)
	}
}

func createMemorySession(t *testing.T, store *memoryStore, accountID, hostID, clientID string, epoch uint64, now time.Time) SignalingAdmission {
	t.Helper()
	ctx := context.Background()
	if err := store.EnsureAccount(ctx, accountID); err != nil {
		t.Fatal(err)
	}
	for _, deviceID := range []string{hostID, clientID} {
		if err := store.RegisterDevice(ctx, accountID, deviceID); err != nil {
			t.Fatal(err)
		}
	}
	admission, err := store.CreateSignaling(ctx, SignalingRequest{RequestID: fmt.Sprintf("request-%s-%s-%d", hostID, clientID, epoch), AccountID: accountID, HostDeviceID: hostID, ClientDeviceID: clientID, SessionEpoch: epoch, TTLSeconds: 60}, now)
	if err != nil {
		t.Fatal(err)
	}
	return admission
}

func TestDenyWinsAcrossConcurrentSignalingAdmissionAndRevocation(t *testing.T) {
	for iteration := uint64(1); iteration <= 100; iteration++ {
		store := newMemoryStore()
		ctx := context.Background()
		_ = store.EnsureAccount(ctx, "account")
		_ = store.RegisterDevice(ctx, "account", "host")
		_ = store.RegisterDevice(ctx, "account", "client")
		request := SignalingRequest{RequestID: "request", AccountID: "account", HostDeviceID: "host", ClientDeviceID: "client", SessionEpoch: 1, TTLSeconds: 60}
		start := make(chan struct{})
		var admission SignalingAdmission
		var createErr, revokeErr error
		var wait sync.WaitGroup
		wait.Add(2)
		go func() {
			defer wait.Done()
			<-start
			admission, createErr = store.CreateSignaling(ctx, request, time.Now())
		}()
		go func() {
			defer wait.Done()
			<-start
			revokeErr = store.RevokeDevice(ctx, "client", iteration, time.Now())
		}()
		close(start)
		wait.Wait()
		if revokeErr != nil {
			t.Fatal(revokeErr)
		}
		if createErr == nil {
			if _, err := store.AuthorizeSignaling(ctx, admission.SessionID, admission.ClientToken, time.Now()); !errors.Is(err, ErrRevoked) {
				t.Fatalf("iteration %d authorized after completed revoke: %v", iteration, err)
			}
		} else if !errors.Is(createErr, ErrRevoked) {
			t.Fatalf("iteration %d create error %v", iteration, createErr)
		}
	}
}

func TestRelayAdmissionIsAtomicAtLimitAcrossReplicas(t *testing.T) {
	store := newMemoryStore()
	ctx := context.Background()
	now := time.Now()
	session := createMemorySession(t, store, "account", "host", "device", 1, now)
	var accepted atomic.Int32
	var wait sync.WaitGroup
	start := make(chan struct{})
	for _, id := range []string{"one", "two"} {
		wait.Add(1)
		go func(id string) {
			defer wait.Done()
			<-start
			if err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "device", SessionID: session.SessionID, AllocationID: id, SourceID: "node"}, now); err == nil {
				accepted.Add(1)
			} else if !errors.Is(err, ErrQuotaExceeded) {
				t.Errorf("unexpected admission error: %v", err)
			}
		}(id)
	}
	close(start)
	wait.Wait()
	if accepted.Load() != 1 {
		t.Fatalf("accepted %d allocations, want exactly one", accepted.Load())
	}
}

func TestSignalingEpochCannotRollBack(t *testing.T) {
	store := newMemoryStore()
	ctx := context.Background()
	_ = store.EnsureAccount(ctx, "account")
	_ = store.RegisterDevice(ctx, "account", "host")
	_ = store.RegisterDevice(ctx, "account", "client")
	base := SignalingRequest{RequestID: "newer", AccountID: "account", HostDeviceID: "host", ClientDeviceID: "client", SessionEpoch: 19, TTLSeconds: 60}
	if _, err := store.CreateSignaling(ctx, base, time.Now()); err != nil {
		t.Fatal(err)
	}
	base.RequestID = "older"
	base.SessionEpoch = 1
	if _, err := store.CreateSignaling(ctx, base, time.Now()); !errors.Is(err, ErrConflict) {
		t.Fatalf("epoch rollback error=%v", err)
	}
	_ = store.RegisterDevice(ctx, "account", "other-client")
	base.RequestID = "other-pair"
	base.ClientDeviceID = "other-client"
	if _, err := store.CreateSignaling(ctx, base, time.Now()); !errors.Is(err, ErrConflict) {
		t.Fatalf("per-device epoch rollback error=%v", err)
	}
	base.RequestID = "overflow"
	base.SessionEpoch = math.MaxInt64 + 1
	if _, err := store.CreateSignaling(ctx, base, time.Now()); !errors.Is(err, ErrConflict) {
		t.Fatalf("epoch overflow error=%v", err)
	}
}

func TestRelayAdmissionRequiresActiveBoundSession(t *testing.T) {
	store := newMemoryStore()
	now := time.Now().UTC()
	session := createMemorySession(t, store, "account", "host", "client", 1, now)
	_ = store.RegisterDevice(context.Background(), "account", "other")
	for name, request := range map[string]RelayAdmissionRequest{
		"missing": {DeviceID: "client", SessionID: "missing", AllocationID: "missing", SourceID: "node"},
		"unbound": {DeviceID: "other", SessionID: session.SessionID, AllocationID: "unbound", SourceID: "node"},
	} {
		if err := store.AdmitRelay(context.Background(), request, now); !errors.Is(err, ErrNotFound) {
			t.Fatalf("%s error=%v", name, err)
		}
	}
	if err := store.InvalidateSignaling(context.Background(), session.SessionID, now); err != nil {
		t.Fatal(err)
	}
	if err := store.AdmitRelay(context.Background(), RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: "revoked", SourceID: "node"}, now); !errors.Is(err, ErrRevoked) {
		t.Fatalf("revoked session error=%v", err)
	}
	expiredStore := newMemoryStore()
	expired := createMemorySession(t, expiredStore, "account", "host", "client", 1, now.Add(-2*time.Minute))
	if err := expiredStore.AdmitRelay(context.Background(), RelayAdmissionRequest{DeviceID: "client", SessionID: expired.SessionID, AllocationID: "expired", SourceID: "node"}, now); !errors.Is(err, ErrRevoked) {
		t.Fatalf("expired session error=%v", err)
	}
}

func TestRelayAdmissionRetryIsExactlyIdempotent(t *testing.T) {
	store := newMemoryStore()
	now := time.Now().UTC()
	session := createMemorySession(t, store, "account", "host", "client", 1, now)
	request := RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: "allocation", SourceID: "node"}
	if err := store.AdmitRelay(context.Background(), request, now); err != nil {
		t.Fatal(err)
	}
	if err := store.AdmitRelay(context.Background(), request, now.Add(time.Second)); err != nil {
		t.Fatalf("exact retry failed after quota was consumed: %v", err)
	}
	changed := request
	changed.DeviceID = "host"
	if err := store.AdmitRelay(context.Background(), changed, now); !errors.Is(err, ErrConflict) {
		t.Fatalf("changed retry error=%v", err)
	}
}

func TestCoturnCountersAreIdempotentAndFinalUsageSurvivesRevocation(t *testing.T) {
	store := newMemoryStore()
	ctx := context.Background()
	now := time.Now().UTC()
	session := createMemorySession(t, store, "account", "host", "device", 1, now)
	admission := RelayAdmissionRequest{DeviceID: "device", SessionID: session.SessionID, AllocationID: "allocation", SourceID: "node"}
	if err := store.AdmitRelay(ctx, admission, now); err != nil {
		t.Fatal(err)
	}
	first := CoturnUsage{SourceID: "node", EventID: "event-1", AllocationID: "allocation", DeviceID: "device", SessionID: session.SessionID, Sequence: 1, IngressBytes: 10, EgressBytes: 20, ObservedAt: now}
	if duplicate, err := store.ApplyCoturnUsage(ctx, first); err != nil || duplicate {
		t.Fatalf("first=%v/%v", duplicate, err)
	}
	if duplicate, err := store.ApplyCoturnUsage(ctx, first); err != nil || !duplicate {
		t.Fatalf("retry=%v/%v", duplicate, err)
	}
	backward := first
	backward.EventID = "event-backward"
	backward.Sequence = 2
	backward.ObservedAt = now.Add(-time.Second)
	if _, err := store.ApplyCoturnUsage(ctx, backward); !errors.Is(err, ErrStaleUsage) {
		t.Fatalf("backward observed_at error=%v", err)
	}
	if err := store.RevokeDevice(ctx, "device", 1, now); err != nil {
		t.Fatal(err)
	}
	final := first
	final.EventID = "event-2"
	final.Sequence = 2
	final.IngressBytes = 15
	final.EgressBytes = 30
	final.Closed = true
	if _, err := store.ApplyCoturnUsage(ctx, final); err != nil {
		t.Fatalf("final revoked usage rejected: %v", err)
	}
	if got := store.daily["device"]; got != 45 {
		t.Fatalf("daily bytes=%d, want 45", got)
	}
	if err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "device", SessionID: "new", AllocationID: "new", SourceID: "node"}, now); !errors.Is(err, ErrRevoked) {
		t.Fatalf("new allocation after revoke: %v", err)
	}
}

func TestCoturnEventIdentityAndReconcileConflicts(t *testing.T) {
	store := newMemoryStore()
	store.allocationLimit = 3
	now := time.Now().UTC()
	session := createMemorySession(t, store, "account", "host", "client", 1, now)
	ctx := context.Background()
	for _, allocationID := range []string{"conflict", "valid"} {
		if err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "client", SessionID: session.SessionID, AllocationID: allocationID, SourceID: "node"}, now); err != nil {
			t.Fatal(err)
		}
	}
	emptyEvent := CoturnUsage{SourceID: "node", AllocationID: "valid", DeviceID: "client", SessionID: session.SessionID, Sequence: 1, ObservedAt: now}
	if _, err := store.ApplyCoturnUsage(ctx, emptyEvent); !errors.Is(err, ErrConflict) {
		t.Fatalf("empty event id error=%v", err)
	}
	first := emptyEvent
	first.EventID = "stable-event"
	if _, err := store.ApplyCoturnUsage(ctx, first); err != nil {
		t.Fatal(err)
	}
	changed := first
	changed.IngressBytes = 1
	if _, err := store.ApplyCoturnUsage(ctx, changed); !errors.Is(err, ErrConflict) {
		t.Fatalf("reused event id with changed payload error=%v", err)
	}
	result, err := store.Reconcile(ctx, ReconcileRequest{SourceID: "node", ObservedAt: now.Add(time.Second), Allocations: []CoturnUsage{
		{AllocationID: "conflict", DeviceID: "wrong-device", SessionID: session.SessionID, Sequence: 1},
		{AllocationID: "unknown", DeviceID: "client", SessionID: session.SessionID, Sequence: 1},
		{AllocationID: "valid", DeviceID: "client", SessionID: session.SessionID, Sequence: 2, IngressBytes: 2},
	}}, time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	if result.Applied != 1 || !slices.Equal(result.ConflictAllocationIDs, []string{"conflict"}) || !slices.Equal(result.UnauthorizedAllocationIDs, []string{"unknown"}) {
		t.Fatalf("reconcile result=%+v", result)
	}
}

func TestReconciliationEventIDIsStableAndBounded(t *testing.T) {
	observedAt := time.Date(1678, 1, 2, 3, 4, 5, 6, time.UTC)
	allocationID := strings.Repeat("a", 128)
	first := reconciliationEventID(strings.Repeat("s", 128), observedAt, allocationID)
	second := reconciliationEventID(strings.Repeat("s", 128), observedAt, allocationID)
	if first != second || !validIdentifier(first) {
		t.Fatalf("derived event id is not stable and bounded: %q / %q", first, second)
	}
	if first == reconciliationEventID(strings.Repeat("s", 128), observedAt, allocationID[:127]+"b") {
		t.Fatal("different allocation identities produced the same event id")
	}
}

func TestEmptyReconcileSnapshotStillChecksClockBound(t *testing.T) {
	store := newMemoryStore()
	cfg := testAuthorityConfig()
	server, err := NewServer(cfg, store)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	server.now = func() time.Time { return now }
	body := fmt.Sprintf(`{"source_id":"node","observed_at":%q,"allocations":[]}`, now.Add(time.Nanosecond).Format(time.RFC3339Nano))
	request(t, server.Handler(), http.MethodPost, "/v1/coturn/reconcile", cfg.CoturnToken, body, http.StatusBadRequest)
}

func TestHTTPAuthorityStrictlyScopesTokensAndIdempotentSession(t *testing.T) {
	store := newMemoryStore()
	cfg := testAuthorityConfig()
	server, err := NewServer(cfg, store)
	if err != nil {
		t.Fatal(err)
	}
	handler := server.Handler()
	request(t, handler, http.MethodPut, "/v1/accounts/account", cfg.AdminToken, "", http.StatusNoContent)
	request(t, handler, http.MethodPut, "/v1/accounts/account/devices/host", cfg.AdminToken, "", http.StatusNoContent)
	request(t, handler, http.MethodPut, "/v1/accounts/account/devices/client", cfg.AdminToken, "", http.StatusNoContent)
	body := `{"request_id":"request","account_id":"account","host_device_id":"host","client_device_id":"client","session_epoch":1,"ttl_seconds":60}`
	first := request(t, handler, http.MethodPost, "/v1/signaling/sessions", cfg.SignalingToken, body, http.StatusCreated)
	second := request(t, handler, http.MethodPost, "/v1/signaling/sessions", cfg.SignalingToken, body, http.StatusOK)
	var a, b SignalingAdmission
	if err := json.Unmarshal(first.Body.Bytes(), &a); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(second.Body.Bytes(), &b); err != nil {
		t.Fatal(err)
	}
	a.Created, b.Created = false, false
	if a != b {
		t.Fatalf("idempotent response changed: %#v %#v", a, b)
	}
	request(t, handler, http.MethodPost, "/v1/signaling/sessions", cfg.AdminToken, body, http.StatusUnauthorized)
	request(t, handler, http.MethodPost, "/v1/devices/client/revoke", cfg.AdminToken, `{"epoch":1}`, http.StatusNoContent)
	authorize := `{"role_token":"` + b.ClientToken + `"}`
	request(t, handler, http.MethodPost, "/v1/signaling/sessions/"+b.SessionID+"/authorize", cfg.SignalingToken, authorize, http.StatusForbidden)
}

func request(t *testing.T, handler http.Handler, method, path, token, body string, want int) *httptest.ResponseRecorder {
	t.Helper()
	request := httptest.NewRequest(method, path, bytes.NewBufferString(body))
	if token != "" {
		request.Header.Set("Authorization", "Bearer "+token)
	}
	if body != "" {
		request.Header.Set("Content-Type", "application/json")
	}
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != want {
		t.Fatalf("%s %s=%d want %d: %s", method, path, response.Code, want, response.Body.String())
	}
	return response
}
