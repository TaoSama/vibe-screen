package signaling_test

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"testing"
	"time"
)

// authorityProcessTest holds the tokens, addresses, and process handles for a
// single authority-backed signaling integration run. All secrets are generated
// per test so a leak in one run cannot compromise another.
type authorityProcessTest struct {
	authorityDatabaseURL string
	signalingDatabaseURL string

	authorityAdminToken     string
	authoritySignalingToken string
	authorityRelayToken     string
	authorityCoturnToken    string
	authorityRoleSecret     string

	signalingIssuerToken  string
	signalingMetricsToken string
	relayClientToken      string
	relayUsageToken       string
	relayMetricsToken     string
	relayAdminToken       string
	relayTurnSecret       string

	authorityAddress string
	signalingAddress string
	relayAddress     string

	authorityBinary string
	signalingBinary string
	relayBinary     string

	authorityLog bytes.Buffer
	signalingLog bytes.Buffer
	relayLog     bytes.Buffer

	authorityCmd *exec.Cmd
	signalingCmd *exec.Cmd
	relayCmd     *exec.Cmd
}

func TestAuthorityProcessSessionRevocationFailClosed(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("signal-based process test is Unix-only")
	}
	authorityDatabaseURL := os.Getenv("VIBE_AUTHORITY_TEST_DATABASE_URL")
	signalingDatabaseURL := os.Getenv("VIBE_SIGNALING_TEST_DATABASE_URL")
	if authorityDatabaseURL == "" || signalingDatabaseURL == "" {
		t.Skip("VIBE_AUTHORITY_TEST_DATABASE_URL and VIBE_SIGNALING_TEST_DATABASE_URL must be set")
	}

	run := &authorityProcessTest{
		authorityDatabaseURL: authorityDatabaseURL,
		signalingDatabaseURL: signalingDatabaseURL,

		authorityAdminToken:     "authority-admin-token-" + randomSuffix(t),
		authoritySignalingToken: "authority-signaling-token-" + randomSuffix(t),
		authorityRelayToken:     "authority-relay-token-" + randomSuffix(t),
		authorityCoturnToken:    "authority-coturn-token-" + randomSuffix(t),
		authorityRoleSecret:     "authority-role-secret-" + randomSuffix(t),

		signalingIssuerToken:  "signaling-issuer-token-" + randomSuffix(t),
		signalingMetricsToken: "signaling-metrics-token-" + randomSuffix(t),
		relayClientToken:      "relay-client-token-" + randomSuffix(t),
		relayUsageToken:       "relay-usage-token-" + randomSuffix(t),
		relayMetricsToken:     "relay-metrics-token-" + randomSuffix(t),
		relayAdminToken:       "relay-admin-token-" + randomSuffix(t),
		relayTurnSecret:       "relay-turn-secret-" + randomSuffix(t),

		authorityAddress: reserveAddress(t),
		signalingAddress: reserveAddress(t),
		relayAddress:     reserveAddress(t),
	}

	tmpDir := t.TempDir()
	run.authorityBinary = filepath.Join(tmpDir, "vibe-authority")
	run.signalingBinary = filepath.Join(tmpDir, "vibe-signaling")
	run.relayBinary = filepath.Join(tmpDir, "vibe-relay")

	buildAuthority(t, run.authorityBinary)
	buildSignaling(t, run.signalingBinary)
	buildRelay(t, run.relayBinary)

	// Apply the authority schema before starting the server.
	migrateAuthority(t, run)
	migrateSignaling(t, run)
	resetAuthorityDatabase(t, run.authorityDatabaseURL)
	resetSignalingDatabase(t, run.signalingDatabaseURL)
	t.Cleanup(func() { resetAuthorityDatabase(t, run.authorityDatabaseURL) })
	t.Cleanup(func() { resetSignalingDatabase(t, run.signalingDatabaseURL) })

	// Start the authority service first; signaling depends on it for /readyz.
	startAuthority(t, run)
	t.Cleanup(func() { stopProcess(t, run.authorityCmd, &run.authorityLog, "authority") })

	startSignaling(t, run)
	t.Cleanup(func() { stopProcess(t, run.signalingCmd, &run.signalingLog, "signaling") })
	startRelay(t, run)
	t.Cleanup(func() { stopProcess(t, run.relayCmd, &run.relayLog, "relay") })

	authorityBase := "http://" + run.authorityAddress
	signalingBase := "http://" + run.signalingAddress
	relayBase := "http://" + run.relayAddress

	waitUntilHealthy(t, authorityBase+"/healthz")
	waitUntilHealthy(t, signalingBase+"/healthz")
	waitUntilHealthy(t, relayBase+"/healthz")
	waitUntilReady(t, authorityBase+"/readyz")
	waitUntilReady(t, signalingBase+"/readyz")
	waitUntilReady(t, relayBase+"/readyz")

	accountID := "acct-" + randomSuffix(t)
	hostDeviceID := "host-" + randomSuffix(t)
	clientDeviceID := "client-" + randomSuffix(t)
	requestID := "req-" + randomSuffix(t)
	const sessionEpoch uint64 = 1

	// Register the account and both devices through the authority admin API.
	authorityRequest(t, http.MethodPut, authorityBase+"/v1/accounts/"+accountID,
		run.authorityAdminToken, "", http.StatusNoContent)
	authorityRequest(t, http.MethodPut,
		authorityBase+"/v1/accounts/"+accountID+"/devices/"+hostDeviceID,
		run.authorityAdminToken, "", http.StatusNoContent)
	authorityRequest(t, http.MethodPut,
		authorityBase+"/v1/accounts/"+accountID+"/devices/"+clientDeviceID,
		run.authorityAdminToken, "", http.StatusNoContent)

	// Create an authority-backed signaling session.
	createBody := fmt.Sprintf(`{
  "request_id": %q,
  "account_id": %q,
  "host_device_id": %q,
  "client_device_id": %q,
  "session_epoch": %d,
  "ttl_seconds": 60
}`, requestID, accountID, hostDeviceID, clientDeviceID, sessionEpoch)
	createResp := postJSON(t, signalingBase+"/v1/sessions", run.signalingIssuerToken,
		createBody, http.StatusCreated)
	var firstSession sessionResponse
	if err := json.Unmarshal(createResp, &firstSession); err != nil {
		t.Fatal(err)
	}
	if firstSession.SessionID == "" || firstSession.HostToken == "" || firstSession.DeviceToken == "" {
		t.Fatalf("incomplete session response: %#v", firstSession)
	}
	if firstSession.HostToken == firstSession.DeviceToken {
		t.Fatalf("host and device tokens must differ: %#v", firstSession)
	}
	credentialPasswords := []string{}
	assertCredential := func(body string) {
		t.Helper()
		credentialResp := relayRequest(t, http.MethodPost, relayBase+"/v1/credentials", run.relayClientToken, body, http.StatusOK)
		var credential struct {
			Username string `json:"username"`
			Password string `json:"password"`
		}
		if err := json.Unmarshal(credentialResp, &credential); err != nil {
			t.Fatal(err)
		}
		if !strings.HasSuffix(credential.Username, ":"+clientDeviceID) || credential.Password == "" {
			t.Fatalf("relay returned incomplete TURN credential: %#v", credential)
		}
		credentialPasswords = append(credentialPasswords, credential.Password)
	}

	// Host posts an offer; the client polls and receives it.
	const offerSDP = "v=0\r\na=fingerprint:sha-256 AUTHORITY-OFFER-SECRET\r\n"
	postJSON(t, signalingBase+"/v1/sessions/"+firstSession.SessionID+"/messages",
		firstSession.HostToken,
		fmt.Sprintf(`{"message_id":"offer-1","type":"offer","sdp":%q}`, offerSDP),
		http.StatusCreated)
	clientPoll := poll(t, signalingBase, firstSession.SessionID, firstSession.DeviceToken, 0)
	if len(clientPoll.Events) != 1 || clientPoll.Events[0].Type != "offer" ||
		clientPoll.Events[0].SDP != offerSDP {
		t.Fatalf("client did not receive host offer: %#v", clientPoll)
	}

	// Relay credentials are issued only after relay asks the shared authority to
	// reserve capacity for this signaling session/device/allocation tuple.
	credentialBody := fmt.Sprintf(`{"device_id":%q,"session_id":%q,"allocation_id":"allocation-before-session-invalidate"}`, clientDeviceID, firstSession.SessionID)
	assertCredential(credentialBody)

	// Session-only invalidation must also propagate to relay admission. The
	// device is still registered and not revoked, so this proves the authority
	// session tombstone is enough to block a future TURN credential.
	status, _, err := requestStatus(http.MethodDelete,
		signalingBase+"/v1/sessions/"+firstSession.SessionID,
		run.signalingIssuerToken, "")
	if err != nil {
		t.Fatalf("invalidate first session: %v", err)
	}
	if status != http.StatusNoContent {
		t.Fatalf("invalidate first session status=%d, want 204", status)
	}
	postJSON(t, signalingBase+"/v1/sessions/"+firstSession.SessionID+"/messages",
		firstSession.HostToken,
		`{"message_id":"offer-after-session-invalidate","type":"offer","sdp":"v=0\r\n"}`,
		http.StatusNotFound)
	credentialAfterSessionInvalidate := fmt.Sprintf(`{"device_id":%q,"session_id":%q,"allocation_id":"allocation-after-session-invalidate"}`, clientDeviceID, firstSession.SessionID)
	relayRequest(t, http.MethodPost, relayBase+"/v1/credentials", run.relayClientToken, credentialAfterSessionInvalidate, http.StatusForbidden)

	secondRequestID := "req-" + randomSuffix(t)
	const secondSessionEpoch uint64 = 2
	secondCreateBody := fmt.Sprintf(`{
  "request_id": %q,
  "account_id": %q,
  "host_device_id": %q,
  "client_device_id": %q,
  "session_epoch": %d,
  "ttl_seconds": 60
}`, secondRequestID, accountID, hostDeviceID, clientDeviceID, secondSessionEpoch)
	secondCreateResp := postJSON(t, signalingBase+"/v1/sessions", run.signalingIssuerToken,
		secondCreateBody, http.StatusCreated)
	var secondSession sessionResponse
	if err := json.Unmarshal(secondCreateResp, &secondSession); err != nil {
		t.Fatal(err)
	}
	if secondSession.SessionID == "" || secondSession.HostToken == "" || secondSession.DeviceToken == "" {
		t.Fatalf("incomplete second session response: %#v", secondSession)
	}
	secondCredentialBody := fmt.Sprintf(`{"device_id":%q,"session_id":%q,"allocation_id":"allocation-before-device-revoke"}`, clientDeviceID, secondSession.SessionID)
	assertCredential(secondCredentialBody)

	// Revoke the client device through the authority admin API. The session
	// epoch is the revocation epoch; the authority marks every session that
	// involves the client device as revoked.
	authorityRequest(t, http.MethodPost,
		authorityBase+"/v1/devices/"+clientDeviceID+"/revoke",
		run.authorityAdminToken,
		fmt.Sprintf(`{"epoch": %d}`, secondSessionEpoch),
		http.StatusNoContent)

	// After revocation, both role tokens must be rejected by signaling with
	// 404. The authority returns 403 for revoked sessions; signaling maps that
	// to 404 so it does not disclose whether the session exists.
	postJSON(t, signalingBase+"/v1/sessions/"+secondSession.SessionID+"/messages",
		secondSession.HostToken,
		`{"message_id":"offer-after-revoke","type":"offer","sdp":"v=0\r\n"}`,
		http.StatusNotFound)
	pollExpectStatus(t, signalingBase, secondSession.SessionID, secondSession.DeviceToken,
		0, http.StatusNotFound)

	// The same authority tombstone must propagate to relay admission: a new TURN
	// credential for the revoked device/session fails closed instead of falling
	// back to the relay-local JSON store.
	credentialAfterRevokeBody := fmt.Sprintf(`{"device_id":%q,"session_id":%q,"allocation_id":"allocation-after-revoke"}`, clientDeviceID, secondSession.SessionID)
	relayRequest(t, http.MethodPost, relayBase+"/v1/credentials", run.relayClientToken, credentialAfterRevokeBody, http.StatusForbidden)

	// The issuer can still invalidate the session record, but the underlying
	// authority admission is already revoked.
	status, _, err = requestStatus(http.MethodDelete,
		signalingBase+"/v1/sessions/"+secondSession.SessionID,
		run.signalingIssuerToken, "")
	if err != nil {
		t.Fatalf("invalidate after revoke: %v", err)
	}
	if status != http.StatusNoContent {
		t.Fatalf("invalidate after revoke status=%d, want 204", status)
	}

	// Stop both processes with SIGTERM and assert bounded shutdown.
	stopProcess(t, run.signalingCmd, &run.signalingLog, "signaling")
	run.signalingCmd = nil
	stopProcess(t, run.relayCmd, &run.relayLog, "relay")
	run.relayCmd = nil
	stopProcess(t, run.authorityCmd, &run.authorityLog, "authority")
	run.authorityCmd = nil

	// Neither process may log any service token, role token, or SDP secret.
	secrets := []string{
		run.authorityAdminToken, run.authoritySignalingToken,
		run.authorityRelayToken, run.authorityCoturnToken, run.authorityRoleSecret,
		run.signalingIssuerToken, run.signalingMetricsToken,
		run.relayClientToken, run.relayUsageToken, run.relayMetricsToken,
		run.relayAdminToken, run.relayTurnSecret,
		firstSession.HostToken, firstSession.DeviceToken,
		secondSession.HostToken, secondSession.DeviceToken,
		offerSDP, "AUTHORITY-OFFER-SECRET",
	}
	secrets = append(secrets, credentialPasswords...)
	for _, secret := range secrets {
		if secret == "" {
			continue
		}
		if strings.Contains(run.authorityLog.String(), secret) {
			t.Fatalf("authority log leaked secret %q", secret)
		}
		if strings.Contains(run.signalingLog.String(), secret) {
			t.Fatalf("signaling log leaked secret %q", secret)
		}
		if strings.Contains(run.relayLog.String(), secret) {
			t.Fatalf("relay log leaked secret %q", secret)
		}
	}
}

