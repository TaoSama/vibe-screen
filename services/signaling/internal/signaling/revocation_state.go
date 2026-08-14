package signaling

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

type durableRevocation struct {
	AuthorityDigest string `json:"authority_digest"`
	Sequence        uint64 `json:"sequence"`
	Digest          string `json:"digest"`
	NonceDigest     string `json:"nonce_digest"`
	RelayComplete   bool   `json:"relay_complete"`
}

type revocationStateFile struct {
	Revocations      map[string]durableRevocation `json:"revocations,omitempty"`
	MaximumSequences map[string]uint64            `json:"maximum_sequences,omitempty"`
	UsedNonceDigests []string                     `json:"used_nonce_digests,omitempty"`
	RevokedDeviceIDs []string                     `json:"revoked_device_ids,omitempty"` // legacy read only
}

type revocationState struct {
	revocations      map[string]durableRevocation
	maximumSequences map[string]uint64
	usedNonceDigests map[string]bool
}

func loadRevocationState(path string) (revocationState, error) {
	state := revocationState{revocations: make(map[string]durableRevocation), maximumSequences: make(map[string]uint64), usedNonceDigests: make(map[string]bool)}
	contents, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return state, nil
	}
	if err != nil {
		return state, fmt.Errorf("read signaling state: %w", err)
	}
	var wire revocationStateFile
	decoder := json.NewDecoder(bytes.NewReader(contents))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&wire); err != nil {
		return state, fmt.Errorf("decode signaling state: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return state, errors.New("signaling state must contain one JSON object")
	}
	if len(wire.RevokedDeviceIDs) > 0 {
		return state, errors.New("legacy unsigned revocation state must be migrated by a trusted authority")
	}
	for deviceID, record := range wire.Revocations {
		if !validIdentifier(deviceID) || record.AuthorityDigest == "" || record.Sequence == 0 || record.Digest == "" || record.NonceDigest == "" ||
			record.Sequence > uint64(^uint64(0)>>1) || record.Sequence > wire.MaximumSequences[record.AuthorityDigest] {
			return state, errors.New("signaling state contains invalid revocation")
		}
		state.revocations[deviceID] = record
	}
	for _, digest := range wire.UsedNonceDigests {
		if digest == "" || state.usedNonceDigests[digest] {
			return state, errors.New("signaling state contains invalid nonce digest")
		}
		state.usedNonceDigests[digest] = true
	}
	for authority, sequence := range wire.MaximumSequences {
		if authority == "" || sequence == 0 || sequence > uint64(^uint64(0)>>1) {
			return state, errors.New("signaling state contains invalid authority sequence")
		}
		state.maximumSequences[authority] = sequence
	}
	return state, nil
}

func persistRevocationState(path string, state revocationState) error {
	nonces := make([]string, 0, len(state.usedNonceDigests))
	for digest := range state.usedNonceDigests {
		nonces = append(nonces, digest)
	}
	sortStrings(nonces)
	contents, err := json.Marshal(revocationStateFile{Revocations: state.revocations,
		MaximumSequences: state.maximumSequences, UsedNonceDigests: nonces})
	if err != nil {
		return fmt.Errorf("encode signaling state: %w", err)
	}
	contents = append(contents, '\n')
	directory := filepath.Dir(path)
	if err := os.MkdirAll(directory, 0o700); err != nil {
		return fmt.Errorf("create signaling state directory: %w", err)
	}
	temporary, err := os.CreateTemp(directory, ".signaling-state-*")
	if err != nil {
		return fmt.Errorf("create signaling state temporary file: %w", err)
	}
	temporaryPath := temporary.Name()
	committed := false
	defer func() {
		_ = temporary.Close()
		if !committed {
			_ = os.Remove(temporaryPath)
		}
	}()
	if err := temporary.Chmod(0o600); err != nil {
		return fmt.Errorf("protect signaling state temporary file: %w", err)
	}
	if _, err := temporary.Write(contents); err != nil {
		return fmt.Errorf("write signaling state: %w", err)
	}
	if err := temporary.Sync(); err != nil {
		return fmt.Errorf("sync signaling state: %w", err)
	}
	if err := temporary.Close(); err != nil {
		return fmt.Errorf("close signaling state: %w", err)
	}
	if err := os.Rename(temporaryPath, path); err != nil {
		return fmt.Errorf("replace signaling state: %w", err)
	}
	committed = true
	directoryHandle, err := os.Open(directory)
	if err != nil {
		return fmt.Errorf("open signaling state directory: %w", err)
	}
	defer directoryHandle.Close()
	if err := directoryHandle.Sync(); err != nil {
		return fmt.Errorf("sync signaling state directory: %w", err)
	}
	return nil
}

func sortStrings(values []string) {
	for i := 1; i < len(values); i++ {
		for j := i; j > 0 && values[j] < values[j-1]; j-- {
			values[j], values[j-1] = values[j-1], values[j]
		}
	}
}
