package signaling

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type readinessRoundTripFunc func(*http.Request) (*http.Response, error)

func (roundTrip readinessRoundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return roundTrip(request)
}

func testAuthorityConfig(authorityURL string) Config {
	return Config{
		ListenAddress: "127.0.0.1:0", SessionTTLSeconds: 60, MaxSessionTTLSeconds: 120,
		MaxActiveSessions: 10, SessionCreatesPerMinute: 20, MessagesPerMinute: 20,
		MaxRequestBodyBytes: 2048, MaxSDPBytes: 1024, MaxCandidateBytes: 512,
		MaxCandidatesPerRole: 2, MaxWaitSeconds: 1, MaxWaitersPerRole: 1,
		CleanupIntervalSeconds: 1, AuthorityMode: AuthorityModeProductionAuthority,
		AuthorityURL: authorityURL, AuthorityToken: testAuthorityToken,
		IssuerToken: testIssuerToken, MetricsToken: testMetricsToken,
	}
}

func TestAuthorityModeCreateSessionDelegatesToAuthority(t *testing.T) {
	var createCalls atomic.Int32
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v1/signaling/sessions" && r.Method == http.MethodPost {
			createCalls.Add(1)
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
				SessionID:   "sess-1",
				HostToken:   "host-token-1",
				ClientToken: "client-token-1",
				ExpiresAt:   time.Now().Add(time.Hour).UTC(),
				Created:     true,
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()

	body := `{"request_id":"req-1","account_id":"acct-1","host_device_id":"host-1","client_device_id":"client-1","session_epoch":1,"ttl_seconds":60}`
	response := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, body)
	if response.Code != http.StatusCreated {
		t.Fatalf("create status = %d: %s", response.Code, response.Body.String())
	}
	var created SessionResponse
	if err := json.Unmarshal(response.Body.Bytes(), &created); err != nil {
		t.Fatal(err)
	}
	if created.SessionID != "sess-1" || created.HostToken != "host-token-1" || created.DeviceToken != "client-token-1" {
		t.Errorf("unexpected session response: %#v", created)
	}
	if createCalls.Load() != 1 {
		t.Errorf("expected 1 authority create call, got %d", createCalls.Load())
	}
}

func TestAuthorityModeCreateSessionReplay(t *testing.T) {
	var calls atomic.Int32
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		status := http.StatusCreated
		created := true
		if calls.Add(1) > 1 {
			status = http.StatusOK
			created = false
		}
		w.WriteHeader(status)
		_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
			SessionID:   "sess-1",
			HostToken:   "host-token-1",
			ClientToken: "client-token-1",
			ExpiresAt:   time.Now().Add(time.Hour).UTC(),
			Created:     created,
		})
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()

	body := `{"request_id":"req-1","account_id":"acct-1","host_device_id":"host-1","client_device_id":"client-1","session_epoch":1,"ttl_seconds":60}`
	first := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, body)
	if first.Code != http.StatusCreated {
		t.Fatalf("initial create status = %d: %s", first.Code, first.Body.String())
	}
	response := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, body)
	if response.Code != http.StatusOK {
		t.Fatalf("replay status = %d: %s", response.Code, response.Body.String())
	}
}

func TestAuthorityModeReplayExtendsLocalExpiryForSameAdmission(t *testing.T) {
	initialExpiry := time.Now().Add(time.Hour).UTC().Round(time.Microsecond)
	extendedExpiry := initialExpiry.Add(time.Minute)
	var calls atomic.Int32
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		call := calls.Add(1)
		status := http.StatusCreated
		created := true
		expiresAt := initialExpiry
		hostToken := "host-token-1"
		clientToken := "client-token-1"
		if call > 1 {
			status = http.StatusOK
			created = false
			expiresAt = extendedExpiry
			hostToken = "host-token-2"
			clientToken = "client-token-2"
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
			SessionID: "sess-1", HostToken: hostToken, ClientToken: clientToken,
			ExpiresAt: expiresAt, Created: created,
		})
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()
	body := "{\"request_id\":\"req-1\",\"account_id\":\"acct-1\",\"host_device_id\":\"host-1\",\"client_device_id\":\"client-1\",\"session_epoch\":1,\"ttl_seconds\":60}"
	if response := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, body); response.Code != http.StatusCreated {
		t.Fatalf("initial create status=%d body=%s", response.Code, response.Body.String())
	}
	replay := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, body)
	if replay.Code != http.StatusOK {
		t.Fatalf("extended replay status=%d body=%s", replay.Code, replay.Body.String())
	}
	var replayed SessionResponse
	if err := json.Unmarshal(replay.Body.Bytes(), &replayed); err != nil {
		t.Fatal(err)
	}
	if replayed.HostToken != "host-token-2" || replayed.DeviceToken != "client-token-2" {
		t.Fatalf("replay did not return latest authority tokens: %#v", replayed)
	}
	service.store.mu.Lock()
	storedResponse := service.store.sessions["sess-1"].response
	service.store.mu.Unlock()
	if !storedResponse.ExpiresAt.Equal(extendedExpiry) {
		t.Fatalf("local expiry=%s want=%s", storedResponse.ExpiresAt, extendedExpiry)
	}
	if storedResponse.HostToken != "" || storedResponse.DeviceToken != "" {
		t.Fatal("production store retained authority role tokens for local fallback")
	}
}

