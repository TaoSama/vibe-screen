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
	RequestID      string                 `json:"request_id"`
	AccountID      string                 `json:"account_id"`
	HostDeviceID   string                 `json:"host_device_id"`
	ClientDeviceID string                 `json:"client_device_id"`
	SessionEpoch   uint64                 `json:"session_epoch"`
	TTLSeconds     int64                  `json:"ttl_seconds"`
	SessionProfile *SessionProfileRequest `json:"session_profile,omitempty"`
}

// authoritySignalingAdmission mirrors the authority service's SignalingAdmission.
type authoritySignalingAdmission struct {
	SessionID      string                  `json:"session_id"`
	HostToken      string                  `json:"host_token"`
	ClientToken    string                  `json:"client_token"`
	ExpiresAt      time.Time               `json:"expires_at"`
	Created        bool                    `json:"created"`
	SessionProfile *SessionProfileResponse `json:"session_profile,omitempty"`
}

type authoritySignalingAuthorization struct {
	Role      string    `json:"role"`
	ExpiresAt time.Time `json:"expires_at"`
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
		(response.status == http.StatusCreated) != admission.Created ||
		!validAuthoritySessionProfile(request, admission) {
		return authoritySignalingAdmission{}, fmt.Errorf("%w: incomplete admission", ErrAuthorityUnavailable)
	}
	return admission, nil
}

func validAuthoritySessionProfile(request authoritySignalingRequest, admission authoritySignalingAdmission) bool {
	if request.SessionProfile == nil {
		return admission.SessionProfile == nil
	}
	profile := admission.SessionProfile
	if profile == nil || profile.AccountID != request.AccountID ||
		profile.PairingID != request.SessionProfile.PairingID ||
		profile.SignalingSessionID != admission.SessionID ||
		profile.HostSignalingToken != admission.HostToken ||
		!profile.ExpiresAt.Equal(admission.ExpiresAt) ||
		profile.Created != admission.Created ||
		len(profile.UnsignedAndroidLease) == 0 || len(profile.UnsignedAndroidLease) > authorityMaxResponseBytes ||
		!json.Valid(profile.UnsignedAndroidLease) {
		return false
	}
	lease, ok := decodeAuthorityUnsignedAndroidLease(profile.UnsignedAndroidLease)
	if !ok {
		return false
	}
	return lease.Version == 1 &&
		lease.PairingID == request.SessionProfile.PairingID &&
		lease.PinnedHostID == request.HostDeviceID &&
		lease.PinnedDeviceID == request.ClientDeviceID &&
		lease.LeaseDeviceKeyID == request.SessionProfile.ClientIdentity.KeyID &&
		lease.SignalingURL == request.SessionProfile.SignalingURL &&
		lease.SignalingSessionID == admission.SessionID &&
		lease.SessionEpoch == request.SessionEpoch &&
		lease.HostIdentityEpoch == request.SessionProfile.HostIdentity.KeyEpoch &&
		lease.DeviceIdentityEpoch == request.SessionProfile.ClientIdentity.KeyEpoch &&
		lease.ExpiresAt == uint64(admission.ExpiresAt.Unix()) &&
		lease.TranscriptContext == request.SessionProfile.TranscriptContext &&
		lease.ProtocolSessionID == request.SessionProfile.ProtocolSessionID &&
		lease.SignalingToken == admission.ClientToken &&
		sameAuthorityICE(lease.ICEServers, request.SessionProfile.ICEServers) &&
		lease.AllowInsecureTesting == request.SessionProfile.AllowInsecureForTesting
}

