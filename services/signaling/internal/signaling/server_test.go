package signaling

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strconv"
	"strings"
	"testing"
	"time"
)

const (
	testIssuerToken  = "issuer-token-with-at-least-32-characters"
	testMetricsToken = "metrics-token-with-at-least-32-characters"
)

func testConfig() Config {
	return Config{
		ListenAddress: "127.0.0.1:0", SessionTTLSeconds: 60, MaxSessionTTLSeconds: 120,
		MaxActiveSessions: 10, SessionCreatesPerMinute: 20, MessagesPerMinute: 20,
		MaxRequestBodyBytes: 2048, MaxSDPBytes: 1024, MaxCandidateBytes: 512,
		MaxCandidatesPerRole: 2, MaxWaitSeconds: 1, MaxWaitersPerRole: 1,
		CleanupIntervalSeconds: 1, AuthorityMode: AuthorityModeLocalDevelopment,
		StoreBackend: StoreBackendMemory,
		IssuerToken:  testIssuerToken, MetricsToken: testMetricsToken,
	}
}

func testServerWithStore(t *testing.T, cfg Config, store Store) *Server {
	t.Helper()
	return &Server{cfg: cfg, store: store, now: time.Now}
}

func localMemoryStoreForTest(t *testing.T, service *Server) *MemoryStore {
	t.Helper()
	store, ok := service.store.(*MemoryStore)
	if !ok {
		t.Fatalf("server store = %T, want *MemoryStore", service.store)
	}
	return store
}

func TestHTTPRendezvousAndRoleIsolation(t *testing.T) {
	service, err := NewServer(testConfig())
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()

	created := createSessionForTest(t, handler, "create-one", 0)
	replayed := createSessionForTest(t, handler, "create-one", 0)
	if created != replayed {
		t.Fatalf("idempotent create changed response: %#v != %#v", created, replayed)
	}

	postMessageForTest(t, handler, created.SessionID, created.DeviceToken,
		MessageRequest{MessageID: "wrong-role", Type: MessageOffer, SDP: "v=0\r\n"}, http.StatusConflict)
	offer := postMessageForTest(t, handler, created.SessionID, created.HostToken,
		MessageRequest{MessageID: "offer-1", Type: MessageOffer, SDP: "v=0\r\na=fingerprint:sha-256 AA\r\n"}, http.StatusCreated)
	if offer.Sequence != 1 || offer.SenderRole != RoleHost {
		t.Fatalf("unexpected offer event: %#v", offer)
	}
	postMessageForTest(t, handler, created.SessionID, created.HostToken,
		MessageRequest{MessageID: "offer-1", Type: MessageOffer, SDP: offer.SDP}, http.StatusOK)
	postMessageForTest(t, handler, created.SessionID, created.HostToken,
		MessageRequest{MessageID: "offer-1", Type: MessageOffer, SDP: "v=0-different"}, http.StatusConflict)

	deviceEvents := pollForTest(t, handler, created.SessionID, created.DeviceToken, 0, 0, http.StatusOK)
	if len(deviceEvents.Events) != 1 || deviceEvents.Events[0].Type != MessageOffer || deviceEvents.NextCursor != 1 {
		t.Fatalf("device did not receive offer: %#v", deviceEvents)
	}
	deviceEvents = pollForTest(t, handler, created.SessionID, created.DeviceToken, 1, 0, http.StatusOK)
	if len(deviceEvents.Events) != 0 || deviceEvents.NextCursor != 1 {
		t.Fatalf("immediate empty poll blocked or advanced: %#v", deviceEvents)
	}
	answer := postMessageForTest(t, handler, created.SessionID, created.DeviceToken,
		MessageRequest{MessageID: "answer-1", Type: MessageAnswer, SDP: "v=0\r\na=fingerprint:sha-256 BB\r\n"}, http.StatusCreated)
	if answer.Sequence != 2 {
		t.Fatalf("unexpected answer sequence: %d", answer.Sequence)
	}
	hostEvents := pollForTest(t, handler, created.SessionID, created.HostToken, 1, 0, http.StatusOK)
	if len(hostEvents.Events) != 1 || hostEvents.Events[0].Type != MessageAnswer || hostEvents.NextCursor != 2 {
		t.Fatalf("host did not receive answer: %#v", hostEvents)
	}

	postMessageForTest(t, handler, created.SessionID, created.HostToken,
		MessageRequest{MessageID: "host-ice", Type: MessageICECandidate, Candidate: &ICECandidate{Candidate: "candidate:host", SDPMid: "0"}}, http.StatusCreated)
	deviceEvents = pollForTest(t, handler, created.SessionID, created.DeviceToken, 1, 0, http.StatusOK)
	if len(deviceEvents.Events) != 1 || deviceEvents.Events[0].Candidate.Candidate != "candidate:host" || deviceEvents.NextCursor != 3 {
		t.Fatalf("device did not receive host candidate: %#v", deviceEvents)
	}
	postMessageForTest(t, handler, created.SessionID, created.DeviceToken,
		MessageRequest{MessageID: "device-ice", Type: MessageICECandidate, Candidate: &ICECandidate{Candidate: "candidate:device", SDPMid: "0"}}, http.StatusCreated)
	hostEvents = pollForTest(t, handler, created.SessionID, created.HostToken, 2, 0, http.StatusOK)
	if len(hostEvents.Events) != 1 || hostEvents.Events[0].Candidate.Candidate != "candidate:device" || hostEvents.NextCursor != 4 {
		t.Fatalf("host did not receive device candidate: %#v", hostEvents)
	}

	pollForTest(t, handler, created.SessionID, "wrong-token", 0, 0, http.StatusNotFound)
	second := createSessionForTest(t, handler, "create-two", 0)
	pollForTest(t, handler, created.SessionID, second.HostToken, 0, 0, http.StatusNotFound)
}

