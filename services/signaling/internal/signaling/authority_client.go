package signaling

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
	// authorityMaxResponseBytes bounds every authority response body so a
	// malfunctioning or compromised authority cannot exhaust signaling memory.
	authorityMaxResponseBytes = 64 * 1024
	// authorityRequestTimeout bounds every outbound authority call.
	authorityRequestTimeout = 10 * time.Second
)

// ErrAuthorityUnavailable is returned when the authority service is
// unreachable, returns a server error, or returns a malformed response.
// Callers must treat it as fail-closed and never fall back to local token
// issuance.
var ErrAuthorityUnavailable = errors.New("authority service unavailable")

// authoritySignalingRequest mirrors the authority service's SignalingRequest.
type authoritySignalingRequest struct {
	RequestID      string `json:"request_id"`
	AccountID      string `json:"account_id"`
	HostDeviceID   string `json:"host_device_id"`
	ClientDeviceID string `json:"client_device_id"`
	SessionEpoch   uint64 `json:"session_epoch"`
	TTLSeconds     int64  `json:"ttl_seconds"`
}

// authoritySignalingAdmission mirrors the authority service's SignalingAdmission.
type authoritySignalingAdmission struct {
	SessionID   string    `json:"session_id"`
	HostToken   string    `json:"host_token"`
	ClientToken string    `json:"client_token"`
	ExpiresAt   time.Time `json:"expires_at"`
	Created     bool      `json:"created"`
}

// AuthorityClient is the strict HTTP client used to delegate session
// lifecycle decisions to the authority service. It enforces a safe URL
// policy, bounded responses, strict JSON decoding, and never includes
// secrets in returned errors.
type AuthorityClient struct {
	baseURL    *url.URL
	token      string
	httpClient *http.Client
}

type authorityHTTPResponse struct {
	body        []byte
	contentType string
	status      int
}

// NewAuthorityClient constructs an AuthorityClient. Production traffic uses
// HTTPS; plaintext HTTP is accepted only for a loopback development endpoint.
func NewAuthorityClient(rawBaseURL, token string) (*AuthorityClient, error) {
	base, err := parseAuthorityURL(rawBaseURL)
	if err != nil {
		return nil, err
	}
	if len(token) < 32 {
		return nil, errors.New("authority token must contain at least 32 characters")
	}
	return &AuthorityClient{
		baseURL: base,
		token:   token,
		httpClient: &http.Client{
			Timeout: authorityRequestTimeout,
			CheckRedirect: func(req *http.Request, via []*http.Request) error {
				// Reject all redirects. The authority endpoint must be reached
				// directly; a redirect could be used to exfiltrate the bearer
				// token or to downgrade to an unsafe scheme.
				return errors.New("authority redirects are not permitted")
			},
		},
	}, nil
}

// parseAuthorityURL validates that the authority base URL is safe to call.
func parseAuthorityURL(raw string) (*url.URL, error) {
	parsed, err := url.Parse(raw)
	if err != nil {
		return nil, fmt.Errorf("invalid URL: %w", err)
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return nil, errors.New("scheme must be https or loopback http")
	}
	if parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" {
		return nil, errors.New("URL must not contain userinfo, query, or fragment")
	}
	if parsed.Path != "" && parsed.Path != "/" {
		return nil, errors.New("URL must not contain a path")
	}
	if parsed.Host == "" {
		return nil, errors.New("URL must contain a host")
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

// CreateSession asks the authority to create (or idempotently replay) a
// signaling session. On any authority failure it returns ErrAuthorityUnavailable.
func (c *AuthorityClient) CreateSession(ctx context.Context, request authoritySignalingRequest) (authoritySignalingAdmission, error) {
	ctx, cancel := context.WithTimeout(ctx, authorityRequestTimeout)
	defer cancel()
	body, err := json.Marshal(request)
	if err != nil {
		return authoritySignalingAdmission{}, fmt.Errorf("%w: encode request", ErrAuthorityUnavailable)
	}
	endpoint := c.baseURL.JoinPath("v1", "signaling", "sessions")
	var admission authoritySignalingAdmission
	response, err := c.doRequest(ctx, http.MethodPost, endpoint.String(), body)
	if err != nil {
		return authoritySignalingAdmission{}, err
	}
	switch response.status {
	case http.StatusOK, http.StatusCreated:
	case http.StatusForbidden, http.StatusNotFound:
		return authoritySignalingAdmission{}, ErrUnauthorized
	case http.StatusConflict:
		return authoritySignalingAdmission{}, ErrConflict
	case http.StatusTooManyRequests:
		return authoritySignalingAdmission{}, ErrRateLimited
	default:
		return authoritySignalingAdmission{}, fmt.Errorf("%w: status %d", ErrAuthorityUnavailable, response.status)
	}
	if err := decodeStrictJSON(response, &admission); err != nil {
		return authoritySignalingAdmission{}, fmt.Errorf("%w: invalid admission response", ErrAuthorityUnavailable)
	}
	if !validIdentifier(admission.SessionID) || !validIdentifier(admission.HostToken) ||
		!validIdentifier(admission.ClientToken) || admission.HostToken == admission.ClientToken ||
		!admission.ExpiresAt.After(time.Now()) ||
		(response.status == http.StatusCreated) != admission.Created {
		return authoritySignalingAdmission{}, fmt.Errorf("%w: incomplete admission", ErrAuthorityUnavailable)
	}
	return admission, nil
}

// AuthorizeRole asks the authority to validate a role token for a session.
// It returns the resolved role ("host" or "client"). A 404 or 403 from the
// authority means the token or session was definitively rejected and maps to
// ErrUnauthorized; any other non-2xx maps to ErrAuthorityUnavailable.
func (c *AuthorityClient) AuthorizeRole(ctx context.Context, sessionID, roleToken string) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, authorityRequestTimeout)
	defer cancel()
	if !validIdentifier(sessionID) || !validIdentifier(roleToken) {
		return "", ErrUnauthorized
	}
	body, err := json.Marshal(map[string]string{"role_token": roleToken})
	if err != nil {
		return "", fmt.Errorf("%w: encode request", ErrAuthorityUnavailable)
	}
	endpoint := c.baseURL.JoinPath("v1", "signaling", "sessions", url.PathEscape(sessionID), "authorize")
	authorityResponse, err := c.doRequest(ctx, http.MethodPost, endpoint.String(), body)
	if err != nil {
		return "", err
	}
	switch authorityResponse.status {
	case http.StatusOK:
		var roleResponse struct {
			Role string `json:"role"`
		}
		if err := decodeStrictJSON(authorityResponse, &roleResponse); err != nil {
			return "", fmt.Errorf("%w: invalid authorization response", ErrAuthorityUnavailable)
		}
		switch roleResponse.Role {
		case "host", "client":
			return roleResponse.Role, nil
		default:
			return "", fmt.Errorf("%w: unexpected role", ErrAuthorityUnavailable)
		}
	case http.StatusNotFound, http.StatusForbidden:
		// The authority definitively rejected the token or revoked the
		// session. Map to ErrUnauthorized so the signaling service returns
		// 404 without disclosing whether the session exists.
		return "", ErrUnauthorized
	default:
		return "", fmt.Errorf("%w: status %d", ErrAuthorityUnavailable, authorityResponse.status)
	}
}

