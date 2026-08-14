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
	ErrNotFound           = errors.New("session not found")
	ErrExpired            = errors.New("session expired")
	ErrInvalidated        = errors.New("session creation request was invalidated")
	ErrUnauthorized       = errors.New("unauthorized")
	ErrConflict           = errors.New("message conflicts with session state")
	ErrRateLimited        = errors.New("rate limit exceeded")
	ErrCapacity           = errors.New("session capacity reached")
	ErrCandidateLimit     = errors.New("candidate limit reached")
	ErrTooManyWaiters     = errors.New("too many concurrent waiters")
	ErrRefreshUnsupported = errors.New("session does not support refresh")
	ErrDeviceRevoked      = errors.New("device revoked")
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
	deviceID       string
	sessionEpoch   uint64
	authority      PublicIdentity
	peerIdentity   PublicIdentity
	superseded     bool
	revoked        bool
	successorID    string
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
	stateFile         string
	revocationState   revocationState
	deviceEpochs      map[string]uint64
}

type StoreStats struct {
	ActiveSessions  int
	Tombstones      int
	ReservedRecords int
	BlockedWaiters  int
}

func NewStore(cfg Config) (*Store, error) {
	revocations, err := loadRevocationState(cfg.StateFile)
	if err != nil {
		return nil, err
	}
	return &Store{
		sessions:          make(map[string]*session),
		requestSessions:   make(map[string]string),
		now:               time.Now,
		maxSessions:       cfg.MaxActiveSessions,
		messagesPerMinute: cfg.MessagesPerMinute,
		maxCandidates:     cfg.MaxCandidatesPerRole,
		maxWaiters:        cfg.MaxWaitersPerRole,
		stateFile:         cfg.StateFile, revocationState: revocations,
		deviceEpochs: make(map[string]uint64),
	}, nil
}

func (s *Store) Create(requestID string, ttl time.Duration) (SessionResponse, bool, error) {
	return s.CreateBound(requestID, ttl, "", 0)
}

func (s *Store) CreateBound(requestID string, ttl time.Duration, deviceID string, sessionEpoch uint64) (SessionResponse, bool, error) {
	return s.CreateBoundIdentity(requestID, ttl, deviceID, sessionEpoch, PublicIdentity{}, PublicIdentity{})
}

