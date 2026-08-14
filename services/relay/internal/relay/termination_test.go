package relay

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestTerminationWebhookRejectsRedirectWithoutForwardingToken(t *testing.T) {
	forwarded := false
	destination := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		forwarded = true
	}))
	defer destination.Close()
	redirect := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, destination.URL, http.StatusTemporaryRedirect)
	}))
	defer redirect.Close()

	cfg := testConfig(t)
	cfg.AllocationTerminationWebhookURL = redirect.URL
	cfg.AllocationTerminationTimeoutSeconds = 1
	cfg.TerminationToken = strings.Repeat("x", 32)
	terminator := newWebhookAllocationTerminator(cfg)
	err := terminator.Terminate(context.Background(), allocationTerminationRequest{RevocationID: "revocation", DeviceID: "device"})
	if err == nil || forwarded {
		t.Fatalf("redirect error = %v, token forwarded = %t", err, forwarded)
	}
}