func resetAuthorityDatabase(t *testing.T, databaseURL string) {
	t.Helper()
	const statement = "TRUNCATE authority_coturn_events, authority_relay_allocations, authority_relay_daily_usage, authority_signaling_sessions, authority_session_epoch_floors, authority_devices, authority_accounts, authority_audit_events RESTART IDENTITY CASCADE"
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "psql", databaseURL, "--no-psqlrc", "--set=ON_ERROR_STOP=1", "--quiet", "--command", statement)
	if output, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("reset authority integration database: %v\n%s", err, output)
	}
}

func resetSignalingDatabase(t *testing.T, databaseURL string) {
	t.Helper()
	const statement = "TRUNCATE signaling_waiters, signaling_role_rates, signaling_messages, signaling_sessions RESTART IDENTITY CASCADE"
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "psql", databaseURL, "--no-psqlrc", "--set=ON_ERROR_STOP=1", "--quiet", "--command", statement)
	if output, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("reset signaling integration database: %v\n%s", err, output)
	}
}

func buildAuthority(t *testing.T, binaryPath string) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	build := exec.CommandContext(ctx, "go", "build", "-o", binaryPath, "./cmd/vibe-authority")
	build.Dir = "../authority"
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build authority process: %v\n%s", err, output)
	}
}

