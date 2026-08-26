package security

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/ecdh"
	"crypto/hkdf"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"errors"
	"io"
	"sync"
	"time"
)

const (
	KeyAgreementAlgorithmECDHP256 = "ECDH_P256"
	AeadAlgorithmAES256GCM        = "AES_256_GCM"
	pairingSecretSize             = 32
	pairingIDSize                 = 16
	pairingChallengeSize          = 32
	credentialSize                = 32
	pairingRequestDomain          = "vibescreen/pairing-request/v1"
	pairingResultDomain           = "vibescreen/pairing-result/v1"
	pairingBootstrapDomain        = "vibescreen/pairing-bootstrap/v1"
	pairingKDFInfo                = "vibescreen/pairing-session-keys/v1"
	credentialAAD                 = "vibescreen/device-credential/v1"
)

var (
	ErrExpiredOffer      = errors.New("pairing offer expired")
	ErrOfferMismatch     = errors.New("pairing offer mismatch")
	ErrUnsupportedCrypto = errors.New("unsupported cryptographic algorithm")
)

type PairingOffer struct {
	OfferID                []byte
	OneTimeCredential      []byte
	ExpiresAt              time.Time
	HostIdentity           PublicIdentity
	Challenge              []byte
	HostEphemeralPublicKey []byte
	SignatureAlgorithm     string
	KeyAgreementAlgorithm  string
	AeadAlgorithm          string
}

type PairingRequest struct {
	OfferID                  []byte
	DeviceIdentity           PublicIdentity
	DeviceEphemeralPublicKey []byte
	Signature                []byte
	BootstrapMAC             []byte
}

type PairingResult struct {
	HostIdentity        PublicIdentity
	HostSignature       []byte
	EncryptedCredential []byte
	CredentialNonce     []byte
	SessionKeyID        string
	SessionKeyEpoch     uint64
}

type SessionKeys struct {
	KeyID            string
	KeyEpoch         uint64
	HostControlKey   [32]byte
	DeviceControlKey [32]byte
	HostMediaKey     [32]byte
	DeviceMediaKey   [32]byte
}

type HostPairingSession struct {
	host      *Identity
	offer     PairingOffer
	ephemeral *ecdh.PrivateKey
	used      bool
	mu        sync.Mutex
	random    io.Reader
}

type DevicePairingSession struct {
	device    *Identity
	offer     PairingOffer
	request   PairingRequest
	ephemeral *ecdh.PrivateKey
}

func NewHostPairingSession(host *Identity, now time.Time, ttl time.Duration, random io.Reader) (*HostPairingSession, error) {
	if host == nil || ttl <= 0 {
		return nil, ErrInvalidIdentity
	}
	if random == nil {
		random = rand.Reader
	}
	ephemeral, err := ecdh.P256().GenerateKey(random)
	if err != nil {
		return nil, err
	}
	offer := PairingOffer{
		OfferID:                make([]byte, pairingIDSize),
		OneTimeCredential:      make([]byte, pairingSecretSize),
		ExpiresAt:              now.Add(ttl),
		HostIdentity:           host.Public(),
		Challenge:              make([]byte, pairingChallengeSize),
		HostEphemeralPublicKey: ephemeral.PublicKey().Bytes(),
		SignatureAlgorithm:     SignatureAlgorithmECDSAP256SHA256,
		KeyAgreementAlgorithm:  KeyAgreementAlgorithmECDHP256,
		AeadAlgorithm:          AeadAlgorithmAES256GCM,
	}
	for _, target := range [][]byte{offer.OfferID, offer.OneTimeCredential, offer.Challenge} {
		if _, err := io.ReadFull(random, target); err != nil {
			return nil, err
		}
	}
	return &HostPairingSession{host: host, offer: offer, ephemeral: ephemeral, random: random}, nil
}

func (session *HostPairingSession) Offer() PairingOffer {
	return cloneOffer(session.offer)
}

func NewDevicePairingSession(device *Identity, offer PairingOffer, now time.Time, random io.Reader) (*DevicePairingSession, PairingRequest, error) {
	if device == nil {
		return nil, PairingRequest{}, ErrInvalidIdentity
	}
	if err := validateOffer(offer, now); err != nil {
		return nil, PairingRequest{}, err
	}
	if random == nil {
		random = rand.Reader
	}
	ephemeral, err := ecdh.P256().GenerateKey(random)
	if err != nil {
		return nil, PairingRequest{}, err
	}
	request := PairingRequest{
		OfferID:                  append([]byte(nil), offer.OfferID...),
		DeviceIdentity:           device.Public(),
		DeviceEphemeralPublicKey: ephemeral.PublicKey().Bytes(),
	}
	request.Signature, err = device.sign(pairingRequestDomain, pairingRequestParts(offer, request)...)
	if err != nil {
		return nil, PairingRequest{}, err
	}
	request.BootstrapMAC = pairingBootstrapMAC(offer.OneTimeCredential, offer, request)
	return &DevicePairingSession{device: device, offer: cloneOffer(offer), request: request, ephemeral: ephemeral}, cloneRequest(request), nil
}

