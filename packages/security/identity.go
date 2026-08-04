package security

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"io"
	"sync"
)

const (
	SignatureAlgorithmECDSAP256SHA256 = "ECDSA_P256_SHA256"
	identityDomain                    = "vibescreen/identity/v1"
)

var (
	ErrInvalidIdentity = errors.New("invalid device identity")
	ErrInvalidProof    = errors.New("invalid signature proof")
)

// PublicIdentity is the stable, serializable part of a device identity.
type PublicIdentity struct {
	DeviceID         string
	KeyID            string
	KeyEpoch         uint64
	Algorithm        string
	SigningPublicKey []byte
}

// Identity owns an ECDSA P-256 private key. Callers should persist it in the
// platform keystore rather than serializing it with protocol messages.
type Identity struct {
	public  PublicIdentity
	private *ecdsa.PrivateKey
	random  io.Reader
	signMu  sync.Mutex
}

func GenerateIdentity(deviceID string, keyEpoch uint64, random io.Reader) (*Identity, error) {
	if deviceID == "" || keyEpoch == 0 {
		return nil, ErrInvalidIdentity
	}
	if random == nil {
		random = rand.Reader
	}
	privateKey, err := ecdsa.GenerateKey(elliptic.P256(), random)
	if err != nil {
		return nil, err
	}
	publicKey := elliptic.Marshal(elliptic.P256(), privateKey.PublicKey.X, privateKey.PublicKey.Y)
	return &Identity{
		public: PublicIdentity{
			DeviceID:         deviceID,
			KeyID:            keyID(publicKey),
			KeyEpoch:         keyEpoch,
			Algorithm:        SignatureAlgorithmECDSAP256SHA256,
			SigningPublicKey: append([]byte(nil), publicKey...),
		},
		private: privateKey,
		random:  random,
	}, nil
}

func (i *Identity) Public() PublicIdentity {
	result := i.public
	result.SigningPublicKey = append([]byte(nil), result.SigningPublicKey...)
	return result
}

func (i *Identity) sign(domain string, parts ...[]byte) ([]byte, error) {
	i.signMu.Lock()
	defer i.signMu.Unlock()
	digest := transcript(domain, parts...)
	return ecdsa.SignASN1(i.random, i.private, digest)
}

func validateIdentity(identity PublicIdentity) error {
	if identity.DeviceID == "" || identity.KeyEpoch == 0 ||
		identity.Algorithm != SignatureAlgorithmECDSAP256SHA256 ||
		len(identity.SigningPublicKey) != 65 ||
		subtle.ConstantTimeCompare([]byte(identity.KeyID), []byte(keyID(identity.SigningPublicKey))) != 1 {
		return ErrInvalidIdentity
	}
	x, y := elliptic.Unmarshal(elliptic.P256(), identity.SigningPublicKey)
	if x == nil || y == nil {
		return ErrInvalidIdentity
	}
	return nil
}

func verify(identity PublicIdentity, domain string, signature []byte, parts ...[]byte) error {
	if err := validateIdentity(identity); err != nil {
		return err
	}
	digest := transcript(domain, parts...)
	x, y := elliptic.Unmarshal(elliptic.P256(), identity.SigningPublicKey)
	if x == nil || !ecdsa.VerifyASN1(&ecdsa.PublicKey{Curve: elliptic.P256(), X: x, Y: y}, digest, signature) {
		return ErrInvalidProof
	}
	return nil
}

func keyID(publicKey []byte) string {
	digest := sha256.Sum256(publicKey)
	return hex.EncodeToString(digest[:])
}

// transcript length-prefixes every value and domain-separates every protocol
// operation, avoiding ambiguous concatenation and cross-protocol signatures.
func transcript(domain string, parts ...[]byte) []byte {
	hash := sha256.New()
	writePart(hash, []byte(identityDomain))
	writePart(hash, []byte(domain))
	for _, part := range parts {
		writePart(hash, part)
	}
	return hash.Sum(nil)
}

func writePart(writer io.Writer, value []byte) {
	var size [8]byte
	binary.BigEndian.PutUint64(size[:], uint64(len(value)))
	_, _ = writer.Write(size[:])
	_, _ = writer.Write(value)
}

func uint64Bytes(value uint64) []byte {
	var encoded [8]byte
	binary.BigEndian.PutUint64(encoded[:], value)
	return encoded[:]
}