func TestValidationLimitsAndProbes(t *testing.T) {
	cfg := testConfig()
	cfg.MaxCandidatesPerRole = 1
	service, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	handler := service.Handler()

	response := performRequest(t, handler, http.MethodGet, "/readyz", "", "")
	if response.Code != http.StatusServiceUnavailable {
		t.Fatalf("not-ready status = %d", response.Code)
	}
	service.SetReady(true)
	response = performRequest(t, handler, http.MethodGet, "/readyz", "", "")
	if response.Code != http.StatusOK {
		t.Fatalf("ready status = %d", response.Code)
	}
	response = performRequest(t, handler, http.MethodGet, "/metrics", "", "")
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("unauthorized metrics status = %d", response.Code)
	}
	response = performRequest(t, handler, http.MethodGet, "/metrics", testMetricsToken, "")
	if response.Code != http.StatusOK || !strings.Contains(response.Body.String(), "vibescreen_signaling_active_sessions") {
		t.Fatalf("metrics response = %d %q", response.Code, response.Body.String())
	}

	created := createSessionForTest(t, handler, "validation", 0)
	postMessageForTest(t, handler, created.SessionID, created.DeviceToken,
		MessageRequest{MessageID: "early-answer", Type: MessageAnswer, SDP: "v=0"}, http.StatusConflict)
	postMessageForTest(t, handler, created.SessionID, created.HostToken,
		MessageRequest{MessageID: "candidate-1", Type: MessageICECandidate, Candidate: &ICECandidate{Candidate: "candidate:one"}}, http.StatusCreated)
	postMessageForTest(t, handler, created.SessionID, created.HostToken,
		MessageRequest{MessageID: "candidate-2", Type: MessageICECandidate, Candidate: &ICECandidate{Candidate: "candidate:two"}}, http.StatusTooManyRequests)

	unknown := `{"message_id":"x","type":"end_of_candidates","payload":"forbidden"}`
	response = performRequest(t, handler, http.MethodPost, "/v1/sessions/"+created.SessionID+"/messages", created.HostToken, unknown)
	if response.Code != http.StatusBadRequest {
		t.Fatalf("unknown field status = %d", response.Code)
	}
	oversized := `{"message_id":"big","type":"offer","sdp":"` + strings.Repeat("x", cfg.MaxSDPBytes+1) + `"}`
	response = performRequest(t, handler, http.MethodPost, "/v1/sessions/"+created.SessionID+"/messages", created.HostToken, oversized)
	if response.Code != http.StatusBadRequest {
		t.Fatalf("oversized SDP status = %d", response.Code)
	}
	response = performRequest(t, handler, http.MethodGet, "/v1/sessions/"+created.SessionID+"/events?after=0&after=1", created.HostToken, "")
	if response.Code != http.StatusBadRequest {
		t.Fatalf("repeated query status = %d", response.Code)
	}
}

