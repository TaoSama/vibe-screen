package relay

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha1"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type failingStore struct{}

func (failingStore) Apply(context.Context, time.Time, UsageEvent) error { return ErrStorage }
func (failingStore) Duplicate(context.Context, time.Time, UsageEvent) (bool, error) {
	return false, ErrStorage
}
func (failingStore) Snapshot(context.Context, time.Time, string) (uint64, uint64, int, error) {
	return 0, 0, 0, ErrStorage
}
func (failingStore) IsRevoked(context.Context, string) (bool, error) { return false, ErrStorage }
func (failingStore) Revoke(context.Context, string, time.Time) error { return ErrStorage }
func (failingStore) Ready(context.Context) error                     { return ErrStorage }
func (failingStore) Totals(context.Context, time.Time) (uint64, uint64, int64, error) {
	return 0, 0, 0, ErrStorage
}
func (failingStore) Close() {}

const (
	testClientToken    = "client-token-at-least-thirty-two-bytes"
	testUsageToken     = "usage-token-at-least-thirty-two-bytes-"
	testMetricsToken   = "metrics-token-at-least-thirty-two-bytes"
	testAdminToken     = "admin-token-at-least-thirty-two-bytes-"
	testAuthorityToken = "authority-token-at-least-thirty-two-bytes"
)

func testConfig(t *testing.T) Config {
	t.Helper()
	return Config{
		ListenAddress: "127.0.0.1:0", TurnRealm: "relay.test", TurnURIs: []string{"turn:relay.test:3478?transport=udp"},
		CredentialTTLSeconds: 600, MaxCredentialTTLSeconds: 900, CredentialRequestsPerMinute: 2,
		MaxConcurrentSessionsPerDevice: 1, DailyBytesPerDevice: 1000, MaxUsageEventBytes: 800,
		EgressMicrocentsPerGibibyte: 9_000_000, StateFile: filepath.Join(t.TempDir(), "state.json"),
		TurnSecret: "turn-secret-at-least-thirty-two-bytes-", ClientToken: testClientToken, UsageToken: testUsageToken, MetricsToken: testMetricsToken, AdminToken: testAdminToken,
	}
}

func useProductionAuthority(t *testing.T, cfg *Config, authorityURL string) {
	t.Helper()
	cfg.AuthorityMode = AuthorityModeProd
	cfg.AuthorityURL = authorityURL
	cfg.AuthoritySourceID = "turn-node-1"
	cfg.AuthorityToken = testAuthorityToken
	cfg.AllocationRegistryFile = filepath.Join(t.TempDir(), "allocations.json")
}

func TestCredentialsUseTURNRESTAndRateLimit(t *testing.T) {
	server, err := NewServer(testConfig(t))
	if err != nil {
		t.Fatal(err)
	}
	fixed := time.Date(2026, 8, 4, 10, 0, 0, 0, time.UTC)
	server.now = func() time.Time { return fixed }
	handler := server.Handler()

	response := requestJSON(t, handler, http.MethodPost, "/v1/credentials", testClientToken, `{"device_id":"xiaomi-12","session_id":"session-1"}`)
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
	var credential map[string]any
	if err := json.Unmarshal(response.Body.Bytes(), &credential); err != nil {
		t.Fatal(err)
	}
	username := credential["username"].(string)
	mac := hmac.New(sha1.New, []byte(server.cfg.TurnSecret))
	if _, err := mac.Write([]byte(username)); err != nil {
		t.Fatal(err)
	}
	wantPassword := base64.StdEncoding.EncodeToString(mac.Sum(nil))
	if credential["password"] != wantPassword {
		t.Fatalf("password does not match TURN REST HMAC")
	}

	_ = requestJSON(t, handler, http.MethodPost, "/v1/credentials", testClientToken, `{"device_id":"xiaomi-12","session_id":"session-1"}`)
	limited := requestJSON(t, handler, http.MethodPost, "/v1/credentials", testClientToken, `{"device_id":"xiaomi-12","session_id":"session-1"}`)
	if limited.Code != http.StatusTooManyRequests {
		t.Fatalf("rate-limit status = %d", limited.Code)
	}
}

