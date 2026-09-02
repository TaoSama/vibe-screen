package signaling

import (
	"bytes"
	"context"
	"crypto/ecdh"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

const testAuthorityToken = "authority-token-with-at-least-32-characters"

func newTestAuthorityServer(t *testing.T, handler http.HandlerFunc) (*httptest.Server, *AuthorityClient) {
	t.Helper()
	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)
	client, err := NewAuthorityClient(server.URL, testAuthorityToken)
	if err != nil {
		t.Fatal(err)
	}
	return server, client
}

func TestAuthorityClientCreateSession(t *testing.T) {
	var called atomic.Int32
	_, client := newTestAuthorityServer(t, func(w http.ResponseWriter, r *http.Request) {
		called.Add(1)
		if r.Header.Get("Authorization") != "Bearer "+testAuthorityToken {
			t.Errorf("unexpected authorization header: %q", r.Header.Get("Authorization"))
		}
		if r.Method != http.MethodPost || r.URL.Path != "/v1/signaling/sessions" {
			t.Errorf("unexpected request: %s %s", r.Method, r.URL.Path)
		}
		var request authoritySignalingRequest
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Errorf("decode authority request: %v", err)
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		if request.RequestID != "req-1" || request.AccountID != "acct-1" ||
			request.HostDeviceID != "host-1" || request.ClientDeviceID != "client-1" ||
			request.SessionEpoch != 1 || request.TTLSeconds != 60 {
			t.Errorf("unexpected request: %#v", request)
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
			SessionID:   "sess-1",
			HostToken:   "host-token-1",
			ClientToken: "client-token-1",
			ExpiresAt:   time.Now().Add(time.Hour).UTC(),
			Created:     true,
		})
	})

	admission, err := client.CreateSession(context.Background(), authoritySignalingRequest{
		RequestID: "req-1", AccountID: "acct-1", HostDeviceID: "host-1",
		ClientDeviceID: "client-1", SessionEpoch: 1, TTLSeconds: 60,
	})
	if err != nil {
		t.Fatal(err)
	}
	if admission.SessionID != "sess-1" || admission.HostToken != "host-token-1" ||
		admission.ClientToken != "client-token-1" || !admission.Created {
		t.Errorf("unexpected admission: %#v", admission)
	}
	if called.Load() != 1 {
		t.Errorf("expected 1 call, got %d", called.Load())
	}
}

func TestAuthorityClientCreateSessionReplay(t *testing.T) {
	_, client := newTestAuthorityServer(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
			SessionID:   "sess-1",
			HostToken:   "host-token-1",
			ClientToken: "client-token-1",
			ExpiresAt:   time.Now().Add(time.Hour).UTC(),
			Created:     false,
		})
	})

	admission, err := client.CreateSession(context.Background(), authoritySignalingRequest{
		RequestID: "req-1", AccountID: "acct-1", HostDeviceID: "host-1",
		ClientDeviceID: "client-1", SessionEpoch: 1, TTLSeconds: 60,
	})
	if err != nil {
		t.Fatal(err)
	}
	if admission.Created {
		t.Errorf("expected replay (created=false), got %#v", admission)
	}
}

func TestAuthorityClientCreateSessionWithSessionProfile(t *testing.T) {
	expiresAt := time.Now().Add(time.Hour).UTC().Round(time.Second)
	profileRequest := testSessionProfileRequest(t, "host-1", "client-1")
	unsignedLease := testUnsignedAndroidLease(t, profileRequest, authoritySignalingAdmission{
		SessionID: "sess-1", HostToken: "host-token-1", ClientToken: "client-token-1", ExpiresAt: expiresAt, Created: true,
	})
	_, client := newTestAuthorityServer(t, func(w http.ResponseWriter, r *http.Request) {
		var request authoritySignalingRequest
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Fatalf("decode authority request: %v", err)
		}
		if request.SessionProfile == nil {
			t.Fatal("authority request omitted session_profile")
		}
		if request.SessionProfile.PairingID != profileRequest.PairingID ||
			request.SessionProfile.ClientIdentity.KeyID != profileRequest.ClientIdentity.KeyID {
			t.Fatalf("unexpected authority profile request: %#v", request.SessionProfile)
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
			SessionID: "sess-1", HostToken: "host-token-1", ClientToken: "client-token-1",
			ExpiresAt: expiresAt, Created: true,
			SessionProfile: &SessionProfileResponse{
				AccountID: "acct-1", PairingID: profileRequest.PairingID,
				SignalingSessionID: "sess-1", HostSignalingToken: "host-token-1",
				ExpiresAt: expiresAt, Created: true, UnsignedAndroidLease: unsignedLease,
			},
		})
	})

	admission, err := client.CreateSession(context.Background(), authoritySignalingRequest{
		RequestID: "req-1", AccountID: "acct-1", HostDeviceID: "host-1",
		ClientDeviceID: "client-1", SessionEpoch: 7, TTLSeconds: 60, SessionProfile: profileRequest,
	})
	if err != nil {
		t.Fatal(err)
	}
	if admission.SessionProfile == nil || string(admission.SessionProfile.UnsignedAndroidLease) != string(unsignedLease) {
		t.Fatalf("session profile was not returned exactly: %#v", admission.SessionProfile)
	}
}