func TestAuthorizedRejectsEmptyExpectedToken(t *testing.T) {
	request := httptest.NewRequestWithContext(context.Background(), http.MethodGet, "/metrics", nil)
	if authorized(request, "") {
		t.Fatal("empty expected token authorized an empty request")
	}
}

func TestPollWakesForRemoteEventAndEnforcesWaiterLimit(t *testing.T) {
	service, err := NewServer(testConfig())
	if err != nil {
		t.Fatal(err)
	}
	created, _, err := service.store.Create(context.Background(), CreateSessionRequest{RequestID: "poll-test", TTL: time.Minute})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	result := make(chan []Event, 1)
	go func() {
		events, _, pollErr := service.store.PollAuthorized(ctx, created.SessionID, RoleDevice, 0, true)
		if pollErr != nil {
			result <- nil
			return
		}
		result <- events
	}()
	waitForWaiter(t, localMemoryStoreForTest(t, service), created.SessionID, RoleDevice)
	if _, _, err := service.store.PollAuthorized(context.Background(), created.SessionID, RoleDevice, 0, true); !errors.Is(err, ErrTooManyWaiters) {
		t.Fatalf("second waiter error = %v", err)
	}
	_, _, err = service.store.AddMessageAuthorized(context.Background(), created.SessionID, RoleHost, MessageRequest{MessageID: "wake", Type: MessageOffer, SDP: "v=0"})
	if err != nil {
		t.Fatal(err)
	}
	select {
	case events := <-result:
		if len(events) != 1 || events[0].MessageID != "wake" {
			t.Fatalf("unexpected wake events: %#v", events)
		}
	case <-time.After(time.Second):
		t.Fatal("poll did not wake")
	}
}

func TestPollFailsWhenSessionExpiresWhileWaiting(t *testing.T) {
	service, err := NewServer(testConfig())
	if err != nil {
		t.Fatal(err)
	}
	created, _, err := service.store.Create(context.Background(), CreateSessionRequest{RequestID: "expiring-poll", TTL: 25 * time.Millisecond})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	started := time.Now()
	_, _, err = service.store.PollAuthorized(ctx, created.SessionID, RoleHost, 0, true)
	if !errors.Is(err, ErrExpired) {
		t.Fatalf("poll expiration error = %v", err)
	}
	if elapsed := time.Since(started); elapsed > 250*time.Millisecond {
		t.Fatalf("expiration did not wake poll promptly: %s", elapsed)
	}
	removed := service.store.Cleanup()
	stats := service.store.Stats()
	if removed != 1 || stats.ActiveSessions != 0 {
		t.Fatalf("expired cleanup removed=%d active=%d", removed, stats.ActiveSessions)
	}
}

func TestInvalidateDestroysSessionAndRetainsRequestTombstoneUntilExpiry(t *testing.T) {
	store := NewMemoryStore(testConfig(), nil)
	now := time.Date(2026, time.August, 5, 12, 0, 0, 0, time.UTC)
	store.now = func() time.Time { return now }
	created, _, err := store.Create(context.Background(), CreateSessionRequest{RequestID: "invalidate-request", TTL: time.Minute})
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := store.AddMessageAuthorized(context.Background(), created.SessionID, RoleHost, MessageRequest{
		MessageID: "offer-before-invalidation", Type: MessageOffer, SDP: "v=0",
	}); err != nil {
		t.Fatal(err)
	}

	pollResult := make(chan error, 1)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	go func() {
		_, _, pollErr := store.PollAuthorized(ctx, created.SessionID, RoleDevice, 1, true)
		pollResult <- pollErr
	}()
	waitForWaiter(t, store, created.SessionID, RoleDevice)

	invalidated, err := store.Invalidate(context.Background(), created.SessionID)
	if err != nil || !invalidated {
		t.Fatalf("invalidate created session: invalidated=%t err=%v", invalidated, err)
	}
	select {
	case err := <-pollResult:
		if !errors.Is(err, ErrNotFound) {
			t.Fatalf("waiting poll error = %v, want ErrNotFound", err)
		}
	case <-time.After(250 * time.Millisecond):
		t.Fatal("invalidation did not wake waiting poll")
	}
	if _, err := store.Authorize(context.Background(), created.SessionID, created.HostToken); !errors.Is(err, ErrNotFound) {
		t.Fatalf("host token remained valid: %v", err)
	}
	if _, _, err := store.AddMessageAuthorized(context.Background(), created.SessionID, RoleDevice, MessageRequest{
		MessageID: "candidate-after-invalidation", Type: MessageICECandidate,
		Candidate: &ICECandidate{Candidate: "candidate:invalidated"},
	}); !errors.Is(err, ErrNotFound) {
		t.Fatalf("device token remained valid: %v", err)
	}
	if store.ActiveCount() != 0 {
		t.Fatalf("invalidated session counted as active: %d", store.ActiveCount())
	}
	current := store.sessions[created.SessionID]
	if current == nil || !current.invalidated || current.hostToken != "" || current.deviceToken != "" ||
		current.response.HostToken != "" || current.response.DeviceToken != "" || current.events != nil || current.messages != nil {
		t.Fatalf("sensitive session state was not destroyed: %#v", current)
	}
	if invalidated, err := store.Invalidate(context.Background(), created.SessionID); err != nil || invalidated {
		t.Fatalf("repeated invalidation: invalidated=%t err=%v", invalidated, err)
	}
	if _, _, err := store.Create(context.Background(), CreateSessionRequest{RequestID: "invalidate-request", TTL: time.Minute}); !errors.Is(err, ErrInvalidated) {
		t.Fatalf("request_id was reusable before expiry: %v", err)
	}

	now = now.Add(time.Minute)
	recreated, wasCreated, err := store.Create(context.Background(), CreateSessionRequest{RequestID: "invalidate-request", TTL: time.Minute})
	if err != nil || !wasCreated || recreated.SessionID == created.SessionID {
		t.Fatalf("request_id was not reusable after expiry: created=%t session=%#v err=%v", wasCreated, recreated, err)
	}
}