func TestStorageFailuresFailClosed(t *testing.T) {
	server, err := NewServer(testConfig(t))
	if err != nil {
		t.Fatal(err)
	}
	server.store = failingStore{}
	handler := server.Handler()
	credentialBody := "{\"device_id\":\"device\",\"session_id\":\"session\"}"
	usageBody := "{\"event_id\":\"event\",\"device_id\":\"device\",\"session_id\":\"session\",\"kind\":\"start\"}"
	for name, response := range map[string]*httptest.ResponseRecorder{
		"ready":       requestJSON(t, handler, http.MethodGet, "/readyz", "", ""),
		"credentials": requestJSON(t, handler, http.MethodPost, "/v1/credentials", testClientToken, credentialBody),
		"usage":       requestJSON(t, handler, http.MethodPost, "/v1/usage", testUsageToken, usageBody),
		"revoke":      requestJSON(t, handler, http.MethodPost, "/v1/devices/device/revoke", testAdminToken, "{}"),
		"metrics":     requestJSON(t, handler, http.MethodGet, "/metrics", testMetricsToken, ""),
	} {
		if response.Code != http.StatusServiceUnavailable {
			t.Fatalf("%s status=%d body=%s", name, response.Code, response.Body.String())
		}
	}
}

func TestCredentialsUseStableDeviceQuotaPrincipalAcrossSessionsAndExpiries(t *testing.T) {
	cfg := testConfig(t)
	cfg.CredentialRequestsPerMinute = 10
	server, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 8, 5, 10, 0, 0, 0, time.UTC)
	server.now = func() time.Time { return now }
	issue := func(sessionID string) string {
		body := fmt.Sprintf(`{"device_id":"device-1","session_id":"%s"}`, sessionID)
		response := requestJSON(t, server.Handler(), http.MethodPost, "/v1/credentials", testClientToken, body)
		if response.Code != http.StatusOK {
			t.Fatalf("credential = %d: %s", response.Code, response.Body.String())
		}
		var credential map[string]any
		if err := json.Unmarshal(response.Body.Bytes(), &credential); err != nil {
			t.Fatal(err)
		}
		return credential["username"].(string)
	}
	first := issue("session-1")
	now = now.Add(time.Second)
	second := issue("session-2")
	if first == second {
		t.Fatal("test did not produce distinct credential expiries")
	}
	for _, username := range []string{first, second} {
		parts := strings.Split(username, ":")
		if len(parts) != 2 || parts[1] != "device-1" {
			t.Fatalf("username %q does not map to one stable device quota principal", username)
		}
		if strings.Contains(username, "session-") {
			t.Fatalf("username %q leaks session into coturn quota principal", username)
		}
	}
}

