package signaling

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
	"time"
)

const (
	issuerTokenEnv  = "VIBE_SIGNALING_ISSUER_TOKEN"
	metricsTokenEnv = "VIBE_SIGNALING_METRICS_TOKEN"
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
	IssuerToken             string `json:"-"`
	MetricsToken            string `json:"-"`
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
	cfg.IssuerToken = os.Getenv(issuerTokenEnv)
	cfg.MetricsToken = os.Getenv(metricsTokenEnv)
	if err := cfg.Validate(); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

func (c Config) Validate() error {
	var missing []string
	if c.ListenAddress == "" {
		missing = append(missing, "listen_address")
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
	if c.SessionTTLSeconds <= 0 || c.MaxSessionTTLSeconds < c.SessionTTLSeconds {
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