func (s *Store) CreateBoundIdentity(requestID string, ttl time.Duration, deviceID string, sessionEpoch uint64, authority, peer PublicIdentity) (SessionResponse, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.cleanupLocked(s.now())
	if sessionID, ok := s.requestSessions[requestID]; ok {
		existing := s.sessions[sessionID]
		if existing == nil {
			delete(s.requestSessions, requestID)
		} else if existing.invalidated {
			return SessionResponse{}, false, ErrInvalidated
		} else if existing.ttlSeconds != int64(ttl/time.Second) || existing.deviceID != deviceID || existing.sessionEpoch != sessionEpoch ||
			!sameIdentity(existing.authority, authority) || !sameIdentity(existing.peerIdentity, peer) {
			return SessionResponse{}, false, ErrConflict
		} else {
			if deviceID != "" && s.isRevokedLocked(deviceID) {
				return SessionResponse{}, false, ErrDeviceRevoked
			}
			return existing.response, false, nil
		}
	}
	if deviceID != "" {
		if s.isRevokedLocked(deviceID) {
			return SessionResponse{}, false, ErrDeviceRevoked
		}
		if sessionEpoch == 0 || sessionEpoch <= s.deviceEpochs[deviceID] {
			return SessionResponse{}, false, ErrConflict
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
		ExpiresAt: s.now().UTC().Add(ttl), DeviceID: deviceID, SessionEpoch: sessionEpoch,
	}
	s.sessions[sessionID] = &session{
		requestID: requestID, ttlSeconds: int64(ttl / time.Second), response: response,
		hostToken: hostToken, deviceToken: deviceToken,
		messages:       map[Role]map[string]MessageRequest{RoleHost: {}, RoleDevice: {}},
		ended:          map[Role]bool{RoleHost: false, RoleDevice: false},
		candidateCount: map[Role]int{RoleHost: 0, RoleDevice: 0},
		rates:          map[Role]rateWindow{}, waiters: map[Role]int{}, notify: make(chan struct{}),
		deviceID: deviceID, sessionEpoch: sessionEpoch, authority: authority, peerIdentity: peer,
	}
	s.requestSessions[requestID] = sessionID
	if deviceID != "" {
		s.deviceEpochs[deviceID] = sessionEpoch
	}
	return response, true, nil
}

type refreshResult struct {
	Response RefreshResponse
	DeviceID string
}

func (s *Store) Refresh(sessionID, token string) (refreshResult, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.cleanupLocked(s.now())
	current, role, err := s.refreshAuthorizeLocked(sessionID, token)
	if err != nil {
		return refreshResult{}, err
	}
	if current.deviceID == "" || current.sessionEpoch == 0 {
		return refreshResult{}, ErrRefreshUnsupported
	}
	if s.isRevokedLocked(current.deviceID) || current.revoked {
		return refreshResult{}, ErrNotFound
	}
	if current.successorID == "" {
		if len(s.sessions) >= s.maxSessions {
			return refreshResult{}, ErrCapacity
		}
		successor, err := s.createSuccessorLocked(current)
		if err != nil {
			return refreshResult{}, err
		}
		current.successorID = successor.response.SessionID
		current.superseded = true
		current.events = nil
		current.messages = nil
		current.rates = nil
		close(current.notify)
		current.notify = make(chan struct{})
	}
	successor := s.sessions[current.successorID]
	if successor == nil || successor.revoked || s.isRevokedLocked(current.deviceID) {
		return refreshResult{}, ErrNotFound
	}
	roleToken := successor.deviceToken
	if role == RoleHost {
		roleToken = successor.hostToken
	}
	return refreshResult{Response: RefreshResponse{
		SessionID: successor.response.SessionID, RoleToken: roleToken,
		SessionEpoch: successor.sessionEpoch, ExpiresAt: successor.response.ExpiresAt,
	}, DeviceID: successor.deviceID}, nil
}

func (s *Store) createSuccessorLocked(current *session) (*session, error) {
	if current.sessionEpoch >= uint64(^uint64(0)>>1) {
		return nil, ErrConflict
	}
	sessionID, err := randomToken(16)
	if err != nil {
		return nil, fmt.Errorf("generate session ID: %w", err)
	}
	hostToken, err := randomToken(32)
	if err != nil {
		return nil, fmt.Errorf("generate host token: %w", err)
	}
	deviceToken, err := randomToken(32)
	if err != nil {
		return nil, fmt.Errorf("generate device token: %w", err)
	}
	epoch := current.sessionEpoch + 1
	response := SessionResponse{SessionID: sessionID, HostToken: hostToken, DeviceToken: deviceToken,
		ExpiresAt: s.now().UTC().Add(time.Duration(current.ttlSeconds) * time.Second), DeviceID: current.deviceID, SessionEpoch: epoch}
	successor := &session{requestID: "refresh:" + current.response.SessionID, ttlSeconds: current.ttlSeconds,
		response: response, hostToken: hostToken, deviceToken: deviceToken, deviceID: current.deviceID, sessionEpoch: epoch,
		authority: current.authority, peerIdentity: current.peerIdentity,
		messages: map[Role]map[string]MessageRequest{RoleHost: {}, RoleDevice: {}}, ended: map[Role]bool{RoleHost: false, RoleDevice: false},
		candidateCount: map[Role]int{RoleHost: 0, RoleDevice: 0}, rates: map[Role]rateWindow{}, waiters: map[Role]int{}, notify: make(chan struct{})}
	s.sessions[sessionID] = successor
	s.deviceEpochs[current.deviceID] = epoch
	return successor, nil
}

func (s *Store) Invalidate(sessionID string) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.cleanupLocked(s.now())
	current := s.sessions[sessionID]
	if current == nil {
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
	close(current.notify)
	current.notify = make(chan struct{})
	return true, nil
}

func (s *Store) RevocationBinding(sessionID, hostToken, deviceID string) (PublicIdentity, PublicIdentity, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.cleanupLocked(s.now())
	current := s.sessions[sessionID]
	if current == nil || current.deviceID == "" || current.deviceID != deviceID || !secureEqual(hostToken, current.hostToken) {
		return PublicIdentity{}, PublicIdentity{}, ErrUnauthorized
	}
	if current.authority.DeviceID == "" || current.peerIdentity.DeviceID == "" {
		return PublicIdentity{}, PublicIdentity{}, ErrUnauthorized
	}
	return current.authority, current.peerIdentity, nil
}

func (s *Store) RevokeDevice(sessionID, hostToken, deviceID string, tombstone SignedDeviceRevocation, authorityDigest, digest, nonceDigest string) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.cleanupLocked(s.now())
	current := s.sessions[sessionID]
	if current == nil || current.deviceID != deviceID || !secureEqual(hostToken, current.hostToken) {
		return false, ErrUnauthorized
	}
	if existing, ok := s.revocationState.revocations[deviceID]; ok {
		if existing.Sequence != tombstone.Sequence || existing.Digest != digest {
			return false, ErrConflict
		}
		return !existing.RelayComplete, nil
	}
	authorityNonceDigest := authorityDigest + ":" + nonceDigest
	if tombstone.Sequence <= s.revocationState.maximumSequences[authorityDigest] || s.revocationState.usedNonceDigests[authorityNonceDigest] {
		return false, ErrConflict
	}
	next := cloneRevocationState(s.revocationState)
	next.revocations[deviceID] = durableRevocation{AuthorityDigest: authorityDigest, Sequence: tombstone.Sequence, Digest: digest, NonceDigest: nonceDigest}
	next.maximumSequences[authorityDigest] = tombstone.Sequence
	next.usedNonceDigests[authorityNonceDigest] = true
	if err := persistRevocationState(s.stateFile, next); err != nil {
		return false, err
	}
	s.revocationState = next
	for _, candidate := range s.sessions {
		if candidate.deviceID != deviceID || candidate.revoked {
			continue
		}
		candidate.revoked = true
		candidate.events = nil
		candidate.messages = nil
		candidate.rates = nil
		close(candidate.notify)
		candidate.notify = make(chan struct{})
	}
	return true, nil
}