func TestAuthorityModeReplayShortensLocalExpiry(t *testing.T) {
	initialExpiry := time.Now().Add(time.Hour).UTC().Round(time.Microsecond)
	var calls atomic.Int32
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		call := calls.Add(1)
		status := http.StatusCreated
		created := true
		expiresAt := initialExpiry
		if call > 1 {
			status = http.StatusOK
			created = false
			expiresAt = initialExpiry.Add(-time.Minute)
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
			SessionID: "sess-1", HostToken: "host-token-1", ClientToken: "client-token-1",
			ExpiresAt: expiresAt, Created: created,
		})
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()
	body := "{\"request_id\":\"req-1\",\"account_id\":\"acct-1\",\"host_device_id\":\"host-1\",\"client_device_id\":\"client-1\",\"session_epoch\":1,\"ttl_seconds\":60}"
	if response := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, body); response.Code != http.StatusCreated {
		t.Fatalf("initial create status=%d body=%s", response.Code, response.Body.String())
	}
	replay := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, body)
	if replay.Code != http.StatusOK {
		t.Fatalf("shorter replay status=%d body=%s", replay.Code, replay.Body.String())
	}
	service.store.mu.Lock()
	storedExpiry := service.store.sessions["sess-1"].response.ExpiresAt
	service.store.mu.Unlock()
	wantExpiry := initialExpiry.Add(-time.Minute)
	if !storedExpiry.Equal(wantExpiry) {
		t.Fatalf("local expiry=%s want=%s", storedExpiry, wantExpiry)
	}
}

func TestAuthorityModeReplayExpiryChangeWakesActivePoll(t *testing.T) {
	initialExpiry := time.Now().Add(time.Hour).UTC()
	shortExpiry := time.Now().Add(2 * time.Second).UTC()
	var calls atomic.Int32
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		call := calls.Add(1)
		status := http.StatusCreated
		created := true
		expiresAt := initialExpiry
		if call > 1 {
			status = http.StatusOK
			created = false
			expiresAt = shortExpiry
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
			SessionID: "sess-1", HostToken: "host-token-1", ClientToken: "client-token-1",
			ExpiresAt: expiresAt, Created: created,
		})
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	request := CreateSessionRequest{
		RequestID: "req-1", TTL: time.Minute,
		AccountID: "acct-1", HostDeviceID: "host-1", ClientDeviceID: "client-1", SessionEpoch: 1,
	}
	created, wasCreated, err := service.store.Create(context.Background(), request)
	if err != nil || !wasCreated {
		t.Fatalf("initial create: created=%t err=%v", wasCreated, err)
	}

	type pollResult struct {
		events []Event
		err    error
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	result := make(chan pollResult, 1)
	go func() {
		events, _, pollErr := service.store.PollAuthorized(ctx, created.SessionID, RoleDevice, 0)
		result <- pollResult{events: events, err: pollErr}
	}()
	waitForWaiter(t, service.store, created.SessionID, RoleDevice)

	if _, replayCreated, err := service.store.Create(context.Background(), request); err != nil || replayCreated {
		t.Fatalf("short-expiry replay: created=%t err=%v", replayCreated, err)
	}
	select {
	case polled := <-result:
		if !errors.Is(polled.err, ErrExpired) {
			t.Fatalf("poll error=%v, want ErrExpired", polled.err)
		}
		if len(polled.events) != 0 {
			t.Fatalf("expiry replay released events: %#v", polled.events)
		}
	case <-time.After(4 * time.Second):
		t.Fatal("active poll did not recompute shortened authority expiry")
	}
}

func TestAuthorityModeReplayAfterLocalStateLossRequiresFreshAdmission(t *testing.T) {
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
			SessionID:   "stale-session",
			HostToken:   "stale-host-token",
			ClientToken: "stale-client-token",
			ExpiresAt:   time.Now().Add(time.Hour).UTC(),
			Created:     false,
		})
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	service.store.mu.Lock()
	service.store.requestSessions["old-request"] = "stale-session"
	service.store.mu.Unlock()
	body := "{\"request_id\":\"old-request\",\"account_id\":\"acct-1\",\"host_device_id\":\"host-1\",\"client_device_id\":\"client-1\",\"session_epoch\":1,\"ttl_seconds\":60}"
	response := performRequest(t, service.Handler(), http.MethodPost, "/v1/sessions", testIssuerToken, body)
	if response.Code != http.StatusConflict {
		t.Fatalf("durable replay without local state status=%d body=%s", response.Code, response.Body.String())
	}
	if strings.Contains(response.Body.String(), "stale-host-token") || strings.Contains(response.Body.String(), "stale-client-token") {
		t.Fatal("durable replay returned stale role credentials")
	}
	if stats := service.store.Stats(); stats.ReservedRecords != 0 {
		t.Fatalf("durable replay reconstructed local routing state: %#v", stats)
	}
	service.store.mu.Lock()
	_, mappingExists := service.store.requestSessions["old-request"]
	service.store.mu.Unlock()
	if mappingExists {
		t.Fatal("missing local session left a stale request mapping")
	}
}