func TestAuthorityClientRejectsMalformedSessionProfileAdmission(t *testing.T) {
	expiresAt := time.Now().Add(time.Hour).UTC().Round(time.Second)
	profileRequest := testSessionProfileRequest(t, "host-1", "client-1")
	baseAdmission := authoritySignalingAdmission{
		SessionID: "sess-1", HostToken: "host-token-1", ClientToken: "client-token-1", ExpiresAt: expiresAt, Created: true,
	}
	validLease := testUnsignedAndroidLease(t, profileRequest, baseAdmission)
	mutatedLease := func(mutate func(map[string]any)) json.RawMessage {
		var root map[string]any
		if err := json.Unmarshal(validLease, &root); err != nil {
			t.Fatal(err)
		}
		mutate(root)
		encoded, err := json.Marshal(root)
		if err != nil {
			t.Fatal(err)
		}
		return encoded
	}
	for name, lease := range map[string]json.RawMessage{
		"signed-only field":  mutatedLease(func(root map[string]any) { root["lease_signature"] = "sig" }),
		"unknown root field": mutatedLease(func(root map[string]any) { root["unexpected"] = true }),
		"client token drift": mutatedLease(func(root map[string]any) { root["signaling_token"] = "other-client-token" }),
		"ICE drift": mutatedLease(func(root map[string]any) {
			root["ice_servers"] = []any{map[string]any{"urls": []any{"stun:other.example.test"}, "username": nil, "credential": nil}}
		}),
	} {
		t.Run(name, func(t *testing.T) {
			_, client := newTestAuthorityServer(t, func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(http.StatusCreated)
				admission := baseAdmission
				admission.SessionProfile = &SessionProfileResponse{
					AccountID: "acct-1", PairingID: profileRequest.PairingID,
					SignalingSessionID: baseAdmission.SessionID, HostSignalingToken: baseAdmission.HostToken,
					ExpiresAt: expiresAt, Created: true, UnsignedAndroidLease: lease,
				}
				_ = json.NewEncoder(w).Encode(admission)
			})
			_, err := client.CreateSession(context.Background(), authoritySignalingRequest{
				RequestID: "req-1", AccountID: "acct-1", HostDeviceID: "host-1",
				ClientDeviceID: "client-1", SessionEpoch: 7, TTLSeconds: 60, SessionProfile: profileRequest,
			})
			if !errors.Is(err, ErrAuthorityUnavailable) {
				t.Fatalf("malformed profile admission did not fail closed: %v", err)
			}
		})
	}
}

func TestAuthorityClientAuthorizeRole(t *testing.T) {
	_, client := newTestAuthorityServer(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || !strings.HasSuffix(r.URL.Path, "/authorize") {
			t.Errorf("unexpected request: %s %s", r.Method, r.URL.Path)
		}
		var request struct {
			RoleToken string `json:"role_token"`
		}
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Errorf("decode authorization request: %v", err)
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		role := "client"
		if request.RoleToken == "host-token" {
			role = "host"
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{
			"role":       role,
			"expires_at": time.Now().Add(time.Hour).UTC(),
		})
	})

	authorization, err := client.AuthorizeRole(context.Background(), "sess-1", "host-token")
	if err != nil {
		t.Fatal(err)
	}
	if authorization.Role != "host" || !authorization.ExpiresAt.After(time.Now()) {
		t.Errorf("unexpected host authorization: %#v", authorization)
	}

	authorization, err = client.AuthorizeRole(context.Background(), "sess-1", "client-token")
	if err != nil {
		t.Fatal(err)
	}
	if authorization.Role != "client" || !authorization.ExpiresAt.After(time.Now()) {
		t.Errorf("unexpected client authorization: %#v", authorization)
	}
}

