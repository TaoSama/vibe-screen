package security

import (
	"crypto/cipher"
	"encoding/binary"
	"errors"
	"math"
	"sync"
	"sync/atomic"
)

const (
	ProtocolVersion  uint32     = 1
	ChannelControl   Channel    = 1
	ChannelMedia     Channel    = 2
	SenderHost       SenderRole = 1
	SenderDevice     SenderRole = 2
	replayWindowSize            = 64
	// maxSequence bounds the per-session send sequence so the 4-byte
	// nonce suffix never wraps and reuses a (key, nonce) pair.
	maxSequence = uint64(math.MaxUint32)
)

var (
	ErrInvalidPacket = errors.New("invalid secure packet")
	ErrReplay        = errors.New("replayed or stale packet")
	ErrSequenceLimit = errors.New("secure channel sequence exhausted")
)

type Channel uint32
type SenderRole uint32

type PacketHeader struct {
	ProtocolVersion uint32
	SessionID       []byte
	SessionEpoch    uint64
	KeyID           string
	KeyEpoch        uint64
	Channel         Channel
	SenderRole      SenderRole
	AeadAlgorithm   string
	Sequence        uint64
	Nonce           []byte
}

type EncryptedPacket struct {
	Header     PacketHeader
	Ciphertext []byte
}

// SecureChannelState encrypts exactly one logical channel. Control and media
// must use separate states and keys so their reliability and replay semantics
// cannot interfere with each other.
type SecureChannelState struct {
	protocolVersion uint32
	sessionID       []byte
	sessionEpoch    uint64
	keyID           string
	keyEpoch        uint64
	channel         Channel
	senderRole      SenderRole
	aead            cipher.AEAD
	sendSequence    atomic.Uint64
	receiveMu       sync.Mutex
	replay          replayWindow
}

func NewSecureChannel(sessionID []byte, sessionEpoch uint64, keys SessionKeys, channel Channel, senderRole SenderRole) (*SecureChannelState, error) {
	if len(sessionID) < 16 || sessionEpoch == 0 || keys.KeyID == "" || keys.KeyEpoch == 0 ||
		(channel != ChannelControl && channel != ChannelMedia) ||
		(senderRole != SenderHost && senderRole != SenderDevice) {
		return nil, ErrInvalidPacket
	}
	key := keys.HostControlKey[:]
	if senderRole == SenderDevice {
		key = keys.DeviceControlKey[:]
	}
	if channel == ChannelMedia && senderRole == SenderHost {
		key = keys.HostMediaKey[:]
	} else if channel == ChannelMedia {
		key = keys.DeviceMediaKey[:]
	}
	aead, err := newAEAD(key)
	if err != nil {
		return nil, err
	}
	return &SecureChannelState{
		protocolVersion: ProtocolVersion,
		sessionID:       append([]byte(nil), sessionID...),
		sessionEpoch:    sessionEpoch,
		keyID:           keys.KeyID,
		keyEpoch:        keys.KeyEpoch,
		channel:         channel,
		senderRole:      senderRole,
		aead:            aead,
	}, nil
}

func (state *SecureChannelState) Seal(plaintext []byte) (EncryptedPacket, error) {
	sequence, err := state.nextSequence()
	if err != nil {
		return EncryptedPacket{}, err
	}
	nonce := packetNonce(state.sessionEpoch, sequence)
	header := PacketHeader{
		ProtocolVersion: state.protocolVersion,
		SessionID:       append([]byte(nil), state.sessionID...),
		SessionEpoch:    state.sessionEpoch,
		KeyID:           state.keyID,
		KeyEpoch:        state.keyEpoch,
		Channel:         state.channel,
		SenderRole:      state.senderRole,
		AeadAlgorithm:   AeadAlgorithmAES256GCM,
		Sequence:        sequence,
		Nonce:           nonce,
	}
	ciphertext := state.aead.Seal(nil, nonce, plaintext, packetAAD(header))
	return EncryptedPacket{Header: header, Ciphertext: ciphertext}, nil
}

