package authority

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"math"
	"net/http"
	"strings"
	"time"
)

const maximumRequestBytes = 256 * 1024

type Server struct {
	cfg   Config
	store Store
	now   func() time.Time
}

func NewServer(cfg Config, store Store) (*Server, error) {
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	if store == nil {
		return nil, errors.New("authority store is required")
	}
	return &Server{cfg: cfg, store: store, now: time.Now}, nil
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
	mux.HandleFunc("GET /readyz", s.ready)
	mux.HandleFunc("PUT /v1/accounts/{account_id}", s.account)
	mux.HandleFunc("POST /v1/accounts/{account_id}/suspend", s.suspendAccount)
	mux.HandleFunc("PUT /v1/accounts/{account_id}/devices/{device_id}", s.device)
	mux.HandleFunc("POST /v1/devices/{device_id}/revoke", s.revokeDevice)
	mux.HandleFunc("POST /v1/relay/devices/{device_id}/revoke", s.revokeDeviceByRelay)
	mux.HandleFunc("POST /v1/signaling/sessions", s.createSignaling)
	mux.HandleFunc("DELETE /v1/signaling/sessions/{session_id}", s.invalidateSignaling)
	mux.HandleFunc("POST /v1/signaling/sessions/{session_id}/authorize", s.authorizeSignaling)
	mux.HandleFunc("POST /v1/relay/admissions", s.admitRelay)
	mux.HandleFunc("POST /v1/coturn/usage", s.coturnUsage)
	mux.HandleFunc("POST /v1/coturn/reconcile", s.reconcile)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Referrer-Policy", "no-referrer")
		mux.ServeHTTP(w, r)
	})
}