func TestAuthorityClientRejectsExpiredAuthorization(t *testing.T) {
	_, client := newTestAuthorityServer(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{
			"role":       "host",
			"expires_at": time.Now().Add(-time.Second).UTC(),
		})
	})

	if _, err := client.AuthorizeRole(context.Background(), "sess-1", "host-token"); !errors.Is(err, ErrAuthorityUnavailable) {
		t.Fatalf("expired authority authorization did not fail closed: %v", err)
	}
}

func TestAuthorityClientInvalidateSession(t *testing.T) {
	var called atomic.Int32
	_, client := newTestAuthorityServer(t, func(w http.ResponseWriter, r *http.Request) {
		called.Add(1)
		if r.Method != http.MethodDelete {
			t.Errorf("unexpected method: %s", r.Method)
		}
		if !strings.HasPrefix(r.URL.Path, "/v1/signaling/sessions/") {
			t.Errorf("unexpected path: %s", r.URL.Path)
		}
		w.WriteHeader(http.StatusNoContent)
	})

	if err := client.InvalidateSession(context.Background(), "sess-1"); err != nil {
		t.Fatal(err)
	}
	if called.Load() != 1 {
		t.Errorf("expected 1 call, got %d", called.Load())
	}
}

func TestAuthorityClientInvalidateMissingSessionIsIdempotent(t *testing.T) {
	_, client := newTestAuthorityServer(t, func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	})

	if err := client.InvalidateSession(context.Background(), "sess-1"); err != nil {
		t.Fatalf("missing authority admission was not treated as invalidated: %v", err)
	}
}

func TestInvalidateAuthorityAdmissionIgnoresCallerCancellation(t *testing.T) {
	var called atomic.Int32
	_, client := newTestAuthorityServer(t, func(w http.ResponseWriter, r *http.Request) {
		called.Add(1)
		if r.Method != http.MethodDelete {
			t.Errorf("unexpected method: %s", r.Method)
		}
		w.WriteHeader(http.StatusNoContent)
	})

	canceled, cancel := context.WithCancel(context.Background())
	cancel()
	if err := client.InvalidateSession(canceled, "sess-1"); !errors.Is(err, ErrAuthorityUnavailable) {
		t.Fatalf("direct invalidation with canceled context error=%v, want ErrAuthorityUnavailable", err)
	}
	called.Store(0)
	if err := invalidateAuthorityAdmission(client, "sess-1"); err != nil {
		t.Fatalf("compensating invalidation failed: %v", err)
	}
	if called.Load() != 1 {
		t.Fatalf("compensating invalidation calls=%d, want 1", called.Load())
	}
}

func TestAuthorityClientFailClosedOnNon2xx(t *testing.T) {
	_, client := newTestAuthorityServer(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	})

	_, err := client.CreateSession(context.Background(), authoritySignalingRequest{
		RequestID: "req-1", AccountID: "acct-1", HostDeviceID: "host-1",
		ClientDeviceID: "client-1", SessionEpoch: 1, TTLSeconds: 60,
	})
	if !errors.Is(err, ErrAuthorityUnavailable) {
		t.Fatalf("expected ErrAuthorityUnavailable, got %v", err)
	}

	if _, err := client.AuthorizeRole(context.Background(), "sess-1", "token"); !errors.Is(err, ErrAuthorityUnavailable) {
		t.Fatalf("expected ErrAuthorityUnavailable, got %v", err)
	}

	if err := client.InvalidateSession(context.Background(), "sess-1"); !errors.Is(err, ErrAuthorityUnavailable) {
		t.Fatalf("expected ErrAuthorityUnavailable, got %v", err)
	}
}

func TestAuthorityClientFailClosedOnMalformedResponse(t *testing.T) {
	_, client := newTestAuthorityServer(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = io.WriteString(w, `{not valid json`)
	})

	_, err := client.CreateSession(context.Background(), authoritySignalingRequest{
		RequestID: "req-1", AccountID: "acct-1", HostDeviceID: "host-1",
		ClientDeviceID: "client-1", SessionEpoch: 1, TTLSeconds: 60,
	})
	if !errors.Is(err, ErrAuthorityUnavailable) {
		t.Fatalf("expected ErrAuthorityUnavailable, got %v", err)
	}
}

