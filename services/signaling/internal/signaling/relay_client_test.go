package signaling

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestRelayClientRejectsTrailingJSONAndExcessiveTTL(t *testing.T) {
	for name, response := range map[string]string{
		"trailing": `{"username":"u","password":"p","ttl_seconds":30,"realm":"r","uris":["turn:relay.test:3478"]}{}`,
		"ttl":      `{"username":"u","password":"p","ttl_seconds":31,"realm":"r","uris":["turn:relay.test:3478"]}`,
	} {
		t.Run(name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { _, _ = w.Write([]byte(response)) }))
			defer server.Close()
			client := &httpRelayClient{baseURL: server.URL, clientToken: strings.Repeat("c", 32), adminToken: strings.Repeat("a", 32), client: server.Client()}
			if _, err := client.Credentials(context.Background(), "device", "session", 30); err == nil {
				t.Fatal("invalid relay response accepted")
			}
		})
	}
}

func TestRelayRevokeRequiresStrictConfirmation(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"status":"revoked"} {}`))
	}))
	defer server.Close()
	client := &httpRelayClient{baseURL: server.URL, clientToken: strings.Repeat("c", 32), adminToken: strings.Repeat("a", 32), client: server.Client()}
	if err := client.Revoke(context.Background(), "device"); err == nil {
		t.Fatal("trailing relay revoke response accepted")
	}
}
