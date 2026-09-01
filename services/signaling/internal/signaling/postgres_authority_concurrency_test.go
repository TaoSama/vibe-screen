package signaling

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestPostgresAuthorityConcurrentCreateWithAuthorityRateLimitDoesNotReturnStorageError(t *testing.T) {
	var authorityCalls atomic.Int32
	authorityServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var request authoritySignalingRequest
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Errorf("decode authority request: %v", err)
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		call := authorityCalls.Add(1)
		if call%2 == 0 {
			w.WriteHeader(http.StatusTooManyRequests)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		_ = json.NewEncoder(w).Encode(authoritySignalingAdmission{
			SessionID:   fmt.Sprintf("authority-rate-%d", request.SessionEpoch),
			HostToken:   fmt.Sprintf("host-token-%d", request.SessionEpoch),
			ClientToken: fmt.Sprintf("client-token-%d", request.SessionEpoch),
			ExpiresAt:   time.Now().Add(time.Hour).UTC(),
			Created:     true,
		})
	}))
	defer authorityServer.Close()

	cfg := testAuthorityConfig(authorityServer.URL)
	cfg.SessionCreatesPerMinute = 100
	cfg.MaxActiveSessions = 1000
	store, _ := openSignalingIntegrationStore(t, cfg)
	ctx := context.Background()
	authority, err := NewAuthorityClient(cfg.AuthorityURL, cfg.AuthorityToken)
	if err != nil {
		t.Fatal(err)
	}
	store.authority = authority

	cleanupCtx, cleanupCancel := context.WithCancel(ctx)
	defer cleanupCancel()
	go func() {
		ticker := time.NewTicker(1 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-cleanupCtx.Done():
				return
			case <-ticker.C:
				store.Cleanup()
			}
		}
	}()

	const numCreates = 100
	var wg sync.WaitGroup
	errs := make([]error, numCreates)
	for i := 0; i < numCreates; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			_, _, errs[i] = store.Create(ctx, CreateSessionRequest{
				RequestID:      fmt.Sprintf("req-%d", i),
				TTL:            time.Minute,
				AccountID:      "acct-1",
				HostDeviceID:   fmt.Sprintf("host-%d", i%5),
				ClientDeviceID: fmt.Sprintf("client-%d", i%5),
				SessionEpoch:   uint64(i + 1),
			})
		}(i)
	}
	wg.Wait()

	var accepted, rateLimited, storageErr, authorityUnavailable, other int
	for _, err := range errs {
		switch {
		case err == nil:
			accepted++
		case errors.Is(err, ErrRateLimited):
			rateLimited++
		case errors.Is(err, ErrStorage):
			storageErr++
			t.Logf("storage error: %v", err)
		case errors.Is(err, ErrAuthorityUnavailable):
			authorityUnavailable++
		default:
			other++
			t.Logf("other error: %v", err)
		}
	}
	t.Logf("accepted=%d rateLimited=%d storageErr=%d authorityUnavailable=%d other=%d", accepted, rateLimited, storageErr, authorityUnavailable, other)
	if storageErr > 0 {
		t.Fatalf("got %d storage errors (503)", storageErr)
	}
	if authorityUnavailable > 0 || other > 0 {
		t.Fatalf("authorityUnavailable=%d other=%d, want only accepted or rate-limited results", authorityUnavailable, other)
	}
	if accepted == 0 || rateLimited == 0 || accepted+rateLimited != numCreates {
		t.Fatalf("accepted=%d rateLimited=%d, want mixed accepted/rate-limited results for all %d creates", accepted, rateLimited, numCreates)
	}
	if got := int(authorityCalls.Load()); got != numCreates {
		t.Fatalf("authority calls=%d, want %d", got, numCreates)
	}
}

func TestPostgresDualInstanceConcurrentCreateWithCleanupDoesNotReturnStorageError(t *testing.T) {
	cfg := testConfig()
	cfg.SessionCreatesPerMinute = 10
	cfg.MaxActiveSessions = 1000
	first, cfg := openSignalingIntegrationStore(t, cfg)
	ctx := context.Background()
	second, err := OpenPostgresStore(ctx, cfg, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer second.Close()

	cleanupCtx, cleanupCancel := context.WithCancel(ctx)
	defer cleanupCancel()
	for _, store := range []*PostgresStore{first, second} {
		go func(store *PostgresStore) {
			ticker := time.NewTicker(time.Millisecond)
			defer ticker.Stop()
			for {
				select {
				case <-cleanupCtx.Done():
					return
				case <-ticker.C:
					store.Cleanup()
				}
			}
		}(store)
	}

	const numCreates = 100
	var wait sync.WaitGroup
	errs := make([]error, numCreates)
	for index := 0; index < numCreates; index++ {
		wait.Add(1)
		store := first
		if index%2 == 1 {
			store = second
		}
		go func(index int, store *PostgresStore) {
			defer wait.Done()
			_, _, errs[index] = store.Create(ctx, CreateSessionRequest{
				RequestID:      fmt.Sprintf("dual-instance-%d", index),
				TTL:            time.Minute,
				HostDeviceID:   "host-shared",
				ClientDeviceID: "client-shared",
			})
		}(index, store)
	}
	wait.Wait()

	var accepted, rateLimited, storageErr, other int
	for _, err := range errs {
		switch {
		case err == nil:
			accepted++
		case errors.Is(err, ErrRateLimited):
			rateLimited++
		case errors.Is(err, ErrStorage):
			storageErr++
			t.Logf("storage error: %v", err)
		default:
			other++
			t.Logf("other error: %v", err)
		}
	}
	if storageErr > 0 || other > 0 {
		t.Fatalf("storageErr=%d other=%d, want only accepted or rate-limited results", storageErr, other)
	}
	if accepted != cfg.SessionCreatesPerMinute || rateLimited != numCreates-cfg.SessionCreatesPerMinute {
		t.Fatalf("accepted=%d rateLimited=%d, want accepted=%d rateLimited=%d", accepted, rateLimited, cfg.SessionCreatesPerMinute, numCreates-cfg.SessionCreatesPerMinute)
	}
}
