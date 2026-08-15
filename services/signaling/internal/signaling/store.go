package signaling

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"errors"
	"fmt"
	"reflect"
	"sync"
	"time"
)

var (
	ErrNotFound       = errors.New("session not found")
	ErrExpired        = errors.New("session expired")
	ErrInvalidated    = errors.New("session creation request was invalidated")
	ErrUnauthorized   = errors.New("unauthorized")
	ErrConflict       = errors.New("message conflicts with session state")
	ErrRateLimited    = errors.New("rate limit exceeded")
	ErrCapacity       = errors.New("session capacity reached")
	ErrCandidateLimit = errors.New("candidate limit reached")
	ErrTooManyWaiters = errors.New("too many concurrent waiters")
)

type rateWindow struct {
	started time.Time
	count   int
}

type session struct {
	requestID      string
	ttlSeconds     int64
	response       SessionResponse
	hostToken      string
	deviceToken    string
	events         []Event
	messages       map[Role]map[string]MessageRequest
	offerSent      bool
	answerSent     bool
	ended          map[Role]bool
	candidateCount map[Role]int
	rates          map[Role]rateWindow
	waiters        map[Role]int
	notify         chan struct{}
	invalidated    bool
}

// CreateSessionRequest carries the fields needed to create a session. In
// local development mode only RequestID and TTL are used. In production
// authority mode the remaining fields are forwarded to the authority service.
type CreateSessionRequest struct {
	RequestID      string
	TTL            time.Duration
	AccountID      string
	HostDeviceID   string
	ClientDeviceID string
	SessionEpoch   uint64
}

type Store struct {
	mu                sync.Mutex
	authorityCreateMu sync.Mutex
	sessions          map[string]*session
	requestSessions   map[string]string
	now               func() time.Time
	maxSessions       int
	messagesPerMinute int
	maxCandidates     int
	maxWaiters        int
	authority         *AuthorityClient
}

type StoreStats struct {
	ActiveSessions  int
	Tombstones      int
	ReservedRecords int
	BlockedWaiters  int
}

func NewStore(cfg Config, authority *AuthorityClient) *Store {
	return &Store{
		sessions:          make(map[string]*session),
		requestSessions:   make(map[string]string),
		now:               time.Now,
		maxSessions:       cfg.MaxActiveSessions,
		messagesPerMinute: cfg.MessagesPerMinute,
		maxCandidates:     cfg.MaxCandidatesPerRole,
		maxWaiters:        cfg.MaxWaitersPerRole,
		authority:         authority,
	}
}

// Create creates a new session or returns an existing one for the same
// request ID. In production authority mode the session identity and role
// tokens are issued by the authority service; the local store only records
// them for event routing. The authority HTTP call is made outside the store
// lock.
func (s *Store) Create(ctx context.Context, request CreateSessionRequest) (SessionResponse, bool, error) {
	if s.authority != nil {
		return s.createAuthority(ctx, request)
	}
	return s.createLocal(request)
}

func (s *Store) createLocal(request CreateSessionRequest) (SessionResponse, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.cleanupLocked(s.now())
	if sessionID, ok := s.requestSessions[request.RequestID]; ok {
		existing := s.sessions[sessionID]
		if existing == nil {
			delete(s.requestSessions, request.RequestID)
		} else if existing.invalidated {
			return SessionResponse{}, false, ErrInvalidated
		} else if existing.ttlSeconds != int64(request.TTL/time.Second) {
			return SessionResponse{}, false, ErrConflict
		} else {
			return existing.response, false, nil
		}
	}
	if len(s.sessions) >= s.maxSessions {
		return SessionResponse{}, false, ErrCapacity
	}
	sessionID, err := randomToken(16)
	if err != nil {
		return SessionResponse{}, false, fmt.Errorf("generate session ID: %w", err)
	}
	hostToken, err := randomToken(32)
	if err != nil {
		return SessionResponse{}, false, fmt.Errorf("generate host token: %w", err)
	}
	deviceToken, err := randomToken(32)
	if err != nil {
		return SessionResponse{}, false, fmt.Errorf("generate device token: %w", err)
	}
	response := SessionResponse{
		SessionID: sessionID, HostToken: hostToken, DeviceToken: deviceToken,
		ExpiresAt: s.now().UTC().Add(request.TTL),
	}
	s.sessions[sessionID] = &session{
		requestID: request.RequestID, ttlSeconds: int64(request.TTL / time.Second), response: response,
		hostToken: hostToken, deviceToken: deviceToken,
		messages:       map[Role]map[string]MessageRequest{RoleHost: {}, RoleDevice: {}},
		ended:          map[Role]bool{RoleHost: false, RoleDevice: false},
		candidateCount: map[Role]int{RoleHost: 0, RoleDevice: 0},
		rates:          map[Role]rateWindow{}, waiters: map[Role]int{}, notify: make(chan struct{}),
	}
	s.requestSessions[request.RequestID] = sessionID
	return response, true, nil
}