func TestAuthorityModeSessionIDCollisionFailsClosedWithoutOverwrite(t *testing.T) {
	var call atomic.Int32
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		currentCall := call.Add(1)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
			SessionID:   "colliding-session",
			HostToken:   fmt.Sprintf("host-token-%d", currentCall),
			ClientToken: fmt.Sprintf("client-token-%d", currentCall),
			ExpiresAt:   time.Now().Add(time.Hour).UTC(),
			Created:     true,
		})
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()
	firstBody := "{\"request_id\":\"req-1\",\"account_id\":\"acct-1\",\"host_device_id\":\"host-1\",\"client_device_id\":\"client-1\",\"session_epoch\":1,\"ttl_seconds\":60}"
	secondBody := "{\"request_id\":\"req-2\",\"account_id\":\"acct-1\",\"host_device_id\":\"host-1\",\"client_device_id\":\"client-1\",\"session_epoch\":2,\"ttl_seconds\":60}"

	first := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, firstBody)
	if first.Code != http.StatusCreated {
		t.Fatalf("first create status=%d body=%s", first.Code, first.Body.String())
	}
	originalEvent := Event{Sequence: 1, MessageID: "existing-offer", Type: MessageOffer, SenderRole: RoleHost, SDP: "v=0"}
	service.store.mu.Lock()
	original := service.store.sessions["colliding-session"]
	original.offerSent = true
	original.events = []Event{originalEvent}
	service.store.mu.Unlock()
	second := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, secondBody)
	if second.Code != http.StatusBadGateway {
		t.Fatalf("colliding create status=%d body=%s", second.Code, second.Body.String())
	}

	service.store.mu.Lock()
	stored := service.store.sessions["colliding-session"]
	firstMapping := service.store.requestSessions["req-1"]
	_, secondMappingExists := service.store.requestSessions["req-2"]
	service.store.mu.Unlock()
	if stored == nil || stored != original || stored.requestID != "req-1" || !stored.offerSent || len(stored.events) != 1 || stored.events[0] != originalEvent || firstMapping != "colliding-session" || secondMappingExists {
		t.Fatalf("collision overwrote local state: stored=%#v first=%q second_exists=%t", stored, firstMapping, secondMappingExists)
	}
}

func TestAuthorityModeInconsistentSameRequestDoesNotResetSession(t *testing.T) {
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
			SessionID:   "existing-session",
			HostToken:   "new-host-token",
			ClientToken: "new-client-token",
			ExpiresAt:   time.Now().Add(time.Hour).UTC(),
			Created:     true,
		})
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	originalEvent := Event{Sequence: 1, MessageID: "existing-offer", Type: MessageOffer, SenderRole: RoleHost, SDP: "v=0"}
	service.store.mu.Lock()
	service.store.sessions["existing-session"] = &session{
		requestID: "same-request", ttlSeconds: 60,
		response:       SessionResponse{SessionID: "existing-session", ExpiresAt: time.Now().Add(time.Hour)},
		events:         []Event{originalEvent},
		messages:       map[Role]map[string]MessageRequest{RoleHost: {"existing-offer": {MessageID: "existing-offer", Type: MessageOffer, SDP: "v=0"}}, RoleDevice: {}},
		offerSent:      true,
		ended:          map[Role]bool{RoleHost: false, RoleDevice: false},
		candidateCount: map[Role]int{RoleHost: 0, RoleDevice: 0},
		rates:          map[Role]rateWindow{}, waiters: map[Role]int{}, notify: make(chan struct{}),
	}
	service.store.mu.Unlock()
	service.SetReady(true)
	body := "{\"request_id\":\"same-request\",\"account_id\":\"acct-1\",\"host_device_id\":\"host-1\",\"client_device_id\":\"client-1\",\"session_epoch\":1,\"ttl_seconds\":60}"

	response := performRequest(t, service.Handler(), http.MethodPost, "/v1/sessions", testIssuerToken, body)
	if response.Code != http.StatusConflict {
		t.Fatalf("inconsistent same-request create status=%d body=%s", response.Code, response.Body.String())
	}
	service.store.mu.Lock()
	stored := service.store.sessions["existing-session"]
	_, mappingCreated := service.store.requestSessions["same-request"]
	service.store.mu.Unlock()
	if stored == nil || !stored.offerSent || len(stored.events) != 1 || stored.events[0] != originalEvent || mappingCreated {
		t.Fatalf("inconsistent create reset local state: stored=%#v mapping_created=%t", stored, mappingCreated)
	}
}

func TestAuthorityModeCreateRequiresAuthorityFields(t *testing.T) {
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Error("authority should not be called when required fields are missing")
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()

	body := `{"request_id":"req-1","ttl_seconds":60}`
	response := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, body)
	if response.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for missing authority fields, got %d: %s", response.Code, response.Body.String())
	}
}

