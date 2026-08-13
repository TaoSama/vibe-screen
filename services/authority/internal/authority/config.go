package authority

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
	"time"
)

type Config struct {
	ListenAddress               string `json:"listen_address"`
	DatabaseURL                 string `json:"-"`
	AdminToken                  string `json:"-"`
	SignalingToken              string `json:"-"`
	RelayToken                  string `json:"-"`
	CoturnToken                 string `json:"-"`
	RoleTokenSecret             string `json:"-"`
	MaximumSessionTTLSeconds    int64  `json:"maximum_session_ttl_seconds"`
	DailyBytesPerDevice         uint64 `json:"daily_bytes_per_device"`
	MaximumAllocationsPerDevice int    `json:"maximum_allocations_per_device"`
	ReconciliationGraceSeconds  int64  `json:"reconciliation_grace_seconds"`
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
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		if err == nil {
			err = errors.New("multiple JSON values")
		}
		return Config{}, fmt.Errorf("decode config: trailing content: %w", err)
	}
	cfg.DatabaseURL = os.Getenv("VIBE_AUTHORITY_DATABASE_URL")
	cfg.AdminToken = os.Getenv("VIBE_AUTHORITY_ADMIN_TOKEN")
	cfg.SignalingToken = os.Getenv("VIBE_AUTHORITY_SIGNALING_TOKEN")
	cfg.RelayToken = os.Getenv("VIBE_AUTHORITY_RELAY_TOKEN")
	cfg.CoturnToken = os.Getenv("VIBE_AUTHORITY_COTURN_TOKEN")
	cfg.RoleTokenSecret = os.Getenv("VIBE_AUTHORITY_ROLE_TOKEN_SECRET")
	if err := cfg.Validate(); err != nil {
		return Config{}, err
	}
	return cfg, nil
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
	if c.MaximumSessionTTLSeconds <= 0 || c.DailyBytesPerDevice == 0 || c.MaximumAllocationsPerDevice <= 0 || c.ReconciliationGraceSeconds <= 0 {
		return errors.New("authority limits must be positive")
	}
	return nil
}

func (c Config) ReconciliationGrace() time.Duration {
	return time.Duration(c.ReconciliationGraceSeconds) * time.Second
}