// createAuthority delegates session creation to the authority service. The
// HTTP call runs outside the store lock; the returned admission is then
// recorded locally under the lock.
func (s *Store) createAuthority(ctx context.Context, request CreateSessionRequest) (SessionResponse, bool, error) {
	// Serialize authority-backed creates so local capacity is reserved before
	// the durable authority admission is created. The main store lock remains
	// available to message and polling paths while the HTTP call is in flight.
	s.authorityCreateMu.Lock()
	defer s.authorityCreateMu.Unlock()
	s.mu.Lock()
	s.cleanupLocked(s.now())
	sessionID, replay := s.requestSessions[request.RequestID]
	if replay {
		existing := s.sessions[sessionID]
		if existing == nil {
			delete(s.requestSessions, request.RequestID)
			replay = false
		} else if existing.invalidated {
			s.mu.Unlock()
			return SessionResponse{}, false, ErrInvalidated
		}
	}
	if !replay && len(s.sessions) >= s.maxSessions {
		s.mu.Unlock()
		return SessionResponse{}, false, ErrCapacity
	}
	s.mu.Unlock()

	admission, err := s.authority.CreateSession(ctx, authoritySignalingRequest{
		RequestID:      request.RequestID,
		AccountID:      request.AccountID,
		HostDeviceID:   request.HostDeviceID,
		ClientDeviceID: request.ClientDeviceID,
		SessionEpoch:   request.SessionEpoch,
		TTLSeconds:     int64(request.TTL / time.Second),
	})
	if err != nil {
		return SessionResponse{}, false, err
	}
	response := SessionResponse{
		SessionID:   admission.SessionID,
		HostToken:   admission.HostToken,
		DeviceToken: admission.ClientToken,
		ExpiresAt:   admission.ExpiresAt,
	}
	// Role tokens are returned only from the latest authority response. The
	// production store never retains them for local authorization fallback.
	s.mu.Lock()
	defer s.mu.Unlock()
	s.cleanupLocked(s.now())
	if sessionID, ok := s.requestSessions[request.RequestID]; ok {
		if sessionID != admission.SessionID {
			return SessionResponse{}, false, ErrAuthorityUnavailable
		}
		existing := s.sessions[sessionID]
		if existing == nil {
			return SessionResponse{}, false, ErrAuthorityUnavailable
		}
		if existing.invalidated {
			return SessionResponse{}, false, ErrInvalidated
		}
		// Only a replay of this same request/session may refresh the local
		// expiry. The authority remains the lifecycle source of truth, so both
		// extensions and fail-closed shortenings must update the local gate.
		if admission.Created {
			return SessionResponse{}, false, ErrAuthorityUnavailable
		}
		if !admission.ExpiresAt.Equal(existing.response.ExpiresAt) {
			existing.response.ExpiresAt = admission.ExpiresAt
			notifySessionLocked(existing)
		}
		return response, admission.Created, nil
	}
	// The authority can durably replay an admission after this process has
	// lost its in-memory SDP/ICE state. Reconstructing an empty rendezvous for
	// that old session would permit a second offer generation under the same
	// session epoch, so require the owner to issue a fresh request instead.
	if !admission.Created {
		return SessionResponse{}, false, ErrInvalidated
	}
	if existing, ok := s.sessions[admission.SessionID]; ok {
		if existing.requestID != request.RequestID {
			return SessionResponse{}, false, ErrAuthorityUnavailable
		}
		return SessionResponse{}, false, ErrConflict
	}
	s.sessions[admission.SessionID] = &session{
		requestID: request.RequestID, ttlSeconds: int64(request.TTL / time.Second),
		response:       SessionResponse{SessionID: admission.SessionID, ExpiresAt: admission.ExpiresAt},
		messages:       map[Role]map[string]MessageRequest{RoleHost: {}, RoleDevice: {}},
		ended:          map[Role]bool{RoleHost: false, RoleDevice: false},
		candidateCount: map[Role]int{RoleHost: 0, RoleDevice: 0},
		rates:          map[Role]rateWindow{}, waiters: map[Role]int{}, notify: make(chan struct{}),
	}
	s.requestSessions[request.RequestID] = admission.SessionID
	return response, admission.Created, nil
}

