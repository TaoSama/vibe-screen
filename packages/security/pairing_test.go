package security

import (
	"bytes"
	"crypto/rand"
	"errors"
	"sync"
	"testing"
	"time"
)

func TestPairingDerivesMatchingSeparatedKeysAndCredential(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	host := mustIdentity(t, "host", 1)
	device := mustIdentity(t, "device", 1)
	hostSession, err := NewHostPairingSession(host, now, time.Minute, rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	deviceSession, request, err := NewDevicePairingSession(device, hostSession.Offer(), now, rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	result, hostKeys, issuedCredential, err := hostSession.Accept(request, now)
	if err != nil {
		t.Fatal(err)
	}
	deviceKeys, receivedCredential, err := deviceSession.Complete(result)
	if err != nil {
		t.Fatal(err)
	}
	if hostKeys != deviceKeys {
		t.Fatal("host and device derived different session keys")
	}
	if !bytes.Equal(issuedCredential, receivedCredential) {
		t.Fatal("device credential did not decrypt")
	}
	if bytes.Equal(hostKeys.HostControlKey[:], hostKeys.DeviceControlKey[:]) ||
		bytes.Equal(hostKeys.HostControlKey[:], hostKeys.HostMediaKey[:]) ||
		bytes.Equal(hostKeys.HostMediaKey[:], hostKeys.DeviceMediaKey[:]) {
		t.Fatal("direction or channel keys were not separated")
	}
	if bytes.Contains(result.EncryptedCredential, issuedCredential) {
		t.Fatal("credential appears in ciphertext")
	}
}

func TestPairingRejectsExpiredWrongAndReusedOffer(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	hostSession, err := NewHostPairingSession(mustIdentity(t, "host", 1), now, time.Second, rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	_, _, err = NewDevicePairingSession(mustIdentity(t, "device", 1), hostSession.Offer(), now.Add(2*time.Second), rand.Reader)
	if !errors.Is(err, ErrExpiredOffer) {
		t.Fatalf("expected expired offer, got %v", err)
	}
	deviceSession, request, err := NewDevicePairingSession(mustIdentity(t, "device", 1), hostSession.Offer(), now, rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	wrong := cloneRequest(request)
	wrong.BootstrapMAC[0] ^= 0xff
	if _, _, _, err := hostSession.Accept(wrong, now); !errors.Is(err, ErrOfferMismatch) {
		t.Fatalf("expected credential rejection, got %v", err)
	}
	result, _, _, err := hostSession.Accept(request, now)
	if err != nil {
		t.Fatal(err)
	}
	result.EncryptedCredential[0] ^= 0xff
	if _, _, err := deviceSession.Complete(result); err == nil {
		t.Fatal("tampered pairing result was accepted")
	}
	if _, _, _, err := hostSession.Accept(request, now); !errors.Is(err, ErrOfferMismatch) {
		t.Fatalf("expected consumed offer rejection, got %v", err)
	}
}

func TestPairingOfferIsConsumedAtomically(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	hostSession, err := NewHostPairingSession(mustIdentity(t, "host", 1), now, time.Minute, rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	_, request, err := NewDevicePairingSession(mustIdentity(t, "device", 1), hostSession.Offer(), now, rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	var wait sync.WaitGroup
	results := make(chan error, 2)
	for range 2 {
		wait.Add(1)
		go func() {
			defer wait.Done()
			_, _, _, acceptErr := hostSession.Accept(request, now)
			results <- acceptErr
		}()
	}
	wait.Wait()
	close(results)
	successes := 0
	for result := range results {
		if result == nil {
			successes++
		}
	}
	if successes != 1 {
		t.Fatalf("expected one successful consumer, got %d", successes)
	}
}

func TestTrafficKeyRotationAdvancesEpochAndInvalidatesOldPackets(t *testing.T) {
	current := testSessionKeys()
	nonce := make([]byte, 16)
	if _, err := rand.Read(nonce); err != nil {
		t.Fatal(err)
	}
	next, err := RotateTrafficKeys(current, current.KeyEpoch+1, nonce)
	if err != nil {
		t.Fatal(err)
	}
	if next.KeyEpoch != 2 || next.KeyID == current.KeyID || bytes.Equal(next.HostControlKey[:], current.HostControlKey[:]) {
		t.Fatal("traffic key rotation did not create a fresh epoch")
	}
	oldSender := mustChannel(t, current, ChannelControl, SenderHost)
	newReceiver := mustChannel(t, next, ChannelControl, SenderHost)
	packet, err := oldSender.Seal([]byte("old epoch"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := newReceiver.Open(packet); !errors.Is(err, ErrInvalidPacket) {
		t.Fatalf("old epoch packet accepted after rotation: %v", err)
	}
	if _, err := RotateTrafficKeys(current, current.KeyEpoch+2, nonce); !errors.Is(err, ErrInvalidKeyEpoch) {
		t.Fatalf("skipped key epoch accepted: %v", err)
	}
}

func mustIdentity(t *testing.T, deviceID string, epoch uint64) *Identity {
	t.Helper()
	identity, err := GenerateIdentity(deviceID, epoch, rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	return identity
}
