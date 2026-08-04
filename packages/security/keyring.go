package security

import (
	"crypto/sha256"
	"errors"
	"sync"
	"time"
)

const (
	rotationDomain      = "vibescreen/key-rotation/v1"
	revocationDomain    = "vibescreen/device-revocation/v1"
	rotationNonceDomain = "vibescreen/key-rotation-nonce/v1"
)

var (
	ErrUnknownDevice       = errors.New("unknown device")
	ErrDeviceRevoked       = errors.New("device revoked")
	ErrInvalidKeyEpoch     = errors.New("invalid key epoch")
	ErrRevocationOrder     = errors.New("revocation sequence is not increasing")
	ErrAuthorityMismatch   = errors.New("authority identity mismatch")
	ErrRotationNonceReuse  = errors.New("rotation nonce already used")
	ErrInvalidKeyringState = errors.New("invalid persisted keyring state")
)

type RotationRequest struct {
	Authority        PublicIdentity
	CurrentIdentity  PublicIdentity
	NextIdentity     PublicIdentity
	RotationNonce    []byte
	NotBefore        time.Time
	Signature        []byte
	NextKeySignature []byte
}

type Revocation struct {
	DeviceID           string
	KeyID              string
	Sequence           uint64
	RevokedAt          time.Time
	Nonce              []byte
	ReasonCode         string
	Authority          PublicIdentity
	AuthoritySignature []byte
}

// KeyringState contains all authority-scoped monotonic security state that
// must be committed atomically with a successful rotation or revocation.
type KeyringState struct {
	Authority           PublicIdentity
	Active              []PublicIdentity
	Revoked             []Revocation
	RevocationSequence  uint64
	RotationNonceHashes [][]byte
}

type Keyring struct {
	mu                    sync.RWMutex
	authority             PublicIdentity
	active                map[string]PublicIdentity
	revoked               map[string]Revocation
	revocationSequence    uint64
	usedRotationNonceHash map[[sha256.Size]byte]struct{}
}

func NewKeyring(authority PublicIdentity) (*Keyring, error) {
	return NewKeyringFromState(KeyringState{Authority: authority})
}

// NewKeyringFromState validates and restores a complete authority-scoped
// snapshot. Callers must persist Snapshot transactionally before acknowledging
// a successful state-changing operation to its peer.
func NewKeyringFromState(state KeyringState) (*Keyring, error) {
	if err := validateIdentity(state.Authority); err != nil {
		return nil, err
	}
	keyring := &Keyring{
		authority:             clonePublicIdentity(state.Authority),
		active:                make(map[string]PublicIdentity),
		revoked:               make(map[string]Revocation),
		revocationSequence:    state.RevocationSequence,
		usedRotationNonceHash: make(map[[sha256.Size]byte]struct{}),
	}
	for _, identity := range state.Active {
		if err := validateIdentity(identity); err != nil {
			return nil, ErrInvalidKeyringState
		}
		if _, exists := keyring.active[identity.DeviceID]; exists {
			return nil, ErrInvalidKeyringState
		}
		keyring.active[identity.DeviceID] = clonePublicIdentity(identity)
	}
	seenSequences := make(map[uint64]struct{})
	var maximumSequence uint64
	for _, revocation := range state.Revoked {
		if !sameIdentity(revocation.Authority, keyring.authority) || revocation.Sequence == 0 {
			return nil, ErrInvalidKeyringState
		}
		if _, exists := keyring.active[revocation.DeviceID]; exists {
			return nil, ErrInvalidKeyringState
		}
		if _, exists := keyring.revoked[revocation.DeviceID]; exists {
			return nil, ErrInvalidKeyringState
		}
		if _, exists := seenSequences[revocation.Sequence]; exists {
			return nil, ErrInvalidKeyringState
		}
		if err := verify(keyring.authority, revocationDomain, revocation.AuthoritySignature, revocationParts(revocation)...); err != nil {
			return nil, ErrInvalidKeyringState
		}
		seenSequences[revocation.Sequence] = struct{}{}
		if revocation.Sequence > maximumSequence {
			maximumSequence = revocation.Sequence
		}
		keyring.revoked[revocation.DeviceID] = cloneRevocation(revocation)
	}
	if maximumSequence > state.RevocationSequence || (len(state.Revoked) > 0 && maximumSequence != state.RevocationSequence) {
		return nil, ErrInvalidKeyringState
	}
	for _, encodedHash := range state.RotationNonceHashes {
		if len(encodedHash) != sha256.Size {
			return nil, ErrInvalidKeyringState
		}
		var hash [sha256.Size]byte
		copy(hash[:], encodedHash)
		if _, exists := keyring.usedRotationNonceHash[hash]; exists {
			return nil, ErrInvalidKeyringState
		}
		keyring.usedRotationNonceHash[hash] = struct{}{}
	}
	return keyring, nil
}