func (session *HostPairingSession) Accept(request PairingRequest, now time.Time) (PairingResult, SessionKeys, []byte, error) {
	session.mu.Lock()
	defer session.mu.Unlock()
	if session.used {
		return PairingResult{}, SessionKeys{}, nil, ErrOfferMismatch
	}
	if err := validateOffer(session.offer, now); err != nil {
		return PairingResult{}, SessionKeys{}, nil, err
	}
	if subtle.ConstantTimeCompare(request.OfferID, session.offer.OfferID) != 1 ||
		!hmac.Equal(request.BootstrapMAC, pairingBootstrapMAC(session.offer.OneTimeCredential, session.offer, request)) {
		return PairingResult{}, SessionKeys{}, nil, ErrOfferMismatch
	}
	if err := verify(request.DeviceIdentity, pairingRequestDomain, request.Signature, pairingRequestParts(session.offer, request)...); err != nil {
		return PairingResult{}, SessionKeys{}, nil, err
	}
	peerKey, err := ecdh.P256().NewPublicKey(request.DeviceEphemeralPublicKey)
	if err != nil {
		return PairingResult{}, SessionKeys{}, nil, err
	}
	sharedSecret, err := session.ephemeral.ECDH(peerKey)
	if err != nil {
		return PairingResult{}, SessionKeys{}, nil, err
	}
	keys, err := deriveSessionKeys(sharedSecret, session.offer, request)
	if err != nil {
		return PairingResult{}, SessionKeys{}, nil, err
	}
	issuedCredential := make([]byte, credentialSize)
	if _, err := io.ReadFull(session.random, issuedCredential); err != nil {
		return PairingResult{}, SessionKeys{}, nil, err
	}
	ciphertext, nonce, err := sealCredential(keys.HostControlKey[:], issuedCredential, session.random)
	if err != nil {
		return PairingResult{}, SessionKeys{}, nil, err
	}
	result := PairingResult{
		HostIdentity:        session.host.Public(),
		EncryptedCredential: ciphertext,
		CredentialNonce:     nonce,
		SessionKeyID:        keys.KeyID,
		SessionKeyEpoch:     keys.KeyEpoch,
	}
	result.HostSignature, err = session.host.sign(pairingResultDomain, pairingResultParts(session.offer, request, result)...)
	if err != nil {
		return PairingResult{}, SessionKeys{}, nil, err
	}
	session.used = true
	return result, keys, append([]byte(nil), issuedCredential...), nil
}

func (session *DevicePairingSession) Complete(result PairingResult) (SessionKeys, []byte, error) {
	if err := verify(result.HostIdentity, pairingResultDomain, result.HostSignature, pairingResultParts(session.offer, session.request, result)...); err != nil {
		return SessionKeys{}, nil, err
	}
	if result.HostIdentity.KeyID != session.offer.HostIdentity.KeyID {
		return SessionKeys{}, nil, ErrOfferMismatch
	}
	peerKey, err := ecdh.P256().NewPublicKey(session.offer.HostEphemeralPublicKey)
	if err != nil {
		return SessionKeys{}, nil, err
	}
	sharedSecret, err := session.ephemeral.ECDH(peerKey)
	if err != nil {
		return SessionKeys{}, nil, err
	}
	keys, err := deriveSessionKeys(sharedSecret, session.offer, session.request)
	if err != nil {
		return SessionKeys{}, nil, err
	}
	if keys.KeyID != result.SessionKeyID || keys.KeyEpoch != result.SessionKeyEpoch {
		return SessionKeys{}, nil, ErrOfferMismatch
	}
	credential, err := openCredential(keys.HostControlKey[:], result.EncryptedCredential, result.CredentialNonce)
	return keys, credential, err
}

func validateOffer(offer PairingOffer, now time.Time) error {
	if !now.Before(offer.ExpiresAt) {
		return ErrExpiredOffer
	}
	if len(offer.OfferID) != pairingIDSize || len(offer.OneTimeCredential) != pairingSecretSize ||
		len(offer.Challenge) != pairingChallengeSize ||
		offer.SignatureAlgorithm != SignatureAlgorithmECDSAP256SHA256 ||
		offer.KeyAgreementAlgorithm != KeyAgreementAlgorithmECDHP256 ||
		offer.AeadAlgorithm != AeadAlgorithmAES256GCM {
		return ErrUnsupportedCrypto
	}
	if err := validateIdentity(offer.HostIdentity); err != nil {
		return err
	}
	_, err := ecdh.P256().NewPublicKey(offer.HostEphemeralPublicKey)
	return err
}

func deriveSessionKeys(sharedSecret []byte, offer PairingOffer, request PairingRequest) (SessionKeys, error) {
	context := transcript(pairingKDFInfo, pairingRequestParts(offer, request)...)
	material, err := hkdf.Key(sha256.New, sharedSecret, offer.OneTimeCredential, string(context), 128)
	if err != nil {
		return SessionKeys{}, err
	}
	keyDigest := sha256.Sum256(append(context, material...))
	keys := SessionKeys{KeyID: keyID(keyDigest[:]), KeyEpoch: 1}
	copy(keys.HostControlKey[:], material[:32])
	copy(keys.DeviceControlKey[:], material[32:64])
	copy(keys.HostMediaKey[:], material[64:96])
	copy(keys.DeviceMediaKey[:], material[96:])
	return keys, nil
}

