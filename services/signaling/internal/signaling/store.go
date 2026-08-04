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
}

type Store struct {
	mu                sync.Mutex
	sessions          map[string]*session
	requestSessions   map[string]string
	now               func() time.Time
	maxSessions       int
	messagesPerMinute int
	maxCandidates     int
	maxWaiters        int
}

func NewStore(cfg Config) *Store {
	return &Store{
		sessions:          make(map[string]*session),
		requestSessions:   make(map[string]string),
		now:               time.Now,
		maxSessions:       cfg.MaxActiveSessions,
		messagesPerMinute: cfg.MessagesPerMinute,
		maxCandidates:     cfg.MaxCandidatesPerRole,
		maxWaiters:        cfg.MaxWaitersPerRole,
	}
}

func (s *Store) Create(requestID string, ttl time.Duration) (SessionResponse, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.cleanupLocked(s.now())
	if sessionID, ok := s.requestSessions[requestID]; ok {
		existing := s.sessions[sessionID]
		if existing == nil {
			delete(s.requestSessions, requestID)
		} else if existing.ttlSeconds != int64(ttl/time.Second) {
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
		ExpiresAt: s.now().UTC().Add(ttl),
	}
	s.sessions[sessionID] = &session{
		requestID: requestID, ttlSeconds: int64(ttl / time.Second), response: response,
		hostToken: hostToken, deviceToken: deviceToken,
		messages:       map[Role]map[string]MessageRequest{RoleHost: {}, RoleDevice: {}},
		ended:          map[Role]bool{RoleHost: false, RoleDevice: false},
		candidateCount: map[Role]int{RoleHost: 0, RoleDevice: 0},
		rates:          map[Role]rateWindow{}, waiters: map[Role]int{}, notify: make(chan struct{}),
	}
	s.requestSessions[requestID] = sessionID
	return response, true, nil
}

func (s *Store) AddMessage(sessionID, token string, request MessageRequest) (Event, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	current, role, err := s.authorizeLocked(sessionID, token)
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
	close(current.notify)
	current.notify = make(chan struct{})
	return event, true, nil
}

func (s *Store) Authorize(sessionID, token string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	_, _, err := s.authorizeLocked(sessionID, token)
	return err
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

func (s *Store) Poll(ctx context.Context, sessionID, token string, after uint64) ([]Event, uint64, error) {
	waiting := false
	var role Role
	defer func() {
		if waiting {
			s.releaseWaiter(sessionID, role)
		}
	}()
	for {
		s.mu.Lock()
		current, authorizedRole, err := s.authorizeLocked(sessionID, token)
		if err != nil {
			s.mu.Unlock()
			return nil, after, err
		}
		role = authorizedRole
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

func (s *Store) releaseWaiter(sessionID string, role Role) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if current := s.sessions[sessionID]; current != nil && current.waiters[role] > 0 {
		current.waiters[role]--
	}
}

func (s *Store) ActiveCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.cleanupLocked(s.now())
	return len(s.sessions)
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
	if current == nil {
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