func TestHTTPAuthorityInvalidationRejectsRoleCredentialsAndIsIdempotent(t *testing.T) {
	service, err := NewServer(testConfig())
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()
	created := createSessionForTest(t, handler, "http-invalidation", 0)
	path := "/v1/sessions/" + created.SessionID

	if response := performRequest(t, handler, http.MethodDelete, path, created.HostToken, ""); response.Code != http.StatusUnauthorized {
		t.Fatalf("role credential invalidation status = %d", response.Code)
	}
	if response := performRequest(t, handler, http.MethodDelete, "/v1/sessions/not%20valid", testIssuerToken, ""); response.Code != http.StatusBadRequest {
		t.Fatalf("invalid session ID status = %d", response.Code)
	}
	if response := performRequest(t, handler, http.MethodDelete, path, testIssuerToken, ""); response.Code != http.StatusNoContent {
		t.Fatalf("authority invalidation status = %d: %s", response.Code, response.Body.String())
	}
	postMessageForTest(t, handler, created.SessionID, created.HostToken,
		MessageRequest{MessageID: "old-offer", Type: MessageOffer, SDP: "v=0"}, http.StatusNotFound)
	pollForTest(t, handler, created.SessionID, created.DeviceToken, 0, 0, http.StatusNotFound)
	if response := performRequest(t, handler, http.MethodDelete, path, testIssuerToken, ""); response.Code != http.StatusNoContent {
		t.Fatalf("repeated invalidation status = %d", response.Code)
	}
	body, err := json.Marshal(createSessionRequest{RequestID: "http-invalidation"})
	if err != nil {
		t.Fatal(err)
	}
	if response := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, string(body)); response.Code != http.StatusConflict {
		t.Fatalf("invalidated request replay status = %d: %s", response.Code, response.Body.String())
	}
	metrics := performRequest(t, handler, http.MethodGet, "/metrics", testMetricsToken, "")
	if metrics.Code != http.StatusOK ||
		!strings.Contains(metrics.Body.String(), "vibescreen_signaling_sessions_invalidated_total 1") ||
		!strings.Contains(metrics.Body.String(), "vibescreen_signaling_active_sessions 0") ||
		!strings.Contains(metrics.Body.String(), "vibescreen_signaling_invalidated_session_tombstones 1") ||
		!strings.Contains(metrics.Body.String(), "vibescreen_signaling_reserved_session_records 1") {
		t.Fatalf("invalidation metric = %d %q", metrics.Code, metrics.Body.String())
	}
}