// InvalidateSession asks the authority to revoke a signaling session.
func (c *AuthorityClient) InvalidateSession(ctx context.Context, sessionID string) error {
	ctx, cancel := context.WithTimeout(ctx, authorityRequestTimeout)
	defer cancel()
	if !validIdentifier(sessionID) {
		return fmt.Errorf("%w: invalid session id", ErrAuthorityUnavailable)
	}
	endpoint := c.baseURL.JoinPath("v1", "signaling", "sessions", url.PathEscape(sessionID))
	response, err := c.doRequest(ctx, http.MethodDelete, endpoint.String(), nil)
	if err != nil {
		return err
	}
	// A missing admission is already invalid from the authority's point of
	// view. Treat it as an idempotent success so the signaling process still
	// destroys any stale local routing state.
	if response.status == http.StatusNotFound {
		return nil
	}
	if response.status != http.StatusNoContent || len(response.body) != 0 {
		return fmt.Errorf("%w: status %d", ErrAuthorityUnavailable, response.status)
	}
	return nil
}

// Ready verifies that the authority storage and schema are ready. It returns
// no dependency details to the signaling readiness endpoint.
func (c *AuthorityClient) Ready(ctx context.Context) error {
	ctx, cancel := context.WithTimeout(ctx, authorityRequestTimeout)
	defer cancel()
	response, err := c.doRequest(ctx, http.MethodGet, c.baseURL.JoinPath("readyz").String(), nil)
	if err != nil || response.status != http.StatusOK {
		return ErrAuthorityUnavailable
	}
	var status struct {
		Status string `json:"status"`
	}
	if err := decodeStrictJSON(response, &status); err != nil || status.Status != "ok" {
		return ErrAuthorityUnavailable
	}
	return nil
}

// doRequest performs an HTTP request against the authority and returns the
// bounded response body and status code. Secrets are never included in
// returned errors.
func (c *AuthorityClient) doRequest(ctx context.Context, method, endpoint string, body []byte) (authorityHTTPResponse, error) {
	var bodyReader io.Reader
	if body != nil {
		bodyReader = bytes.NewReader(body)
	}
	req, err := http.NewRequestWithContext(ctx, method, endpoint, bodyReader)
	if err != nil {
		return authorityHTTPResponse{}, fmt.Errorf("%w: build request", ErrAuthorityUnavailable)
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return authorityHTTPResponse{}, fmt.Errorf("%w: request failed", ErrAuthorityUnavailable)
	}
	raw, err := io.ReadAll(io.LimitReader(resp.Body, authorityMaxResponseBytes+1))
	closeErr := resp.Body.Close()
	if err != nil {
		return authorityHTTPResponse{}, fmt.Errorf("%w: read response", ErrAuthorityUnavailable)
	}
	if closeErr != nil {
		return authorityHTTPResponse{}, fmt.Errorf("%w: close response", ErrAuthorityUnavailable)
	}
	if len(raw) > authorityMaxResponseBytes {
		return authorityHTTPResponse{}, fmt.Errorf("%w: response too large", ErrAuthorityUnavailable)
	}
	return authorityHTTPResponse{body: raw, contentType: resp.Header.Get("Content-Type"), status: resp.StatusCode}, nil
}

// decodeStrictJSON decodes a JSON object with strict field checking and
// rejects trailing data.
func decodeStrictJSON(response authorityHTTPResponse, destination any) error {
	contentType := strings.TrimSpace(strings.SplitN(response.contentType, ";", 2)[0])
	if contentType != "application/json" {
		return errors.New("response Content-Type must be application/json")
	}
	decoder := json.NewDecoder(bytes.NewReader(response.body))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return fmt.Errorf("decode response: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return errors.New("trailing response data")
	}
	return nil
}

// roleFromAuthority maps the authority's "client" role to signaling's
// "device" role. The authority's "host" role maps unchanged.
func roleFromAuthority(authorityRole string) (Role, error) {
	switch authorityRole {
	case "host":
		return RoleHost, nil
	case "client":
		return RoleDevice, nil
	default:
		return "", ErrAuthorityUnavailable
	}
}
