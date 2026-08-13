package signaling

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
)

type revocationStateFile struct {
	RevokedDeviceIDs []string `json:"revoked_device_ids"`
}

func loadRevokedDevices(path string) (map[string]bool, error) {
	revoked := make(map[string]bool)
	contents, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return revoked, nil
	}
	if err != nil {
		return nil, fmt.Errorf("read signaling state: %w", err)
	}
	var state revocationStateFile
	decoder := json.NewDecoder(bytes.NewReader(contents))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&state); err != nil {
		return nil, fmt.Errorf("decode signaling state: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return nil, errors.New("signaling state must contain one JSON object")
	}
	for _, deviceID := range state.RevokedDeviceIDs {
		if !validIdentifier(deviceID) {
			return nil, errors.New("signaling state contains invalid device_id")
		}
		revoked[deviceID] = true
	}
	return revoked, nil
}

func persistRevokedDevices(path string, revoked map[string]bool) error {
	ids := make([]string, 0, len(revoked))
	for deviceID, denied := range revoked {
		if denied {
			ids = append(ids, deviceID)
		}
	}
	sort.Strings(ids)
	contents, err := json.Marshal(revocationStateFile{RevokedDeviceIDs: ids})
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
