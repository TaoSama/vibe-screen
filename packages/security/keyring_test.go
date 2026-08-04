package security

import (
	"bytes"
	"crypto/rand"
	"errors"
	"sync"
	"testing"
	"time"
)

func TestKeyRotationRequiresCurrentAndNextKeyProof(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	authority := mustIdentity(t, "host", 1)
	current := mustIdentity(t, "device", 1)
	next := mustIdentity(t, "device", 2)
	keyring, err := NewKeyring(authority.Public())
	if err != nil {
		t.Fatal(err)
	}
	if err := keyring.Register(current.Public()); err != nil {
		t.Fatal(err)
	}
	if err := keyring.Register(next.Public()); !errors.Is(err, ErrInvalidKeyEpoch) {
		t.Fatalf("unsigned replacement bypassed rotation: %v", err)
	}
	nonce := make([]byte, 16)
	if _, err := rand.Read(nonce); err != nil {
		t.Fatal(err)
	}
	request, err := NewRotationRequest(authority.Public(), current, next, nonce, now)
	if err != nil {
		t.Fatal(err)
	}
	tampered := request
	tampered.NextKeySignature = append([]byte(nil), request.NextKeySignature...)
	tampered.NextKeySignature[0] ^= 0x80
	if err := keyring.Rotate(tampered, now); !errors.Is(err, ErrInvalidProof) {
		t.Fatalf("expected next-key proof rejection, got %v", err)
	}
	if err := keyring.Rotate(request, now); err != nil {
		t.Fatal(err)
	}
	if err := keyring.Authorize(current.public.DeviceID, current.public.KeyID); !errors.Is(err, ErrInvalidKeyEpoch) {
		t.Fatalf("old key remains authorized: %v", err)
	}
	if err := keyring.Authorize(next.public.DeviceID, next.public.KeyID); err != nil {
		t.Fatalf("rotated key not authorized: %v", err)
	}
}

func TestKeyRotationTranscriptIsBoundToAuthority(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	authority := mustIdentity(t, "host-a", 1)
	otherAuthority := mustIdentity(t, "host-b", 1)
	current := mustIdentity(t, "device", 1)
	next := mustIdentity(t, "device", 2)
	request, err := NewRotationRequest(authority.Public(), current, next, bytes.Repeat([]byte{1}, 16), now)
	if err != nil {
		t.Fatal(err)
	}
	otherKeyring, err := NewKeyring(otherAuthority.Public())
	if err != nil {
		t.Fatal(err)
	}
	if err := otherKeyring.Register(current.Public()); err != nil {
		t.Fatal(err)
	}
	if err := otherKeyring.Rotate(request, now); !errors.Is(err, ErrAuthorityMismatch) {
		t.Fatalf("rotation proof transferred to a different authority: %v", err)
	}
}

func TestRotationNonceReuseIsRejectedAfterPersistenceRestore(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	authority := mustIdentity(t, "host", 1)
	current := mustIdentity(t, "device", 1)
	next := mustIdentity(t, "device", 2)
	afterNext := mustIdentity(t, "device", 3)
	keyring, err := NewKeyring(authority.Public())
	if err != nil {
		t.Fatal(err)
	}
	if err := keyring.Register(current.Public()); err != nil {
		t.Fatal(err)
	}
	nonce := bytes.Repeat([]byte{2}, 16)
	first, err := NewRotationRequest(authority.Public(), current, next, nonce, now)
	if err != nil {
		t.Fatal(err)
	}
	if err := keyring.Rotate(first, now); err != nil {
		t.Fatal(err)
	}
	restored, err := NewKeyringFromState(keyring.Snapshot())
	if err != nil {
		t.Fatal(err)
	}
	replayedNonce, err := NewRotationRequest(authority.Public(), next, afterNext, nonce, now)
	if err != nil {
		t.Fatal(err)
	}
	if err := restored.Rotate(replayedNonce, now); !errors.Is(err, ErrRotationNonceReuse) {
		t.Fatalf("persisted rotation nonce was reusable: %v", err)
	}
}

func TestConcurrentRotationNonceReuseHasSingleWinner(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	authority := mustIdentity(t, "host", 1)
	keyring, err := NewKeyring(authority.Public())
	if err != nil {
		t.Fatal(err)
	}
	nonce := bytes.Repeat([]byte{3}, 16)
	requests := make([]RotationRequest, 2)
	for index, deviceID := range []string{"device-a", "device-b"} {
		current := mustIdentity(t, deviceID, 1)
		next := mustIdentity(t, deviceID, 2)
		if err := keyring.Register(current.Public()); err != nil {
			t.Fatal(err)
		}
		requests[index], err = NewRotationRequest(authority.Public(), current, next, nonce, now)
		if err != nil {
			t.Fatal(err)
		}
	}
	results := make(chan error, len(requests))
	var wait sync.WaitGroup
	for _, request := range requests {
		wait.Add(1)
		go func(candidate RotationRequest) {
			defer wait.Done()
			results <- keyring.Rotate(candidate, now)
		}(request)
	}
	wait.Wait()
	close(results)
	var successes, reuses int
	for result := range results {
		switch {
		case result == nil:
			successes++
		case errors.Is(result, ErrRotationNonceReuse):
			reuses++
		default:
			t.Fatalf("unexpected concurrent rotation result: %v", result)
		}
	}
	if successes != 1 || reuses != 1 {
		t.Fatalf("expected one rotation and one nonce rejection, got success=%d reuse=%d", successes, reuses)
	}
}

