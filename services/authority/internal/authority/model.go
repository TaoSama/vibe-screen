package authority

import (
	"encoding/json"
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

type SignalingAuthorization struct {
	Role      string    `json:"role"`
	ExpiresAt time.Time `json:"expires_at"`
}

type PublicDeviceIdentity struct {
	DeviceID           string `json:"device_id"`
	KeyID              string `json:"key_id"`
	KeyEpoch           uint64 `json:"key_epoch"`
	SignatureAlgorithm string `json:"signature_algorithm"`
	SigningPublicKey   string `json:"signing_public_key"`
}

type LeaseICEServer struct {
	URLs       []string `json:"urls"`
	Username   *string  `json:"username"`
	Credential *string  `json:"credential"`
}

type SessionProfileRequest struct {
	RequestID               string               `json:"request_id"`
	AccountID               string               `json:"account_id"`
	PairingID               string               `json:"pairing_id"`
	HostIdentity            PublicDeviceIdentity `json:"host_identity"`
	ClientIdentity          PublicDeviceIdentity `json:"client_identity"`
	SignalingURL            string               `json:"signaling_url"`
	SessionEpoch            uint64               `json:"session_epoch"`
	TTLSeconds              int64                `json:"ttl_seconds"`
	TranscriptContext       string               `json:"transcript_context"`
	ProtocolSessionID       string               `json:"protocol_session_id"`
	ICEServers              []LeaseICEServer     `json:"ice_servers"`
	AllowInsecureForTesting bool                 `json:"allow_insecure_for_testing"`
}

type SessionProfileResponse struct {
	AccountID            string          `json:"account_id"`
	PairingID            string          `json:"pairing_id"`
	SignalingSessionID   string          `json:"signaling_session_id"`
	HostSignalingToken   string          `json:"host_signaling_token"`
	ExpiresAt            time.Time       `json:"expires_at"`
	Created              bool            `json:"created"`
	UnsignedAndroidLease json.RawMessage `json:"unsigned_android_lease"`
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