func TestTombstoneCapacityMetricsExplainCreateRejection(t *testing.T) {
	cfg := testConfig()
	cfg.MaxActiveSessions = 1
	service, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	handler := service.Handler()
	created := createSessionForTest(t, handler, "capacity-tombstone", 0)
	if response := performRequest(t, handler, http.MethodDelete,
		"/v1/sessions/"+created.SessionID, testIssuerToken, ""); response.Code != http.StatusNoContent {
		t.Fatalf("invalidate status = %d", response.Code)
	}
	body, err := json.Marshal(createSessionRequest{RequestID: "capacity-new"})
	if err != nil {
		t.Fatal(err)
	}
	if response := performRequest(t, handler, http.MethodPost,
		"/v1/sessions", testIssuerToken, string(body)); response.Code != http.StatusTooManyRequests {
		t.Fatalf("capacity status = %d: %s", response.Code, response.Body.String())
	}
	metrics := performRequest(t, handler, http.MethodGet, "/metrics", testMetricsToken, "")
	for _, expected := range []string{
		"vibescreen_signaling_active_sessions 0",
		"vibescreen_signaling_invalidated_session_tombstones 1",
		"vibescreen_signaling_reserved_session_records 1",
	} {
		if !strings.Contains(metrics.Body.String(), expected) {
			t.Fatalf("capacity metric %q missing: %s", expected, metrics.Body.String())
		}
	}
}

func TestMessageRateLimit(t *testing.T) {
	cfg := testConfig()
	cfg.MessagesPerMinute = 1
	service, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	handler := service.Handler()
	created := createSessionForTest(t, handler, "message-rate", 0)
	postMessageForTest(t, handler, created.SessionID, created.HostToken,
		MessageRequest{MessageID: "offer-rate", Type: MessageOffer, SDP: "v=0"}, http.StatusCreated)
	postMessageForTest(t, handler, created.SessionID, created.HostToken,
		MessageRequest{MessageID: "candidate-rate", Type: MessageICECandidate, Candidate: &ICECandidate{Candidate: "candidate:rate"}}, http.StatusTooManyRequests)
}

func TestCreateSessionRateLimitIsStoreOwned(t *testing.T) {
	cfg := testConfig()
	cfg.SessionCreatesPerMinute = 1
	service, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	handler := service.Handler()

	createSessionForTest(t, handler, "create-rate-1", 0)
	firstReplay := createSessionForTest(t, handler, "create-rate-1", 0)
	secondReplay := createSessionForTest(t, handler, "create-rate-1", 0)
	if firstReplay != secondReplay {
		t.Fatalf("idempotent replay consumed create quota: %#v != %#v", firstReplay, secondReplay)
	}
	body, err := json.Marshal(createSessionRequest{RequestID: "create-rate-2"})
	if err != nil {
		t.Fatal(err)
	}
	response := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, string(body))
	if response.Code != http.StatusTooManyRequests {
		t.Fatalf("create rate status=%d body=%s", response.Code, response.Body.String())
	}
}

func TestCreateRateDeviceIDs(t *testing.T) {
	tests := []struct {
		name    string
		request CreateSessionRequest
		want    []string
	}{
		{
			name:    "local development",
			request: CreateSessionRequest{},
			want:    []string{localDevelopmentDeviceID},
		},
		{
			name:    "host only",
			request: CreateSessionRequest{HostDeviceID: "host-a"},
			want:    []string{"host-a"},
		},
		{
			name:    "client only",
			request: CreateSessionRequest{ClientDeviceID: "client-a"},
			want:    []string{"client-a"},
		},
		{
			name:    "same device",
			request: CreateSessionRequest{HostDeviceID: "device-a", ClientDeviceID: "device-a"},
			want:    []string{"device-a"},
		},
		{
			name:    "sorted identities",
			request: CreateSessionRequest{HostDeviceID: "host-z", ClientDeviceID: "client-a"},
			want:    []string{"client-a", "host-z"},
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got := createRateDeviceIDs(test.request)
			if !reflect.DeepEqual(got, test.want) {
				t.Fatalf("device IDs = %#v, want %#v", got, test.want)
			}
		})
	}
}