func (s *Store) MarkRelayRevoked(deviceID string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	record, ok := s.revocationState.revocations[deviceID]
	if !ok || record.RelayComplete {
		return nil
	}
	next := cloneRevocationState(s.revocationState)
	record.RelayComplete = true
	next.revocations[deviceID] = record
	if err := persistRevocationState(s.stateFile, next); err != nil {
		return err
	}
	s.revocationState = next
	return nil
}

func (s *Store) PendingRelayRevocations() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	var result []string
	for deviceID, record := range s.revocationState.revocations {
		if !record.RelayComplete {
			result = append(result, deviceID)
		}
	}
	sortStrings(result)
	return result
}

func (s *Store) RefreshStillAllowed(sessionID, deviceID string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	current := s.sessions[sessionID]
	return current != nil && current.deviceID == deviceID && !current.revoked && !s.isRevokedLocked(deviceID)
}

func (s *Store) SessionStillAllowed(sessionID, deviceID string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	current := s.sessions[sessionID]
	return current != nil && current.deviceID == deviceID && !current.invalidated && !current.superseded &&
		!current.revoked && (deviceID == "" || !s.isRevokedLocked(deviceID))
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
	if current == nil || current.invalidated || current.superseded || current.revoked || (current.deviceID != "" && s.isRevokedLocked(current.deviceID)) {
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

func (s *Store) isRevokedLocked(deviceID string) bool {
	_, revoked := s.revocationState.revocations[deviceID]
	return revoked
}

func cloneRevocationState(source revocationState) revocationState {
	copy := revocationState{revocations: make(map[string]durableRevocation, len(source.revocations)),
		maximumSequences: make(map[string]uint64, len(source.maximumSequences)), usedNonceDigests: make(map[string]bool, len(source.usedNonceDigests))}
	for key, value := range source.revocations {
		copy.revocations[key] = value
	}
	for key, value := range source.maximumSequences {
		copy.maximumSequences[key] = value
	}
	for key, value := range source.usedNonceDigests {
		copy.usedNonceDigests[key] = value
	}
	return copy
}

func (s *Store) refreshAuthorizeLocked(sessionID, token string) (*session, Role, error) {
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
