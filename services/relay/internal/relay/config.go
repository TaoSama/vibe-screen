package relay

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/url"
	"os"
	"strings"
	"time"
)

const (
	turnSecretEnv      = "VIBE_RELAY_TURN_SECRET"
	clientTokenEnv     = "VIBE_RELAY_CLIENT_TOKEN"
	usageTokenEnv      = "VIBE_RELAY_USAGE_TOKEN"
	metricsTokenEnv    = "VIBE_RELAY_METRICS_TOKEN"
	adminTokenEnv      = "VIBE_RELAY_ADMIN_TOKEN"
	authorityTokenEnv  = "VIBE_RELAY_AUTHORITY_TOKEN"
	databaseURLEnv     = "VIBE_RELAY_DATABASE_URL"
	databaseTLSModeEnv = "VIBE_RELAY_DATABASE_TLS_MODE"

	AuthorityModeLocal = "local_development"
	AuthorityModeProd  = "production_authority"

	storageBackendFile     = "file"
	storageBackendPostgres = "postgres"

	maxDurationSeconds                           = math.MaxInt64 / int64(time.Second)
	defaultMaximumDatabaseClockSkewSeconds int64 = 5
	maximumDatabaseClockSkewSeconds              = defaultMaximumDatabaseClockSkewSeconds
)

type Config struct {
	ListenAddress                   string   `json:"listen_address"`
	TurnRealm                       string   `json:"turn_realm"`
	TurnURIs                        []string `json:"turn_uris"`
	CredentialTTLSeconds            int64    `json:"credential_ttl_seconds"`
	MaxCredentialTTLSeconds         int64    `json:"max_credential_ttl_seconds"`
	CredentialRequestsPerMinute     int      `json:"credential_requests_per_minute"`
	MaxConcurrentSessionsPerDevice  int      `json:"max_concurrent_sessions_per_device"`
	DailyBytesPerDevice             uint64   `json:"daily_bytes_per_device"`
	MaxUsageEventBytes              uint64   `json:"max_usage_event_bytes"`
	EgressMicrocentsPerGibibyte     uint64   `json:"egress_microcents_per_gibibyte"`
	StorageBackend                  string   `json:"storage_backend,omitempty"`
	StateFile                       string   `json:"state_file"`
	AuthorityMode                   string   `json:"authority_mode,omitempty"`
	AuthorityURL                    string   `json:"authority_url,omitempty"`
	AuthoritySourceID               string   `json:"authority_source_id,omitempty"`
	AllocationRegistryFile          string   `json:"allocation_registry_file,omitempty"`
	MaximumDatabaseClockSkewSeconds int64    `json:"maximum_database_clock_skew_seconds,omitempty"`

	TurnSecret     string `json:"-"`
	ClientToken    string `json:"-"`
	UsageToken     string `json:"-"`
	MetricsToken   string `json:"-"`
	AdminToken     string `json:"-"`
	AuthorityToken string `json:"-"`
	DatabaseURL    string `json:"-"`
}