func TestConsumeTokenBucket(t *testing.T) {
	now := time.Date(2026, time.September, 1, 10, 0, 0, 0, time.UTC)
	bucket := tokenBucket{}
	if !consumeTokenBucket(&bucket, now, 2) {
		t.Fatal("first token rejected")
	}
	if bucket.tokensAvailable != 1 {
		t.Fatalf("tokens after first consume = %d, want 1", bucket.tokensAvailable)
	}
	if !consumeTokenBucket(&bucket, now.Add(30*time.Second), 2) {
		t.Fatal("second token rejected")
	}
	if consumeTokenBucket(&bucket, now.Add(59*time.Second), 2) {
		t.Fatal("third token admitted before refill")
	}
	if !consumeTokenBucket(&bucket, now.Add(time.Minute), 2) {
		t.Fatal("token rejected after refill")
	}
	if bucket.tokensAvailable != 1 {
		t.Fatalf("tokens after refill consume = %d, want 1", bucket.tokensAvailable)
	}

	bucket = tokenBucket{refilledAt: now, tokensAvailable: 100}
	if !consumeTokenBucket(&bucket, now.Add(time.Second), 2) {
		t.Fatal("clamped oversized bucket rejected")
	}
	if bucket.tokensAvailable != 1 {
		t.Fatalf("clamped tokens = %d, want 1", bucket.tokensAvailable)
	}

	bucket = tokenBucket{refilledAt: now.Add(-24 * time.Hour), tokensAvailable: 0}
	if !consumeTokenBucket(&bucket, now, 2) {
		t.Fatal("stale bucket rejected")
	}
	if bucket.tokensAvailable != 1 {
		t.Fatalf("stale bucket tokens = %d, want 1", bucket.tokensAvailable)
	}
}

func waitForWaiter(t *testing.T, store *MemoryStore, sessionID string, role Role) {
	t.Helper()
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		store.mu.Lock()
		current := store.sessions[sessionID]
		waiting := current != nil && current.waiters[role] == 1
		store.mu.Unlock()
		if waiting {
			return
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatal("poll did not register a waiter")
}

type pollResponse struct {
	Events     []Event `json:"events"`
	NextCursor uint64  `json:"next_cursor"`
}

func createSessionForTest(t *testing.T, handler http.Handler, requestID string, ttl int64) SessionResponse {
	t.Helper()
	body, err := json.Marshal(createSessionRequest{RequestID: requestID, TTLSeconds: ttl})
	if err != nil {
		t.Fatal(err)
	}
	response := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, string(body))
	if response.Code != http.StatusCreated && response.Code != http.StatusOK {
		t.Fatalf("create session: %d %s", response.Code, response.Body.String())
	}
	var created SessionResponse
	if err := json.Unmarshal(response.Body.Bytes(), &created); err != nil {
		t.Fatal(err)
	}
	return created
}

func postMessageForTest(t *testing.T, handler http.Handler, sessionID, token string, request MessageRequest, wantStatus int) Event {
	t.Helper()
	body, err := json.Marshal(request)
	if err != nil {
		t.Fatal(err)
	}
	response := performRequest(t, handler, http.MethodPost, "/v1/sessions/"+sessionID+"/messages", token, string(body))
	if response.Code != wantStatus {
		t.Fatalf("post message: got %d, want %d: %s", response.Code, wantStatus, response.Body.String())
	}
	var event Event
	if response.Code == http.StatusCreated || response.Code == http.StatusOK {
		if err := json.Unmarshal(response.Body.Bytes(), &event); err != nil {
			t.Fatal(err)
		}
	}
	return event
}

func pollForTest(t *testing.T, handler http.Handler, sessionID, token string, after uint64, wait int, wantStatus int) pollResponse {
	t.Helper()
	path := "/v1/sessions/" + sessionID + "/events?after=" + strconvFormatUint(after) + "&wait_seconds=" + strconvItoa(wait)
	response := performRequest(t, handler, http.MethodGet, path, token, "")
	if response.Code != wantStatus {
		t.Fatalf("poll: got %d, want %d: %s", response.Code, wantStatus, response.Body.String())
	}
	var result pollResponse
	if response.Code == http.StatusOK {
		if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil {
			t.Fatal(err)
		}
	}
	return result
}

func performRequest(t *testing.T, handler http.Handler, method, path, token, body string) *httptest.ResponseRecorder {
	t.Helper()
	request := httptest.NewRequestWithContext(context.Background(), method, path, bytes.NewBufferString(body))
	if body != "" {
		request.Header.Set("Content-Type", "application/json")
	}
	if token != "" {
		request.Header.Set("Authorization", "Bearer "+token)
	}
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	return response
}

func strconvFormatUint(value uint64) string { return strconv.FormatUint(value, 10) }
func strconvItoa(value int) string          { return strconv.Itoa(value) }