func (keyring *Keyring) Snapshot() KeyringState {
	keyring.mu.RLock()
	defer keyring.mu.RUnlock()
	state := KeyringState{
		Authority:           clonePublicIdentity(keyring.authority),
		RevocationSequence:  keyring.revocationSequence,
		Active:              make([]PublicIdentity, 0, len(keyring.active)),
		Revoked:             make([]Revocation, 0, len(keyring.revoked)),
		RotationNonceHashes: make([][]byte, 0, len(keyring.usedRotationNonceHash)),
	}
	for _, identity := range keyring.active {
		state.Active = append(state.Active, clonePublicIdentity(identity))
	}
	for _, revocation := range keyring.revoked {
		state.Revoked = append(state.Revoked, cloneRevocation(revocation))
	}
	for hash := range keyring.usedRotationNonceHash {
		state.RotationNonceHashes = append(state.RotationNonceHashes, append([]byte(nil), hash[:]...))
	}
	return state
}

func (keyring *Keyring) Register(identity PublicIdentity) error {
	if err := validateIdentity(identity); err != nil {
		return err
	}
	keyring.mu.Lock()
	defer keyring.mu.Unlock()
	if _, revoked := keyring.revoked[identity.DeviceID]; revoked {
		return ErrDeviceRevoked
	}
	if _, exists := keyring.active[identity.DeviceID]; exists {
		return ErrInvalidKeyEpoch
	}
	keyring.active[identity.DeviceID] = clonePublicIdentity(identity)
	return nil
}

func NewRotationRequest(authority PublicIdentity, current, next *Identity, nonce []byte, notBefore time.Time) (RotationRequest, error) {
	if err := validateIdentity(authority); err != nil {
		return RotationRequest{}, err
	}
	if current == nil || next == nil || current.public.DeviceID != next.public.DeviceID ||
		next.public.KeyEpoch != current.public.KeyEpoch+1 || len(nonce) < 16 {
		return RotationRequest{}, ErrInvalidKeyEpoch
	}
	request := RotationRequest{Authority: clonePublicIdentity(authority), CurrentIdentity: current.Public(), NextIdentity: next.Public(),
		RotationNonce: append([]byte(nil), nonce...), NotBefore: notBefore}
	var err error
	request.Signature, err = current.sign(rotationDomain, rotationParts(request)...)
	if err != nil {
		return RotationRequest{}, err
	}
	request.NextKeySignature, err = next.sign(rotationDomain, rotationParts(request)...)
	if err != nil {
		return RotationRequest{}, err
	}
	return request, nil
}

func (keyring *Keyring) Rotate(request RotationRequest, now time.Time) error {
	if now.Before(request.NotBefore) || request.NextIdentity.DeviceID != request.CurrentIdentity.DeviceID ||
		request.NextIdentity.KeyEpoch != request.CurrentIdentity.KeyEpoch+1 || len(request.RotationNonce) < 16 {
		return ErrInvalidKeyEpoch
	}
	if !sameIdentity(request.Authority, keyring.authority) {
		return ErrAuthorityMismatch
	}
	if err := validateIdentity(request.NextIdentity); err != nil {
		return err
	}
	keyring.mu.Lock()
	defer keyring.mu.Unlock()
	nonceHash := rotationNonceHash(keyring.authority, request.RotationNonce)
	if _, used := keyring.usedRotationNonceHash[nonceHash]; used {
		return ErrRotationNonceReuse
	}
	if _, revoked := keyring.revoked[request.CurrentIdentity.DeviceID]; revoked {
		return ErrDeviceRevoked
	}
	current, exists := keyring.active[request.CurrentIdentity.DeviceID]
	if !exists {
		return ErrUnknownDevice
	}
	if !sameIdentity(current, request.CurrentIdentity) {
		return ErrInvalidKeyEpoch
	}
	if err := verify(current, rotationDomain, request.Signature, rotationParts(request)...); err != nil {
		return err
	}
	if err := verify(request.NextIdentity, rotationDomain, request.NextKeySignature, rotationParts(request)...); err != nil {
		return err
	}
	keyring.active[current.DeviceID] = clonePublicIdentity(request.NextIdentity)
	keyring.usedRotationNonceHash[nonceHash] = struct{}{}
	return nil
}

