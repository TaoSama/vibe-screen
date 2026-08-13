package authority

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"sort"
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
	events          map[string]bool
	daily           map[string]uint64
	epochFloors     map[string]uint64
	allocationLimit int
	dailyLimit      uint64
}

func newMemoryStore() *memoryStore {
	return &memoryStore{accounts: map[string]bool{}, devices: map[string]string{}, revoked: map[string]uint64{}, sessions: map[string]*memorySession{}, requests: map[string]string{}, allocations: map[string]*memoryAllocation{}, events: map[string]bool{}, daily: map[string]uint64{}, epochFloors: map[string]uint64{}, allocationLimit: 1, dailyLimit: 100}
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
	epochKey := request.HostDeviceID + "/" + request.ClientDeviceID
	if request.SessionEpoch <= s.epochFloors[epochKey] {
		return SignalingAdmission{}, ErrConflict
	}
	s.epochFloors[epochKey] = request.SessionEpoch
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
	if s.revoked[request.DeviceID] > 0 || s.accounts[s.devices[request.DeviceID]] {
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
	if s.allocations[request.AllocationID] != nil {
		return ErrConflict
	}
	s.allocations[request.AllocationID] = &memoryAllocation{request: request, observed: now}
	return nil
}
func (s *memoryStore) ApplyCoturnUsage(_ context.Context, usage CoturnUsage) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	key := usage.SourceID + "/" + usage.EventID
	if s.events[key] {
		return true, nil
	}
	allocation := s.allocations[usage.AllocationID]
	if allocation == nil {
		return false, ErrNotFound
	}
	if allocation.request.SourceID != usage.SourceID || allocation.request.DeviceID != usage.DeviceID || allocation.request.SessionID != usage.SessionID || usage.Sequence <= allocation.sequence || usage.IngressBytes < allocation.ingress || usage.EgressBytes < allocation.egress || allocation.closed {
		return false, ErrStaleUsage
	}
	s.events[key] = true
	s.daily[usage.DeviceID] += usage.IngressBytes - allocation.ingress + usage.EgressBytes - allocation.egress
	allocation.sequence, allocation.ingress, allocation.egress, allocation.closed, allocation.observed = usage.Sequence, usage.IngressBytes, usage.EgressBytes, usage.Closed, usage.ObservedAt
	return false, nil
}
func (s *memoryStore) Reconcile(ctx context.Context, request ReconcileRequest, grace time.Duration) (ReconcileResult, error) {
	result := ReconcileResult{}
	seen := map[string]bool{}
	for index, usage := range request.Allocations {
		usage.SourceID = request.SourceID
		usage.EventID = "reconcile-" + usage.AllocationID
		usage.ObservedAt = request.ObservedAt
		duplicate, err := s.ApplyCoturnUsage(ctx, usage)
		if err != nil {
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
	return result, nil
}

func testAuthorityConfig() Config {
	return Config{ListenAddress: "127.0.0.1:0", DatabaseURL: "postgres://unused", AdminToken: "admin" + testSecretSuffix, SignalingToken: "signaling" + testSecretSuffix, RelayToken: "relay" + testSecretSuffix, CoturnToken: "coturn" + testSecretSuffix, RoleTokenSecret: "role" + testSecretSuffix, MaximumSessionTTLSeconds: 900, DailyBytesPerDevice: 100, MaximumAllocationsPerDevice: 1, ReconciliationGraceSeconds: 10}
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
	_ = store.EnsureAccount(ctx, "account")
	_ = store.RegisterDevice(ctx, "account", "device")
	var accepted atomic.Int32
	var wait sync.WaitGroup
	start := make(chan struct{})
	for _, id := range []string{"one", "two"} {
		wait.Add(1)
		go func(id string) {
			defer wait.Done()
			<-start
			if err := store.AdmitRelay(ctx, RelayAdmissionRequest{DeviceID: "device", SessionID: id, AllocationID: id, SourceID: "node"}, time.Now()); err == nil {
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
}

func TestCoturnCountersAreIdempotentAndFinalUsageSurvivesRevocation(t *testing.T) {
	store := newMemoryStore()
	ctx := context.Background()
	_ = store.EnsureAccount(ctx, "account")
	_ = store.RegisterDevice(ctx, "account", "device")
	now := time.Now().UTC()
	admission := RelayAdmissionRequest{DeviceID: "device", SessionID: "session", AllocationID: "allocation", SourceID: "node"}
	if err := store.AdmitRelay(ctx, admission, now); err != nil {
		t.Fatal(err)
	}
	first := CoturnUsage{SourceID: "node", EventID: "event-1", AllocationID: "allocation", DeviceID: "device", SessionID: "session", Sequence: 1, IngressBytes: 10, EgressBytes: 20, ObservedAt: now}
	if duplicate, err := store.ApplyCoturnUsage(ctx, first); err != nil || duplicate {
		t.Fatalf("first=%v/%v", duplicate, err)
	}
	if duplicate, err := store.ApplyCoturnUsage(ctx, first); err != nil || !duplicate {
		t.Fatalf("retry=%v/%v", duplicate, err)
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