func TestAuthorityModeCapacityRejectsBeforeAuthorityAdmission(t *testing.T) {
	var createCalls atomic.Int32
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		call := createCalls.Add(1)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
			SessionID:   fmt.Sprintf("session-%d", call),
			HostToken:   fmt.Sprintf("host-token-%d", call),
			ClientToken: fmt.Sprintf("client-token-%d", call),
			ExpiresAt:   time.Now().Add(time.Hour).UTC(),
			Created:     true,
		})
	}))
	defer authorityServer.Close()

	cfg := testAuthorityConfig(authorityServer.URL)
	cfg.MaxActiveSessions = 1
	service, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()
	firstBody := "{\"request_id\":\"req-1\",\"account_id\":\"acct-1\",\"host_device_id\":\"host-1\",\"client_device_id\":\"client-1\",\"session_epoch\":1,\"ttl_seconds\":60}"
	secondBody := "{\"request_id\":\"req-2\",\"account_id\":\"acct-1\",\"host_device_id\":\"host-1\",\"client_device_id\":\"client-1\",\"session_epoch\":2,\"ttl_seconds\":60}"

	if response := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, firstBody); response.Code != http.StatusCreated {
		t.Fatalf("first create status=%d body=%s", response.Code, response.Body.String())
	}
	response := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, secondBody)
	if response.Code != http.StatusTooManyRequests {
		t.Fatalf("capacity create status=%d body=%s", response.Code, response.Body.String())
	}
	if createCalls.Load() != 1 {
		t.Fatalf("authority received %d creates at local capacity", createCalls.Load())
	}
}

func TestAuthorityModePostMessageAuthorizesViaAuthority(t *testing.T) {
	var authorizeCalls atomic.Int32
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/signaling/sessions" && r.Method == http.MethodPost:
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
				SessionID:   "sess-1",
				HostToken:   "host-token-1",
				ClientToken: "client-token-1",
				ExpiresAt:   time.Now().Add(time.Hour).UTC(),
				Created:     true,
			})
		case strings.HasSuffix(r.URL.Path, "/authorize") && r.Method == http.MethodPost:
			authorizeCalls.Add(1)
			var request struct {
				RoleToken string `json:"role_token"`
			}
			_ = json.NewDecoder(r.Body).Decode(&request)
			role := "client"
			if request.RoleToken == "host-token-1" {
				role = "host"
			}
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]string{"role": role})
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()

	createBody := `{"request_id":"req-1","account_id":"acct-1","host_device_id":"host-1","client_device_id":"client-1","session_epoch":1,"ttl_seconds":60}`
	createResp := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, createBody)
	if createResp.Code != http.StatusCreated {
		t.Fatalf("create status = %d", createResp.Code)
	}

	msgBody := `{"message_id":"offer-1","type":"offer","sdp":"v=0\r\n"}`
	msgResp := performRequest(t, handler, http.MethodPost, "/v1/sessions/sess-1/messages", "host-token-1", msgBody)
	if msgResp.Code != http.StatusCreated {
		t.Fatalf("post message status = %d: %s", msgResp.Code, msgResp.Body.String())
	}
	if authorizeCalls.Load() != 2 {
		t.Errorf("expected pre-parse and pre-commit authority checks, got %d", authorizeCalls.Load())
	}
}

func TestAuthorityModeRevocationBeforeMessageCommitDoesNotPublish(t *testing.T) {
	var authorizeCalls atomic.Int32
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/signaling/sessions" && r.Method == http.MethodPost:
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
				SessionID:   "sess-1",
				HostToken:   "host-token-1",
				ClientToken: "client-token-1",
				ExpiresAt:   time.Now().Add(time.Hour).UTC(),
				Created:     true,
			})
		case strings.HasSuffix(r.URL.Path, "/authorize") && r.Method == http.MethodPost:
			if authorizeCalls.Add(1) == 1 {
				w.Header().Set("Content-Type", "application/json")
				_ = json.NewEncoder(w).Encode(map[string]string{"role": "host"})
				return
			}
			w.WriteHeader(http.StatusForbidden)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()

	createBody := "{\"request_id\":\"req-1\",\"account_id\":\"acct-1\",\"host_device_id\":\"host-1\",\"client_device_id\":\"client-1\",\"session_epoch\":1,\"ttl_seconds\":60}"
	create := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, createBody)
	if create.Code != http.StatusCreated {
		t.Fatalf("create status=%d body=%s", create.Code, create.Body.String())
	}

	messageBody := "{\"message_id\":\"offer-revoked\",\"type\":\"offer\",\"sdp\":\"v=0\\r\\na=ice-pwd:must-not-publish\\r\\n\"}"
	response := performRequest(t, handler, http.MethodPost, "/v1/sessions/sess-1/messages", "host-token-1", messageBody)
	if response.Code != http.StatusNotFound {
		t.Fatalf("message accepted after pre-commit revocation: status=%d body=%s", response.Code, response.Body.String())
	}
	service.store.mu.Lock()
	eventCount := len(service.store.sessions["sess-1"].events)
	service.store.mu.Unlock()
	if eventCount != 0 {
		t.Fatalf("revoked message published %d local events", eventCount)
	}
	if strings.Contains(response.Body.String(), "must-not-publish") {
		t.Fatal("revoked message payload leaked in the response")
	}
}