// Invalidate revokes a session. In production authority mode the authority
// service is notified first; the local state is then destroyed.
func (s *Store) Invalidate(ctx context.Context, sessionID string) (bool, error) {
	if s.authority != nil {
		if err := s.authority.InvalidateSession(ctx, sessionID); err != nil {
			return false, err
		}
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.cleanupLocked(s.now())
	current := s.sessions[sessionID]
	if current == nil {
		if s.authority != nil {
			return false, nil
		}
		return false, ErrNotFound
	}
	if current.invalidated {
		return false, nil
	}
	current.invalidated = true
	current.hostToken = ""
	current.deviceToken = ""
	current.response.HostToken = ""
	current.response.DeviceToken = ""
	current.events = nil
	current.messages = nil
	current.rates = nil
	notifySessionLocked(current)
	return true, nil
}

// Authorize resolves a role token to a session role. In production authority
// mode it delegates to the authority service. In local mode it checks the
// locally stored token. This method never holds the store lock during the
// authority HTTP call.
func (s *Store) Authorize(ctx context.Context, sessionID, token string) (Role, error) {
	if s.authority != nil {
		authorityRole, err := s.authority.AuthorizeRole(ctx, sessionID, token)
		if err != nil {
			return "", err
		}
		return roleFromAuthority(authorityRole)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	_, role, err := s.authorizeLocked(sessionID, token)
	return role, err
}

// AddMessageAuthorized adds a message to a session after the caller has
// already verified the role. The session existence, invalidation, and expiry
// are re-checked under the lock to avoid TOCTOU.
func (s *Store) AddMessageAuthorized(sessionID string, role Role, request MessageRequest) (Event, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	current, err := s.sessionForRoleLocked(sessionID, role)
	if err != nil {
		return Event{}, false, err
	}
	if existing, ok := current.messages[role][request.MessageID]; ok {
		if !reflect.DeepEqual(existing, request) {
			return Event{}, false, ErrConflict
		}
		for _, event := range current.events {
			if event.SenderRole == role && event.MessageID == request.MessageID {
				return event, false, nil
			}
		}
	}
	if !allowRate(current.rates, role, s.now(), s.messagesPerMinute) {
		return Event{}, false, ErrRateLimited
	}
	if err := s.validateStateLocked(current, role, request); err != nil {
		return Event{}, false, err
	}
	event := Event{
		Sequence: uint64(len(current.events) + 1), MessageID: request.MessageID,
		Type: request.Type, SenderRole: role, SDP: request.SDP,
		Candidate: cloneCandidate(request.Candidate), CreatedAt: s.now().UTC(),
	}
	current.events = append(current.events, event)
	current.messages[role][request.MessageID] = cloneRequest(request)
	notifySessionLocked(current)
	return event, true, nil
}

// PollAuthorized polls for events after the caller has already verified the
// role. The session existence, invalidation, and expiry are re-checked under
// the lock to avoid TOCTOU.
func (s *Store) PollAuthorized(ctx context.Context, sessionID string, role Role, after uint64) ([]Event, uint64, error) {
	waiting := false
	defer func() {
		if waiting {
			s.releaseWaiter(sessionID, role)
		}
	}()
	for {
		s.mu.Lock()
		current, err := s.sessionForRoleLocked(sessionID, role)
		if err != nil {
			s.mu.Unlock()
			return nil, after, err
		}
		events, next := eventsAfter(current.events, role, after)
		if next > after {
			s.mu.Unlock()
			return events, next, nil
		}
		if !waiting {
			if current.waiters[role] >= s.maxWaiters {
				s.mu.Unlock()
				return nil, after, ErrTooManyWaiters
			}
			current.waiters[role]++
			waiting = true
		}
		notify := current.notify
		expiresAt := current.response.ExpiresAt
		s.mu.Unlock()
		expiryTimer := time.NewTimer(time.Until(expiresAt))
		select {
		case <-ctx.Done():
			if !expiryTimer.Stop() {
				<-expiryTimer.C
			}
			if errors.Is(ctx.Err(), context.DeadlineExceeded) {
				return []Event{}, after, nil
			}
			return nil, after, ctx.Err()
		case <-notify:
			if !expiryTimer.Stop() {
				<-expiryTimer.C
			}
		case <-expiryTimer.C:
		}
	}
}

func (s *Store) sessionForRoleLocked(sessionID string, role Role) (*session, error) {
	if role != RoleHost && role != RoleDevice {
		return nil, ErrUnauthorized
	}
	current := s.sessions[sessionID]
	if current == nil || current.invalidated {
		return nil, ErrNotFound
	}
	if !s.now().Before(current.response.ExpiresAt) {
		return nil, ErrExpired
	}
	return current, nil
}

func (s *Store) validateStateLocked(current *session, role Role, request MessageRequest) error {
	switch request.Type {
	case MessageOffer:
		if role != RoleHost || current.offerSent {
			return ErrConflict
		}
		current.offerSent = true
	case MessageAnswer:
		if role != RoleDevice || !current.offerSent || current.answerSent {
			return ErrConflict
		}
		current.answerSent = true
	case MessageICECandidate:
		if current.ended[role] {
			return ErrConflict
		}
		if current.candidateCount[role] >= s.maxCandidates {
			return ErrCandidateLimit
		}
		current.candidateCount[role]++
	case MessageEndOfCandidates:
		if current.ended[role] {
			return ErrConflict
		}
		current.ended[role] = true
	default:
		return ErrConflict
	}
	return nil
}

func (s *Store) releaseWaiter(sessionID string, role Role) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if current := s.sessions[sessionID]; current != nil && current.waiters[role] > 0 {
		current.waiters[role]--
	}
}

// notifySessionLocked wakes every current waiter and installs a fresh channel
// for later messages or lifecycle changes. The caller must hold s.mu.
func notifySessionLocked(current *session) {
	close(current.notify)
	current.notify = make(chan struct{})
}

func (s *Store) ActiveCount() int {
	return s.Stats().ActiveSessions
}

func (s *Store) Stats() StoreStats {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.cleanupLocked(s.now())
	stats := StoreStats{ReservedRecords: len(s.sessions)}
	for _, current := range s.sessions {
		if current.invalidated {
			stats.Tombstones++
		} else {
			stats.ActiveSessions++
		}
		for _, waiters := range current.waiters {
			stats.BlockedWaiters += waiters
		}
	}
	return stats
}

func (s *Store) Cleanup() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.cleanupLocked(s.now())
}