func TestCredentialsRequireAuthorityAdmissionInProduction(t *testing.T) {
	var admitted relayAdmissionRequest
	authority := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/readyz" {
			writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
			return
		}
		if r.URL.Path != "/v1/relay/admissions" {
			t.Fatalf("unexpected authority path %s", r.URL.Path)
		}
		if !authorized(r, testAuthorityToken) {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		if err := json.NewDecoder(r.Body).Decode(&admitted); err != nil {
			t.Fatalf("decode authority admission: %v", err)
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	defer authority.Close()

	cfg := testConfig(t)
	cfg.CredentialRequestsPerMinute = 10
	useProductionAuthority(t, &cfg, authority.URL)
	server, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	response := requestJSON(t, server.Handler(), http.MethodPost, "/v1/credentials", testClientToken, `{"device_id":"device-1","session_id":"session-1","allocation_id":"allocation-1"}`)
	if response.Code != http.StatusOK {
		t.Fatalf("credential status = %d: %s", response.Code, response.Body.String())
	}
	if admitted != (relayAdmissionRequest{DeviceID: "device-1", SessionID: "session-1", AllocationID: "allocation-1", SourceID: "turn-node-1"}) {
		t.Fatalf("authority admission = %#v", admitted)
	}
	registry, err := readAllocationRegistry(cfg.AllocationRegistryFile, cfg.AuthoritySourceID)
	if err != nil {
		t.Fatal(err)
	}
	if len(registry.Allocations) != 1 {
		t.Fatalf("registry allocations = %#v", registry.Allocations)
	}
	entry := registry.Allocations[0]
	if entry.AllocationID != "allocation-1" || entry.DeviceID != "device-1" || entry.SessionID != "session-1" || !strings.HasSuffix(entry.Username, ":device-1") {
		t.Fatalf("registry entry = %#v", entry)
	}
	ready := requestJSON(t, server.Handler(), http.MethodGet, "/readyz", "", "")
	if ready.Code != http.StatusOK {
		t.Fatalf("ready status = %d: %s", ready.Code, ready.Body.String())
	}
}

func TestCredentialsFailClosedWhenAllocationRegistryCannotBeWritten(t *testing.T) {
	authority := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/readyz" {
			writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
			return
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	defer authority.Close()
	cfg := testConfig(t)
	cfg.CredentialRequestsPerMinute = 10
	useProductionAuthority(t, &cfg, authority.URL)
	cfg.AllocationRegistryFile = t.TempDir()
	server, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	response := requestJSON(t, server.Handler(), http.MethodPost, "/v1/credentials", testClientToken, `{"device_id":"device-1","session_id":"session-1","allocation_id":"allocation-1"}`)
	if response.Code != http.StatusServiceUnavailable || !strings.Contains(response.Body.String(), "state storage unavailable") {
		t.Fatalf("registry failure status = %d: %s", response.Code, response.Body.String())
	}
}

func TestReadyFailsClosedWhenAuthorityUnavailable(t *testing.T) {
	authority := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer authority.Close()
	cfg := testConfig(t)
	useProductionAuthority(t, &cfg, authority.URL)
	server, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	ready := requestJSON(t, server.Handler(), http.MethodGet, "/readyz", "", "")
	if ready.Code != http.StatusServiceUnavailable || !strings.Contains(ready.Body.String(), "authority unavailable") {
		t.Fatalf("ready status = %d: %s", ready.Code, ready.Body.String())
	}
}

func TestReadyFailsClosedWhenAllocationRegistryUnavailable(t *testing.T) {
	authority := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	}))
	defer authority.Close()
	cfg := testConfig(t)
	useProductionAuthority(t, &cfg, authority.URL)
	cfg.AllocationRegistryFile = t.TempDir()
	server, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	ready := requestJSON(t, server.Handler(), http.MethodGet, "/readyz", "", "")
	if ready.Code != http.StatusServiceUnavailable || !strings.Contains(ready.Body.String(), "allocation registry unavailable") {
		t.Fatalf("ready status = %d: %s", ready.Code, ready.Body.String())
	}
}

func TestCredentialsFailClosedWhenAuthorityIsUnavailable(t *testing.T) {
	authority := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	authority.Close()
	cfg := testConfig(t)
	useProductionAuthority(t, &cfg, authority.URL)
	server, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	response := requestJSON(t, server.Handler(), http.MethodPost, "/v1/credentials", testClientToken, `{"device_id":"device-1","session_id":"session-1","allocation_id":"allocation-1"}`)
	if response.Code != http.StatusBadGateway || !strings.Contains(response.Body.String(), ErrAuthorityUnavailable.Error()) {
		t.Fatalf("unavailable authority status = %d: %s", response.Code, response.Body.String())
	}
}

func TestCredentialsMapAuthorityPolicyRejections(t *testing.T) {
	for name, tc := range map[string]struct {
		authorityStatus int
		wantStatus      int
		wantBody        string
	}{
		"revoked":     {authorityStatus: http.StatusForbidden, wantStatus: http.StatusForbidden, wantBody: ErrDeviceRevoked.Error()},
		"unknown":     {authorityStatus: http.StatusNotFound, wantStatus: http.StatusForbidden, wantBody: ErrDeviceRevoked.Error()},
		"quota":       {authorityStatus: http.StatusTooManyRequests, wantStatus: http.StatusTooManyRequests, wantBody: ErrQuotaExceeded.Error()},
		"conflict":    {authorityStatus: http.StatusConflict, wantStatus: http.StatusConflict, wantBody: ErrConflict.Error()},
		"bad_gateway": {authorityStatus: http.StatusOK, wantStatus: http.StatusBadGateway, wantBody: ErrAuthorityUnavailable.Error()},
	} {
		t.Run(name, func(t *testing.T) {
			authority := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(tc.authorityStatus)
			}))
			defer authority.Close()
			cfg := testConfig(t)
			useProductionAuthority(t, &cfg, authority.URL)
			server, err := NewServer(cfg)
			if err != nil {
				t.Fatal(err)
			}
			response := requestJSON(t, server.Handler(), http.MethodPost, "/v1/credentials", testClientToken, `{"device_id":"device-1","session_id":"session-1","allocation_id":"allocation-1"}`)
			if response.Code != tc.wantStatus || !strings.Contains(response.Body.String(), tc.wantBody) {
				t.Fatalf("status = %d body = %s, want %d containing %q", response.Code, response.Body.String(), tc.wantStatus, tc.wantBody)
			}
		})
	}
}