func TestAuthorityModePollAuthorizesViaAuthority(t *testing.T) {
	var authorizeCalls atomic.Int32
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/signaling/sessions" && r.Method == http.MethodPost:
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
				SessionID:   "sess-1",
				HostToken:   "host-token-1",
				ClientToken: "client-token-1",
				ExpiresAt:   time.Now().Add(time.Hour).UTC(),
				Created:     true,
			})
		case strings.HasSuffix(r.URL.Path, "/authorize") && r.Method == http.MethodPost:
			authorizeCalls.Add(1)
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]string{"role": "host"})
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()

	createBody := `{"request_id":"req-1","account_id":"acct-1","host_device_id":"host-1","client_device_id":"client-1","session_epoch":1,"ttl_seconds":60}`
	create := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, createBody)
	if create.Code != http.StatusCreated {
		t.Fatalf("create status=%d body=%s", create.Code, create.Body.String())
	}

	pollResp := performRequest(t, handler, http.MethodGet, "/v1/sessions/sess-1/events?after=0&wait_seconds=0", "host-token-1", "")
	if pollResp.Code != http.StatusOK {
		t.Fatalf("poll status = %d: %s", pollResp.Code, pollResp.Body.String())
	}
	if authorizeCalls.Load() != 2 {
		t.Errorf("expected entry and pre-response authority checks for poll, got %d", authorizeCalls.Load())
	}
}

func TestAuthorityModeRevocationBeforePollResponseDoesNotReleaseEvent(t *testing.T) {
	var revoked atomic.Bool
	firstAuthorization := make(chan struct{})
	var signalFirstAuthorization sync.Once
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/signaling/sessions" && r.Method == http.MethodPost:
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
				SessionID:   "sess-1",
				HostToken:   "host-token-1",
				ClientToken: "client-token-1",
				ExpiresAt:   time.Now().Add(time.Hour).UTC(),
				Created:     true,
			})
		case strings.HasSuffix(r.URL.Path, "/authorize") && r.Method == http.MethodPost:
			if revoked.Load() {
				w.WriteHeader(http.StatusForbidden)
				return
			}
			signalFirstAuthorization.Do(func() { close(firstAuthorization) })
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]string{"role": "client"})
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()

	createBody := "{\"request_id\":\"req-1\",\"account_id\":\"acct-1\",\"host_device_id\":\"host-1\",\"client_device_id\":\"client-1\",\"session_epoch\":1,\"ttl_seconds\":60}"
	create := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, createBody)
	if create.Code != http.StatusCreated {
		t.Fatalf("create status=%d body=%s", create.Code, create.Body.String())
	}

	pollResult := make(chan *httptest.ResponseRecorder, 1)
	go func() {
		request := httptest.NewRequestWithContext(context.Background(), http.MethodGet,
			"/v1/sessions/sess-1/events?after=0&wait_seconds=1", nil)
		request.Header.Set("Authorization", "Bearer client-token-1")
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, request)
		pollResult <- response
	}()
	select {
	case <-firstAuthorization:
	case <-time.After(time.Second):
		t.Fatal("poll did not reach authority authorization")
	}
	waitForWaiter(t, service.store, "sess-1", RoleDevice)
	revoked.Store(true)
	_, _, err = service.store.AddMessageAuthorized("sess-1", RoleHost, MessageRequest{
		MessageID: "offer-1", Type: MessageOffer,
		SDP: "v=0\r\na=ice-pwd:must-not-release\r\n",
	})
	if err != nil {
		t.Fatal(err)
	}

	select {
	case response := <-pollResult:
		if response.Code != http.StatusNotFound {
			t.Fatalf("poll released an event after revocation: status=%d body=%s", response.Code, response.Body.String())
		}
		if strings.Contains(response.Body.String(), "must-not-release") {
			t.Fatal("revoked poll response leaked the queued event")
		}
	case <-time.After(2 * time.Second):
		t.Fatal("revoked poll did not return")
	}
}

func TestAuthorityModeInvalidateDelegatesToAuthority(t *testing.T) {
	var invalidateCalls atomic.Int32
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/signaling/sessions" && r.Method == http.MethodPost:
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
				SessionID:   "sess-1",
				HostToken:   "host-token-1",
				ClientToken: "client-token-1",
				ExpiresAt:   time.Now().Add(time.Hour).UTC(),
				Created:     true,
			})
		case r.Method == http.MethodDelete && strings.HasPrefix(r.URL.Path, "/v1/signaling/sessions/"):
			invalidateCalls.Add(1)
			w.WriteHeader(http.StatusNoContent)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()

	createBody := `{"request_id":"req-1","account_id":"acct-1","host_device_id":"host-1","client_device_id":"client-1","session_epoch":1,"ttl_seconds":60}`
	create := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, createBody)
	if create.Code != http.StatusCreated {
		t.Fatalf("create status=%d body=%s", create.Code, create.Body.String())
	}

	invResp := performRequest(t, handler, http.MethodDelete, "/v1/sessions/sess-1", testIssuerToken, "")
	if invResp.Code != http.StatusNoContent {
		t.Fatalf("invalidate status = %d: %s", invResp.Code, invResp.Body.String())
	}
	if invalidateCalls.Load() != 1 {
		t.Errorf("expected 1 authority invalidate call, got %d", invalidateCalls.Load())
	}
}