func TestRevocationIsSignedMonotonicAndFinal(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	authority := mustIdentity(t, "host", 1)
	device := mustIdentity(t, "device", 1)
	keyring, err := NewKeyring(authority.Public())
	if err != nil {
		t.Fatal(err)
	}
	if err := keyring.Register(device.Public()); err != nil {
		t.Fatal(err)
	}
	nonce := make([]byte, 16)
	if _, err := rand.Read(nonce); err != nil {
		t.Fatal(err)
	}
	revocation, err := NewRevocation(authority, device.public.DeviceID, device.public.KeyID, "user_requested", 1, now, nonce)
	if err != nil {
		t.Fatal(err)
	}
	tampered := revocation
	tampered.ReasonCode = "different_reason"
	if err := keyring.Revoke(tampered); !errors.Is(err, ErrInvalidProof) {
		t.Fatalf("expected signed reason rejection, got %v", err)
	}
	if err := keyring.Revoke(revocation); err != nil {
		t.Fatal(err)
	}
	if err := keyring.Authorize(device.public.DeviceID, device.public.KeyID); !errors.Is(err, ErrDeviceRevoked) {
		t.Fatalf("revoked device authorized: %v", err)
	}
	if err := keyring.Register(mustIdentity(t, "device", 2).Public()); !errors.Is(err, ErrDeviceRevoked) {
		t.Fatalf("revoked identity re-registered: %v", err)
	}
	if err := keyring.Revoke(revocation); !errors.Is(err, ErrRevocationOrder) {
		t.Fatalf("replayed revocation accepted: %v", err)
	}
}

func TestRevocationSequenceIsAuthorityGlobalAndPersistent(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	authority := mustIdentity(t, "host", 1)
	first := mustIdentity(t, "device-a", 1)
	second := mustIdentity(t, "device-b", 1)
	keyring, err := NewKeyring(authority.Public())
	if err != nil {
		t.Fatal(err)
	}
	for _, identity := range []*Identity{first, second} {
		if err := keyring.Register(identity.Public()); err != nil {
			t.Fatal(err)
		}
	}
	newer, err := NewRevocation(authority, first.public.DeviceID, first.public.KeyID, "user_requested", 2, now, bytes.Repeat([]byte{4}, 16))
	if err != nil {
		t.Fatal(err)
	}
	if err := keyring.Revoke(newer); err != nil {
		t.Fatal(err)
	}
	restored, err := NewKeyringFromState(keyring.Snapshot())
	if err != nil {
		t.Fatal(err)
	}
	olderForAnotherDevice, err := NewRevocation(authority, second.public.DeviceID, second.public.KeyID, "user_requested", 1, now, bytes.Repeat([]byte{5}, 16))
	if err != nil {
		t.Fatal(err)
	}
	if err := restored.Revoke(olderForAnotherDevice); !errors.Is(err, ErrRevocationOrder) {
		t.Fatalf("authority-global revocation sequence reset per device or process: %v", err)
	}
}

func TestConcurrentRevocationsCannotReuseAuthoritySequence(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	authority := mustIdentity(t, "host", 1)
	keyring, err := NewKeyring(authority.Public())
	if err != nil {
		t.Fatal(err)
	}
	revocations := make([]Revocation, 2)
	for index, deviceID := range []string{"device-a", "device-b"} {
		device := mustIdentity(t, deviceID, 1)
		if err := keyring.Register(device.Public()); err != nil {
			t.Fatal(err)
		}
		revocations[index], err = NewRevocation(authority, device.public.DeviceID, device.public.KeyID,
			"user_requested", 1, now, bytes.Repeat([]byte{byte(6 + index)}, 16))
		if err != nil {
			t.Fatal(err)
		}
	}
	results := make(chan error, len(revocations))
	var wait sync.WaitGroup
	for _, revocation := range revocations {
		wait.Add(1)
		go func(candidate Revocation) {
			defer wait.Done()
			results <- keyring.Revoke(candidate)
		}(revocation)
	}
	wait.Wait()
	close(results)
	var successes, orderFailures int
	for result := range results {
		switch {
		case result == nil:
			successes++
		case errors.Is(result, ErrRevocationOrder):
			orderFailures++
		default:
			t.Fatalf("unexpected concurrent revocation result: %v", result)
		}
	}
	if successes != 1 || orderFailures != 1 {
		t.Fatalf("expected one revocation and one order rejection, got success=%d order=%d", successes, orderFailures)
	}
}
