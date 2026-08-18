package signaling

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"math"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
	"unicode/utf8"
)

const (
	authorityReadinessCacheTTL       = time.Second
	authorityReadinessRefreshTimeout = 2 * time.Second
)

type authorityReadinessRefresh struct {
	done      chan struct{}
	completed bool
}

type Server struct {
	cfg                       Config
	store                     Store
	authority                 *AuthorityClient
	metrics                   Metrics
	ready                     atomic.Bool
	createMu                  sync.Mutex
	createRate                rateWindow
	authorityReadinessMu      sync.Mutex
	authorityReadinessAt      time.Time
	authorityReadinessErr     error
	authorityReadinessPending *authorityReadinessRefresh
	now                       func() time.Time
}

func NewServer(cfg Config) (*Server, error) {
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	var authority *AuthorityClient
	if cfg.AuthorityMode == AuthorityModeProductionAuthority {
		client, err := NewAuthorityClient(cfg.AuthorityURL, cfg.AuthorityToken)
		if err != nil {
			return nil, err
		}
		authority = client
	}
	store, err := openStore(context.Background(), cfg, authority)
	if err != nil {
		return nil, err
	}
	return &Server{
		cfg:       cfg,
		store:     store,
		authority: authority,
		now:       time.Now,
	}, nil
}

func openStore(ctx context.Context, cfg Config, authority *AuthorityClient) (Store, error) {
	switch cfg.StoreBackend {
	case StoreBackendMemory:
		return NewMemoryStore(cfg, authority), nil
	case StoreBackendPostgres:
		return OpenPostgresStore(ctx, cfg, authority)
	default:
		return nil, fmt.Errorf("unsupported store backend %q", cfg.StoreBackend)
	}
}

func (s *Server) Close() { s.store.Close() }

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", s.health)
	mux.HandleFunc("GET /readyz", s.readiness)
	mux.HandleFunc("GET /metrics", s.metricsHandler)
	mux.HandleFunc("POST /v1/sessions", s.createSession)
	mux.HandleFunc("DELETE /v1/sessions/{session_id}", s.invalidateSession)
	mux.HandleFunc("POST /v1/sessions/{session_id}/messages", s.postMessage)
	mux.HandleFunc("GET /v1/sessions/{session_id}/events", s.getEvents)
	return securityHeaders(mux)
}

func (s *Server) invalidateSession(w http.ResponseWriter, r *http.Request) {
	if !authorized(r, s.cfg.IssuerToken) {
		s.reject(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	sessionID := r.PathValue("session_id")
	if !validIdentifier(sessionID) {
		s.reject(w, http.StatusBadRequest, "invalid session_id")
		return
	}
	invalidated, err := s.store.Invalidate(r.Context(), sessionID)
	if err != nil {
		s.writeStoreError(w, err)
		return
	}
	if invalidated {
		s.metrics.sessionsInvalidated.Add(1)
	}
	w.WriteHeader(http.StatusNoContent)
}

func (s *Server) SetReady(ready bool) {
	s.ready.Store(ready)
}

func (s *Server) RunCleanup(ctx context.Context) {
	ticker := time.NewTicker(s.cfg.CleanupInterval())
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			s.metrics.expiredCleaned.Add(uint64(s.store.Cleanup()))
		}
	}
}

