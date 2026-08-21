package authority

import (
	"errors"
	"time"
)

var (
	ErrConflict      = errors.New("conflict")
	ErrNotFound      = errors.New("not found")
	ErrRevoked       = errors.New("device or account revoked")
	ErrQuotaExceeded = errors.New("relay quota exceeded")
	ErrStaleUsage    = errors.New("stale coturn usage")
	ErrStorage       = errors.New("authority storage unavailable")
)

type SignalingRequest struct {
	RequestID      string `json:"request_id"`
	AccountID      string `json:"account_id"`
	HostDeviceID   string `json:"host_device_id"`
	ClientDeviceID string `json:"client_device_id"`
	SessionEpoch   uint64 `json:"session_epoch"`
	TTLSeconds     int64  `json:"ttl_seconds"`
}

type SignalingAdmission struct {
	SessionID   string    `json:"session_id"`
	HostToken   string    `json:"host_token"`
	ClientToken string    `json:"client_token"`
	ExpiresAt   time.Time `json:"expires_at"`
	Created     bool      `json:"created"`
}

type RelayAdmissionRequest struct {
	DeviceID     string `json:"device_id"`
	SessionID    string `json:"session_id"`
	AllocationID string `json:"allocation_id"`
	SourceID     string `json:"source_id"`
}

type CoturnUsage struct {
	SourceID     string    `json:"source_id"`
	EventID      string    `json:"event_id"`
	AllocationID string    `json:"allocation_id"`
	DeviceID     string    `json:"device_id"`
	SessionID    string    `json:"session_id"`
	Sequence     uint64    `json:"sequence"`
	IngressBytes uint64    `json:"ingress_bytes"`
	EgressBytes  uint64    `json:"egress_bytes"`
	Closed       bool      `json:"closed"`
	ObservedAt   time.Time `json:"observed_at"`
}

type ReconcileRequest struct {
	SourceID    string        `json:"source_id"`
	ObservedAt  time.Time     `json:"observed_at"`
	Allocations []CoturnUsage `json:"allocations"`
}

type ReconcileResult struct {
	Applied                   int      `json:"applied"`
	Duplicate                 int      `json:"duplicate"`
	AlreadyAhead              int      `json:"already_ahead"`
	MissingAllocationIDs      []string `json:"missing_allocation_ids"`
	UnauthorizedAllocationIDs []string `json:"unauthorized_allocation_ids"`
	ConflictAllocationIDs     []string `json:"conflict_allocation_ids"`
	RevokedAllocationIDs      []string `json:"revoked_allocation_ids"`
}
