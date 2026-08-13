package relay

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLoadConfigRejectsUnknownFields(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.json")
	if err := os.WriteFile(path, []byte(`{"unexpected":true}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadConfig(path); err == nil {
		t.Fatal("expected unknown field error")
	}
}

func TestLoadSecretFromFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "secret")
	if err := os.WriteFile(path, []byte("file-secret\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv(turnSecretEnv, "")
	t.Setenv(turnSecretEnv+"_FILE", path)

	secret, err := loadSecret(turnSecretEnv)
	if err != nil {
		t.Fatal(err)
	}
	if secret != "file-secret" {
		t.Fatalf("unexpected secret %q", secret)
	}
}

func TestLoadSecretRejectsAmbiguousSources(t *testing.T) {
	t.Setenv(clientTokenEnv, "direct-secret")
	t.Setenv(clientTokenEnv+"_FILE", filepath.Join(t.TempDir(), "secret"))

	_, err := loadSecret(clientTokenEnv)
	if err == nil || !strings.Contains(err.Error(), "cannot both be set") {
		t.Fatalf("expected ambiguous source error, got %v", err)
	}
}

func TestLoadSecretReportsUnreadableFile(t *testing.T) {
	t.Setenv(usageTokenEnv, "")
	t.Setenv(usageTokenEnv+"_FILE", filepath.Join(t.TempDir(), "missing"))

	_, err := loadSecret(usageTokenEnv)
	if err == nil || !strings.Contains(err.Error(), usageTokenEnv+"_FILE") {
		t.Fatalf("expected secret file error, got %v", err)
	}
}

func TestConfigRejectsReusedMetricsToken(t *testing.T) {
	cfg := Config{
		ListenAddress: "127.0.0.1:8090", TurnRealm: "relay.test", TurnURIs: []string{"turn:relay.test:3478"},
		CredentialTTLSeconds: 60, MaxCredentialTTLSeconds: 120, CredentialRequestsPerMinute: 1,
		MaxConcurrentSessionsPerDevice: 1, DailyBytesPerDevice: 1, MaxUsageEventBytes: 1, StateFile: filepath.Join(t.TempDir(), "state.json"),
		TurnSecret: strings.Repeat("t", 32), ClientToken: strings.Repeat("c", 32), UsageToken: strings.Repeat("u", 32),
		MetricsToken: strings.Repeat("u", 32), AdminToken: strings.Repeat("a", 32),
	}
	if err := cfg.Validate(); err == nil || !strings.Contains(err.Error(), "must be different") {
		t.Fatalf("expected duplicate-token rejection, got %v", err)
	}
}

func TestConfigRequiresStrictTerminationWebhook(t *testing.T) {
	cfg := Config{
		ListenAddress: "127.0.0.1:8090", TurnRealm: "relay.test", TurnURIs: []string{"turn:relay.test:3478"},
		CredentialTTLSeconds: 60, MaxCredentialTTLSeconds: 120, CredentialRequestsPerMinute: 1,
		MaxConcurrentSessionsPerDevice: 1, DailyBytesPerDevice: 1, MaxUsageEventBytes: 1, StateFile: filepath.Join(t.TempDir(), "state.json"),
		TurnSecret: strings.Repeat("t", 32), ClientToken: strings.Repeat("c", 32), UsageToken: strings.Repeat("u", 32),
		MetricsToken: strings.Repeat("m", 32), AdminToken: strings.Repeat("a", 32),
		AllocationTerminationWebhookURL: "http://executor.example.com/revoke", AllocationTerminationTimeoutSeconds: 5,
		TerminationToken: strings.Repeat("x", 32),
	}
	if err := cfg.Validate(); err == nil || !strings.Contains(err.Error(), "must use HTTPS") {
		t.Fatalf("expected insecure webhook rejection, got %v", err)
	}
	cfg.AllocationTerminationWebhookURL = "https://user:password@executor.example.com/revoke"
	if err := cfg.Validate(); err == nil || !strings.Contains(err.Error(), "without credentials") {
		t.Fatalf("expected embedded credential rejection, got %v", err)
	}
}
