package signaling

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
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
		CleanupIntervalSeconds: 1, IssuerToken: testIssuerToken, MetricsToken: testMetricsToken,
	}
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

func TestPollWakesForRemoteEventAndEnforcesWaiterLimit(t *testing.T) {
	service, err := NewServer(testConfig())
	if err != nil {
		t.Fatal(err)
	}
	created, _, err := service.store.Create("poll-test", time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	result := make(chan []Event, 1)
	go func() {
		events, _, pollErr := service.store.Poll(ctx, created.SessionID, created.DeviceToken, 0)
		if pollErr != nil {
			result <- nil
			return
		}
		result <- events
	}()
	time.Sleep(20 * time.Millisecond)
	if _, _, err := service.store.Poll(context.Background(), created.SessionID, created.DeviceToken, 0); !errors.Is(err, ErrTooManyWaiters) {
		t.Fatalf("second waiter error = %v", err)
	}
	_, _, err = service.store.AddMessage(created.SessionID, created.HostToken, MessageRequest{MessageID: "wake", Type: MessageOffer, SDP: "v=0"})
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
	created, _, err := service.store.Create("expiring-poll", 25*time.Millisecond)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	started := time.Now()
	_, _, err = service.store.Poll(ctx, created.SessionID, created.HostToken, 0)
	if !errors.Is(err, ErrExpired) {
		t.Fatalf("poll expiration error = %v", err)
	}
	if elapsed := time.Since(started); elapsed > 250*time.Millisecond {
		t.Fatalf("expiration did not wake poll promptly: %s", elapsed)
	}
	if removed := service.store.Cleanup(); removed != 1 || service.store.ActiveCount() != 0 {
		t.Fatalf("expired cleanup removed=%d active=%d", removed, service.store.ActiveCount())
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
	request := httptest.NewRequest(method, path, bytes.NewBufferString(body))
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