func TestCredentialsRequireAllocationIDInProductionAuthorityMode(t *testing.T) {
	cfg := testConfig(t)
	useProductionAuthority(t, &cfg, "http://127.0.0.1:1")
	server, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	response := requestJSON(t, server.Handler(), http.MethodPost, "/v1/credentials", testClientToken, `{"device_id":"device-1","session_id":"session-1"}`)
	if response.Code != http.StatusBadRequest || !strings.Contains(response.Body.String(), "allocation_id") {
		t.Fatalf("missing allocation status = %d: %s", response.Code, response.Body.String())
	}
}

func TestUsageRequiresAuthorityAdmissionInProduction(t *testing.T) {
	var admitted relayAdmissionRequest
	authority := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/relay/admissions" {
			t.Fatalf("unexpected authority path %s", r.URL.Path)
		}
		if !authorized(r, testAuthorityToken) {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		if err := json.NewDecoder(r.Body).Decode(&admitted); err != nil {
			t.Fatalf("decode authority admission: %v", err)
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	defer authority.Close()

	cfg := testConfig(t)
	useProductionAuthority(t, &cfg, authority.URL)
	server, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	body := `{"event_id":"usage-1","device_id":"device-1","session_id":"session-1","allocation_id":"allocation-1","kind":"start","ingress_bytes":10,"egress_bytes":20}`
	response := requestJSON(t, server.Handler(), http.MethodPost, "/v1/usage", testUsageToken, body)
	if response.Code != http.StatusAccepted {
		t.Fatalf("usage status = %d: %s", response.Code, response.Body.String())
	}
	if admitted != (relayAdmissionRequest{DeviceID: "device-1", SessionID: "session-1", AllocationID: "allocation-1", SourceID: "turn-node-1"}) {
		t.Fatalf("authority admission = %#v", admitted)
	}
}

func TestUsageRejectsInvalidKindBeforeAuthorityAdmission(t *testing.T) {
	authorityCalls := 0
	authority := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		authorityCalls++
		w.WriteHeader(http.StatusNoContent)
	}))
	defer authority.Close()

	cfg := testConfig(t)
	useProductionAuthority(t, &cfg, authority.URL)
	server, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	body := "{\"event_id\":\"usage-1\",\"device_id\":\"device-1\",\"session_id\":\"session-1\",\"allocation_id\":\"allocation-1\",\"kind\":\"bogus\",\"ingress_bytes\":10,\"egress_bytes\":20}"
	response := requestJSON(t, server.Handler(), http.MethodPost, "/v1/usage", testUsageToken, body)
	if response.Code != http.StatusBadRequest || !strings.Contains(response.Body.String(), "unsupported event kind") {
		t.Fatalf("invalid kind status = %d: %s", response.Code, response.Body.String())
	}
	if authorityCalls != 0 {
		t.Fatalf("invalid usage kind reached authority %d times", authorityCalls)
	}
}