func TestAuthorityModeInvalidatedRequestDoesNotReplayRevokedCredentials(t *testing.T) {
	var createCalls atomic.Int32
	var invalidated atomic.Bool
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/signaling/sessions" && r.Method == http.MethodPost:
			createCalls.Add(1)
			w.Header().Set("Content-Type", "application/json")
			status := http.StatusCreated
			created := true
			if invalidated.Load() {
				status = http.StatusOK
				created = false
			}
			w.WriteHeader(status)
			_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
				SessionID: "sess-1", HostToken: "host-token-1", ClientToken: "client-token-1",
				ExpiresAt: time.Now().Add(time.Hour).UTC(), Created: created,
			})
		case r.Method == http.MethodDelete:
			invalidated.Store(true)
			w.WriteHeader(http.StatusNoContent)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()
	body := "{\"request_id\":\"req-1\",\"account_id\":\"acct-1\",\"host_device_id\":\"host-1\",\"client_device_id\":\"client-1\",\"session_epoch\":1,\"ttl_seconds\":60}"

	create := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, body)
	if create.Code != http.StatusCreated {
		t.Fatalf("create status=%d body=%s", create.Code, create.Body.String())
	}
	invalidate := performRequest(t, handler, http.MethodDelete, "/v1/sessions/sess-1", testIssuerToken, "")
	if invalidate.Code != http.StatusNoContent {
		t.Fatalf("invalidate status=%d body=%s", invalidate.Code, invalidate.Body.String())
	}
	replay := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, body)
	if replay.Code != http.StatusConflict {
		t.Fatalf("invalidated request replay status=%d body=%s", replay.Code, replay.Body.String())
	}
	if createCalls.Load() != 1 {
		t.Fatalf("invalidated replay reached authority: create_calls=%d", createCalls.Load())
	}
	if strings.Contains(replay.Body.String(), "host-token-1") || strings.Contains(replay.Body.String(), "client-token-1") {
		t.Fatal("invalidated request replay returned revoked credentials")
	}
}

func TestAuthorityModeFailClosedOnCreateFailure(t *testing.T) {
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()

	body := `{"request_id":"req-1","account_id":"acct-1","host_device_id":"host-1","client_device_id":"client-1","session_epoch":1,"ttl_seconds":60}`
	response := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, body)
	if response.Code != http.StatusBadGateway {
		t.Fatalf("expected 502 when authority create fails, got %d: %s", response.Code, response.Body.String())
	}
}

func TestAuthorityModeFailClosedOnAuthorizeFailure(t *testing.T) {
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/signaling/sessions" && r.Method == http.MethodPost:
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
				SessionID:   "sess-1",
				HostToken:   "host-token-1",
				ClientToken: "client-token-1",
				ExpiresAt:   time.Now().Add(time.Hour).UTC(),
				Created:     true,
			})
		default:
			w.WriteHeader(http.StatusServiceUnavailable)
		}
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()

	createBody := `{"request_id":"req-1","account_id":"acct-1","host_device_id":"host-1","client_device_id":"client-1","session_epoch":1,"ttl_seconds":60}`
	create := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, createBody)
	if create.Code != http.StatusCreated {
		t.Fatalf("create status=%d body=%s", create.Code, create.Body.String())
	}

	msgBody := `{"message_id":"offer-1","type":"offer","sdp":"v=0\r\n"}`
	msgResp := performRequest(t, handler, http.MethodPost, "/v1/sessions/sess-1/messages", "host-token-1", msgBody)
	if msgResp.Code != http.StatusBadGateway {
		t.Fatalf("expected 502 when authority authorize fails, got %d: %s", msgResp.Code, msgResp.Body.String())
	}
}

func TestAuthorityModeReadinessFailsWhenAuthorityIsUnavailable(t *testing.T) {
	var readinessCalls atomic.Int32
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/readyz" {
			t.Errorf("unexpected authority readiness path: %s", r.URL.Path)
		}
		readinessCalls.Add(1)
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()
	for i := 0; i < 2; i++ {
		response := performRequest(t, handler, http.MethodGet, "/readyz", "", "")
		if response.Code != http.StatusServiceUnavailable {
			t.Fatalf("readiness status=%d body=%s", response.Code, response.Body.String())
		}
	}
	if readinessCalls.Load() != 1 {
		t.Fatalf("failed readiness cache made %d authority calls, want 1", readinessCalls.Load())
	}
}

func TestAuthorityModeReadinessCachesAndRefreshes(t *testing.T) {
	var readinessCalls atomic.Int32
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		readinessCalls.Add(1)
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	now := time.Now()
	service.now = func() time.Time { return now }
	handler := service.Handler()
	for i := 0; i < 2; i++ {
		response := performRequest(t, handler, http.MethodGet, "/readyz", "", "")
		if response.Code != http.StatusOK {
			t.Fatalf("cached readiness status=%d body=%s", response.Code, response.Body.String())
		}
	}
	if readinessCalls.Load() != 1 {
		t.Fatalf("readiness cache made %d authority calls, want 1", readinessCalls.Load())
	}
	now = now.Add(authorityReadinessCacheTTL)
	response := performRequest(t, handler, http.MethodGet, "/readyz", "", "")
	if response.Code != http.StatusOK {
		t.Fatalf("refreshed readiness status=%d body=%s", response.Code, response.Body.String())
	}
	if readinessCalls.Load() != 2 {
		t.Fatalf("expired readiness cache made %d authority calls, want 2", readinessCalls.Load())
	}
}