func (s *Server) health(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (s *Server) readiness(w http.ResponseWriter, r *http.Request) {
	if !s.ready.Load() {
		s.reject(w, http.StatusServiceUnavailable, "not ready")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), authorityReadinessRefreshTimeout)
	defer cancel()
	if err := s.store.Ready(ctx); err != nil {
		s.reject(w, http.StatusServiceUnavailable, "not ready")
		return
	}
	if s.authority != nil {
		if err := s.cachedAuthorityReadiness(ctx); err != nil {
			s.reject(w, http.StatusServiceUnavailable, "not ready")
			return
		}
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

// cachedAuthorityReadiness prevents the unauthenticated readiness endpoint
// from forwarding every probe to the authority and its database. One caller
// refreshes the short-lived success or failure cache while concurrent probes
// wait for that same result.
func (s *Server) cachedAuthorityReadiness(ctx context.Context) error {
	var observed *authorityReadinessRefresh
	for {
		s.authorityReadinessMu.Lock()
		now := s.now()
		if !s.authorityReadinessAt.IsZero() {
			age := now.Sub(s.authorityReadinessAt)
			if age >= 0 && age < authorityReadinessCacheTTL {
				err := s.authorityReadinessErr
				s.authorityReadinessMu.Unlock()
				return err
			}
		}
		if observed != nil && !observed.completed {
			s.authorityReadinessMu.Unlock()
			return ErrAuthorityUnavailable
		}
		pending := s.authorityReadinessPending
		if pending == nil {
			pending = &authorityReadinessRefresh{done: make(chan struct{})}
			s.authorityReadinessPending = pending
			go s.refreshAuthorityReadiness(pending)
		}
		s.authorityReadinessMu.Unlock()

		select {
		case <-pending.done:
			observed = pending
		case <-ctx.Done():
			return ctx.Err()
		}
	}
}

func (s *Server) refreshAuthorityReadiness(refresh *authorityReadinessRefresh) {
	var result error
	completed := false
	defer func() {
		panicked := recover() != nil
		s.authorityReadinessMu.Lock()
		if completed {
			s.authorityReadinessAt = s.now()
			s.authorityReadinessErr = result
		} else {
			s.authorityReadinessAt = time.Time{}
			s.authorityReadinessErr = ErrAuthorityUnavailable
		}
		refresh.completed = completed
		s.authorityReadinessPending = nil
		close(refresh.done)
		s.authorityReadinessMu.Unlock()
		if panicked {
			slog.Error("authority readiness refresh panicked")
		}
	}()

	refreshCtx, cancel := context.WithTimeout(context.Background(), authorityReadinessRefreshTimeout)
	defer cancel()
	result = s.authority.Ready(refreshCtx)
	completed = true
}

func (s *Server) metricsHandler(w http.ResponseWriter, r *http.Request) {
	if !authorized(r, s.cfg.MetricsToken) {
		s.reject(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	w.Header().Set("Content-Type", "text/plain; version=0.0.4")
	if err := s.metrics.WritePrometheus(w, s.store.Stats()); err != nil {
		return
	}
}

type createSessionRequest struct {
	RequestID      string `json:"request_id"`
	TTLSeconds     int64  `json:"ttl_seconds,omitempty"`
	AccountID      string `json:"account_id,omitempty"`
	HostDeviceID   string `json:"host_device_id,omitempty"`
	ClientDeviceID string `json:"client_device_id,omitempty"`
	SessionEpoch   uint64 `json:"session_epoch,omitempty"`
}

func (s *Server) createSession(w http.ResponseWriter, r *http.Request) {
	if !authorized(r, s.cfg.IssuerToken) {
		s.reject(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	if !s.allowCreate() {
		s.reject(w, http.StatusTooManyRequests, "session creation rate limit exceeded")
		return
	}
	var request createSessionRequest
	if err := s.decodeJSON(w, r, &request); err != nil {
		s.reject(w, http.StatusBadRequest, err.Error())
		return
	}
	if !validIdentifier(request.RequestID) {
		s.reject(w, http.StatusBadRequest, "invalid request_id")
		return
	}
	ttl := s.cfg.SessionTTL()
	if request.TTLSeconds != 0 {
		if request.TTLSeconds < 0 || request.TTLSeconds > s.cfg.MaxSessionTTLSeconds {
			s.reject(w, http.StatusBadRequest, "ttl_seconds outside allowed range")
			return
		}
		ttl = time.Duration(request.TTLSeconds) * time.Second
	}
	createReq := CreateSessionRequest{
		RequestID: request.RequestID,
		TTL:       ttl,
	}
	if s.authority != nil {
		if !validIdentifier(request.AccountID) || !validIdentifier(request.HostDeviceID) ||
			!validIdentifier(request.ClientDeviceID) || request.HostDeviceID == request.ClientDeviceID ||
			request.SessionEpoch == 0 || request.SessionEpoch > math.MaxInt64 {
			s.reject(w, http.StatusBadRequest, "account_id, host_device_id, client_device_id, and session_epoch are required in production authority mode")
			return
		}
		createReq.AccountID = request.AccountID
		createReq.HostDeviceID = request.HostDeviceID
		createReq.ClientDeviceID = request.ClientDeviceID
		createReq.SessionEpoch = request.SessionEpoch
	}
	response, created, err := s.store.Create(r.Context(), createReq)
	if err != nil {
		s.writeStoreError(w, err)
		return
	}
	status := http.StatusCreated
	if created {
		s.metrics.sessionsCreated.Add(1)
	} else {
		status = http.StatusOK
		s.metrics.idempotentReplays.Add(1)
	}
	w.Header().Set("Location", "/v1/sessions/"+url.PathEscape(response.SessionID))
	writeJSON(w, status, response)
}

func (s *Server) postMessage(w http.ResponseWriter, r *http.Request) {
	sessionID := r.PathValue("session_id")
	token := bearerToken(r)
	role, err := s.store.Authorize(r.Context(), sessionID, token)
	if err != nil {
		s.writeStoreError(w, err)
		return
	}
	var request MessageRequest
	if err := s.decodeJSON(w, r, &request); err != nil {
		s.reject(w, http.StatusBadRequest, err.Error())
		return
	}
	if err := s.validateMessage(request); err != nil {
		s.reject(w, http.StatusBadRequest, err.Error())
		return
	}
	refreshedRole, err := s.store.Authorize(r.Context(), sessionID, token)
	if err != nil {
		s.writeStoreError(w, err)
		return
	}
	if refreshedRole != role {
		s.writeStoreError(w, ErrUnauthorized)
		return
	}
	event, created, err := s.store.AddMessageAuthorized(r.Context(), sessionID, refreshedRole, request)
	if err != nil {
		s.writeStoreError(w, err)
		return
	}
	status := http.StatusCreated
	if created {
		s.metrics.messagesAccepted.Add(1)
	} else {
		status = http.StatusOK
		s.metrics.idempotentReplays.Add(1)
	}
	writeJSON(w, status, event)
}

func (s *Server) getEvents(w http.ResponseWriter, r *http.Request) {
	if err := validateQuery(r.URL.Query(), "after", "wait_seconds"); err != nil {
		s.reject(w, http.StatusBadRequest, err.Error())
		return
	}
	after, err := parseUintQuery(r.URL.Query().Get("after"), 0)
	if err != nil {
		s.reject(w, http.StatusBadRequest, "after must be an unsigned integer")
		return
	}
	waitSeconds, err := parseIntQuery(r.URL.Query().Get("wait_seconds"), s.cfg.MaxWaitSeconds)
	if err != nil || waitSeconds < 0 || waitSeconds > s.cfg.MaxWaitSeconds {
		s.reject(w, http.StatusBadRequest, "wait_seconds outside allowed range")
		return
	}
	sessionID := r.PathValue("session_id")
	token := bearerToken(r)
	role, err := s.store.Authorize(r.Context(), sessionID, token)
	if err != nil {
		s.writeStoreError(w, err)
		return
	}
	ctx := r.Context()
	if waitSeconds > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(r.Context(), time.Duration(waitSeconds)*time.Second)
		defer cancel()
	}
	events, next, err := s.store.PollAuthorized(ctx, sessionID, role, after, waitSeconds > 0)
	if err != nil {
		s.writeStoreError(w, err)
		return
	}
	// Re-authorize after the wait and before releasing queued SDP/ICE so an
	// authority revocation that happened during a long poll wins.
	refreshedRole, err := s.store.Authorize(r.Context(), sessionID, token)
	if err != nil {
		s.writeStoreError(w, err)
		return
	}
	if refreshedRole != role {
		s.writeStoreError(w, ErrUnauthorized)
		return
	}
	if len(events) == 0 && next == after {
		s.metrics.pollTimeouts.Add(1)
	}
	writeJSON(w, http.StatusOK, map[string]any{"events": events, "next_cursor": next})
}

func (s *Server) validateMessage(request MessageRequest) error {
	if !validIdentifier(request.MessageID) {
		return errors.New("invalid message_id")
	}
	switch request.Type {
	case MessageOffer, MessageAnswer:
		if request.Candidate != nil || !validSDP(request.SDP, s.cfg.MaxSDPBytes) {
			return errors.New("SDP message has invalid fields or size")
		}
	case MessageICECandidate:
		if request.SDP != "" || request.Candidate == nil ||
			!validCandidate(request.Candidate.Candidate, s.cfg.MaxCandidateBytes) ||
			!validAttributeToken(request.Candidate.SDPMid, 256) ||
			!validAttributeToken(request.Candidate.UsernameFragment, 256) {
			return errors.New("ICE candidate has invalid fields or size")
		}
	case MessageEndOfCandidates:
		if request.SDP != "" || request.Candidate != nil {
			return errors.New("end_of_candidates cannot carry a payload")
		}
	default:
		return errors.New("unsupported message type")
	}
	return nil
}

func validSDP(value string, maximum int) bool {
	return len(value) >= len("v=0") && len(value) <= maximum && strings.HasPrefix(value, "v=0") &&
		utf8.ValidString(value) && !strings.ContainsRune(value, '\x00')
}

func validCandidate(value string, maximum int) bool {
	return len(value) > len("candidate:") && len(value) <= maximum && strings.HasPrefix(value, "candidate:") &&
		utf8.ValidString(value) && !strings.ContainsAny(value, "\x00\r\n")
}

func validAttributeToken(value string, maximum int) bool {
	if len(value) > maximum || !utf8.ValidString(value) {
		return false
	}
	for _, char := range value {
		if char < 0x21 || char > 0x7e {
			return false
		}
	}
	return true
}

func (s *Server) decodeJSON(w http.ResponseWriter, r *http.Request, destination any) error {
	contentType := strings.TrimSpace(strings.SplitN(r.Header.Get("Content-Type"), ";", 2)[0])
	if contentType != "application/json" {
		return errors.New("Content-Type must be application/json")
	}
	r.Body = http.MaxBytesReader(w, r.Body, s.cfg.MaxRequestBodyBytes)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return fmt.Errorf("invalid JSON: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return errors.New("request body must contain one JSON object")
	}
	return nil
}

func (s *Server) allowCreate() bool {
	now := s.now()
	s.createMu.Lock()
	defer s.createMu.Unlock()
	if s.createRate.started.IsZero() || now.Sub(s.createRate.started) >= time.Minute {
		s.createRate = rateWindow{started: now}
	}
	if s.createRate.count >= s.cfg.SessionCreatesPerMinute {
		return false
	}
	s.createRate.count++
	return true
}

func (s *Server) writeStoreError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, ErrNotFound):
		s.reject(w, http.StatusNotFound, "session not found")
	case errors.Is(err, ErrExpired):
		s.reject(w, http.StatusGone, "session expired")
	case errors.Is(err, ErrUnauthorized):
		// Do not disclose whether a guessed session identifier exists.
		s.reject(w, http.StatusNotFound, "session not found")
	case errors.Is(err, ErrConflict), errors.Is(err, ErrInvalidated):
		s.reject(w, http.StatusConflict, err.Error())
	case errors.Is(err, ErrRateLimited), errors.Is(err, ErrTooManyWaiters), errors.Is(err, ErrCapacity), errors.Is(err, ErrCandidateLimit):
		s.reject(w, http.StatusTooManyRequests, err.Error())
	case errors.Is(err, ErrStorage):
		s.reject(w, http.StatusServiceUnavailable, "signaling storage unavailable")
	case errors.Is(err, ErrAuthorityUnavailable):
		s.reject(w, http.StatusBadGateway, "authority service unavailable")
	default:
		s.reject(w, http.StatusInternalServerError, "internal error")
	}
}

func (s *Server) reject(w http.ResponseWriter, status int, message string) {
	s.metrics.requestsRejected.Add(1)
	writeJSON(w, status, map[string]string{"error": message})
}

func securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Referrer-Policy", "no-referrer")
		next.ServeHTTP(w, r)
	})
}