func TestUsageDuplicateRetryAfterAuthorityRevocationDoesNotReauthorize(t *testing.T) {
	authorityCalls := 0
	revoked := false
	authority := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/relay/admissions" {
			t.Fatalf("unexpected authority path %s", r.URL.Path)
		}
		authorityCalls++
		if !authorized(r, testAuthorityToken) {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		if revoked {
			w.WriteHeader(http.StatusForbidden)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	defer authority.Close()

	cfg := testConfig(t)
	useProductionAuthority(t, &cfg, authority.URL)
	server, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	body := "{\"event_id\":\"usage-1\",\"device_id\":\"device-1\",\"session_id\":\"session-1\",\"allocation_id\":\"allocation-1\",\"kind\":\"start\",\"ingress_bytes\":10,\"egress_bytes\":20}"
	if response := requestJSON(t, server.Handler(), http.MethodPost, "/v1/usage", testUsageToken, body); response.Code != http.StatusAccepted {
		t.Fatalf("usage status = %d: %s", response.Code, response.Body.String())
	}
	revoked = true
	if response := requestJSON(t, server.Handler(), http.MethodPost, "/v1/usage", testUsageToken, body); response.Code != http.StatusOK || !strings.Contains(response.Body.String(), "duplicate") {
		t.Fatalf("duplicate retry after revoke = %d: %s", response.Code, response.Body.String())
	}
	if authorityCalls != 1 {
		t.Fatalf("duplicate retry reauthorized %d times", authorityCalls)
	}
}

func TestUsageDuplicateEventIDWithChangedPayloadReturnsBadRequest(t *testing.T) {
	authorityCalls := 0
	authority := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/relay/admissions" {
			t.Fatalf("unexpected authority path %s", r.URL.Path)
		}
		authorityCalls++
		if !authorized(r, testAuthorityToken) {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	defer authority.Close()

	cfg := testConfig(t)
	useProductionAuthority(t, &cfg, authority.URL)
	server, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	handler := server.Handler()
	original := `{"event_id":"usage-1","device_id":"device-1","session_id":"session-1","allocation_id":"allocation-1","kind":"start","ingress_bytes":10,"egress_bytes":20}`
	changed := `{"event_id":"usage-1","device_id":"device-1","session_id":"session-1","allocation_id":"allocation-1","kind":"start","ingress_bytes":10,"egress_bytes":21}`

	if response := requestJSON(t, handler, http.MethodPost, "/v1/usage", testUsageToken, original); response.Code != http.StatusAccepted {
		t.Fatalf("initial usage status = %d: %s", response.Code, response.Body.String())
	}
	response := requestJSON(t, handler, http.MethodPost, "/v1/usage", testUsageToken, changed)
	if response.Code != http.StatusBadRequest || !strings.Contains(response.Body.String(), ErrInvalidEvent.Error()) {
		t.Fatalf("changed duplicate status = %d: %s", response.Code, response.Body.String())
	}
	if authorityCalls != 1 {
		t.Fatalf("changed duplicate reauthorized %d times", authorityCalls)
	}
}

func TestUsageFailsClosedAfterAuthorityRevocation(t *testing.T) {
	authority := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/relay/admissions" {
			t.Fatalf("unexpected authority path %s", r.URL.Path)
		}
		if !authorized(r, testAuthorityToken) {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		w.WriteHeader(http.StatusForbidden)
	}))
	defer authority.Close()

	cfg := testConfig(t)
	useProductionAuthority(t, &cfg, authority.URL)
	server, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	body := `{"event_id":"usage-after-revoke","device_id":"device-1","session_id":"session-1","allocation_id":"allocation-1","kind":"start","ingress_bytes":10,"egress_bytes":20}`
	response := requestJSON(t, server.Handler(), http.MethodPost, "/v1/usage", testUsageToken, body)
	if response.Code != http.StatusForbidden || !strings.Contains(response.Body.String(), ErrDeviceRevoked.Error()) {
		t.Fatalf("revoked usage status = %d: %s", response.Code, response.Body.String())
	}
	ingress, egress, sessions, err := server.store.Snapshot(context.Background(), time.Now(), "device-1")
	if err != nil {
		t.Fatal(err)
	}
	if ingress != 0 || egress != 0 || sessions != 0 {
		t.Fatalf("revoked usage mutated local store: ingress=%d egress=%d sessions=%d", ingress, egress, sessions)
	}
}

func TestUsageRequiresAllocationIDInProductionAuthorityMode(t *testing.T) {
	cfg := testConfig(t)
	useProductionAuthority(t, &cfg, "http://127.0.0.1:1")
	server, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	response := requestJSON(t, server.Handler(), http.MethodPost, "/v1/usage", testUsageToken, `{"event_id":"usage-1","device_id":"device-1","session_id":"session-1","kind":"start"}`)
	if response.Code != http.StatusBadRequest || !strings.Contains(response.Body.String(), "allocation_id") {
		t.Fatalf("missing allocation status = %d: %s", response.Code, response.Body.String())
	}
}