func TestAuthorityClientFailClosedOnOversizedResponse(t *testing.T) {
	_, client := newTestAuthorityServer(t, func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = io.WriteString(w, strings.Repeat("x", authorityMaxResponseBytes+1))
	})

	_, err := client.CreateSession(context.Background(), authoritySignalingRequest{
		RequestID: "req-1", AccountID: "acct-1", HostDeviceID: "host-1",
		ClientDeviceID: "client-1", SessionEpoch: 1, TTLSeconds: 60,
	})
	if !errors.Is(err, ErrAuthorityUnavailable) {
		t.Fatalf("oversized authority response did not fail closed: %v", err)
	}
}

func TestAuthorityClientRequiresJSONContentType(t *testing.T) {
	_, client := newTestAuthorityServer(t, func(w http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(w, `{"session_id":"s","host_token":"h","client_token":"c","expires_at":"2030-01-01T00:00:00Z","created":false}`)
	})

	_, err := client.CreateSession(context.Background(), authoritySignalingRequest{
		RequestID: "req-1", AccountID: "acct-1", HostDeviceID: "host-1",
		ClientDeviceID: "client-1", SessionEpoch: 1, TTLSeconds: 60,
	})
	if !errors.Is(err, ErrAuthorityUnavailable) {
		t.Fatalf("non-JSON authority response did not fail closed: %v", err)
	}
}

func TestAuthorityClientMapsDefinitiveAuthorizationRejection(t *testing.T) {
	_, client := newTestAuthorityServer(t, func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusForbidden)
	})
	if _, err := client.AuthorizeRole(context.Background(), "sess-1", "role-token"); !errors.Is(err, ErrUnauthorized) {
		t.Fatalf("authority rejection did not map to uniform unauthorized: %v", err)
	}
}

func TestAuthorityClientReady(t *testing.T) {
	ready := true
	_, client := newTestAuthorityServer(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/readyz" {
			t.Errorf("unexpected readiness path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		if !ready {
			w.WriteHeader(http.StatusServiceUnavailable)
		}
		_ = json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
	})
	if err := client.Ready(context.Background()); err != nil {
		t.Fatalf("ready authority rejected: %v", err)
	}
	ready = false
	if err := client.Ready(context.Background()); !errors.Is(err, ErrAuthorityUnavailable) {
		t.Fatalf("unready authority was accepted: %v", err)
	}
}

func TestAuthorityClientFailClosedOnUnknownFields(t *testing.T) {
	_, client := newTestAuthorityServer(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = io.WriteString(w, `{"session_id":"s","host_token":"h","client_token":"c","expires_at":"2030-01-01T00:00:00Z","created":true,"unexpected":"field"}`)
	})

	_, err := client.CreateSession(context.Background(), authoritySignalingRequest{
		RequestID: "req-1", AccountID: "acct-1", HostDeviceID: "host-1",
		ClientDeviceID: "client-1", SessionEpoch: 1, TTLSeconds: 60,
	})
	if !errors.Is(err, ErrAuthorityUnavailable) {
		t.Fatalf("expected ErrAuthorityUnavailable for unknown fields, got %v", err)
	}
}

func TestAuthorityClientFailClosedOnIncompleteAdmission(t *testing.T) {
	_, client := newTestAuthorityServer(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = io.WriteString(w, `{"session_id":"s","host_token":"","client_token":"c","expires_at":"2030-01-01T00:00:00Z","created":true}`)
	})

	_, err := client.CreateSession(context.Background(), authoritySignalingRequest{
		RequestID: "req-1", AccountID: "acct-1", HostDeviceID: "host-1",
		ClientDeviceID: "client-1", SessionEpoch: 1, TTLSeconds: 60,
	})
	if !errors.Is(err, ErrAuthorityUnavailable) {
		t.Fatalf("expected ErrAuthorityUnavailable for incomplete admission, got %v", err)
	}
}

func TestAuthorityClientRejectsRedirects(t *testing.T) {
	redirectServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "http://evil.example.com/steal", http.StatusFound)
	}))
	defer redirectServer.Close()

	client, err := NewAuthorityClient(redirectServer.URL, testAuthorityToken)
	if err != nil {
		t.Fatal(err)
	}

	_, err = client.CreateSession(context.Background(), authoritySignalingRequest{
		RequestID: "req-1", AccountID: "acct-1", HostDeviceID: "host-1",
		ClientDeviceID: "client-1", SessionEpoch: 1, TTLSeconds: 60,
	})
	if !errors.Is(err, ErrAuthorityUnavailable) {
		t.Fatalf("expected ErrAuthorityUnavailable on redirect, got %v", err)
	}
}

