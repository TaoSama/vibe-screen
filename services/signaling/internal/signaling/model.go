package signaling

import "time"

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
	SessionID    string    `json:"session_id"`
	HostToken    string    `json:"host_token"`
	DeviceToken  string    `json:"device_token"`
	ExpiresAt    time.Time `json:"expires_at"`
	DeviceID     string    `json:"device_id,omitempty"`
	SessionEpoch uint64    `json:"session_epoch,omitempty"`
}

type TurnCredentials struct {
	Username   string   `json:"username"`
	Password   string   `json:"password"`
	TTLSeconds int64    `json:"ttl_seconds"`
	Realm      string   `json:"realm"`
	URIs       []string `json:"uris"`
}

type RefreshResponse struct {
	SessionID    string           `json:"session_id"`
	RoleToken    string           `json:"role_token"`
	SessionEpoch uint64           `json:"session_epoch"`
	ExpiresAt    time.Time        `json:"expires_at"`
	Turn         *TurnCredentials `json:"turn,omitempty"`
}

type PublicIdentity struct {
	DeviceID         string `json:"deviceID"`
	KeyID            string `json:"keyID"`
	KeyEpoch         uint64 `json:"keyEpoch"`
	SigningPublicKey []byte `json:"signingPublicKey"`
}

type SignedDeviceRevocation struct {
	PeerIdentity         PublicIdentity `json:"peerIdentity"`
	Sequence             uint64         `json:"sequence"`
	RevokedAtUnixSeconds int64          `json:"revokedAtUnixSeconds"`
	Nonce                []byte         `json:"nonce"`
	ReasonCode           string         `json:"reasonCode"`
	Authority            PublicIdentity `json:"authority"`
	AuthoritySignature   []byte         `json:"authoritySignature"`
}
