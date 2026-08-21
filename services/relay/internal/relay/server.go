package relay

import (
	"context"
	"crypto/hmac"
	"crypto/sha1"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"sync"
	"time"
)

const (
	maxRequestBody = 16 * 1024
	gibibyte       = uint64(1024 * 1024 * 1024)
	maxRateEntries = 10_000
)

type rateWindow struct {
	started time.Time
	count   int
}

type Server struct {
	cfg       Config
	store     Store
	authority relayAuthority
	metrics   Metrics
	now       func() time.Time
	rateMu    sync.Mutex
	rates     map[string]rateWindow
	revokeMu  sync.RWMutex
}

func NewServer(cfg Config) (*Server, error) {
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	store, err := OpenStore(context.Background(), cfg)
	if err != nil {
		return nil, err
	}
	var authority relayAuthority
	if cfg.EffectiveAuthorityMode() == AuthorityModeProd {
		client, err := NewAuthorityClient(cfg.AuthorityURL, cfg.AuthorityToken)
		if err != nil {
			return nil, err
		}
		authority = client
	}
	return &Server{cfg: cfg, store: store, authority: authority, now: time.Now, rates: make(map[string]rateWindow)}, nil
}

func OpenStore(ctx context.Context, cfg Config) (Store, error) {
	switch cfg.EffectiveStorageBackend() {
	case storageBackendFile:
		return NewUsageStore(cfg.StateFile, cfg.DailyBytesPerDevice, cfg.MaxConcurrentSessionsPerDevice)
	case storageBackendPostgres:
		return OpenPostgres(ctx, cfg)
	default:
		return nil, fmt.Errorf("unsupported storage backend %q", cfg.StorageBackend)
	}
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", s.health)
	mux.HandleFunc("GET /readyz", s.ready)
	mux.HandleFunc("GET /metrics", s.metricsHandler)
	mux.HandleFunc("POST /v1/credentials", s.credentials)
	mux.HandleFunc("POST /v1/usage", s.usage)
	mux.HandleFunc("POST /v1/devices/{device_id}/revoke", s.revoke)
	return securityHeaders(mux)
}

func (s *Server) Close() {
	s.store.Close()
}

func securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		next.ServeHTTP(w, r)
	})
}

