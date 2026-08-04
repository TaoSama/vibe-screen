package relay

import (
	"bytes"
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

const (
	testClientToken  = "client-token-at-least-thirty-two-bytes"
	testUsageToken   = "usage-token-at-least-thirty-two-bytes-"
	testMetricsToken = "metrics-token-at-least-thirty-two-bytes"
	testAdminToken   = "admin-token-at-least-thirty-two-bytes-"
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
	ingress, egress, sessions := restarted.store.Snapshot(time.Now(), "device-1")
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

func TestRevokedDeviceCannotReceiveCredentials(t *testing.T) {
	cfg := testConfig(t)
	server, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	handler := server.Handler()
	if got := requestJSON(t, handler, http.MethodPost, "/v1/devices/device-1/revoke", testAdminToken, "{}"); got.Code != http.StatusOK {
		t.Fatalf("revoke = %d: %s", got.Code, got.Body.String())
	}
	credential := requestJSON(t, handler, http.MethodPost, "/v1/credentials", testClientToken, `{"device_id":"device-1","session_id":"session-1"}`)
	if credential.Code != http.StatusForbidden {
		t.Fatalf("credential after revoke = %d", credential.Code)
	}
	restarted, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	if !restarted.store.IsRevoked("device-1") {
		t.Fatal("revocation was not restored")
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