func buildSignaling(t *testing.T, binaryPath string) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	build := exec.CommandContext(ctx, "go", "build", "-o", binaryPath, "./cmd/vibe-signaling")
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build signaling process: %v\n%s", err, output)
	}
}

func buildRelay(t *testing.T, binaryPath string) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	build := exec.CommandContext(ctx, "go", "build", "-o", binaryPath, "./cmd/vibe-relay")
	build.Dir = "../relay"
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build relay process: %v\n%s", err, output)
	}
}

func migrateAuthority(t *testing.T, run *authorityProcessTest) {
	t.Helper()
	migrationPath, err := filepath.Abs("../authority/migrations/001_authority.sql")
	if err != nil {
		t.Fatal(err)
	}
	// The authority binary loads its config before applying the migration, so
	// a minimal config file is required even for the --migrate subcommand.
	configPath := filepath.Join(t.TempDir(), "authority-migrate-config.json")
	const config = `{
  "listen_address": "127.0.0.1:0",
  "maximum_session_ttl_seconds": 900,
  "daily_bytes_per_device": 21474836480,
  "maximum_allocations_per_device": 2,
  "reconciliation_grace_seconds": 120
}`
	if err := os.WriteFile(configPath, []byte(config), 0o600); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, run.authorityBinary, "--config", configPath, "--migrate", migrationPath)
	cmd.Env = append(os.Environ(),
		"VIBE_AUTHORITY_DATABASE_URL="+run.authorityDatabaseURL,
		"VIBE_AUTHORITY_ADMIN_TOKEN="+run.authorityAdminToken,
		"VIBE_AUTHORITY_SIGNALING_TOKEN="+run.authoritySignalingToken,
		"VIBE_AUTHORITY_RELAY_TOKEN="+run.authorityRelayToken,
		"VIBE_AUTHORITY_COTURN_TOKEN="+run.authorityCoturnToken,
		"VIBE_AUTHORITY_ROLE_TOKEN_SECRET="+run.authorityRoleSecret,
	)
	if output, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("authority migrate: %v\n%s", err, output)
	}
}