func (s *Server) health(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (s *Server) ready(w http.ResponseWriter, r *http.Request) {
	if err := s.store.Ready(r.Context()); err != nil {
		s.reject(w, http.StatusServiceUnavailable, "state storage unavailable")
		return
	}
	if s.authority != nil {
		if err := s.authority.Ready(r.Context()); err != nil {
			s.reject(w, http.StatusServiceUnavailable, "authority unavailable")
			return
		}
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (s *Server) metricsHandler(w http.ResponseWriter, r *http.Request) {
	if !authorized(r, s.cfg.MetricsToken) {
		s.reject(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, egress, active, err := s.store.Totals(r.Context(), s.now())
	if err != nil {
		s.rejectStorage(w)
		return
	}
	w.Header().Set("Content-Type", "text/plain; version=0.0.4")
	if err := s.metrics.WritePrometheus(w, active, costMicrocents(egress, s.cfg.EgressMicrocentsPerGibibyte)); err != nil {
		return
	}
}

type credentialRequest struct {
	DeviceID     string `json:"device_id"`
	SessionID    string `json:"session_id"`
	AllocationID string `json:"allocation_id,omitempty"`
	TTLSeconds   int64  `json:"ttl_seconds,omitempty"`
}

func (s *Server) credentials(w http.ResponseWriter, r *http.Request) {
	if !authorized(r, s.cfg.ClientToken) {
		s.reject(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	var request credentialRequest
	if err := decodeJSON(w, r, &request); err != nil {
		s.reject(w, http.StatusBadRequest, err.Error())
		return
	}
	if !validIdentifier(request.DeviceID) || !validIdentifier(request.SessionID) {
		s.reject(w, http.StatusBadRequest, "invalid device_id or session_id")
		return
	}
	if s.authority != nil && !validIdentifier(request.AllocationID) {
		s.reject(w, http.StatusBadRequest, "allocation_id is required in production authority mode")
		return
	}
	s.revokeMu.RLock()
	revoked, err := s.store.IsRevoked(r.Context(), request.DeviceID)
	s.revokeMu.RUnlock()
	if err != nil {
		s.rejectStorage(w)
		return
	}
	if revoked {
		s.rejectRevoked(w)
		return
	}
	if !s.allowCredential(request.DeviceID) {
		s.reject(w, http.StatusTooManyRequests, "credential rate limit exceeded")
		return
	}
	ingress, egress, sessions, err := s.store.Snapshot(r.Context(), s.now(), request.DeviceID)
	if err != nil {
		s.rejectStorage(w)
		return
	}
	if ingress+egress >= s.cfg.DailyBytesPerDevice || sessions >= s.cfg.MaxConcurrentSessionsPerDevice {
		s.reject(w, http.StatusTooManyRequests, "device relay quota exceeded")
		return
	}
	ttl := request.TTLSeconds
	if ttl == 0 {
		ttl = s.cfg.CredentialTTLSeconds
	}
	if ttl <= 0 || ttl > s.cfg.MaxCredentialTTLSeconds {
		s.reject(w, http.StatusBadRequest, "ttl_seconds outside allowed range")
		return
	}
	if s.authority == nil {
		s.revokeMu.RLock()
		defer s.revokeMu.RUnlock()
		revoked, err = s.store.IsRevoked(r.Context(), request.DeviceID)
		if err != nil {
			s.rejectStorage(w)
			return
		}
		if revoked {
			s.rejectRevoked(w)
			return
		}
		s.writeCredential(w, request, ttl)
		return
	}

	if s.authority != nil {
		err := s.authority.AdmitRelay(r.Context(), relayAdmissionRequest{
			DeviceID:     request.DeviceID,
			SessionID:    request.SessionID,
			AllocationID: request.AllocationID,
			SourceID:     s.cfg.AuthoritySourceID,
		})
		switch {
		case err == nil:
		case errors.Is(err, ErrDeviceRevoked):
			s.rejectRevoked(w)
			return
		case errors.Is(err, ErrQuotaExceeded):
			s.reject(w, http.StatusTooManyRequests, err.Error())
			return
		case errors.Is(err, ErrConflict):
			s.reject(w, http.StatusConflict, err.Error())
			return
		case errors.Is(err, ErrAuthorityUnavailable):
			s.reject(w, http.StatusBadGateway, ErrAuthorityUnavailable.Error())
			return
		default:
			s.reject(w, http.StatusBadGateway, ErrAuthorityUnavailable.Error())
			return
		}
	}
	s.revokeMu.RLock()
	defer s.revokeMu.RUnlock()
	revoked, err = s.store.IsRevoked(r.Context(), request.DeviceID)
	if err != nil {
		s.rejectStorage(w)
		return
	}
	if revoked {
		s.rejectRevoked(w)
		return
	}
	s.writeCredential(w, request, ttl)
}

func (s *Server) writeCredential(w http.ResponseWriter, request credentialRequest, ttl int64) {
	expires := s.now().UTC().Add(time.Duration(ttl) * time.Second).Unix()
	allocationID := request.AllocationID
	if allocationID == "" {
		allocationID = request.SessionID
	}
	// The TURN principal is device:session:allocation so the coturn exporter can
	// map each active allocation back to its Authority ledger entry. Per-device
	// allocation limits are enforced by Authority MaximumAllocationsPerDevice
	// and the relay max_concurrent_sessions_per_device gate; coturn user-quota
	// bounds allocations per allocation principal.
	username := fmt.Sprintf("%d:%s:%s:%s", expires, request.DeviceID, request.SessionID, allocationID)
	mac := hmac.New(sha1.New, []byte(s.cfg.TurnSecret))
	if _, err := mac.Write([]byte(username)); err != nil {
		s.reject(w, http.StatusInternalServerError, "credential generation failed")
		return
	}
	password := base64.StdEncoding.EncodeToString(mac.Sum(nil))
	s.metrics.credentialIssued.Add(1)
	writeJSON(w, http.StatusOK, map[string]any{"username": username, "password": password, "ttl_seconds": ttl, "realm": s.cfg.TurnRealm, "uris": s.cfg.TurnURIs})
}

func (s *Server) revoke(w http.ResponseWriter, r *http.Request) {
	if !authorized(r, s.cfg.AdminToken) {
		s.reject(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	deviceID := r.PathValue("device_id")
	if !validIdentifier(deviceID) {
		s.reject(w, http.StatusBadRequest, "invalid device_id")
		return
	}
	// In production authority mode, the authority is the source of truth for
	// revocation. Propagate the revocation to the authority first so it can
	// close the device's signaling sessions and relay allocations atomically.
	// If the authority is unavailable, fail closed rather than revoking only
	// locally, which would leave signaling sessions and relay admissions open.
	if s.authority != nil {
		if err := s.authority.RevokeDevice(r.Context(), deviceID); err != nil {
			s.reject(w, http.StatusBadGateway, ErrAuthorityUnavailable.Error())
			return
		}
	}
	s.revokeMu.Lock()
	defer s.revokeMu.Unlock()
	if err := s.store.Revoke(r.Context(), deviceID, s.now()); err != nil {
		s.rejectStorage(w)
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "revoked"})
}

func (s *Server) usage(w http.ResponseWriter, r *http.Request) {
	if !authorized(r, s.cfg.UsageToken) {
		s.reject(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	var event UsageEvent
	if err := decodeJSON(w, r, &event); err != nil {
		s.reject(w, http.StatusBadRequest, err.Error())
		return
	}
	if !validIdentifier(event.EventID) || !validIdentifier(event.DeviceID) || !validIdentifier(event.SessionID) {
		s.reject(w, http.StatusBadRequest, "invalid event, device, or session identifier")
		return
	}
	if event.IngressBytes > s.cfg.MaxUsageEventBytes || event.EgressBytes > s.cfg.MaxUsageEventBytes {
		s.reject(w, http.StatusBadRequest, "usage event exceeds byte limit")
		return
	}
	err := s.store.Apply(r.Context(), s.now(), event)
	if errors.Is(err, ErrDeviceRevoked) {
		s.rejectRevoked(w)
		return
	}
	if errors.Is(err, ErrDuplicateEvent) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "duplicate"})
		return
	}
	if errors.Is(err, ErrQuotaExceeded) || errors.Is(err, ErrSessionLimit) {
		s.reject(w, http.StatusTooManyRequests, err.Error())
		return
	}
	if errors.Is(err, ErrStorage) {
		s.rejectStorage(w)
		return
	}
	if err != nil {
		s.reject(w, http.StatusBadRequest, err.Error())
		return
	}
	s.metrics.usageAccepted.Add(1)
	s.metrics.ingressBytes.Add(event.IngressBytes)
	s.metrics.egressBytes.Add(event.EgressBytes)
	writeJSON(w, http.StatusAccepted, map[string]string{"status": "accepted"})
}

func (s *Server) allowCredential(key string) bool {
	now := s.now()
	s.rateMu.Lock()
	defer s.rateMu.Unlock()
	window, exists := s.rates[key]
	if !exists && len(s.rates) >= maxRateEntries {
		for candidate, candidateWindow := range s.rates {
			if now.Sub(candidateWindow.started) >= time.Minute {
				delete(s.rates, candidate)
			}
		}
		if len(s.rates) >= maxRateEntries {
			return false
		}
	}
	if window.started.IsZero() || now.Sub(window.started) >= time.Minute {
		window = rateWindow{started: now}
	}
	if window.count >= s.cfg.CredentialRequestsPerMinute {
		s.rates[key] = window
		return false
	}
	window.count++
	s.rates[key] = window
	return true
}

func (s *Server) reject(w http.ResponseWriter, status int, message string) {
	s.metrics.requestRejected.Add(1)
	writeJSON(w, status, map[string]string{"error": message})
}

func (s *Server) rejectRevoked(w http.ResponseWriter) {
	s.metrics.revokedRejected.Add(1)
	s.reject(w, http.StatusForbidden, ErrDeviceRevoked.Error())
}

func (s *Server) rejectStorage(w http.ResponseWriter) {
	s.reject(w, http.StatusServiceUnavailable, "state storage unavailable")
}

func decodeJSON(w http.ResponseWriter, r *http.Request, destination any) error {
	r.Body = http.MaxBytesReader(w, r.Body, maxRequestBody)
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

func authorized(r *http.Request, expected string) bool {
	authorization := r.Header.Get("Authorization")
	const prefix = "Bearer "
	if !strings.HasPrefix(authorization, prefix) || strings.Count(authorization, " ") != 1 {
		return false
	}
	provided := strings.TrimPrefix(authorization, prefix)
	if provided == "" || len(provided) != len(expected) {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(provided), []byte(expected)) == 1
}

func validIdentifier(value string) bool {
	if len(value) < 1 || len(value) > 128 {
		return false
	}
	for _, char := range value {
		if (char >= 'a' && char <= 'z') || (char >= 'A' && char <= 'Z') || (char >= '0' && char <= '9') || char == '-' || char == '_' || char == '.' {
			continue
		}
		return false
	}
	return true
}

func costMicrocents(bytes, rate uint64) uint64 {
	if bytes == 0 || rate == 0 {
		return 0
	}
	whole, remainder := bytes/gibibyte, bytes%gibibyte
	return whole*rate + remainder*rate/gibibyte
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(value); err != nil {
		slog.Debug("response write failed", "error", err)
	}
}
