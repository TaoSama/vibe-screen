package authority

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

type Config struct {
	ListenAddress                   string `json:"listen_address"`
	DatabaseURL                     string `json:"-"`
	AdminToken                      string `json:"-"`
	SignalingToken                  string `json:"-"`
	RelayToken                      string `json:"-"`
	CoturnToken                     string `json:"-"`
	RoleTokenSecret                 string `json:"-"`
	MaximumSessionTTLSeconds        int64  `json:"maximum_session_ttl_seconds"`
	MaximumDatabaseClockSkewSeconds int64  `json:"maximum_database_clock_skew_seconds"`
	DailyBytesPerDevice             uint64 `json:"daily_bytes_per_device"`
	MaximumAllocationsPerDevice     int    `json:"maximum_allocations_per_device"`
	ReconciliationGraceSeconds      int64  `json:"reconciliation_grace_seconds"`
}

const (
	databaseURLEnv     = "VIBE_AUTHORITY_DATABASE_URL"
	adminTokenEnv      = "VIBE_AUTHORITY_ADMIN_TOKEN"
	signalingTokenEnv  = "VIBE_AUTHORITY_SIGNALING_TOKEN"
	relayTokenEnv      = "VIBE_AUTHORITY_RELAY_TOKEN"
	coturnTokenEnv     = "VIBE_AUTHORITY_COTURN_TOKEN"
	roleTokenSecretEnv = "VIBE_AUTHORITY_ROLE_TOKEN_SECRET"

	// maxDurationSeconds bounds integer-seconds config values so that
	// time.Duration(seconds) * time.Second cannot overflow int64.
	maxDurationSeconds = math.MaxInt64 / int64(time.Second)
	// maxAllocationsPerDevice bounds the per-device concurrent relay
	// allocation count. The active-allocation count is a Postgres bigint
	// scanned into a Go int; capping at MaxInt32 keeps the value safe on both
	// 32-bit and 64-bit hosts and prevents a misconfigured huge value from
	// effectively disabling the per-device allocation limit.
	maxAllocationsPerDevice = math.MaxInt32
	// A missing clock-skew limit uses a conservative default so existing
	// configuration files gain the readiness check on upgrade. An explicit zero
	// overwrites this initializer and is rejected by validation.
	defaultMaximumDatabaseClockSkewSeconds int64 = 5
	// The default is also the hard maximum: configuration may tighten this
	// bound, but cannot conceal broken time synchronization by relaxing it.
	maximumDatabaseClockSkewSeconds = defaultMaximumDatabaseClockSkewSeconds
)

func LoadConfig(path string) (Config, error) {
	contents, err := os.ReadFile(path)
	if err != nil {
		return Config{}, fmt.Errorf("read config: %w", err)
	}
	cfg := Config{MaximumDatabaseClockSkewSeconds: defaultMaximumDatabaseClockSkewSeconds}
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
	values := []struct {
		name        string
		destination *string
	}{
		{databaseURLEnv, &cfg.DatabaseURL},
		{adminTokenEnv, &cfg.AdminToken},
		{signalingTokenEnv, &cfg.SignalingToken},
		{relayTokenEnv, &cfg.RelayToken},
		{coturnTokenEnv, &cfg.CoturnToken},
		{roleTokenSecretEnv, &cfg.RoleTokenSecret},
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
	if c.ListenAddress == "" || c.DatabaseURL == "" {
		return errors.New("listen_address and VIBE_AUTHORITY_DATABASE_URL are required")
	}
	secrets := []string{c.AdminToken, c.SignalingToken, c.RelayToken, c.CoturnToken, c.RoleTokenSecret}
	for _, value := range secrets {
		if len(value) < 32 {
			return errors.New("authority tokens and role secret must each contain at least 32 characters")
		}
	}
	for i := range secrets {
		for j := i + 1; j < len(secrets); j++ {
			if secrets[i] == secrets[j] {
				return errors.New("authority secrets must be distinct")
			}
		}
	}
	if c.MaximumSessionTTLSeconds <= 0 || c.MaximumDatabaseClockSkewSeconds <= 0 || c.DailyBytesPerDevice == 0 || c.MaximumAllocationsPerDevice <= 0 || c.ReconciliationGraceSeconds <= 0 {
		return errors.New("authority limits must be positive")
	}
	if c.MaximumSessionTTLSeconds > maxDurationSeconds || c.ReconciliationGraceSeconds > maxDurationSeconds {
		return errors.New("authority duration limits exceed the safe int64 nanosecond bound")
	}
	if c.MaximumAllocationsPerDevice > maxAllocationsPerDevice {
		return errors.New("authority allocation limit exceeds the safe int32 bound")
	}
	if c.MaximumDatabaseClockSkewSeconds > maximumDatabaseClockSkewSeconds {
		return fmt.Errorf("maximum_database_clock_skew_seconds must not exceed %d", maximumDatabaseClockSkewSeconds)
	}
	return nil
}

func (c Config) ReconciliationGrace() time.Duration {
	return time.Duration(c.ReconciliationGraceSeconds) * time.Second
}

func (c Config) MaximumDatabaseClockSkew() time.Duration {
	return time.Duration(c.MaximumDatabaseClockSkewSeconds) * time.Second
}