func migrateSignaling(t *testing.T, run *authorityProcessTest) {
	t.Helper()
	migrationPath, err := filepath.Abs("migrations/001_signaling.sql")
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, run.signalingBinary, "--migrate", migrationPath)
	cmd.Env = append(os.Environ(), "VIBE_SIGNALING_DATABASE_URL="+run.signalingDatabaseURL)
	if output, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("signaling migrate: %v\n%s", err, output)
	}
}

func startAuthority(t *testing.T, run *authorityProcessTest) {
	t.Helper()
	configPath := filepath.Join(t.TempDir(), "authority-config.json")
	config := fmt.Sprintf(`{
  "listen_address": %q,
  "maximum_session_ttl_seconds": 900,
  "daily_bytes_per_device": 21474836480,
  "maximum_allocations_per_device": 2,
  "reconciliation_grace_seconds": 120
}`, run.authorityAddress)
	if err := os.WriteFile(configPath, []byte(config), 0o600); err != nil {
		t.Fatal(err)
	}
	cmd := exec.CommandContext(context.Background(), run.authorityBinary, "--config", configPath)
	cmd.Env = append(os.Environ(),
		"VIBE_AUTHORITY_DATABASE_URL="+run.authorityDatabaseURL,
		"VIBE_AUTHORITY_ADMIN_TOKEN="+run.authorityAdminToken,
		"VIBE_AUTHORITY_SIGNALING_TOKEN="+run.authoritySignalingToken,
		"VIBE_AUTHORITY_RELAY_TOKEN="+run.authorityRelayToken,
		"VIBE_AUTHORITY_COTURN_TOKEN="+run.authorityCoturnToken,
		"VIBE_AUTHORITY_ROLE_TOKEN_SECRET="+run.authorityRoleSecret,
	)
	cmd.Stdout = &run.authorityLog
	cmd.Stderr = &run.authorityLog
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	run.authorityCmd = cmd
}