func (state *SecureChannelState) nextSequence() (uint64, error) {
	for {
		current := state.sendSequence.Load()
		if current >= maxSequence {
			return 0, ErrSequenceLimit
		}
		if state.sendSequence.CompareAndSwap(current, current+1) {
			return current + 1, nil
		}
	}
}

func (state *SecureChannelState) Open(packet EncryptedPacket) ([]byte, error) {
	if !state.matches(packet.Header) {
		return nil, ErrInvalidPacket
	}
	state.receiveMu.Lock()
	defer state.receiveMu.Unlock()
	if !state.canAccept(packet.Header.Sequence) {
		return nil, ErrReplay
	}
	plaintext, err := state.aead.Open(nil, packet.Header.Nonce, packet.Ciphertext, packetAAD(packet.Header))
	if err != nil {
		return nil, err
	}
	state.replay.accept(packet.Header.Sequence)
	return plaintext, nil
}

func (state *SecureChannelState) canAccept(sequence uint64) bool {
	if state.channel == ChannelControl {
		return sequence > state.replay.highest
	}
	return state.replay.canAccept(sequence)
}

func (state *SecureChannelState) matches(header PacketHeader) bool {
	expectedNonce := packetNonce(header.SessionEpoch, header.Sequence)
	return header.ProtocolVersion == state.protocolVersion &&
		header.SessionEpoch == state.sessionEpoch && header.KeyID == state.keyID &&
		header.KeyEpoch == state.keyEpoch && header.Channel == state.channel &&
		header.SenderRole == state.senderRole &&
		header.AeadAlgorithm == AeadAlgorithmAES256GCM &&
		header.Sequence > 0 && equalBytes(header.SessionID, state.sessionID) &&
		equalBytes(header.Nonce, expectedNonce)
}

// packetNonce derives a 12-byte AES-GCM nonce from the session epoch and
// the per-channel sequence. The session epoch guarantees that two sessions
// sharing the same key epoch never reuse a (key, nonce) pair; the 32-bit
// sequence suffix is bounded by maxSequence so it cannot wrap.
func packetNonce(sessionEpoch uint64, sequence uint64) []byte {
	nonce := make([]byte, 12)
	binary.BigEndian.PutUint64(nonce[:8], sessionEpoch)
	binary.BigEndian.PutUint32(nonce[8:], uint32(sequence))
	return nonce
}

func packetAAD(header PacketHeader) []byte {
	return transcript("vibescreen/secure-packet-header/v1", uint64Bytes(uint64(header.ProtocolVersion)),
		header.SessionID, uint64Bytes(header.SessionEpoch), []byte(header.KeyID),
		uint64Bytes(header.KeyEpoch), uint64Bytes(uint64(header.Channel)),
		uint64Bytes(uint64(header.SenderRole)), []byte(header.AeadAlgorithm),
		uint64Bytes(header.Sequence), header.Nonce)
}

type replayWindow struct {
	highest uint64
	bitmap  uint64
}

func (window *replayWindow) canAccept(sequence uint64) bool {
	if sequence == 0 {
		return false
	}
	if sequence > window.highest {
		return true
	}
	distance := window.highest - sequence
	return distance < replayWindowSize && window.bitmap&(uint64(1)<<distance) == 0
}

func (window *replayWindow) accept(sequence uint64) {
	if sequence > window.highest {
		shift := sequence - window.highest
		if shift >= replayWindowSize {
			window.bitmap = 0
		} else {
			window.bitmap <<= shift
		}
		window.highest = sequence
		window.bitmap |= 1
		return
	}
	window.bitmap |= uint64(1) << (window.highest - sequence)
}

func equalBytes(left, right []byte) bool {
	if len(left) != len(right) {
		return false
	}
	var difference byte
	for index := range left {
		difference |= left[index] ^ right[index]
	}
	return difference == 0
}