func NewRevocation(authority *Identity, deviceID, keyID, reason string, sequence uint64, now time.Time, nonce []byte) (Revocation, error) {
	if authority == nil || deviceID == "" || reason == "" || sequence == 0 || len(nonce) < 16 {
		return Revocation{}, ErrRevocationOrder
	}
	revocation := Revocation{DeviceID: deviceID, KeyID: keyID, Sequence: sequence,
		RevokedAt: now, Nonce: append([]byte(nil), nonce...), ReasonCode: reason, Authority: authority.Public()}
	var err error
	revocation.AuthoritySignature, err = authority.sign(revocationDomain, revocationParts(revocation)...)
	if err != nil {
		return Revocation{}, err
	}
	return revocation, nil
}

func (keyring *Keyring) Revoke(revocation Revocation) error {
	keyring.mu.Lock()
	defer keyring.mu.Unlock()
	if !sameIdentity(revocation.Authority, keyring.authority) {
		return ErrAuthorityMismatch
	}
	if revocation.Sequence <= keyring.revocationSequence {
		return ErrRevocationOrder
	}
	current, exists := keyring.active[revocation.DeviceID]
	if !exists {
		return ErrUnknownDevice
	}
	if revocation.KeyID != "" && revocation.KeyID != current.KeyID {
		return ErrInvalidKeyEpoch
	}
	if err := verify(keyring.authority, revocationDomain, revocation.AuthoritySignature, revocationParts(revocation)...); err != nil {
		return err
	}
	keyring.revoked[revocation.DeviceID] = cloneRevocation(revocation)
	delete(keyring.active, revocation.DeviceID)
	keyring.revocationSequence = revocation.Sequence
	return nil
}

func (keyring *Keyring) Authorize(deviceID, keyID string) error {
	keyring.mu.RLock()
	defer keyring.mu.RUnlock()
	if _, revoked := keyring.revoked[deviceID]; revoked {
		return ErrDeviceRevoked
	}
	identity, exists := keyring.active[deviceID]
	if !exists {
		return ErrUnknownDevice
	}
	if identity.KeyID != keyID {
		return ErrInvalidKeyEpoch
	}
	return nil
}

func rotationParts(request RotationRequest) [][]byte {
	return [][]byte{identityParts(request.Authority), identityParts(request.CurrentIdentity),
		identityParts(request.NextIdentity), request.RotationNonce,
		uint64Bytes(uint64(request.NotBefore.Unix()))}
}

func revocationParts(revocation Revocation) [][]byte {
	return [][]byte{identityParts(revocation.Authority), []byte(revocation.DeviceID), []byte(revocation.KeyID),
		uint64Bytes(revocation.Sequence), uint64Bytes(uint64(revocation.RevokedAt.Unix())),
		revocation.Nonce, []byte(revocation.ReasonCode)}
}

func identityParts(identity PublicIdentity) []byte {
	return transcript("vibescreen/public-identity/v1", []byte(identity.DeviceID), []byte(identity.KeyID),
		uint64Bytes(identity.KeyEpoch), []byte(identity.Algorithm), identity.SigningPublicKey)
}

func rotationNonceHash(authority PublicIdentity, nonce []byte) [sha256.Size]byte {
	return sha256.Sum256(transcript(rotationNonceDomain, identityParts(authority), nonce))
}

func sameIdentity(left, right PublicIdentity) bool {
	return left.DeviceID == right.DeviceID && left.KeyID == right.KeyID && left.KeyEpoch == right.KeyEpoch &&
		left.Algorithm == right.Algorithm && equalBytes(left.SigningPublicKey, right.SigningPublicKey)
}

func clonePublicIdentity(identity PublicIdentity) PublicIdentity {
	identity.SigningPublicKey = append([]byte(nil), identity.SigningPublicKey...)
	return identity
}

func cloneRevocation(revocation Revocation) Revocation {
	revocation.Nonce = append([]byte(nil), revocation.Nonce...)
	revocation.Authority = clonePublicIdentity(revocation.Authority)
	revocation.AuthoritySignature = append([]byte(nil), revocation.AuthoritySignature...)
	return revocation
}