func startSignaling(t *testing.T, run *authorityProcessTest) {
	t.Helper()
	configPath := filepath.Join(t.TempDir(), "signaling-config.json")
	config := fmt.Sprintf(`{
  "listen_address": %q,
  "session_ttl_seconds": 60,
  "max_session_ttl_seconds": 120,
  "max_active_sessions": 100,
  "session_creates_per_minute": 60,
  "messages_per_minute": 120,
  "max_request_body_bytes": 131072,
  "max_sdp_bytes": 65536,
  "max_candidate_bytes": 4096,
  "max_candidates_per_role": 64,
  "max_wait_seconds": 2,
  "max_waiters_per_role": 1,
  "cleanup_interval_seconds": 1,
  "authority_mode": "production_authority",
  "store_backend": "postgres",
  "authority_url": "http://%s"
}`, run.signalingAddress, run.authorityAddress)
	if err := os.WriteFile(configPath, []byte(config), 0o600); err != nil {
		t.Fatal(err)
	}
	cmd := exec.CommandContext(context.Background(), run.signalingBinary, "--config", configPath)
	cmd.Env = append(os.Environ(),
		"VIBE_SIGNALING_ISSUER_TOKEN="+run.signalingIssuerToken,
		"VIBE_SIGNALING_METRICS_TOKEN="+run.signalingMetricsToken,
		"VIBE_SIGNALING_AUTHORITY_TOKEN="+run.authoritySignalingToken,
		"VIBE_SIGNALING_DATABASE_URL="+run.signalingDatabaseURL,
	)
	cmd.Stdout = &run.signalingLog
	cmd.Stderr = &run.signalingLog
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	run.signalingCmd = cmd
}