func authorized(r *http.Request, expected string) bool {
	if expected == "" {
		return false
	}
	return secureEqual(bearerToken(r), expected)
}

func bearerToken(r *http.Request) string {
	const prefix = "Bearer "
	value := r.Header.Get("Authorization")
	if !strings.HasPrefix(value, prefix) {
		return ""
	}
	return strings.TrimPrefix(value, prefix)
}

func validIdentifier(value string) bool {
	if len(value) < 1 || len(value) > 128 {
		return false
	}
	for _, char := range value {
		if (char >= 'a' && char <= 'z') || (char >= 'A' && char <= 'Z') ||
			(char >= '0' && char <= '9') || char == '-' || char == '_' || char == '.' {
			continue
		}
		return false
	}
	return true
}

func validateQuery(values url.Values, allowed ...string) error {
	permitted := make(map[string]bool, len(allowed))
	for _, name := range allowed {
		permitted[name] = true
	}
	for name, entries := range values {
		if !permitted[name] || len(entries) != 1 {
			return fmt.Errorf("unsupported or repeated query parameter %q", name)
		}
	}
	return nil
}

func parseUintQuery(value string, fallback uint64) (uint64, error) {
	if value == "" {
		return fallback, nil
	}
	return strconv.ParseUint(value, 10, 64)
}

func parseIntQuery(value string, fallback int) (int, error) {
	if value == "" {
		return fallback, nil
	}
	return strconv.Atoi(value)
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(value); err != nil {
		// Do not include the network error because it can contain a raw peer address.
		slog.Warn("signaling response write failed")
	}
}
