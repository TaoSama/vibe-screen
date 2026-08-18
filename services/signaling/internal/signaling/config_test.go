package signaling

import (
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestConfigRequiresExplicitAuthorityMode(t *testing.T) {
	cfg := testConfig()
	cfg.AuthorityMode = ""
	if err := cfg.Validate(); err == nil {
		t.Fatal("missing authority_mode was accepted")
	}
}

func TestConfigSeparatesLocalDevelopmentAndProductionAuthority(t *testing.T) {
	local := testConfig()
	local.AuthorityURL = "https://authority.example.test"
	local.AuthorityToken = testAuthorityToken
	if err := local.Validate(); err == nil {
		t.Fatal("local development accepted production authority configuration")
	}

	production := testConfig()
	production.AuthorityMode = AuthorityModeProductionAuthority
	production.AuthorityURL = "https://authority.example.test"
	production.AuthorityToken = testAuthorityToken
	production.StoreBackend = StoreBackendPostgres
	production.DatabaseURL = "postgres://authority@127.0.0.1/vibescreen?sslmode=disable"
	if err := production.Validate(); err != nil {
		t.Fatalf("valid production authority config: %v", err)
	}

	production.IssuerToken = production.AuthorityToken
	if err := production.Validate(); err == nil {
		t.Fatal("production config reused the authority token as the issuer token")
	}
}

func TestConfigRequiresStoreBackendAndProductionPostgres(t *testing.T) {
	cfg := testConfig()
	cfg.StoreBackend = ""
	if err := cfg.Validate(); err == nil {
		t.Fatal("missing store_backend was accepted")
	}

	production := testConfig()
	production.AuthorityMode = AuthorityModeProductionAuthority
	production.AuthorityURL = "https://authority.example.test"
	production.AuthorityToken = testAuthorityToken
	production.StoreBackend = StoreBackendMemory
	if err := production.Validate(); err == nil || !strings.Contains(err.Error(), "requires postgres") {
		t.Fatalf("production memory store error = %v", err)
	}
}

func TestConfigValidatesDatabaseURLPolicy(t *testing.T) {
	cfg := testConfig()
	cfg.StoreBackend = StoreBackendMemory
	cfg.DatabaseURL = "postgres://authority@127.0.0.1/vibescreen?sslmode=disable"
	if err := cfg.Validate(); err == nil {
		t.Fatal("memory store accepted database URL")
	}

	cfg = testConfig()
	cfg.StoreBackend = StoreBackendPostgres
	cfg.DatabaseURL = ""
	if err := cfg.Validate(); err == nil || !strings.Contains(err.Error(), databaseURLEnv) {
		t.Fatalf("missing postgres URL error = %v", err)
	}

	cfg.DatabaseURL = "postgres://authority@example.com/vibescreen?sslmode=require"
	if err := cfg.Validate(); err == nil || !strings.Contains(err.Error(), "verify-full") {
		t.Fatalf("non-loopback weak TLS mode error = %v", err)
	}

	cfg.DatabaseURL = "postgresql://authority@example.com/vibescreen?sslmode=verify-full"
	if err := cfg.Validate(); err != nil {
		t.Fatalf("verify-full postgres URL rejected: %v", err)
	}
}

func TestConfigRejectsSessionTTLDurationOverflow(t *testing.T) {
	cfg := testConfig()
	cfg.MaxSessionTTLSeconds = math.MaxInt64/int64(time.Second) + 1
	if err := cfg.Validate(); err == nil {
		t.Fatal("overflowing session TTL was accepted")
	}
}

func TestLoadEnvironmentValueReadsExclusiveFile(t *testing.T) {
	const variable = "VIBE_SIGNALING_TEST_SECRET"
	secretPath := filepath.Join(t.TempDir(), "secret")
	if err := os.WriteFile(secretPath, []byte("  file-secret-value  \n"), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv(variable, "")
	t.Setenv(variable+"_FILE", secretPath)

	value, err := loadEnvironmentValue(variable)
	if err != nil {
		t.Fatal(err)
	}
	if value != "file-secret-value" {
		t.Fatalf("file secret = %q", value)
	}
}

func TestLoadEnvironmentValueRejectsValueAndFile(t *testing.T) {
	const variable = "VIBE_SIGNALING_TEST_SECRET"
	t.Setenv(variable, "direct-secret")
	t.Setenv(variable+"_FILE", filepath.Join(t.TempDir(), "secret"))

	if _, err := loadEnvironmentValue(variable); err == nil || !strings.Contains(err.Error(), "cannot both be set") {
		t.Fatalf("expected exclusive environment forms error, got %v", err)
	}
}

func TestConfigRejectsUnknownAuthorityMode(t *testing.T) {
	cfg := testConfig()
	cfg.AuthorityMode = "automatic"
	if err := cfg.Validate(); err == nil {
		t.Fatal("unknown authority mode was accepted")
	}
}

func TestConfigRejectsAuthorityTokenReuseAndWeakToken(t *testing.T) {
	cfg := testConfig()
	cfg.AuthorityMode = AuthorityModeProductionAuthority
	cfg.AuthorityURL = "https://authority.example.test"
	cfg.StoreBackend = StoreBackendPostgres
	cfg.DatabaseURL = "postgres://authority@127.0.0.1/vibescreen?sslmode=disable"
	cfg.AuthorityToken = "short"
	if err := cfg.Validate(); err == nil {
		t.Fatal("weak authority token was accepted")
	}

	cfg.AuthorityToken = cfg.MetricsToken
	if err := cfg.Validate(); err == nil {
		t.Fatal("authority token reused as metrics token was accepted")
	}
}
