package signaling

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"path/filepath"
	"testing"
)

type recordingRelay struct {
	credentialsCalls int
	revokeCalls      int
	revokeFailures   int
}

func (r *recordingRelay) Credentials(_ context.Context, _, _ string, _ int64) (*TurnCredentials, error) {
	r.credentialsCalls++
	return &TurnCredentials{Username: "turn-user", Password: "turn-password", TTLSeconds: 60,
		Realm: "relay.test", URIs: []string{"turn:relay.test:3478"}}, nil
}

func (r *recordingRelay) Revoke(_ context.Context, _ string) error {
	r.revokeCalls++
	if r.revokeFailures > 0 {
		r.revokeFailures--
		return errors.New("relay unavailable")
	}
	return nil
}

func TestRefreshSupersedesOldPathAndSharesOneSuccessor(t *testing.T) {
	service, err := NewServer(testConfig())
	if err != nil {
		t.Fatal(err)
	}
	relay := &recordingRelay{}
	service.relay = relay
	handler := service.Handler()
	created := createBoundSessionForTest(t, handler, "fresh-1", "device-1", 41)

	host := refreshForTest(t, handler, created.SessionID, created.HostToken, http.StatusOK)
	device := refreshForTest(t, handler, created.SessionID, created.DeviceToken, http.StatusOK)
	if host.SessionID != device.SessionID || host.SessionEpoch != 42 || device.SessionEpoch != 42 {
		t.Fatalf("roles did not receive one successor: host=%#v device=%#v", host, device)
	}
	if host.RoleToken == device.RoleToken || host.RoleToken == "" || device.RoleToken == "" {
		t.Fatal("successor role tokens are not distinct")
	}
	postMessageForTest(t, handler, created.SessionID, created.HostToken,
		MessageRequest{MessageID: "stale", Type: MessageOffer, SDP: "v=0"}, http.StatusNotFound)
	if repeated := refreshForTest(t, handler, created.SessionID, created.HostToken, http.StatusOK); repeated.SessionID != host.SessionID ||
		repeated.RoleToken != host.RoleToken || repeated.SessionEpoch != host.SessionEpoch || !repeated.ExpiresAt.Equal(host.ExpiresAt) {
		t.Fatalf("refresh retry changed successor: %#v != %#v", repeated, host)
	}
	if relay.credentialsCalls != 3 {
		t.Fatalf("relay credential calls = %d, want 3 per response", relay.credentialsCalls)
	}
}

func TestRevokeDeniesBeforeRelayRetryAndPersistsDeviceTombstone(t *testing.T) {
	cfg := testConfig()
	cfg.StateFile = filepath.Join(t.TempDir(), "signaling-state.json")
	service, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	relay := &recordingRelay{revokeFailures: 1}
	service.relay = relay
	handler := service.Handler()
	created := createBoundSessionForTest(t, handler, "fresh-revoke", "device-revoke", 9)
	body := `{"device_id":"device-revoke","tombstone":{"sequence":1}}`
	if response := performRequest(t, handler, http.MethodPost, "/v1/sessions/"+created.SessionID+"/revoke", created.HostToken, body); response.Code != http.StatusBadGateway {
		t.Fatalf("first revoke = %d: %s", response.Code, response.Body.String())
	}
	postMessageForTest(t, handler, created.SessionID, created.HostToken,
		MessageRequest{MessageID: "denied", Type: MessageOffer, SDP: "v=0"}, http.StatusNotFound)
	if response := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken,
		`{"request_id":"revoked-create","device_id":"device-revoke","session_epoch":10}`); response.Code != http.StatusConflict {
		t.Fatalf("create after relay failure = %d: %s", response.Code, response.Body.String())
	}
	if response := performRequest(t, handler, http.MethodPost, "/v1/sessions/"+created.SessionID+"/revoke", created.HostToken, body); response.Code != http.StatusOK {
		t.Fatalf("revoke retry = %d: %s", response.Code, response.Body.String())
	}
	if relay.revokeCalls != 2 {
		t.Fatalf("relay revoke calls = %d, want 2", relay.revokeCalls)
	}
	restarted, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	if response := performRequest(t, restarted.Handler(), http.MethodPost, "/v1/sessions", testIssuerToken,
		`{"request_id":"restart-create","device_id":"device-revoke","session_epoch":11}`); response.Code != http.StatusConflict {
		t.Fatalf("create after restart = %d: %s", response.Code, response.Body.String())
	}
}

func createBoundSessionForTest(t *testing.T, handler http.Handler, requestID, deviceID string, epoch uint64) SessionResponse {
	t.Helper()
	body, err := json.Marshal(createSessionRequest{RequestID: requestID, DeviceID: deviceID, SessionEpoch: epoch})
	if err != nil {
		t.Fatal(err)
	}
	response := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken, string(body))
	if response.Code != http.StatusCreated {
		t.Fatalf("create bound session: %d %s", response.Code, response.Body.String())
	}
	var created SessionResponse
	if err := json.Unmarshal(response.Body.Bytes(), &created); err != nil {
		t.Fatal(err)
	}
	return created
}

func refreshForTest(t *testing.T, handler http.Handler, sessionID, token string, wantStatus int) RefreshResponse {
	t.Helper()
	response := performRequest(t, handler, http.MethodPost, "/v1/sessions/"+sessionID+"/refresh", token, `{}`)
	if response.Code != wantStatus {
		t.Fatalf("refresh: got %d, want %d: %s", response.Code, wantStatus, response.Body.String())
	}
	var refreshed RefreshResponse
	if wantStatus == http.StatusOK {
		if err := json.Unmarshal(response.Body.Bytes(), &refreshed); err != nil {
			t.Fatal(err)
		}
	}
	return refreshed
}