func TestUsageEnforcesSessionsQuotaAndIdempotency(t *testing.T) {
	server, err := NewServer(testConfig(t))
	if err != nil {
		t.Fatal(err)
	}
	handler := server.Handler()
	start := `{"event_id":"event-1","device_id":"device-1","session_id":"session-1","kind":"start","ingress_bytes":10,"egress_bytes":20}`
	if got := requestJSON(t, handler, http.MethodPost, "/v1/usage", testUsageToken, start); got.Code != http.StatusAccepted {
		t.Fatalf("start = %d: %s", got.Code, got.Body.String())
	}
	if got := requestJSON(t, handler, http.MethodPost, "/v1/usage", testUsageToken, start); got.Code != http.StatusOK || !strings.Contains(got.Body.String(), "duplicate") {
		t.Fatalf("duplicate = %d: %s", got.Code, got.Body.String())
	}
	second := `{"event_id":"event-2","device_id":"device-1","session_id":"session-2","kind":"start","ingress_bytes":0,"egress_bytes":0}`
	if got := requestJSON(t, handler, http.MethodPost, "/v1/usage", testUsageToken, second); got.Code != http.StatusTooManyRequests {
		t.Fatalf("session limit = %d", got.Code)
	}
	oversized := `{"event_id":"event-3","device_id":"device-1","session_id":"session-1","kind":"update","ingress_bytes":0,"egress_bytes":801}`
	if got := requestJSON(t, handler, http.MethodPost, "/v1/usage", testUsageToken, oversized); got.Code != http.StatusBadRequest {
		t.Fatalf("event byte limit = %d", got.Code)
	}
}

func TestUsagePersistsAndMetricsRequireAuthentication(t *testing.T) {
	cfg := testConfig(t)
	server, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	event := `{"event_id":"event-1","device_id":"device-1","session_id":"session-1","kind":"start","ingress_bytes":100,"egress_bytes":200}`
	if got := requestJSON(t, server.Handler(), http.MethodPost, "/v1/usage", testUsageToken, event); got.Code != http.StatusAccepted {
		t.Fatalf("usage = %d", got.Code)
	}
	restarted, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	ingress, egress, sessions, err := restarted.store.Snapshot(context.Background(), time.Now(), "device-1")
	if err != nil {
		t.Fatal(err)
	}
	if ingress != 100 || egress != 200 || sessions != 1 {
		t.Fatalf("restored = %d/%d/%d", ingress, egress, sessions)
	}
	if got := requestJSON(t, restarted.Handler(), http.MethodGet, "/metrics", "", ""); got.Code != http.StatusUnauthorized {
		t.Fatalf("unauthenticated metrics = %d", got.Code)
	}
	if got := requestJSON(t, restarted.Handler(), http.MethodGet, "/metrics", testUsageToken, ""); got.Code != http.StatusUnauthorized {
		t.Fatalf("usage token must not scrape metrics: %d", got.Code)
	}
	got := requestJSON(t, restarted.Handler(), http.MethodGet, "/metrics", testMetricsToken, "")
	if got.Code != http.StatusOK || !strings.Contains(got.Body.String(), "vibescreen_relay_active_sessions 1") {
		t.Fatalf("metrics = %d: %s", got.Code, got.Body.String())
	}
	if !strings.Contains(got.Body.String(), "# TYPE vibescreen_relay_estimated_daily_egress_microcents gauge") {
		t.Fatalf("daily cost must be exported as a gauge: %s", got.Body.String())
	}
}

func TestAuthorizationRequiresExactBearerScheme(t *testing.T) {
	server, err := NewServer(testConfig(t))
	if err != nil {
		t.Fatal(err)
	}
	for _, value := range []string{
		"bearer " + testClientToken,
		"Basic " + testClientToken,
		"prefixBearer " + testClientToken,
		"Bearer  " + testClientToken,
		"Bearer " + testClientToken + " trailing",
	} {
		request := httptest.NewRequest(http.MethodPost, "/v1/credentials", strings.NewReader(`{"device_id":"d","session_id":"s"}`))
		request.Header.Set("Authorization", value)
		response := httptest.NewRecorder()
		server.Handler().ServeHTTP(response, request)
		if response.Code != http.StatusUnauthorized {
			t.Fatalf("authorization %q returned %d", value, response.Code)
		}
	}
}

func TestRejectsUnknownJSONAndUnauthorizedRequests(t *testing.T) {
	server, err := NewServer(testConfig(t))
	if err != nil {
		t.Fatal(err)
	}
	unknown := requestJSON(t, server.Handler(), http.MethodPost, "/v1/credentials", testClientToken, `{"device_id":"d","session_id":"s","unexpected":true}`)
	if unknown.Code != http.StatusBadRequest {
		t.Fatalf("unknown-field status = %d", unknown.Code)
	}
	unauthorized := requestJSON(t, server.Handler(), http.MethodPost, "/v1/credentials", "wrong", `{"device_id":"d","session_id":"s"}`)
	if unauthorized.Code != http.StatusUnauthorized {
		t.Fatalf("unauthorized status = %d", unauthorized.Code)
	}
}