func LoadConfig(path string) (Config, error) {
	contents, err := os.ReadFile(path)
	if err != nil {
		return Config{}, fmt.Errorf("read config: %w", err)
	}
	cfg := Config{StorageBackend: storageBackendFile, MaximumDatabaseClockSkewSeconds: defaultMaximumDatabaseClockSkewSeconds}
	decoder := json.NewDecoder(strings.NewReader(string(contents)))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&cfg); err != nil {
		return Config{}, fmt.Errorf("decode config: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		if err == nil {
			err = errors.New("multiple JSON values")
		}
		return Config{}, fmt.Errorf("decode config: trailing content: %w", err)
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
	cfg.AuthorityToken, err = loadSecret(authorityTokenEnv)
	if err != nil {
		return Config{}, err
	}
	if cfg.EffectiveStorageBackend() == storageBackendPostgres {
		databaseURL, err := LoadDatabaseURL()
		if err != nil {
			return Config{}, err
		}
		cfg.DatabaseURL = databaseURL
	}
	if err := cfg.Validate(); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

func LoadDatabaseURL() (string, error) {
	value, err := loadSecret(databaseURLEnv)
	if err != nil {
		return "", err
	}
	if value == "" {
		return "", fmt.Errorf("%s is required when storage_backend is postgres", databaseURLEnv)
	}
	if err := validateDatabaseTLS(value, strings.TrimSpace(os.Getenv(databaseTLSModeEnv))); err != nil {
		return "", err
	}
	return value, nil
}

func validateDatabaseTLS(databaseURL, requiredMode string) error {
	if requiredMode == "" {
		return nil
	}
	if requiredMode != "verify-full" {
		return fmt.Errorf("%s must be empty or verify-full", databaseTLSModeEnv)
	}
	parsed, err := url.Parse(databaseURL)
	if err != nil || (parsed.Scheme != "postgres" && parsed.Scheme != "postgresql") || parsed.Host == "" {
		return errors.New("production relay requires a PostgreSQL URL with sslmode=verify-full")
	}
	sslModes := parsed.Query()["sslmode"]
	if len(sslModes) != 1 || sslModes[0] != requiredMode {
		return errors.New("production relay requires sslmode=verify-full")
	}
	return nil
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
	mode := c.AuthorityMode
	if mode == "" {
		mode = AuthorityModeLocal
	}
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
	backend := c.EffectiveStorageBackend()
	if backend != storageBackendFile && backend != storageBackendPostgres {
		return fmt.Errorf("unsupported storage_backend %q", c.StorageBackend)
	}
	if backend == storageBackendFile && c.StateFile == "" {
		missing = append(missing, "state_file")
	}
	if backend == storageBackendPostgres && c.DatabaseURL == "" {
		missing = append(missing, databaseURLEnv)
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
	if mode == AuthorityModeProd {
		if c.AuthorityURL == "" {
			missing = append(missing, "authority_url")
		}
		if c.AuthoritySourceID == "" {
			missing = append(missing, "authority_source_id")
		}
		if c.AllocationRegistryFile == "" {
			missing = append(missing, "allocation_registry_file")
		}
		if c.AuthorityToken == "" {
			missing = append(missing, authorityTokenEnv)
		}
	}
	if len(missing) > 0 {
		return fmt.Errorf("missing required configuration: %s", strings.Join(missing, ", "))
	}
	if len(c.TurnSecret) < 32 || len(c.ClientToken) < 32 || len(c.UsageToken) < 32 || len(c.MetricsToken) < 32 || len(c.AdminToken) < 32 {
		return errors.New("TURN secret and API tokens must each contain at least 32 characters")
	}
	if mode == AuthorityModeProd && len(c.AuthorityToken) < 32 {
		return errors.New("authority API token must contain at least 32 characters")
	}
	tokens := []string{c.ClientToken, c.UsageToken, c.MetricsToken, c.AdminToken}
	if c.AuthorityToken != "" {
		tokens = append(tokens, c.AuthorityToken)
	}
	for left := range tokens {
		for right := left + 1; right < len(tokens); right++ {
			if tokens[left] == tokens[right] {
				return errors.New("client, usage, metrics, admin, and authority API tokens must be different")
			}
		}
	}
	if mode != AuthorityModeLocal && mode != AuthorityModeProd {
		return fmt.Errorf("unsupported authority_mode %q", c.AuthorityMode)
	}
	if mode == AuthorityModeLocal && (c.AuthorityURL != "" || c.AuthoritySourceID != "" || c.AllocationRegistryFile != "") {
		return errors.New("authority_url, authority_source_id, and allocation_registry_file require production_authority mode")
	}
	if mode == AuthorityModeProd && !validIdentifier(c.AuthoritySourceID) {
		return errors.New("authority_source_id must be a valid identifier")
	}
	if c.CredentialTTLSeconds <= 0 || c.MaxCredentialTTLSeconds < c.CredentialTTLSeconds {
		return errors.New("credential TTL must be positive and no greater than maximum TTL")
	}
	if c.CredentialTTLSeconds > maxDurationSeconds || c.MaxCredentialTTLSeconds > maxDurationSeconds {
		return errors.New("credential TTL values exceed the safe int64 nanosecond bound")
	}
	if c.CredentialRequestsPerMinute <= 0 || c.MaxConcurrentSessionsPerDevice <= 0 {
		return errors.New("rate and concurrent-session limits must be positive")
	}
	if c.DailyBytesPerDevice == 0 || c.MaxUsageEventBytes == 0 {
		return errors.New("byte limits must be positive")
	}
	if backend == storageBackendPostgres {
		if c.MaximumDatabaseClockSkewSeconds <= 0 {
			return errors.New("maximum_database_clock_skew_seconds must be positive for postgres storage")
		}
		if c.MaximumDatabaseClockSkewSeconds > maximumDatabaseClockSkewSeconds {
			return fmt.Errorf("maximum_database_clock_skew_seconds must not exceed %d", maximumDatabaseClockSkewSeconds)
		}
	}
	for _, uri := range c.TurnURIs {
		if !strings.HasPrefix(uri, "turn:") && !strings.HasPrefix(uri, "turns:") {
			return fmt.Errorf("unsupported TURN URI %q", uri)
		}
	}
	return nil
}

func (c Config) EffectiveAuthorityMode() string {
	if c.AuthorityMode == "" {
		return AuthorityModeLocal
	}
	return c.AuthorityMode
}

func (c Config) EffectiveStorageBackend() string {
	if c.StorageBackend == "" {
		return storageBackendFile
	}
	return c.StorageBackend
}

func (c Config) MaximumDatabaseClockSkew() time.Duration {
	return time.Duration(c.MaximumDatabaseClockSkewSeconds) * time.Second
}
