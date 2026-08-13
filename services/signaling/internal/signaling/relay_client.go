package signaling

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type relayClient interface {
	Credentials(context.Context, string, string, int64) (*TurnCredentials, error)
	Revoke(context.Context, string) error
}

type httpRelayClient struct {
	baseURL, clientToken, adminToken string
	client                           *http.Client
}

type disabledRelayClient struct{}

func newRelayClient(cfg Config) relayClient {
	if cfg.RelayBaseURL == "" {
		return disabledRelayClient{}
	}
	return &httpRelayClient{baseURL: strings.TrimRight(cfg.RelayBaseURL, "/"), clientToken: cfg.RelayClientToken,
		adminToken: cfg.RelayAdminToken, client: &http.Client{Timeout: 5 * time.Second}}
}

func (disabledRelayClient) Credentials(context.Context, string, string, int64) (*TurnCredentials, error) {
	return nil, nil
}

func (disabledRelayClient) Revoke(context.Context, string) error { return nil }

func (c *httpRelayClient) Credentials(ctx context.Context, deviceID, sessionID string, ttlSeconds int64) (*TurnCredentials, error) {
	body, err := json.Marshal(map[string]any{"device_id": deviceID, "session_id": sessionID, "ttl_seconds": ttlSeconds})
	if err != nil {
		return nil, err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/v1/credentials", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	request.Header.Set("Authorization", "Bearer "+c.clientToken)
	request.Header.Set("Content-Type", "application/json")
	response, err := c.client.Do(request)
	if err != nil {
		return nil, fmt.Errorf("relay credentials request: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, 4096))
		return nil, fmt.Errorf("relay credentials status %d", response.StatusCode)
	}
	var credentials TurnCredentials
	decoder := json.NewDecoder(io.LimitReader(response.Body, 64*1024))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&credentials); err != nil {
		return nil, fmt.Errorf("decode relay credentials: %w", err)
	}
	if credentials.Username == "" || credentials.Password == "" || credentials.TTLSeconds <= 0 || credentials.Realm == "" || len(credentials.URIs) == 0 {
		return nil, errors.New("relay returned incomplete credentials")
	}
	return &credentials, nil
}

func (c *httpRelayClient) Revoke(ctx context.Context, deviceID string) error {
	request, err := http.NewRequestWithContext(ctx, http.MethodPost,
		c.baseURL+"/v1/devices/"+url.PathEscape(deviceID)+"/revoke", strings.NewReader("{}"))
	if err != nil {
		return err
	}
	request.Header.Set("Authorization", "Bearer "+c.adminToken)
	request.Header.Set("Content-Type", "application/json")
	response, err := c.client.Do(request)
	if err != nil {
		return fmt.Errorf("relay revoke request: %w", err)
	}
	defer response.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, 4096))
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("relay revoke status %d", response.StatusCode)
	}
	return nil
}
