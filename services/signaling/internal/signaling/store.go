package signaling

import (
	"context"
	"errors"
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
	ErrStorage        = errors.New("signaling storage unavailable")
)

type Store interface {
	Create(context.Context, CreateSessionRequest) (SessionResponse, bool, error)
	Invalidate(context.Context, string) (bool, error)
	Authorize(context.Context, string, string) (Role, error)
	AddMessageAuthorized(context.Context, string, Role, MessageRequest) (Event, bool, error)
	PollAuthorized(context.Context, string, Role, uint64, bool) ([]Event, uint64, error)
	Stats() StoreStats
	Cleanup() int
	Ready(context.Context) error
	Close()
}

type rateWindow struct {
	started time.Time
	count   int
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
	SessionProfile *SessionProfileRequest
}

type StoreStats struct {
	ActiveSessions  int
	Tombstones      int
	ReservedRecords int
	BlockedWaiters  int
}
