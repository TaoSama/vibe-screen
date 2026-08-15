package signaling

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"strings"
	"time"
)

const (
	issuerTokenEnv    = "VIBE_SIGNALING_ISSUER_TOKEN"
	metricsTokenEnv   = "VIBE_SIGNALING_METRICS_TOKEN"
	authorityTokenEnv = "VIBE_SIGNALING_AUTHORITY_TOKEN"

	// AuthorityModeLocalDevelopment keeps the historical in-process session
	// issuance and role-token authorization. It is intended only for local
	// self-tests and scripts; production must not use it.
	AuthorityModeLocalDevelopment = "local_development"
	// AuthorityModeProductionAuthority delegates session creation, per-request
	// role-token authorization, and session invalidation to the authority
	// service. Any authority failure is fail-closed: the signaling process
	// never falls back to locally minted tokens.
	AuthorityModeProductionAuthority = "production_authority"
)

type Config struct {
	ListenAddress           string `json:"listen_address"`
	SessionTTLSeconds       int64  `json:"session_ttl_seconds"`
	MaxSessionTTLSeconds    int64  `json:"max_session_ttl_seconds"`
	MaxActiveSessions       int    `json:"max_active_sessions"`
	SessionCreatesPerMinute int    `json:"session_creates_per_minute"`
	MessagesPerMinute       int    `json:"messages_per_minute"`
	MaxRequestBodyBytes     int64  `json:"max_request_body_bytes"`
	MaxSDPBytes             int    `json:"max_sdp_bytes"`
	MaxCandidateBytes       int    `json:"max_candidate_bytes"`
	MaxCandidatesPerRole    int    `json:"max_candidates_per_role"`
	MaxWaitSeconds          int    `json:"max_wait_seconds"`
	MaxWaitersPerRole       int    `json:"max_waiters_per_role"`
	CleanupIntervalSeconds  int    `json:"cleanup_interval_seconds"`
	AuthorityMode           string `json:"authority_mode"`
	AuthorityURL            string `json:"authority_url,omitempty"`
	IssuerToken             string `json:"-"`
	MetricsToken            string `json:"-"`
	AuthorityToken          string `json:"-"`
}

func LoadConfig(path string) (Config, error) {
	contents, err := os.ReadFile(path)
	if err != nil {
		return Config{}, fmt.Errorf("read config: %w", err)
	}
	var cfg Config
	decoder := json.NewDecoder(strings.NewReader(string(contents)))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&cfg); err != nil {
		return Config{}, fmt.Errorf("decode config: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); err == nil {
		return Config{}, errors.New("config must contain one JSON object")
	} else if !errors.Is(err, io.EOF) {
		return Config{}, fmt.Errorf("decode trailing config data: %w", err)
	}
	values := []struct {
		name        string
		destination *string
	}{
		{issuerTokenEnv, &cfg.IssuerToken},
		{metricsTokenEnv, &cfg.MetricsToken},
		{authorityTokenEnv, &cfg.AuthorityToken},
	}
	for _, value := range values {
		loaded, err := loadEnvironmentValue(value.name)
		if err != nil {
			return Config{}, err
		}
		*value.destination = loaded
	}
	if err := cfg.Validate(); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

func loadEnvironmentValue(name string) (string, error) {
	value := os.Getenv(name)
	fileVariable := name + "_FILE"
	path := os.Getenv(fileVariable)
	if value != "" && path != "" {
		return "", fmt.Errorf("%s and %s cannot both be set", name, fileVariable)
	}
	if path == "" {
		return value, nil
	}
	contents, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("read %s: %w", fileVariable, err)
	}
	return strings.TrimSpace(string(contents)), nil
}

func (c Config) Validate() error {
	var missing []string
	if c.ListenAddress == "" {
		missing = append(missing, "listen_address")
	}
	if c.AuthorityMode == "" {
		missing = append(missing, "authority_mode")
	}
	if c.IssuerToken == "" {
		missing = append(missing, issuerTokenEnv)
	}
	if c.MetricsToken == "" {
		missing = append(missing, metricsTokenEnv)
	}
	if len(missing) != 0 {
		return fmt.Errorf("missing required configuration: %s", strings.Join(missing, ", "))
	}
	if len(c.IssuerToken) < 32 || len(c.MetricsToken) < 32 {
		return errors.New("issuer and metrics tokens must each contain at least 32 characters")
	}
	if c.IssuerToken == c.MetricsToken {
		return errors.New("issuer and metrics tokens must be different")
	}
	switch c.AuthorityMode {
	case AuthorityModeLocalDevelopment:
		if c.AuthorityURL != "" || c.AuthorityToken != "" {
			return errors.New("local_development mode must not configure an authority URL or token")
		}
	case AuthorityModeProductionAuthority:
		if c.AuthorityURL == "" {
			return errors.New("authority_url is required when authority_mode is production_authority")
		}
		if c.AuthorityToken == "" {
			return fmt.Errorf("%s is required when authority_mode is production_authority", authorityTokenEnv)
		}
		if len(c.AuthorityToken) < 32 {
			return errors.New("authority token must contain at least 32 characters")
		}
		if _, err := parseAuthorityURL(c.AuthorityURL); err != nil {
			return fmt.Errorf("authority_url: %w", err)
		}
		if c.IssuerToken == c.AuthorityToken {
			return errors.New("issuer token must be distinct from authority token")
		}
	default:
		return fmt.Errorf("authority_mode must be %q or %q", AuthorityModeLocalDevelopment, AuthorityModeProductionAuthority)
	}
	if c.AuthorityToken != "" && c.AuthorityToken == c.MetricsToken {
		return errors.New("authority and metrics tokens must be different")
	}
	if c.SessionTTLSeconds <= 0 || c.MaxSessionTTLSeconds < c.SessionTTLSeconds ||
		c.MaxSessionTTLSeconds > math.MaxInt64/int64(time.Second) {
		return errors.New("session TTL must be positive and no greater than maximum TTL")
	}
	if c.MaxActiveSessions <= 0 || c.SessionCreatesPerMinute <= 0 || c.MessagesPerMinute <= 0 {
		return errors.New("session and rate limits must be positive")
	}
	if c.MaxRequestBodyBytes < 1024 || c.MaxSDPBytes <= 0 || c.MaxCandidateBytes <= 0 ||
		int64(c.MaxSDPBytes) > c.MaxRequestBodyBytes {
		return errors.New("request, SDP, and candidate byte limits are inconsistent")
	}
	if c.MaxCandidatesPerRole <= 0 || c.MaxWaitSeconds <= 0 || c.MaxWaitSeconds > 60 ||
		c.MaxWaitersPerRole <= 0 || c.CleanupIntervalSeconds <= 0 {
		return errors.New("candidate, wait, and cleanup limits must be positive; max wait cannot exceed 60 seconds")
	}
	return nil
}

func (c Config) SessionTTL() time.Duration {
	return time.Duration(c.SessionTTLSeconds) * time.Second
}

func (c Config) MaxSessionTTL() time.Duration {
	return time.Duration(c.MaxSessionTTLSeconds) * time.Second
}

func (c Config) CleanupInterval() time.Duration {
	return time.Duration(c.CleanupIntervalSeconds) * time.Second
}