func decodeAuthorityUnsignedAndroidLease(raw json.RawMessage) (authorityUnsignedAndroidLease, bool) {
	var root map[string]json.RawMessage
	if err := json.Unmarshal(raw, &root); err != nil || !sameJSONKeys(root, authorityUnsignedAndroidLeaseKeys) {
		return authorityUnsignedAndroidLease{}, false
	}
	if !sameICEKeys(root["ice_servers"]) {
		return authorityUnsignedAndroidLease{}, false
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	var lease authorityUnsignedAndroidLease
	if err := decoder.Decode(&lease); err != nil {
		return authorityUnsignedAndroidLease{}, false
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return authorityUnsignedAndroidLease{}, false
	}
	return lease, true
}

func sameJSONKeys(root map[string]json.RawMessage, expected map[string]struct{}) bool {
	if len(root) != len(expected) {
		return false
	}
	for key := range root {
		if _, ok := expected[key]; !ok {
			return false
		}
	}
	return true
}

func sameICEKeys(raw json.RawMessage) bool {
	var servers []map[string]json.RawMessage
	if err := json.Unmarshal(raw, &servers); err != nil || len(servers) == 0 {
		return false
	}
	for _, server := range servers {
		if !sameJSONKeys(server, authorityUnsignedAndroidLeaseICEKeys) {
			return false
		}
	}
	return true
}

func sameAuthorityICE(raw json.RawMessage, expected []LeaseICEServer) bool {
	if len(expected) == 0 {
		return false
	}
	var actual []LeaseICEServer
	if err := json.Unmarshal(raw, &actual); err != nil {
		return false
	}
	if len(actual) != len(expected) {
		return false
	}
	for i := range actual {
		if len(actual[i].URLs) != len(expected[i].URLs) ||
			!sameOptionalString(actual[i].Username, expected[i].Username) ||
			!sameOptionalString(actual[i].Credential, expected[i].Credential) {
			return false
		}
		for j := range actual[i].URLs {
			if actual[i].URLs[j] != expected[i].URLs[j] {
				return false
			}
		}
	}
	return true
}

func sameOptionalString(left, right *string) bool {
	if left == nil || right == nil {
		return left == nil && right == nil
	}
	return *left == *right
}

type authorityUnsignedAndroidLease struct {
	Version              int             `json:"version"`
	PairingID            string          `json:"pairing_id"`
	PinnedHostID         string          `json:"pinned_host_id"`
	PinnedDeviceID       string          `json:"pinned_device_id"`
	LeaseDeviceKeyID     string          `json:"lease_device_key_id"`
	SignalingURL         string          `json:"signaling_url"`
	SignalingSessionID   string          `json:"signaling_session_id"`
	SessionEpoch         uint64          `json:"session_epoch"`
	HostIdentityEpoch    uint64          `json:"host_identity_epoch"`
	DeviceIdentityEpoch  uint64          `json:"device_identity_epoch"`
	ExpiresAt            uint64          `json:"expires_at"`
	TranscriptContext    string          `json:"transcript_context"`
	ProtocolSessionID    string          `json:"protocol_session_id"`
	SignalingToken       string          `json:"signaling_token"`
	ICEServers           json.RawMessage `json:"ice_servers"`
	AllowInsecureTesting bool            `json:"allow_insecure_for_testing"`
}

var authorityUnsignedAndroidLeaseKeys = map[string]struct{}{
	"version": {}, "pairing_id": {}, "pinned_host_id": {}, "pinned_device_id": {},
	"lease_device_key_id": {}, "signaling_url": {}, "signaling_session_id": {},
	"session_epoch": {}, "host_identity_epoch": {}, "device_identity_epoch": {},
	"expires_at": {}, "transcript_context": {}, "protocol_session_id": {},
	"signaling_token": {}, "ice_servers": {}, "allow_insecure_for_testing": {},
}

var authorityUnsignedAndroidLeaseICEKeys = map[string]struct{}{
	"urls": {}, "username": {}, "credential": {},
}

// AuthorizeRole asks the authority to validate a role token for a session.
// It returns the resolved role ("host" or "client"). A 404 or 403 from the
// authority means the token or session was definitively rejected and maps to
// ErrUnauthorized; any other non-2xx maps to ErrAuthorityUnavailable.
func (c *AuthorityClient) AuthorizeRole(ctx context.Context, sessionID, roleToken string) (authoritySignalingAuthorization, error) {
	ctx, cancel := context.WithTimeout(ctx, authorityRequestTimeout)
	defer cancel()
	if !validIdentifier(sessionID) || !validIdentifier(roleToken) {
		return authoritySignalingAuthorization{}, ErrUnauthorized
	}
	body, err := json.Marshal(map[string]string{"role_token": roleToken})
	if err != nil {
		return authoritySignalingAuthorization{}, fmt.Errorf("%w: encode request", ErrAuthorityUnavailable)
	}
	endpoint := c.baseURL.JoinPath("v1", "signaling", "sessions", url.PathEscape(sessionID), "authorize")
	authorityResponse, err := c.doRequest(ctx, http.MethodPost, endpoint.String(), body)
	if err != nil {
		return authoritySignalingAuthorization{}, err
	}
	switch authorityResponse.status {
	case http.StatusOK:
		var roleResponse authoritySignalingAuthorization
		if err := decodeStrictJSON(authorityResponse, &roleResponse); err != nil {
			return authoritySignalingAuthorization{}, fmt.Errorf("%w: invalid authorization response", ErrAuthorityUnavailable)
		}
		switch roleResponse.Role {
		case "host", "client":
			if !roleResponse.ExpiresAt.After(time.Now()) {
				return authoritySignalingAuthorization{}, fmt.Errorf("%w: incomplete authorization", ErrAuthorityUnavailable)
			}
			return roleResponse, nil
		default:
			return authoritySignalingAuthorization{}, fmt.Errorf("%w: unexpected role", ErrAuthorityUnavailable)
		}
	case http.StatusNotFound, http.StatusForbidden:
		// The authority definitively rejected the token or revoked the
		// session. Map to ErrUnauthorized so the signaling service returns
		// 404 without disclosing whether the session exists.
		return authoritySignalingAuthorization{}, ErrUnauthorized
	default:
		return authoritySignalingAuthorization{}, fmt.Errorf("%w: status %d", ErrAuthorityUnavailable, authorityResponse.status)
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

func invalidateAuthorityAdmission(authority *AuthorityClient, sessionID string) error {
	// This is a compensating rollback after authority admission has succeeded
	// but local commit failed. It must not inherit caller cancellation;
	// InvalidateSession still applies the bounded authority request timeout.
	return authority.InvalidateSession(context.Background(), sessionID)
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

func authoritySessionRequestID(sessionID string) string {
	return "authority-session-" + sessionID
}