// RotateTrafficKeys derives a fresh four-key epoch from the current key
// material. The update message must itself travel inside authenticated control
// encryption; callers retain the previous receive epoch only for a bounded
// reordering window and destroy it after acknowledgement.
func RotateTrafficKeys(current SessionKeys, nextEpoch uint64, updateNonce []byte) (SessionKeys, error) {
	if current.KeyID == "" || current.KeyEpoch == 0 || nextEpoch != current.KeyEpoch+1 || len(updateNonce) < 16 {
		return SessionKeys{}, ErrInvalidKeyEpoch
	}
	material := make([]byte, 0, 128)
	material = append(material, current.HostControlKey[:]...)
	material = append(material, current.DeviceControlKey[:]...)
	material = append(material, current.HostMediaKey[:]...)
	material = append(material, current.DeviceMediaKey[:]...)
	info := transcript("vibescreen/traffic-key-update/v1", []byte(current.KeyID),
		uint64Bytes(current.KeyEpoch), uint64Bytes(nextEpoch), updateNonce)
	rotated, err := hkdf.Key(sha256.New, material, updateNonce, string(info), len(material))
	if err != nil {
		return SessionKeys{}, err
	}
	digest := sha256.Sum256(append(info, rotated...))
	next := SessionKeys{KeyID: keyID(digest[:]), KeyEpoch: nextEpoch}
	copy(next.HostControlKey[:], rotated[:32])
	copy(next.DeviceControlKey[:], rotated[32:64])
	copy(next.HostMediaKey[:], rotated[64:96])
	copy(next.DeviceMediaKey[:], rotated[96:])
	return next, nil
}

func sealCredential(key, plaintext []byte, random io.Reader) ([]byte, []byte, error) {
	aead, err := newAEAD(key)
	if err != nil {
		return nil, nil, err
	}
	nonce := make([]byte, aead.NonceSize())
	if _, err := io.ReadFull(random, nonce); err != nil {
		return nil, nil, err
	}
	return aead.Seal(nil, nonce, plaintext, []byte(credentialAAD)), nonce, nil
}

func openCredential(key, ciphertext, nonce []byte) ([]byte, error) {
	aead, err := newAEAD(key)
	if err != nil {
		return nil, err
	}
	return aead.Open(nil, nonce, ciphertext, []byte(credentialAAD))
}

func newAEAD(key []byte) (cipher.AEAD, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	return cipher.NewGCM(block)
}

func pairingRequestParts(offer PairingOffer, request PairingRequest) [][]byte {
	return [][]byte{offer.OfferID, offer.Challenge, offer.HostIdentity.SigningPublicKey,
		offer.HostEphemeralPublicKey, request.DeviceIdentity.SigningPublicKey,
		request.DeviceEphemeralPublicKey, []byte(request.DeviceIdentity.DeviceID),
		uint64Bytes(request.DeviceIdentity.KeyEpoch)}
}

func pairingResultParts(offer PairingOffer, request PairingRequest, result PairingResult) [][]byte {
	parts := pairingRequestParts(offer, request)
	return append(parts, result.EncryptedCredential, result.CredentialNonce,
		[]byte(result.SessionKeyID), uint64Bytes(result.SessionKeyEpoch))
}

func pairingBootstrapMAC(secret []byte, offer PairingOffer, request PairingRequest) []byte {
	mac := hmac.New(sha256.New, secret)
	parts := append(pairingRequestParts(offer, request), request.Signature)
	_, _ = mac.Write(transcript(pairingBootstrapDomain, parts...))
	return mac.Sum(nil)
}

func cloneOffer(offer PairingOffer) PairingOffer {
	offer.OfferID = append([]byte(nil), offer.OfferID...)
	offer.OneTimeCredential = append([]byte(nil), offer.OneTimeCredential...)
	offer.Challenge = append([]byte(nil), offer.Challenge...)
	offer.HostEphemeralPublicKey = append([]byte(nil), offer.HostEphemeralPublicKey...)
	offer.HostIdentity.SigningPublicKey = append([]byte(nil), offer.HostIdentity.SigningPublicKey...)
	return offer
}

func cloneRequest(request PairingRequest) PairingRequest {
	request.OfferID = append([]byte(nil), request.OfferID...)
	request.DeviceEphemeralPublicKey = append([]byte(nil), request.DeviceEphemeralPublicKey...)
	request.DeviceIdentity.SigningPublicKey = append([]byte(nil), request.DeviceIdentity.SigningPublicKey...)
	request.Signature = append([]byte(nil), request.Signature...)
	request.BootstrapMAC = append([]byte(nil), request.BootstrapMAC...)
	return request
}
