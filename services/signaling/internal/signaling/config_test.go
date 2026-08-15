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
	if err := production.Validate(); err != nil {
		t.Fatalf("valid production authority config: %v", err)
	}

	production.IssuerToken = production.AuthorityToken
	if err := production.Validate(); err == nil {
		t.Fatal("production config reused the authority token as the issuer token")
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
	cfg.AuthorityToken = "short"
	if err := cfg.Validate(); err == nil {
		t.Fatal("weak authority token was accepted")
	}

	cfg.AuthorityToken = cfg.MetricsToken
	if err := cfg.Validate(); err == nil {
		t.Fatal("authority token reused as metrics token was accepted")
	}
}
