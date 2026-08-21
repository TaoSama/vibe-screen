package security

import (
	"bytes"
	"errors"
	"testing"
)

func TestSecureChannelAuthenticatesHeaderAndRejectsReplay(t *testing.T) {
	keys := testSessionKeys()
	sender := mustChannel(t, keys, ChannelControl, SenderHost)
	receiver := mustChannel(t, keys, ChannelControl, SenderHost)
	packet, err := sender.Seal([]byte("control message"))
	if err != nil {
		t.Fatal(err)
	}
	plaintext, err := receiver.Open(packet)
	if err != nil || !bytes.Equal(plaintext, []byte("control message")) {
		t.Fatalf("open failed: %q, %v", plaintext, err)
	}
	if _, err := receiver.Open(packet); !errors.Is(err, ErrReplay) {
		t.Fatalf("expected replay rejection, got %v", err)
	}
}

func TestSecureChannelDoesNotConsumeSequenceBeforeAuthentication(t *testing.T) {
	keys := testSessionKeys()
	sender := mustChannel(t, keys, ChannelControl, SenderDevice)
	receiver := mustChannel(t, keys, ChannelControl, SenderDevice)
	packet, err := sender.Seal([]byte("input"))
	if err != nil {
		t.Fatal(err)
	}
	tampered := packet
	tampered.Ciphertext = append([]byte(nil), packet.Ciphertext...)
	tampered.Ciphertext[0] ^= 0x80
	if _, err := receiver.Open(tampered); err == nil {
		t.Fatal("tampered ciphertext was accepted")
	}
	if _, err := receiver.Open(packet); err != nil {
		t.Fatalf("valid packet rejected after forged packet: %v", err)
	}
}

func TestSecureChannelAuthenticatesEveryHeaderField(t *testing.T) {
	keys := testSessionKeys()
	sender := mustChannel(t, keys, ChannelControl, SenderHost)
	packet, err := sender.Seal([]byte("authenticated"))
	if err != nil {
		t.Fatal(err)
	}
	tests := map[string]func(*PacketHeader){
		"protocol":  func(header *PacketHeader) { header.ProtocolVersion++ },
		"session":   func(header *PacketHeader) { header.SessionID[0] ^= 1 },
		"epoch":     func(header *PacketHeader) { header.SessionEpoch++ },
		"key id":    func(header *PacketHeader) { header.KeyID += "x" },
		"key epoch": func(header *PacketHeader) { header.KeyEpoch++ },
		"channel":   func(header *PacketHeader) { header.Channel = ChannelMedia },
		"role":      func(header *PacketHeader) { header.SenderRole = SenderDevice },
		"algorithm": func(header *PacketHeader) { header.AeadAlgorithm = "unknown" },
		"sequence":  func(header *PacketHeader) { header.Sequence++ },
		"nonce":     func(header *PacketHeader) { header.Nonce[0] ^= 1 },
	}
	for name, mutate := range tests {
		t.Run(name, func(t *testing.T) {
			receiver := mustChannel(t, keys, ChannelControl, SenderHost)
			tampered := packet
			tampered.Header.SessionID = append([]byte(nil), packet.Header.SessionID...)
			tampered.Header.Nonce = append([]byte(nil), packet.Header.Nonce...)
			mutate(&tampered.Header)
			if _, err := receiver.Open(tampered); err == nil {
				t.Fatal("tampered header was accepted")
			}
		})
	}
}

func TestSecureChannelSeparatesDirectionChannelAndEpoch(t *testing.T) {
	keys := testSessionKeys()
	hostControl := mustChannel(t, keys, ChannelControl, SenderHost)
	packet, err := hostControl.Seal([]byte("secret"))
	if err != nil {
		t.Fatal(err)
	}
	for name, receiver := range map[string]*SecureChannelState{
		"direction": mustChannel(t, keys, ChannelControl, SenderDevice),
		"channel":   mustChannel(t, keys, ChannelMedia, SenderHost),
	} {
		if _, err := receiver.Open(packet); !errors.Is(err, ErrInvalidPacket) {
			t.Errorf("%s mismatch: expected invalid packet, got %v", name, err)
		}
	}
	wrongEpoch, err := NewSecureChannel(make([]byte, 16), 2, keys, ChannelControl, SenderHost)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := wrongEpoch.Open(packet); !errors.Is(err, ErrInvalidPacket) {
		t.Fatalf("expected old epoch rejection, got %v", err)
	}
	rotatedKeys := keys
	rotatedKeys.KeyEpoch++
	rotatedKeys.KeyID = "test-key-rotated"
	wrongKeyEpoch := mustChannel(t, rotatedKeys, ChannelControl, SenderHost)
	if _, err := wrongKeyEpoch.Open(packet); !errors.Is(err, ErrInvalidPacket) {
		t.Fatalf("expected old key epoch rejection, got %v", err)
	}
}

