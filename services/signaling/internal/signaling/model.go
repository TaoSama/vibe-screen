package signaling

import (
	"encoding/json"
	"time"
)

type Role string

const (
	RoleHost   Role = "host"
	RoleDevice Role = "device"
)

type MessageType string

const (
	MessageOffer           MessageType = "offer"
	MessageAnswer          MessageType = "answer"
	MessageICECandidate    MessageType = "ice_candidate"
	MessageEndOfCandidates MessageType = "end_of_candidates"
)

type ICECandidate struct {
	Candidate        string  `json:"candidate"`
	SDPMid           string  `json:"sdp_mid,omitempty"`
	SDPMLineIndex    *uint16 `json:"sdp_mline_index,omitempty"`
	UsernameFragment string  `json:"username_fragment,omitempty"`
}

type MessageRequest struct {
	MessageID string        `json:"message_id"`
	Type      MessageType   `json:"type"`
	SDP       string        `json:"sdp,omitempty"`
	Candidate *ICECandidate `json:"candidate,omitempty"`
}

type Event struct {
	Sequence   uint64        `json:"sequence"`
	MessageID  string        `json:"message_id"`
	Type       MessageType   `json:"type"`
	SenderRole Role          `json:"sender_role"`
	SDP        string        `json:"sdp,omitempty"`
	Candidate  *ICECandidate `json:"candidate,omitempty"`
	CreatedAt  time.Time     `json:"created_at"`
}

type SessionResponse struct {
	SessionID      string                  `json:"session_id"`
	HostToken      string                  `json:"host_token"`
	DeviceToken    string                  `json:"device_token"`
	ExpiresAt      time.Time               `json:"expires_at"`
	SessionProfile *SessionProfileResponse `json:"session_profile,omitempty"`
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
	PairingID               string               `json:"pairing_id"`
	HostIdentity            PublicDeviceIdentity `json:"host_identity"`
	ClientIdentity          PublicDeviceIdentity `json:"client_identity"`
	SignalingURL            string               `json:"signaling_url"`
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
