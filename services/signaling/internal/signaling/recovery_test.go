package signaling

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"path/filepath"
	"testing"
	"time"
)

type testSessionBinding struct {
	authorityPrivate *ecdsa.PrivateKey
	authority, peer  PublicIdentity
}

var testSessionBindings = map[string]testSessionBinding{}

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
	body := signedRevokeBody(t, created.SessionID, "device-revoke", 1)
	if response := performRequest(t, handler, http.MethodPost, "/v1/sessions/"+created.SessionID+"/revoke", created.HostToken, body); response.Code != http.StatusBadGateway {
		t.Fatalf("first revoke = %d: %s", response.Code, response.Body.String())
	}
	postMessageForTest(t, handler, created.SessionID, created.HostToken,
		MessageRequest{MessageID: "denied", Type: MessageOffer, SDP: "v=0"}, http.StatusNotFound)
	binding := testSessionBindings[created.SessionID]
	deniedCreateBody, _ := json.Marshal(createSessionRequest{RequestID: "revoked-create", DeviceID: "device-revoke", SessionEpoch: 10,
		Authority: &binding.authority, PeerIdentity: &binding.peer})
	if response := performRequest(t, handler, http.MethodPost, "/v1/sessions", testIssuerToken,
		string(deniedCreateBody)); response.Code != http.StatusConflict {
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
	restartBody, _ := json.Marshal(createSessionRequest{RequestID: "restart-create", DeviceID: "device-revoke", SessionEpoch: 11,
		Authority: &binding.authority, PeerIdentity: &binding.peer})
	if response := performRequest(t, restarted.Handler(), http.MethodPost, "/v1/sessions", testIssuerToken, string(restartBody)); response.Code != http.StatusConflict {
		t.Fatalf("create after restart = %d: %s", response.Code, response.Body.String())
	}
}

func TestRevokeRequiresMatchingSignatureAndRejectsSequenceReplay(t *testing.T) {
	service, err := NewServer(testConfig())
	if err != nil {
		t.Fatal(err)
	}
	handler := service.Handler()
	created := createBoundSessionForTest(t, handler, "signed-revoke", "signed-device", 3)
	tampered := signedRevokeBody(t, created.SessionID, "signed-device", 1)
	var decoded map[string]any
	if err := json.Unmarshal([]byte(tampered), &decoded); err != nil {
		t.Fatal(err)
	}
	tombstone := decoded["tombstone"].(map[string]any)
	tombstone["reasonCode"] = "tampered"
	badBody, _ := json.Marshal(decoded)
	if got := performRequest(t, handler, http.MethodPost, "/v1/sessions/"+created.SessionID+"/revoke", created.HostToken, string(badBody)); got.Code != http.StatusBadRequest {
		t.Fatalf("tampered device accepted: %d %s", got.Code, got.Body.String())
	}
	if got := performRequest(t, handler, http.MethodPost, "/v1/sessions/"+created.SessionID+"/revoke", created.DeviceToken,
		signedRevokeBody(t, created.SessionID, "signed-device", 1)); got.Code != http.StatusNotFound {
		t.Fatalf("device bearer revoked permanently: %d %s", got.Code, got.Body.String())
	}
}

func TestPendingRelayRevocationRetriesAfterRestart(t *testing.T) {
	cfg := testConfig()
	cfg.StateFile = filepath.Join(t.TempDir(), "signaling-state.json")
	service, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	failedRelay := &recordingRelay{revokeFailures: 1}
	service.relay = failedRelay
	created := createBoundSessionForTest(t, service.Handler(), "outbox", "outbox-device", 1)
	if got := performRequest(t, service.Handler(), http.MethodPost, "/v1/sessions/"+created.SessionID+"/revoke", created.HostToken,
		signedRevokeBody(t, created.SessionID, "outbox-device", 1)); got.Code != http.StatusBadGateway {
		t.Fatalf("revoke status = %d", got.Code)
	}
	restarted, err := NewServer(cfg)
	if err != nil {
		t.Fatal(err)
	}
	retryRelay := &recordingRelay{}
	restarted.relay = retryRelay
	restarted.retryPendingRelayRevocations(context.Background())
	if retryRelay.revokeCalls != 1 || len(restarted.store.PendingRelayRevocations()) != 0 {
		t.Fatalf("pending relay revocation was not completed: calls=%d pending=%v", retryRelay.revokeCalls, restarted.store.PendingRelayRevocations())
	}
}

func TestRevocationSequenceIsScopedToAuthority(t *testing.T) {
	service, err := NewServer(testConfig())
	if err != nil {
		t.Fatal(err)
	}
	first := createBoundSessionForTest(t, service.Handler(), "authority-one", "device-one", 1)
	second := createBoundSessionForTest(t, service.Handler(), "authority-two", "device-two", 1)
	for _, target := range []struct {
		created  SessionResponse
		deviceID string
	}{{first, "device-one"}, {second, "device-two"}} {
		got := performRequest(t, service.Handler(), http.MethodPost, "/v1/sessions/"+target.created.SessionID+"/revoke", target.created.HostToken,
			signedRevokeBody(t, target.created.SessionID, target.deviceID, 1))
		if got.Code != http.StatusOK {
			t.Fatalf("authority-scoped sequence rejected: %d %s", got.Code, got.Body.String())
		}
	}
}

func TestRefreshFailsClosedAtMaximumSignedEpoch(t *testing.T) {
	service, err := NewServer(testConfig())
	if err != nil {
		t.Fatal(err)
	}
	created := createBoundSessionForTest(t, service.Handler(), "max-epoch", "max-device", uint64(^uint64(0)>>1))
	refreshForTest(t, service.Handler(), created.SessionID, created.HostToken, http.StatusConflict)
}

func createBoundSessionForTest(t *testing.T, handler http.Handler, requestID, deviceID string, epoch uint64) SessionResponse {
	t.Helper()
	authorityPrivate, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	peerPrivate, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	authority := identityForTest("authority-"+deviceID, authorityPrivate)
	peer := identityForTest(deviceID, peerPrivate)
	body, err := json.Marshal(createSessionRequest{RequestID: requestID, DeviceID: deviceID, SessionEpoch: epoch,
		Authority: &authority, PeerIdentity: &peer})
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
	testSessionBindings[created.SessionID] = testSessionBinding{authorityPrivate: authorityPrivate, authority: authority, peer: peer}
	return created
}

func identityForTest(deviceID string, private *ecdsa.PrivateKey) PublicIdentity {
	encoded := elliptic.Marshal(elliptic.P256(), private.PublicKey.X, private.PublicKey.Y)
	digest := sha256.Sum256(encoded)
	return PublicIdentity{DeviceID: deviceID, KeyID: hex.EncodeToString(digest[:]), KeyEpoch: 1, SigningPublicKey: encoded}
}

func signedRevokeBody(t *testing.T, sessionID, deviceID string, sequence uint64) string {
	t.Helper()
	binding := testSessionBindings[sessionID]
	tombstone := SignedDeviceRevocation{PeerIdentity: binding.peer, Sequence: sequence,
		RevokedAtUnixSeconds: time.Now().Unix(), Nonce: []byte("unique-test-nonce"), ReasonCode: "user_revoked", Authority: binding.authority}
	signature, err := ecdsa.SignASN1(rand.Reader, binding.authorityPrivate, tombstone.signingDigest())
	if err != nil {
		t.Fatal(err)
	}
	tombstone.AuthoritySignature = signature
	body, err := json.Marshal(revokeSessionRequest{DeviceID: deviceID, Tombstone: &tombstone})
	if err != nil {
		t.Fatal(err)
	}
	return string(body)
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