func TestSecureChannelReplayWindowAllowsReorderingAndRejectsStale(t *testing.T) {
	keys := testSessionKeys()
	sender := mustChannel(t, keys, ChannelMedia, SenderHost)
	receiver := mustChannel(t, keys, ChannelMedia, SenderHost)
	packets := make([]EncryptedPacket, replayWindowSize+2)
	for index := range packets {
		var err error
		packets[index], err = sender.Seal([]byte{byte(index)})
		if err != nil {
			t.Fatal(err)
		}
	}
	if _, err := receiver.Open(packets[len(packets)-1]); err != nil {
		t.Fatal(err)
	}
	if _, err := receiver.Open(packets[len(packets)-2]); err != nil {
		t.Fatalf("recent out-of-order packet rejected: %v", err)
	}
	if _, err := receiver.Open(packets[0]); !errors.Is(err, ErrReplay) {
		t.Fatalf("expected stale packet rejection, got %v", err)
	}
}

func TestSecureControlChannelRejectsAuthenticatedOutOfOrderPacket(t *testing.T) {
	sender := mustChannel(t, testSessionKeys(), ChannelControl, SenderHost)
	receiver := mustChannel(t, testSessionKeys(), ChannelControl, SenderHost)
	first, err := sender.Seal([]byte("first"))
	if err != nil {
		t.Fatal(err)
	}
	second, err := sender.Seal([]byte("second"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := receiver.Open(second); err != nil {
		t.Fatalf("newer control packet rejected: %v", err)
	}
	if _, err := receiver.Open(first); !errors.Is(err, ErrReplay) {
		t.Fatalf("authenticated out-of-order control packet accepted: %v", err)
	}
}

func TestSecureChannelSequenceNeverWraps(t *testing.T) {
	state := mustChannel(t, testSessionKeys(), ChannelControl, SenderHost)
	state.sendSequence.Store(^uint64(0))
	if _, err := state.Seal([]byte("must not reuse nonce")); !errors.Is(err, ErrSequenceLimit) {
		t.Fatalf("expected permanent sequence exhaustion, got %v", err)
	}
	if _, err := state.Seal([]byte("still exhausted")); !errors.Is(err, ErrSequenceLimit) {
		t.Fatalf("sequence counter resumed after wrap: %v", err)
	}
}

func TestSecureChannelRejectsOutOfRangeSequenceBeforeNonceWrap(t *testing.T) {
	keys := testSessionKeys()
	sender := mustChannel(t, keys, ChannelMedia, SenderHost)
	receiver := mustChannel(t, keys, ChannelMedia, SenderHost)
	packet, err := sender.Seal([]byte("first"))
	if err != nil {
		t.Fatal(err)
	}

	tampered := packet
	tampered.Header.SessionID = append([]byte(nil), packet.Header.SessionID...)
	tampered.Header.Sequence = maxSequence + 2
	tampered.Header.Nonce = packetNonce(packet.Header.SessionEpoch, tampered.Header.Sequence)
	if !bytes.Equal(tampered.Header.Nonce, packet.Header.Nonce) {
		t.Fatalf("test setup error: expected wrapped nonce suffix, got %x and %x", tampered.Header.Nonce, packet.Header.Nonce)
	}
	if _, err := receiver.Open(tampered); !errors.Is(err, ErrInvalidPacket) {
		t.Fatalf("out-of-range sequence error=%v, want ErrInvalidPacket", err)
	}
	if _, err := receiver.Open(packet); err != nil {
		t.Fatalf("valid packet rejected after out-of-range sequence: %v", err)
	}
}

func TestSecureChannelNonceIncludesSessionEpoch(t *testing.T) {
	keys := testSessionKeys()
	first := mustChannel(t, keys, ChannelControl, SenderHost)
	second, err := NewSecureChannel(make([]byte, 16), 2, keys, ChannelControl, SenderHost)
	if err != nil {
		t.Fatal(err)
	}
	firstPacket, err := first.Seal([]byte("first"))
	if err != nil {
		t.Fatal(err)
	}
	secondPacket, err := second.Seal([]byte("second"))
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Equal(firstPacket.Header.Nonce, secondPacket.Header.Nonce) {
		t.Fatalf("sessions sharing a key must not reuse a nonce: %x", firstPacket.Header.Nonce)
	}
	if firstPacket.Header.SessionEpoch == secondPacket.Header.SessionEpoch {
		t.Fatal("test setup error: session epochs must differ")
	}
}

func mustChannel(t *testing.T, keys SessionKeys, channel Channel, role SenderRole) *SecureChannelState {
	t.Helper()
	state, err := NewSecureChannel(make([]byte, 16), 1, keys, channel, role)
	if err != nil {
		t.Fatal(err)
	}
	return state
}

func testSessionKeys() SessionKeys {
	keys := SessionKeys{KeyID: "test-key", KeyEpoch: 1}
	for index := range keys.HostControlKey {
		keys.HostControlKey[index] = byte(index + 1)
		keys.DeviceControlKey[index] = byte(index + 2)
		keys.HostMediaKey[index] = byte(index + 3)
		keys.DeviceMediaKey[index] = byte(index + 4)
	}
	return keys
}