func TestAuthorityClientURLPolicy(t *testing.T) {
	for _, raw := range []string{
		"ftp://example.com",
		"http://example.com",
		"http://user:pass@example.com",
		"https://example.com/base",
		"https://example.com?region=one",
		"http://example.com#fragment",
		"://bad",
	} {
		_, err := NewAuthorityClient(raw, testAuthorityToken)
		if err == nil {
			t.Errorf("expected error for URL %q", raw)
		}
	}
}

func TestAuthorityClientErrorsDoNotLeakSecrets(t *testing.T) {
	_, client := newTestAuthorityServer(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	})

	_, err := client.CreateSession(context.Background(), authoritySignalingRequest{
		RequestID: "req-1", AccountID: "acct-1", HostDeviceID: "host-1",
		ClientDeviceID: "client-1", SessionEpoch: 1, TTLSeconds: 60,
	})
	if err == nil {
		t.Fatal("expected error")
	}
	if strings.Contains(err.Error(), testAuthorityToken) {
		t.Errorf("error leaked authority token: %v", err)
	}
}

func TestRoleFromAuthority(t *testing.T) {
	if role, err := roleFromAuthority("host"); err != nil || role != RoleHost {
		t.Errorf("expected host")
	}
	if role, err := roleFromAuthority("client"); err != nil || role != RoleDevice {
		t.Errorf("expected device")
	}
	if _, err := roleFromAuthority("peer"); !errors.Is(err, ErrAuthorityUnavailable) {
		t.Errorf("unknown role did not fail closed: %v", err)
	}
}

func testSessionProfileRequest(t *testing.T, hostDeviceID, clientDeviceID string) *SessionProfileRequest {
	t.Helper()
	hostIdentity := testPublicDeviceIdentity(t, hostDeviceID, 3)
	clientIdentity := testPublicDeviceIdentity(t, clientDeviceID, 5)
	return &SessionProfileRequest{
		PairingID:         "pair-1",
		HostIdentity:      hostIdentity,
		ClientIdentity:    clientIdentity,
		SignalingURL:      "https://signal.example.test",
		TranscriptContext: base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{1}, sha256.Size)),
		ProtocolSessionID: base64.StdEncoding.EncodeToString([]byte("protocol-session-1")),
		ICEServers:        []LeaseICEServer{{URLs: []string{"stun:stun.example.test"}}},
	}
}

func testPublicDeviceIdentity(t *testing.T, deviceID string, epoch uint64) PublicDeviceIdentity {
	t.Helper()
	privateKey, err := ecdh.P256().GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	publicKey := privateKey.PublicKey().Bytes()
	digest := sha256.Sum256(publicKey)
	return PublicDeviceIdentity{
		DeviceID:           deviceID,
		KeyID:              hex.EncodeToString(digest[:]),
		KeyEpoch:           epoch,
		SignatureAlgorithm: "ECDSA_P256_SHA256",
		SigningPublicKey:   base64.RawURLEncoding.EncodeToString(publicKey),
	}
}

func testUnsignedAndroidLease(t *testing.T, profile *SessionProfileRequest, admission authoritySignalingAdmission) json.RawMessage {
	t.Helper()
	root := map[string]any{
		"version":                    1,
		"pairing_id":                 profile.PairingID,
		"pinned_host_id":             profile.HostIdentity.DeviceID,
		"pinned_device_id":           profile.ClientIdentity.DeviceID,
		"lease_device_key_id":        profile.ClientIdentity.KeyID,
		"signaling_url":              profile.SignalingURL,
		"signaling_session_id":       admission.SessionID,
		"session_epoch":              uint64(7),
		"host_identity_epoch":        profile.HostIdentity.KeyEpoch,
		"device_identity_epoch":      profile.ClientIdentity.KeyEpoch,
		"expires_at":                 uint64(admission.ExpiresAt.Unix()),
		"transcript_context":         profile.TranscriptContext,
		"protocol_session_id":        base64.StdEncoding.EncodeToString([]byte(admission.SessionID)),
		"signaling_token":            admission.ClientToken,
		"ice_servers":                []any{map[string]any{"urls": []string{"stun:stun.example.test"}, "username": nil, "credential": nil}},
		"allow_insecure_for_testing": profile.AllowInsecureForTesting,
	}
	encoded, err := json.Marshal(root)
	if err != nil {
		t.Fatal(err)
	}
	return encoded
}