func (s *Server) ready(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := contextWithTimeout(r, 2*time.Second)
	defer cancel()
	if err := s.store.Ready(ctx); err != nil {
		s.reject(w, http.StatusServiceUnavailable, "authority storage unavailable")
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (s *Server) account(w http.ResponseWriter, r *http.Request) {
	if !s.admin(w, r) {
		return
	}
	id := r.PathValue("account_id")
	if !validIdentifier(id) {
		s.reject(w, 400, "invalid account_id")
		return
	}
	if err := s.store.EnsureAccount(r.Context(), id); err != nil {
		s.storeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (s *Server) suspendAccount(w http.ResponseWriter, r *http.Request) {
	if !s.admin(w, r) {
		return
	}
	id := r.PathValue("account_id")
	if !validIdentifier(id) {
		s.reject(w, 400, "invalid account_id")
		return
	}
	if err := s.store.SuspendAccount(r.Context(), id, s.now().UTC()); err != nil {
		s.storeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (s *Server) device(w http.ResponseWriter, r *http.Request) {
	if !s.admin(w, r) {
		return
	}
	accountID, deviceID := r.PathValue("account_id"), r.PathValue("device_id")
	if !validIdentifier(accountID) || !validIdentifier(deviceID) {
		s.reject(w, 400, "invalid account_id or device_id")
		return
	}
	if err := s.store.RegisterDevice(r.Context(), accountID, deviceID); err != nil {
		s.storeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

type revokeRequest struct {
	Epoch uint64 `json:"epoch"`
}

func (s *Server) revokeDevice(w http.ResponseWriter, r *http.Request) {
	if !s.admin(w, r) {
		return
	}
	deviceID := r.PathValue("device_id")
	var request revokeRequest
	if !validIdentifier(deviceID) || s.decode(w, r, &request) != nil || request.Epoch == 0 || request.Epoch > math.MaxInt64 {
		s.reject(w, 400, "invalid device revocation")
		return
	}
	if err := s.store.RevokeDevice(r.Context(), deviceID, request.Epoch, s.now().UTC()); err != nil {
		s.storeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// revokeDeviceByRelay allows the relay service to revoke a device using its
// relay bearer token. The authority owns the revocation epoch, so the relay
// does not supply one: this endpoint uses a high-watermark epoch to make the
// revocation durable without trusting relay-provided epoch state.
// Revoking through this endpoint also closes the device's signaling sessions
// and relay allocations in the authority ledger, so signaling and relay
// admission fail closed for the device.
func (s *Server) revokeDeviceByRelay(w http.ResponseWriter, r *http.Request) {
	if !authorized(r, s.cfg.RelayToken) {
		s.reject(w, 401, "unauthorized")
		return
	}
	deviceID := r.PathValue("device_id")
	if !validIdentifier(deviceID) {
		s.reject(w, 400, "invalid device_id")
		return
	}
	if err := s.store.RevokeDevice(r.Context(), deviceID, math.MaxInt64, s.now().UTC()); err != nil {
		s.storeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (s *Server) createSignaling(w http.ResponseWriter, r *http.Request) {
	if !authorized(r, s.cfg.SignalingToken) {
		s.reject(w, 401, "unauthorized")
		return
	}
	var request SignalingRequest
	if err := s.decode(w, r, &request); err != nil {
		s.reject(w, 400, err.Error())
		return
	}
	if !validIdentifier(request.RequestID) || !validIdentifier(request.AccountID) || !validIdentifier(request.HostDeviceID) || !validIdentifier(request.ClientDeviceID) || request.HostDeviceID == request.ClientDeviceID || request.SessionEpoch == 0 || request.SessionEpoch > math.MaxInt64 || request.TTLSeconds <= 0 || request.TTLSeconds > s.cfg.MaximumSessionTTLSeconds {
		s.reject(w, 400, "invalid signaling admission")
		return
	}
	result, err := s.store.CreateSignaling(r.Context(), request, s.now().UTC())
	if err != nil {
		s.storeError(w, err)
		return
	}
	status := http.StatusOK
	if result.Created {
		status = http.StatusCreated
	}
	writeJSON(w, status, result)
}

func (s *Server) invalidateSignaling(w http.ResponseWriter, r *http.Request) {
	if !authorized(r, s.cfg.SignalingToken) && !authorized(r, s.cfg.AdminToken) {
		s.reject(w, 401, "unauthorized")
		return
	}
	sessionID := r.PathValue("session_id")
	if !validIdentifier(sessionID) {
		s.reject(w, 400, "invalid session_id")
		return
	}
	if err := s.store.InvalidateSignaling(r.Context(), sessionID, s.now().UTC()); err != nil {
		s.storeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (s *Server) authorizeSignaling(w http.ResponseWriter, r *http.Request) {
	if !authorized(r, s.cfg.SignalingToken) {
		s.reject(w, 401, "unauthorized")
		return
	}
	sessionID := r.PathValue("session_id")
	if !validIdentifier(sessionID) {
		s.reject(w, 400, "invalid session_id")
		return
	}
	var request struct {
		RoleToken string `json:"role_token"`
	}
	if err := s.decode(w, r, &request); err != nil || request.RoleToken == "" {
		s.reject(w, 400, "invalid role token")
		return
	}
	role, err := s.store.AuthorizeSignaling(r.Context(), sessionID, request.RoleToken, s.now().UTC())
	if err != nil {
		s.storeError(w, err)
		return
	}
	writeJSON(w, 200, map[string]string{"role": role})
}

func (s *Server) admitRelay(w http.ResponseWriter, r *http.Request) {
	if !authorized(r, s.cfg.RelayToken) {
		s.reject(w, 401, "unauthorized")
		return
	}
	var request RelayAdmissionRequest
	if err := s.decode(w, r, &request); err != nil {
		s.reject(w, 400, err.Error())
		return
	}
	if !validIdentifier(request.DeviceID) || !validIdentifier(request.SessionID) || !validIdentifier(request.AllocationID) || !validIdentifier(request.SourceID) {
		s.reject(w, 400, "invalid relay admission")
		return
	}
	if err := s.store.AdmitRelay(r.Context(), request, s.now().UTC()); err != nil {
		s.storeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (s *Server) coturnUsage(w http.ResponseWriter, r *http.Request) {
	if !authorized(r, s.cfg.CoturnToken) {
		s.reject(w, 401, "unauthorized")
		return
	}
	var usage CoturnUsage
	if err := s.decode(w, r, &usage); err != nil {
		s.reject(w, 400, err.Error())
		return
	}
	if err := validateUsage(usage, s.now(), true); err != nil {
		s.reject(w, 400, err.Error())
		return
	}
	duplicate, err := s.store.ApplyCoturnUsage(r.Context(), usage)
	if err != nil {
		s.storeError(w, err)
		return
	}
	status := "accepted"
	code := http.StatusAccepted
	if duplicate {
		status = "duplicate"
		code = http.StatusOK
	}
	writeJSON(w, code, map[string]string{"status": status})
}

func (s *Server) reconcile(w http.ResponseWriter, r *http.Request) {
	if !authorized(r, s.cfg.CoturnToken) {
		s.reject(w, 401, "unauthorized")
		return
	}
	var request ReconcileRequest
	if err := s.decode(w, r, &request); err != nil {
		s.reject(w, 400, err.Error())
		return
	}
	if !validIdentifier(request.SourceID) || request.ObservedAt.IsZero() || request.ObservedAt.After(s.now()) || len(request.Allocations) > 10000 {
		s.reject(w, 400, "invalid reconciliation snapshot")
		return
	}
	for _, usage := range request.Allocations {
		usage.SourceID = request.SourceID
		usage.ObservedAt = request.ObservedAt
		if err := validateUsage(usage, s.now(), false); err != nil {
			s.reject(w, 400, err.Error())
			return
		}
	}
	result, err := s.store.Reconcile(r.Context(), request, s.cfg.ReconciliationGrace())
	if err != nil {
		s.storeError(w, err)
		return
	}
	writeJSON(w, 200, result)
}

func validateUsage(value CoturnUsage, now time.Time, requireEventID bool) error {
	if !validIdentifier(value.SourceID) || (requireEventID && !validIdentifier(value.EventID)) || (!requireEventID && value.EventID != "" && !validIdentifier(value.EventID)) || !validIdentifier(value.AllocationID) || !validIdentifier(value.DeviceID) || !validIdentifier(value.SessionID) || value.Sequence == 0 || value.Sequence > math.MaxInt64 || value.IngressBytes > math.MaxInt64 || value.EgressBytes > math.MaxInt64 || value.ObservedAt.IsZero() || value.ObservedAt.After(now.Add(5*time.Minute)) {
		return errors.New("invalid coturn usage")
	}
	return nil
}

func (s *Server) admin(w http.ResponseWriter, r *http.Request) bool {
	if !authorized(r, s.cfg.AdminToken) {
		s.reject(w, 401, "unauthorized")
		return false
	}
	return true
}
func (s *Server) decode(w http.ResponseWriter, r *http.Request, destination any) error {
	if strings.TrimSpace(strings.SplitN(r.Header.Get("Content-Type"), ";", 2)[0]) != "application/json" {
		return errors.New("Content-Type must be application/json")
	}
	r.Body = http.MaxBytesReader(w, r.Body, maximumRequestBytes)
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
func (s *Server) storeError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, ErrNotFound):
		s.reject(w, 404, "not found")
	case errors.Is(err, ErrRevoked):
		s.reject(w, 403, ErrRevoked.Error())
	case errors.Is(err, ErrConflict), errors.Is(err, ErrStaleUsage):
		s.reject(w, 409, err.Error())
	case errors.Is(err, ErrQuotaExceeded):
		s.reject(w, 429, err.Error())
	default:
		s.reject(w, 503, "authority storage unavailable")
	}
}
func (s *Server) reject(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}
func authorized(r *http.Request, expected string) bool {
	value := r.Header.Get("Authorization")
	if !strings.HasPrefix(value, "Bearer ") || strings.Count(value, " ") != 1 {
		return false
	}
	provided := strings.TrimPrefix(value, "Bearer ")
	return len(provided) == len(expected) && subtle.ConstantTimeCompare([]byte(provided), []byte(expected)) == 1
}
func validIdentifier(value string) bool {
	if len(value) < 1 || len(value) > 128 {
		return false
	}
	for _, char := range value {
		if (char >= 'a' && char <= 'z') || (char >= 'A' && char <= 'Z') || (char >= '0' && char <= '9') || strings.ContainsRune("-_.", char) {
			continue
		}
		return false
	}
	return true
}
func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(value); err != nil {
		slog.Warn("authority response write failed")
	}
}
