package relay

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const (
	authorityRequestTimeout  = 10 * time.Second
	authorityMaxResponseSize = 64 * 1024
)

var ErrAuthorityUnavailable = errors.New("authority service unavailable")

type relayAuthority interface {
	AdmitRelay(context.Context, relayAdmissionRequest) error
	Ready(context.Context) error
}

type relayAdmissionRequest struct {
	DeviceID     string `json:"device_id"`
	SessionID    string `json:"session_id"`
	AllocationID string `json:"allocation_id"`
	SourceID     string `json:"source_id"`
}

type AuthorityClient struct {
	baseURL    *url.URL
	token      string
	httpClient *http.Client
}

func NewAuthorityClient(rawBaseURL, token string) (*AuthorityClient, error) {
	baseURL, err := parseAuthorityURL(rawBaseURL)
	if err != nil {
		return nil, err
	}
	if len(token) < 32 {
		return nil, errors.New("authority token must contain at least 32 characters")
	}
	return &AuthorityClient{
		baseURL: baseURL,
		token:   token,
		httpClient: &http.Client{
			Timeout: authorityRequestTimeout,
			CheckRedirect: func(*http.Request, []*http.Request) error {
				return errors.New("authority redirects are not permitted")
			},
		},
	}, nil
}

func parseAuthorityURL(raw string) (*url.URL, error) {
	parsed, err := url.Parse(raw)
	if err != nil {
		return nil, fmt.Errorf("invalid authority URL: %w", err)
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return nil, errors.New("authority URL scheme must be https or loopback http")
	}
	if parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" {
		return nil, errors.New("authority URL must not contain userinfo, query, or fragment")
	}
	if parsed.Path != "" && parsed.Path != "/" {
		return nil, errors.New("authority URL must not contain a path")
	}
	if parsed.Host == "" {
		return nil, errors.New("authority URL must contain a host")
	}
	if parsed.Scheme == "http" && !isLoopbackHost(parsed.Hostname()) {
		return nil, errors.New("plaintext authority URL must use a loopback host")
	}
	parsed.Path = ""
	return parsed, nil
}

func isLoopbackHost(host string) bool {
	if strings.EqualFold(host, "localhost") {
		return true
	}
	address := net.ParseIP(host)
	return address != nil && address.IsLoopback()
}

func (c *AuthorityClient) AdmitRelay(ctx context.Context, request relayAdmissionRequest) error {
	ctx, cancel := context.WithTimeout(ctx, authorityRequestTimeout)
	defer cancel()
	body, err := json.Marshal(request)
	if err != nil {
		return fmt.Errorf("%w: encode relay admission", ErrAuthorityUnavailable)
	}
	endpoint := c.baseURL.JoinPath("v1", "relay", "admissions")
	status, responseBody, err := c.doRequest(ctx, http.MethodPost, endpoint.String(), body)
	if err != nil {
		return err
	}
	switch status {
	case http.StatusNoContent:
		if len(responseBody) != 0 {
			return fmt.Errorf("%w: unexpected admission body", ErrAuthorityUnavailable)
		}
		return nil
	case http.StatusForbidden, http.StatusNotFound:
		return ErrDeviceRevoked
	case http.StatusConflict:
		return ErrConflict
	case http.StatusTooManyRequests:
		return ErrQuotaExceeded
	default:
		return fmt.Errorf("%w: status %d", ErrAuthorityUnavailable, status)
	}
}

func (c *AuthorityClient) Ready(ctx context.Context) error {
	ctx, cancel := context.WithTimeout(ctx, authorityRequestTimeout)
	defer cancel()
	status, responseBody, err := c.doRequest(ctx, http.MethodGet, c.baseURL.JoinPath("readyz").String(), nil)
	if err != nil || status != http.StatusOK {
		return ErrAuthorityUnavailable
	}
	var response struct {
		Status string `json:"status"`
	}
	if err := json.Unmarshal(responseBody, &response); err != nil || response.Status != "ok" {
		return ErrAuthorityUnavailable
	}
	return nil
}

func (c *AuthorityClient) doRequest(ctx context.Context, method, endpoint string, body []byte) (int, []byte, error) {
	var reader io.Reader
	if body != nil {
		reader = bytes.NewReader(body)
	}
	req, err := http.NewRequestWithContext(ctx, method, endpoint, reader)
	if err != nil {
		return 0, nil, fmt.Errorf("%w: build request", ErrAuthorityUnavailable)
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return 0, nil, fmt.Errorf("%w: request failed", ErrAuthorityUnavailable)
	}
	raw, readErr := io.ReadAll(io.LimitReader(resp.Body, authorityMaxResponseSize+1))
	closeErr := resp.Body.Close()
	if readErr != nil {
		return 0, nil, fmt.Errorf("%w: read response", ErrAuthorityUnavailable)
	}
	if closeErr != nil {
		return 0, nil, fmt.Errorf("%w: close response", ErrAuthorityUnavailable)
	}
	if len(raw) > authorityMaxResponseSize {
		return 0, nil, fmt.Errorf("%w: response too large", ErrAuthorityUnavailable)
	}
	return resp.StatusCode, raw, nil
}
