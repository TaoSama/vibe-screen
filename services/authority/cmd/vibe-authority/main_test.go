package main

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestProbeHealthRequiresReadyJSON(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte("{\"status\":\"ok\"}"))
	}))
	defer server.Close()
	if err := probeHealth(server.URL); err != nil {
		t.Fatal(err)
	}
}

func TestProbeHealthRejectsUnreadyResponse(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "unavailable", http.StatusServiceUnavailable)
	}))
	defer server.Close()
	if err := probeHealth(server.URL); err == nil {
		t.Fatal("unready endpoint passed the healthcheck")
	}
}
