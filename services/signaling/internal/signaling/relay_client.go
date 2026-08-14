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

const maximumRelayResponseBytes = 64 * 1024

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
	contents, err := io.ReadAll(io.LimitReader(response.Body, maximumRelayResponseBytes+1))
	if err != nil || len(contents) > maximumRelayResponseBytes {
		return nil, errors.New("relay credentials response exceeds limit")
	}
	var credentials TurnCredentials
	decoder := json.NewDecoder(bytes.NewReader(contents))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&credentials); err != nil {
		return nil, fmt.Errorf("decode relay credentials: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return nil, errors.New("relay credentials response must contain one JSON object")
	}
	if credentials.Username == "" || len(credentials.Username) > 512 || credentials.Password == "" || len(credentials.Password) > 512 ||
		credentials.TTLSeconds <= 0 || credentials.TTLSeconds > ttlSeconds || credentials.Realm == "" || len(credentials.Realm) > 255 ||
		len(credentials.URIs) == 0 || len(credentials.URIs) > 16 {
		return nil, errors.New("relay returned incomplete credentials")
	}
	for _, rawURI := range credentials.URIs {
		parsed, err := url.Parse(rawURI)
		target := parsed.Host
		if target == "" {
			target = parsed.Opaque
		}
		if err != nil || (parsed.Scheme != "turn" && parsed.Scheme != "turns") || target == "" || parsed.User != nil || parsed.Fragment != "" {
			return nil, errors.New("relay returned invalid TURN URI")
		}
		if parsed.RawQuery != "" && parsed.RawQuery != "transport=udp" && parsed.RawQuery != "transport=tcp" {
			return nil, errors.New("relay returned invalid TURN URI query")
		}
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
	if response.StatusCode != http.StatusOK {
		_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, 4096))
		return fmt.Errorf("relay revoke status %d", response.StatusCode)
	}
	contents, err := io.ReadAll(io.LimitReader(response.Body, maximumRelayResponseBytes+1))
	if err != nil || len(contents) > maximumRelayResponseBytes {
		return errors.New("relay revoke response exceeds limit")
	}
	var result struct {
		Status                string `json:"status"`
		AllocationTermination string `json:"allocation_termination"`
		RevocationID          string `json:"revocation_id"`
	}
	decoder := json.NewDecoder(bytes.NewReader(contents))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&result); err != nil {
		return fmt.Errorf("decode relay revoke: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) || result.Status != "revoked" ||
		result.AllocationTermination != "acknowledged" || !validIdentifier(result.RevocationID) {
		return errors.New("relay revoke response is invalid")
	}
	return nil
}