func startRelay(t *testing.T, run *authorityProcessTest) {
	t.Helper()
	configPath := filepath.Join(t.TempDir(), "relay-config.json")
	config := fmt.Sprintf(`{
  "listen_address": %q,
  "turn_realm": "relay.test",
  "turn_uris": ["turn:127.0.0.1:3478?transport=udp"],
  "credential_ttl_seconds": 60,
  "max_credential_ttl_seconds": 120,
  "credential_requests_per_minute": 60,
  "max_concurrent_sessions_per_device": 2,
  "daily_bytes_per_device": 21474836480,
  "max_usage_event_bytes": 1073741824,
  "egress_microcents_per_gibibyte": 0,
  "state_file": %q,
  "authority_mode": "production_authority",
  "authority_url": "http://%s",
  "authority_source_id": "turn-integration-1"
}`, run.relayAddress, filepath.Join(t.TempDir(), "relay-state.json"), run.authorityAddress)
	if err := os.WriteFile(configPath, []byte(config), 0o600); err != nil {
		t.Fatal(err)
	}
	cmd := exec.CommandContext(context.Background(), run.relayBinary, "--config", configPath)
	cmd.Env = append(os.Environ(),
		"VIBE_RELAY_TURN_SECRET="+run.relayTurnSecret,
		"VIBE_RELAY_CLIENT_TOKEN="+run.relayClientToken,
		"VIBE_RELAY_USAGE_TOKEN="+run.relayUsageToken,
		"VIBE_RELAY_METRICS_TOKEN="+run.relayMetricsToken,
		"VIBE_RELAY_ADMIN_TOKEN="+run.relayAdminToken,
		"VIBE_RELAY_AUTHORITY_TOKEN="+run.authorityRelayToken,
	)
	cmd.Stdout = &run.relayLog
	cmd.Stderr = &run.relayLog
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	run.relayCmd = cmd
}