func TestAuthorityModeReadinessCollapsesConcurrentRefreshes(t *testing.T) {
	var readinessCalls atomic.Int32
	release := make(chan struct{})
	var releaseOnce sync.Once
	releaseAuthority := func() { releaseOnce.Do(func() { close(release) }) }
	defer releaseAuthority()
	entered := make(chan struct{})
	var signalEntered sync.Once
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		readinessCalls.Add(1)
		signalEntered.Do(func() { close(entered) })
		<-release
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()
	const requests = 12
	start := make(chan struct{})
	results := make(chan int, requests)
	for i := 0; i < requests; i++ {
		go func() {
			<-start
			request := httptest.NewRequestWithContext(context.Background(), http.MethodGet, "/readyz", nil)
			response := httptest.NewRecorder()
			handler.ServeHTTP(response, request)
			results <- response.Code
		}()
	}
	close(start)
	select {
	case <-entered:
	case <-time.After(time.Second):
		t.Fatal("readiness refresh did not reach authority")
	}
	releaseAuthority()
	for i := 0; i < requests; i++ {
		if status := <-results; status != http.StatusOK {
			t.Fatalf("concurrent readiness status=%d", status)
		}
	}
	if readinessCalls.Load() != 1 {
		t.Fatalf("concurrent readiness made %d authority calls, want 1", readinessCalls.Load())
	}
}

func TestAuthorityModeReadinessWaiterHonorsRequestContext(t *testing.T) {
	release := make(chan struct{})
	var releaseOnce sync.Once
	releaseAuthority := func() { releaseOnce.Do(func() { close(release) }) }
	defer releaseAuthority()
	entered := make(chan struct{})
	var signalEntered sync.Once
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		signalEntered.Do(func() { close(entered) })
		<-release
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()
	leaderDone := make(chan int, 1)
	go func() {
		request := httptest.NewRequestWithContext(context.Background(), http.MethodGet, "/readyz", nil)
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, request)
		leaderDone <- response.Code
	}()
	select {
	case <-entered:
	case <-time.After(time.Second):
		t.Fatal("leader readiness refresh did not reach authority")
	}

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	request := httptest.NewRequestWithContext(ctx, http.MethodGet, "/readyz", nil)
	response := httptest.NewRecorder()
	started := time.Now()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusServiceUnavailable {
		t.Fatalf("canceled readiness status=%d body=%s", response.Code, response.Body.String())
	}
	if elapsed := time.Since(started); elapsed > 250*time.Millisecond {
		t.Fatalf("canceled readiness waiter took %s", elapsed)
	}

	releaseAuthority()
	select {
	case status := <-leaderDone:
		if status != http.StatusOK {
			t.Fatalf("leader readiness status=%d", status)
		}
	case <-time.After(time.Second):
		t.Fatal("leader readiness did not finish")
	}
}

func TestAuthorityModeCanceledReadinessLeaderDoesNotCancelSharedRefresh(t *testing.T) {
	var readinessCalls atomic.Int32
	entered := make(chan struct{})
	release := make(chan struct{})
	var releaseOnce sync.Once
	releaseAuthority := func() { releaseOnce.Do(func() { close(release) }) }
	defer releaseAuthority()
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		readinessCalls.Add(1)
		close(entered)
		<-release
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()
	ctx, cancel := context.WithCancel(context.Background())
	leaderDone := make(chan int, 1)
	go func() {
		request := httptest.NewRequestWithContext(ctx, http.MethodGet, "/readyz", nil)
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, request)
		leaderDone <- response.Code
	}()
	select {
	case <-entered:
	case <-time.After(time.Second):
		t.Fatal("leader readiness refresh did not reach authority")
	}
	cancel()
	select {
	case status := <-leaderDone:
		if status != http.StatusServiceUnavailable {
			t.Fatalf("canceled leader readiness status=%d", status)
		}
	case <-time.After(time.Second):
		t.Fatal("canceled readiness leader did not return")
	}

	releaseAuthority()
	response := performRequest(t, handler, http.MethodGet, "/readyz", "", "")
	if response.Code != http.StatusOK {
		t.Fatalf("shared refresh after leader cancellation status=%d body=%s", response.Code, response.Body.String())
	}
	if readinessCalls.Load() != 1 {
		t.Fatalf("leader cancellation caused %d authority refreshes, want 1", readinessCalls.Load())
	}
}

func TestAuthorityModeReadinessPanicReleasesRefreshAndDoesNotCacheResult(t *testing.T) {
	service, err := NewServer(testAuthorityConfig("http://127.0.0.1:1"))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	var readinessCalls atomic.Int32
	service.authority.httpClient = &http.Client{Transport: readinessRoundTripFunc(func(request *http.Request) (*http.Response, error) {
		if readinessCalls.Add(1) == 1 {
			panic("readiness transport panic")
		}
		return &http.Response{
			StatusCode: http.StatusOK,
			Header:     http.Header{"Content-Type": []string{"application/json"}},
			Body:       io.NopCloser(strings.NewReader("{\"status\":\"ok\"}")),
			Request:    request,
		}, nil
	})}
	handler := service.Handler()

	first := performRequest(t, handler, http.MethodGet, "/readyz", "", "")
	if first.Code != http.StatusServiceUnavailable {
		t.Fatalf("panicked readiness status=%d body=%s", first.Code, first.Body.String())
	}
	service.authorityReadinessMu.Lock()
	pending := service.authorityReadinessPending
	cacheTime := service.authorityReadinessAt
	service.authorityReadinessMu.Unlock()
	if pending != nil {
		t.Fatal("panicked readiness refresh left an in-flight marker")
	}
	if !cacheTime.IsZero() {
		t.Fatalf("panicked readiness refresh populated cache at %s", cacheTime)
	}

	second := performRequest(t, handler, http.MethodGet, "/readyz", "", "")
	if second.Code != http.StatusOK {
		t.Fatalf("readiness did not recover after panic: status=%d body=%s", second.Code, second.Body.String())
	}
	if readinessCalls.Load() != 2 {
		t.Fatalf("readiness calls=%d, want panic plus fresh retry", readinessCalls.Load())
	}
}

