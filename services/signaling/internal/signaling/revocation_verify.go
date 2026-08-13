package signaling

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"hash"
	"time"
)

const (
	identityAlgorithm = "ECDSA_P256_SHA256"
	identityDomain    = "vibescreen/identity/v1"
	revocationDomain  = "vibescreen/device-revocation/v1"
)

func verifySignedRevocation(t SignedDeviceRevocation, expectedAuthority, expectedPeer PublicIdentity, now time.Time) error {
	if !sameIdentity(t.Authority, expectedAuthority) || !sameIdentity(t.PeerIdentity, expectedPeer) ||
		t.Sequence == 0 || t.RevokedAtUnixSeconds < 0 || len(t.Nonce) < 16 || t.ReasonCode == "" ||
		t.PeerIdentity.DeviceID == "" || t.PeerIdentity.DeviceID != expectedPeer.DeviceID {
		return errors.New("revocation identity or fields do not match session binding")
	}
	// Reject timestamps far in the future without making delayed delivery expire.
	if time.Unix(t.RevokedAtUnixSeconds, 0).After(now.Add(5 * time.Minute)) {
		return errors.New("revocation timestamp is in the future")
	}
	if err := validateIdentity(t.Authority); err != nil {
		return err
	}
	digest := t.signingDigest()
	x, y := elliptic.Unmarshal(elliptic.P256(), t.Authority.SigningPublicKey)
	if x == nil || !ecdsa.VerifyASN1(&ecdsa.PublicKey{Curve: elliptic.P256(), X: x, Y: y}, digest, t.AuthoritySignature) {
		return errors.New("invalid revocation signature")
	}
	return nil
}

func (t SignedDeviceRevocation) signingDigest() []byte {
	return transcript(revocationDomain, identityDigest(t.Authority), []byte(t.PeerIdentity.DeviceID),
		[]byte(t.PeerIdentity.KeyID), uint64Bytes(t.Sequence), uint64Bytes(uint64(t.RevokedAtUnixSeconds)),
		t.Nonce, []byte(t.ReasonCode))
}

func validateIdentity(identity PublicIdentity) error {
	if !validIdentifier(identity.DeviceID) || identity.KeyEpoch == 0 || len(identity.SigningPublicKey) != 65 {
		return errors.New("invalid public identity")
	}
	wantKeyID := sha256.Sum256(identity.SigningPublicKey)
	if subtle.ConstantTimeCompare([]byte(identity.KeyID), []byte(hex.EncodeToString(wantKeyID[:]))) != 1 {
		return errors.New("public identity key id mismatch")
	}
	x, y := elliptic.Unmarshal(elliptic.P256(), identity.SigningPublicKey)
	if x == nil || y == nil {
		return errors.New("invalid public identity key")
	}
	return nil
}

func sameIdentity(a, b PublicIdentity) bool {
	return a.DeviceID == b.DeviceID && a.KeyID == b.KeyID && a.KeyEpoch == b.KeyEpoch &&
		subtle.ConstantTimeCompare(a.SigningPublicKey, b.SigningPublicKey) == 1
}

func identityDigest(identity PublicIdentity) []byte {
	return transcript("vibescreen/public-identity/v1", []byte(identity.DeviceID), []byte(identity.KeyID),
		uint64Bytes(identity.KeyEpoch), []byte(identityAlgorithm), identity.SigningPublicKey)
}

func transcript(domain string, parts ...[]byte) []byte {
	h := sha256.New()
	writePart(h, []byte(identityDomain))
	writePart(h, []byte(domain))
	for _, part := range parts {
		writePart(h, part)
	}
	return h.Sum(nil)
}

func writePart(h hash.Hash, value []byte) {
	_, _ = h.Write(uint64Bytes(uint64(len(value))))
	_, _ = h.Write(value)
}

func uint64Bytes(value uint64) []byte {
	encoded := make([]byte, 8)
	binary.BigEndian.PutUint64(encoded, value)
	return encoded
}