// stopProcess sends SIGTERM and waits up to 5 seconds for the process to exit.
// It is safe to call on a nil or already-exited command.
func stopProcess(t *testing.T, cmd *exec.Cmd, logBuffer *bytes.Buffer, name string) {
	t.Helper()
	if cmd == nil || cmd.Process == nil {
		return
	}
	if err := cmd.Process.Signal(syscall.SIGTERM); err != nil {
		t.Fatalf("signal %s: %v", name, err)
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("%s exited with error: %v\n%s", name, err, logBuffer.String())
		}
	case <-time.After(5 * time.Second):
		_ = cmd.Process.Kill()
		t.Fatalf("%s did not stop within 5s of SIGTERM\n%s", name, logBuffer.String())
	}
}

// authorityRequest performs an authority admin or signaling-token request and
// asserts the expected status code.
func authorityRequest(t *testing.T, method, url, token, body string, expectedStatus int) {
	t.Helper()
	status, responseBody, err := requestStatus(method, url, token, body)
	if err != nil {
		t.Fatalf("authority request %s %s: %v", method, url, err)
	}
	if status != expectedStatus {
		t.Fatalf("authority %s %s status=%d want=%d body=%s",
			method, url, status, expectedStatus, responseBody)
	}
}

func relayRequest(t *testing.T, method, url, token, body string, expectedStatus int) []byte {
	t.Helper()
	status, responseBody, err := requestStatus(method, url, token, body)
	if err != nil {
		t.Fatalf("relay request %s %s: %v", method, url, err)
	}
	if status != expectedStatus {
		t.Fatalf("relay %s %s status=%d want=%d body=%s", method, url, status, expectedStatus, responseBody)
	}
	return responseBody
}

// pollExpectStatus polls for events and asserts the HTTP status without
// requiring a 200 response. Used after revocation to confirm a 404.
func pollExpectStatus(t *testing.T, baseURL, sessionID, token string, cursor uint64, expectedStatus int) {
	t.Helper()
	const requestTimeout = 5 * time.Second
	ctx, cancel := context.WithTimeout(context.Background(), requestTimeout)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, http.MethodGet,
		fmt.Sprintf("%s/v1/sessions/%s/events?after=%d&wait_seconds=0", baseURL, sessionID, cursor), nil)
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("Authorization", "Bearer "+token)
	client := &http.Client{Timeout: requestTimeout}
	response, err := client.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	body, err := io.ReadAll(response.Body)
	closeErr := response.Body.Close()
	if err != nil {
		t.Fatal(err)
	}
	if closeErr != nil {
		t.Fatalf("close poll response: %v", closeErr)
	}
	if response.StatusCode != expectedStatus {
		t.Fatalf("poll after revoke status=%d want=%d body=%s",
			response.StatusCode, expectedStatus, body)
	}
}

// waitUntilReady polls a /readyz endpoint until it returns 200 or the deadline
// expires.
func waitUntilReady(t *testing.T, url string) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	client := &http.Client{Timeout: 2 * time.Second}
	for ctx.Err() == nil {
		request, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
		if err != nil {
			t.Fatal(err)
		}
		response, err := client.Do(request)
		if err == nil {
			status := response.StatusCode
			if closeErr := response.Body.Close(); closeErr != nil {
				t.Fatalf("close readiness response: %v", closeErr)
			}
			if status == http.StatusOK {
				return
			}
		}
		select {
		case <-ctx.Done():
		case <-time.After(25 * time.Millisecond):
		}
	}
	t.Fatalf("process did not become ready at %s", url)
}

// randomSuffix returns a short unique string for test identifiers. It uses the
// unix-nano timestamp plus a small random component so parallel runs do not
// collide on the same database.
func randomSuffix(t *testing.T) string {
	t.Helper()
	now := time.Now().UnixNano()
	buf := make([]byte, 4)
	if _, err := rand.Read(buf); err != nil {
		t.Fatal(err)
	}
	return fmt.Sprintf("%d-%x", now, buf)
}