func TestRevokedDeviceCannotReceiveCredentialsOrReportUsage(t *testing.T) {
	cfg := testConfig(t)
	server, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	handler := server.Handler()
	start := `{"event_id":"event-before-revoke","device_id":"device-1","session_id":"session-1","kind":"start","ingress_bytes":10,"egress_bytes":20}`
	if got := requestJSON(t, handler, http.MethodPost, "/v1/usage", testUsageToken, start); got.Code != http.StatusAccepted {
		t.Fatalf("usage before revoke = %d: %s", got.Code, got.Body.String())
	}
	if got := requestJSON(t, handler, http.MethodPost, "/v1/devices/device-1/revoke", testAdminToken, "{}"); got.Code != http.StatusOK {
		t.Fatalf("revoke = %d: %s", got.Code, got.Body.String())
	}
	credential := requestJSON(t, handler, http.MethodPost, "/v1/credentials", testClientToken, `{"device_id":"device-1","session_id":"session-1"}`)
	if credential.Code != http.StatusForbidden {
		t.Fatalf("credential after revoke = %d", credential.Code)
	}
	if duplicate := requestJSON(t, handler, http.MethodPost, "/v1/usage", testUsageToken, start); duplicate.Code != http.StatusOK || !strings.Contains(duplicate.Body.String(), "duplicate") {
		t.Fatalf("accepted usage retry after revoke = %d: %s", duplicate.Code, duplicate.Body.String())
	}
	for _, event := range []string{
		`{"event_id":"event-start-after-revoke","device_id":"device-1","session_id":"session-2","kind":"start","ingress_bytes":0,"egress_bytes":0}`,
		`{"event_id":"event-update-after-revoke","device_id":"device-1","session_id":"session-1","kind":"update","ingress_bytes":1,"egress_bytes":1}`,
	} {
		got := requestJSON(t, handler, http.MethodPost, "/v1/usage", testUsageToken, event)
		if got.Code != http.StatusForbidden || !strings.Contains(got.Body.String(), ErrDeviceRevoked.Error()) {
			t.Fatalf("usage after revoke = %d: %s", got.Code, got.Body.String())
		}
	}
	metrics := requestJSON(t, handler, http.MethodGet, "/metrics", testMetricsToken, "")
	if metrics.Code != http.StatusOK || !strings.Contains(metrics.Body.String(), "vibescreen_relay_revoked_device_requests_rejected_total 3") {
		t.Fatalf("revocation metrics = %d: %s", metrics.Code, metrics.Body.String())
	}
	restarted, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	revoked, err := restarted.store.IsRevoked(context.Background(), "device-1")
	if err != nil {
		t.Fatal(err)
	}
	if !revoked {
		t.Fatal("revocation was not restored")
	}
	update := `{"event_id":"event-after-restart","device_id":"device-1","session_id":"session-1","kind":"update","ingress_bytes":1,"egress_bytes":1}`
	if got := requestJSON(t, restarted.Handler(), http.MethodPost, "/v1/usage", testUsageToken, update); got.Code != http.StatusForbidden {
		t.Fatalf("usage after restart = %d: %s", got.Code, got.Body.String())
	}
}

func TestCredentialRateTableHasHardCardinalityBound(t *testing.T) {
	server, err := NewServer(testConfig(t))
	if err != nil {
		t.Fatal(err)
	}
	for index := 0; index < maxRateEntries; index++ {
		if !server.allowCredential(fmt.Sprintf("device-%d", index)) {
			t.Fatalf("entry %d rejected before bound", index)
		}
	}
	if server.allowCredential("one-device-too-many") {
		t.Fatal("rate table accepted an entry beyond the hard bound")
	}
}

func requestJSON(t *testing.T, handler http.Handler, method, path, token, body string) *httptest.ResponseRecorder {
	t.Helper()
	request := httptest.NewRequest(method, path, bytes.NewBufferString(body))
	if token != "" {
		request.Header.Set("Authorization", "Bearer "+token)
	}
	request.Header.Set("Content-Type", "application/json")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	return response
}
