package relay

import (
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/url"
	"os"
	"strings"
)

const (
	turnSecretEnv       = "VIBE_RELAY_TURN_SECRET"
	clientTokenEnv      = "VIBE_RELAY_CLIENT_TOKEN"
	usageTokenEnv       = "VIBE_RELAY_USAGE_TOKEN"
	metricsTokenEnv     = "VIBE_RELAY_METRICS_TOKEN"
	adminTokenEnv       = "VIBE_RELAY_ADMIN_TOKEN"
	terminationTokenEnv = "VIBE_RELAY_TERMINATION_TOKEN"
)

type Config struct {
	ListenAddress                       string   `json:"listen_address"`
	TurnRealm                           string   `json:"turn_realm"`
	TurnURIs                            []string `json:"turn_uris"`
	CredentialTTLSeconds                int64    `json:"credential_ttl_seconds"`
	MaxCredentialTTLSeconds             int64    `json:"max_credential_ttl_seconds"`
	CredentialRequestsPerMinute         int      `json:"credential_requests_per_minute"`
	MaxConcurrentSessionsPerDevice      int      `json:"max_concurrent_sessions_per_device"`
	DailyBytesPerDevice                 uint64   `json:"daily_bytes_per_device"`
	MaxUsageEventBytes                  uint64   `json:"max_usage_event_bytes"`
	EgressMicrocentsPerGibibyte         uint64   `json:"egress_microcents_per_gibibyte"`
	StateFile                           string   `json:"state_file"`
	AllocationTerminationWebhookURL     string   `json:"allocation_termination_webhook_url,omitempty"`
	AllocationTerminationTimeoutSeconds int64    `json:"allocation_termination_timeout_seconds,omitempty"`

	TurnSecret       string `json:"-"`
	ClientToken      string `json:"-"`
	UsageToken       string `json:"-"`
	MetricsToken     string `json:"-"`
	AdminToken       string `json:"-"`
	TerminationToken string `json:"-"`
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
	cfg.TurnSecret, err = loadSecret(turnSecretEnv)
	if err != nil {
		return Config{}, err
	}
	cfg.ClientToken, err = loadSecret(clientTokenEnv)
	if err != nil {
		return Config{}, err
	}
	cfg.UsageToken, err = loadSecret(usageTokenEnv)
	if err != nil {
		return Config{}, err
	}
	cfg.MetricsToken, err = loadSecret(metricsTokenEnv)
	if err != nil {
		return Config{}, err
	}
	cfg.AdminToken, err = loadSecret(adminTokenEnv)
	if err != nil {
		return Config{}, err
	}
	if cfg.AllocationTerminationWebhookURL != "" {
		cfg.TerminationToken, err = loadSecret(terminationTokenEnv)
		if err != nil {
			return Config{}, err
		}
	}
	if err := cfg.Validate(); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

func loadSecret(name string) (string, error) {
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
	if c.TurnRealm == "" {
		missing = append(missing, "turn_realm")
	}
	if len(c.TurnURIs) == 0 {
		missing = append(missing, "turn_uris")
	}
	if c.StateFile == "" {
		missing = append(missing, "state_file")
	}
	if c.TurnSecret == "" {
		missing = append(missing, turnSecretEnv)
	}
	if c.ClientToken == "" {
		missing = append(missing, clientTokenEnv)
	}
	if c.UsageToken == "" {
		missing = append(missing, usageTokenEnv)
	}
	if c.MetricsToken == "" {
		missing = append(missing, metricsTokenEnv)
	}
	if c.AdminToken == "" {
		missing = append(missing, adminTokenEnv)
	}
	if c.AllocationTerminationWebhookURL != "" && c.TerminationToken == "" {
		missing = append(missing, terminationTokenEnv)
	}
	if len(missing) > 0 {
		return fmt.Errorf("missing required configuration: %s", strings.Join(missing, ", "))
	}
	if len(c.TurnSecret) < 32 || len(c.ClientToken) < 32 || len(c.UsageToken) < 32 || len(c.MetricsToken) < 32 || len(c.AdminToken) < 32 || (c.AllocationTerminationWebhookURL != "" && len(c.TerminationToken) < 32) {
		return errors.New("TURN secret and API tokens must each contain at least 32 characters")
	}
	if c.AllocationTerminationWebhookURL == "" {
		if c.AllocationTerminationTimeoutSeconds != 0 {
			return errors.New("allocation termination timeout requires a webhook URL")
		}
	} else {
		endpoint, err := url.Parse(c.AllocationTerminationWebhookURL)
		if err != nil || endpoint.Host == "" || endpoint.User != nil || endpoint.RawQuery != "" || endpoint.Fragment != "" {
			return errors.New("allocation termination webhook must be an absolute URL without credentials, query, or fragment")
		}
		host := endpoint.Hostname()
		if endpoint.Scheme != "https" && !(endpoint.Scheme == "http" && (host == "localhost" || net.ParseIP(host).IsLoopback())) {
			return errors.New("allocation termination webhook must use HTTPS (HTTP is allowed only for loopback)")
		}
		if c.AllocationTerminationTimeoutSeconds < 1 || c.AllocationTerminationTimeoutSeconds > 30 {
			return errors.New("allocation termination timeout must be between 1 and 30 seconds")
		}
	}
	tokens := []string{c.ClientToken, c.UsageToken, c.MetricsToken, c.AdminToken}
	if c.TerminationToken != "" {
		tokens = append(tokens, c.TerminationToken)
	}
	for left := range tokens {
		for right := left + 1; right < len(tokens); right++ {
			if tokens[left] == tokens[right] {
				return errors.New("client, usage, metrics, admin, and termination API tokens must be different")
			}
		}
	}
	if c.CredentialTTLSeconds <= 0 || c.MaxCredentialTTLSeconds < c.CredentialTTLSeconds {
		return errors.New("credential TTL must be positive and no greater than maximum TTL")
	}
	if c.CredentialRequestsPerMinute <= 0 || c.MaxConcurrentSessionsPerDevice <= 0 {
		return errors.New("rate and concurrent-session limits must be positive")
	}
	if c.DailyBytesPerDevice == 0 || c.MaxUsageEventBytes == 0 {
		return errors.New("byte limits must be positive")
	}
	for _, uri := range c.TurnURIs {
		if !strings.HasPrefix(uri, "turn:") && !strings.HasPrefix(uri, "turns:") {
			return fmt.Errorf("unsupported TURN URI %q", uri)
		}
	}
	return nil
}