func (s *Store) cleanupLocked(now time.Time) int {
	removed := 0
	for sessionID, current := range s.sessions {
		if !now.Before(current.response.ExpiresAt) {
			delete(s.sessions, sessionID)
			delete(s.requestSessions, current.requestID)
			close(current.notify)
			removed++
		}
	}
	return removed
}

func (s *Store) authorizeLocked(sessionID, token string) (*session, Role, error) {
	current := s.sessions[sessionID]
	if current == nil || current.invalidated {
		return nil, "", ErrNotFound
	}
	var role Role
	if secureEqual(token, current.hostToken) {
		role = RoleHost
	} else if secureEqual(token, current.deviceToken) {
		role = RoleDevice
	} else {
		return nil, "", ErrUnauthorized
	}
	if !s.now().Before(current.response.ExpiresAt) {
		return nil, "", ErrExpired
	}
	return current, role, nil
}

func eventsAfter(events []Event, receiver Role, after uint64) ([]Event, uint64) {
	result := make([]Event, 0)
	next := after
	for _, event := range events {
		if event.Sequence <= after {
			continue
		}
		next = event.Sequence
		if event.SenderRole != receiver {
			cloned := event
			cloned.Candidate = cloneCandidate(event.Candidate)
			result = append(result, cloned)
		}
	}
	return result, next
}

func allowRate(windows map[Role]rateWindow, key Role, now time.Time, limit int) bool {
	window := windows[key]
	if window.started.IsZero() || now.Sub(window.started) >= time.Minute {
		window = rateWindow{started: now}
	}
	if window.count >= limit {
		windows[key] = window
		return false
	}
	window.count++
	windows[key] = window
	return true
}

func randomToken(bytes int) (string, error) {
	buffer := make([]byte, bytes)
	if _, err := rand.Read(buffer); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(buffer), nil
}

func secureEqual(provided, expected string) bool {
	if len(provided) == 0 || len(provided) != len(expected) {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(provided), []byte(expected)) == 1
}

func cloneCandidate(candidate *ICECandidate) *ICECandidate {
	if candidate == nil {
		return nil
	}
	cloned := *candidate
	if candidate.SDPMLineIndex != nil {
		index := *candidate.SDPMLineIndex
		cloned.SDPMLineIndex = &index
	}
	return &cloned
}

func cloneRequest(request MessageRequest) MessageRequest {
	request.Candidate = cloneCandidate(request.Candidate)
	return request
}