func TestAuthorityModeDoesNotFallbackToLocalTokens(t *testing.T) {
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/signaling/sessions" && r.Method == http.MethodPost:
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
				SessionID:   "sess-1",
				HostToken:   "host-token-1",
				ClientToken: "client-token-1",
				ExpiresAt:   time.Now().Add(time.Hour).UTC(),
				Created:     true,
			})
		case strings.HasSuffix(r.URL.Path, "/authorize"):
			// Authority returns 404 for any token - the signaling service must
			// not fall back to checking locally stored tokens.
			w.WriteHeader(http.StatusNotFound)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()

	createBody := `{"request_id":"req-1","account_id":"acct-1","host_device_id":"host-1","client_device_id":"client-1","session_epoch":1,"ttl_seconds":60}`
	create := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, createBody)
	if create.Code != http.StatusCreated {
		t.Fatalf("create status=%d body=%s", create.Code, create.Body.String())
	}

	// Even though the host token was issued by the authority and stored locally,
	// the signaling service must not accept it when the authority rejects it.
	msgBody := `{"message_id":"offer-1","type":"offer","sdp":"v=0\r\n"}`
	msgResp := performRequest(t, handler, http.MethodPost, "/v1/sessions/sess-1/messages", "host-token-1", msgBody)
	if msgResp.Code != http.StatusNotFound {
		t.Fatalf("expected 404 when authority rejects token (no local fallback), got %d: %s", msgResp.Code, msgResp.Body.String())
	}
}

func TestAuthorityModeCreateSessionMapsClientTokenToDeviceToken(t *testing.T) {
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
			SessionID:   "sess-1",
			HostToken:   "host-token-1",
			ClientToken: "client-token-1",
			ExpiresAt:   time.Now().Add(time.Hour).UTC(),
			Created:     true,
		})
	}))
	defer authorityServer.Close()

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}
	service.SetReady(true)
	handler := service.Handler()

	body := `{"request_id":"req-1","account_id":"acct-1","host_device_id":"host-1","client_device_id":"client-1","session_epoch":1,"ttl_seconds":60}`
	response := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, body)
	if response.Code != http.StatusCreated {
		t.Fatalf("create status=%d body=%s", response.Code, response.Body.String())
	}
	var created SessionResponse
	if err := json.Unmarshal(response.Body.Bytes(), &created); err != nil {
		t.Fatal(err)
	}
	if created.DeviceToken != "client-token-1" {
		t.Errorf("expected device_token to map from authority client_token, got %q", created.DeviceToken)
	}
}

func TestAuthorityModeStoreCreateDoesNotHoldLockDuringHTTP(t *testing.T) {
	// Verify that the store's Create method does not hold its mutex during the
	// authority HTTP call by checking that a concurrent store operation can
	// proceed while the authority call is in flight.
	release := make(chan struct{}, 1)
	entered := make(chan struct{})
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(entered)
		<-release
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
			SessionID:   "sess-1",
			HostToken:   "host-token-1",
			ClientToken: "client-token-1",
			ExpiresAt:   time.Now().Add(time.Hour).UTC(),
			Created:     true,
		})
	}))
	defer authorityServer.Close()
	defer close(release)

	service, err := NewServer(testAuthorityConfig(authorityServer.URL))
	if err != nil {
		t.Fatal(err)
	}

	createDone := make(chan struct{})
	go func() {
		_, _, _ = service.store.Create(context.Background(), CreateSessionRequest{
			RequestID: "req-1", TTL: time.Minute,
			AccountID: "acct-1", HostDeviceID: "host-1",
			ClientDeviceID: "client-1", SessionEpoch: 1,
		})
		close(createDone)
	}()

	select {
	case <-entered:
	case <-time.After(time.Second):
		t.Fatal("create did not reach the authority HTTP call")
	}

	// While the authority call is in flight, a store operation that acquires
	// the mutex should succeed, proving the mutex is not held during the HTTP
	// call.
	statsResult := make(chan StoreStats, 1)
	go func() { statsResult <- service.store.Stats() }()
	var stats StoreStats
	select {
	case stats = <-statsResult:
	case <-time.After(250 * time.Millisecond):
		t.Fatal("store mutex was held during authority HTTP call")
	}
	if stats.ReservedRecords != 0 {
		t.Errorf("expected 0 reserved records during authority call, got %d", stats.ReservedRecords)
	}

	release <- struct{}{}
	<-createDone
}
