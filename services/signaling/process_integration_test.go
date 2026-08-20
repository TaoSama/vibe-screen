package signaling_test

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
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

const (
	integrationIssuer  = "integration-issuer-token-32-characters-minimum"
	integrationMetrics = "integration-metrics-token-32-characters-minimum"
)

type sessionResponse struct {
	SessionID   string `json:"session_id"`
	HostToken   string `json:"host_token"`
	DeviceToken string `json:"device_token"`
}

type event struct {
	Sequence  uint64 `json:"sequence"`
	MessageID string `json:"message_id"`
	Type      string `json:"type"`
	SDP       string `json:"sdp,omitempty"`
	Candidate *struct {
		Candidate string `json:"candidate"`
	} `json:"candidate,omitempty"`
}

type pollResponse struct {
	Events     []event `json:"events"`
	NextCursor uint64  `json:"next_cursor"`
}

func TestRealProcessHostDeviceExchangeAndGracefulShutdown(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("signal-based process test is Unix-only")
	}
	temporaryDirectory := t.TempDir()
	binaryPath := filepath.Join(temporaryDirectory, "vibe-signaling")
	build := exec.Command("go", "build", "-o", binaryPath, "./cmd/vibe-signaling")
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build signaling process: %v\n%s", err, output)
	}
	address := reserveAddress(t)
	configPath := filepath.Join(temporaryDirectory, "config.json")
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
  "authority_mode": "local_development",
  "store_backend": "memory"
}`, address)
	if err := os.WriteFile(configPath, []byte(config), 0o600); err != nil {
		t.Fatal(err)
	}

	var processLog bytes.Buffer
	command := exec.Command(binaryPath, "--config", configPath)
	command.Env = append(os.Environ(),
		"VIBE_SIGNALING_ISSUER_TOKEN="+integrationIssuer,
		"VIBE_SIGNALING_METRICS_TOKEN="+integrationMetrics,
	)
	command.Stdout = &processLog
	command.Stderr = &processLog
	if err := command.Start(); err != nil {
		t.Fatal(err)
	}
	stopped := false
	defer func() {
		if !stopped && command.Process != nil {
			_ = command.Process.Kill()
			_ = command.Wait()
		}
	}()

	baseURL := "http://" + address
	waitUntilHealthy(t, baseURL+"/healthz")
	created := createSession(t, baseURL, "process-exchange")
	if len(created.HostToken) < 40 || len(created.DeviceToken) < 40 || created.HostToken == created.DeviceToken {
		t.Fatalf("invalid role credentials: %#v", created)
	}

	const offerSDP = "v=0\r\na=fingerprint:sha-256 PROCESS-OFFER-SECRET\r\n"
	postJSON(t, baseURL+"/v1/sessions/"+created.SessionID+"/messages", created.HostToken,
		`{"message_id":"offer-process","type":"offer","sdp":"v=0\r\na=fingerprint:sha-256 PROCESS-OFFER-SECRET\r\n"}`, http.StatusCreated)
	devicePoll := poll(t, baseURL, created.SessionID, created.DeviceToken, 0)
	if len(devicePoll.Events) != 1 || devicePoll.Events[0].SDP != offerSDP {
		t.Fatalf("device offer events: %#v", devicePoll)
	}

	postJSON(t, baseURL+"/v1/sessions/"+created.SessionID+"/messages", created.DeviceToken,
		`{"message_id":"answer-process","type":"answer","sdp":"v=0\r\na=fingerprint:sha-256 PROCESS-ANSWER-SECRET\r\n"}`, http.StatusCreated)
	postJSON(t, baseURL+"/v1/sessions/"+created.SessionID+"/messages", created.DeviceToken,
		`{"message_id":"device-candidate","type":"ice_candidate","candidate":{"candidate":"candidate:DEVICE-PRIVATE-ADDRESS","sdp_mid":"0","sdp_mline_index":0}}`, http.StatusCreated)
	hostPoll := poll(t, baseURL, created.SessionID, created.HostToken, devicePoll.NextCursor)
	if len(hostPoll.Events) != 2 || hostPoll.Events[0].Type != "answer" || hostPoll.Events[1].Candidate.Candidate != "candidate:DEVICE-PRIVATE-ADDRESS" {
		t.Fatalf("host answer/candidate events: %#v", hostPoll)
	}

	postJSON(t, baseURL+"/v1/sessions/"+created.SessionID+"/messages", created.HostToken,
		`{"message_id":"host-candidate","type":"ice_candidate","candidate":{"candidate":"candidate:HOST-PRIVATE-ADDRESS","sdp_mid":"0","sdp_mline_index":0}}`, http.StatusCreated)
	devicePoll = poll(t, baseURL, created.SessionID, created.DeviceToken, hostPoll.NextCursor)
	if len(devicePoll.Events) != 1 || devicePoll.Events[0].Candidate.Candidate != "candidate:HOST-PRIVATE-ADDRESS" {
		t.Fatalf("device candidate events: %#v", devicePoll)
	}

	pollStatus := make(chan int, 1)
	go func() {
		status, _, requestErr := requestStatus(http.MethodGet,
			fmt.Sprintf("%s/v1/sessions/%s/events?after=4&wait_seconds=2", baseURL, created.SessionID),
			created.HostToken, "")
		if requestErr != nil {
			pollStatus <- 0
			return
		}
		pollStatus <- status
	}()
	waitForMetric(t, baseURL+"/metrics", integrationMetrics,
		"vibescreen_signaling_blocked_long_polls", 1)
	status, body, err := requestStatus(http.MethodDelete,
		baseURL+"/v1/sessions/"+created.SessionID, integrationIssuer, "")
	if err != nil || status != http.StatusNoContent {
		t.Fatalf("invalidate session: status=%d err=%v body=%s", status, err, body)
	}
	select {
	case status := <-pollStatus:
		if status != http.StatusNotFound {
			t.Fatalf("invalidated long poll status=%d", status)
		}
	case <-time.After(500 * time.Millisecond):
		t.Fatal("invalidating real-process session did not wake long poll")
	}
	postJSON(t, baseURL+"/v1/sessions/"+created.SessionID+"/messages", created.HostToken,
		`{"message_id":"invalidated-offer","type":"offer","sdp":"v=0"}`, http.StatusNotFound)
	postJSON(t, baseURL+"/v1/sessions", integrationIssuer,
		`{"request_id":"process-exchange"}`, http.StatusConflict)
	status, body, err = requestStatus(http.MethodDelete,
		baseURL+"/v1/sessions/"+created.SessionID, integrationIssuer, "")
	if err != nil || status != http.StatusNoContent {
		t.Fatalf("repeat invalidate session: status=%d err=%v body=%s", status, err, body)
	}

	metricsRequest, err := http.NewRequest(http.MethodGet, baseURL+"/metrics", nil)
	if err != nil {
		t.Fatal(err)
	}
	metricsRequest.Header.Set("Authorization", "Bearer "+integrationMetrics)
	metricsResponse, err := http.DefaultClient.Do(metricsRequest)
	if err != nil {
		t.Fatal(err)
	}
	metricsBody, err := io.ReadAll(metricsResponse.Body)
	_ = metricsResponse.Body.Close()
	if err != nil || metricsResponse.StatusCode != http.StatusOK ||
		!bytes.Contains(metricsBody, []byte("vibescreen_signaling_messages_accepted_total 4")) ||
		!bytes.Contains(metricsBody, []byte("vibescreen_signaling_sessions_invalidated_total 1")) ||
		!bytes.Contains(metricsBody, []byte("vibescreen_signaling_active_sessions 0")) ||
		!bytes.Contains(metricsBody, []byte("vibescreen_signaling_invalidated_session_tombstones 1")) ||
		!bytes.Contains(metricsBody, []byte("vibescreen_signaling_reserved_session_records 1")) ||
		!bytes.Contains(metricsBody, []byte("vibescreen_signaling_blocked_long_polls 0")) {
		t.Fatalf("metrics response: status=%d err=%v body=%s", metricsResponse.StatusCode, err, metricsBody)
	}

	if err := command.Process.Signal(syscall.SIGTERM); err != nil {
		t.Fatal(err)
	}
	waitResult := make(chan error, 1)
	go func() { waitResult <- command.Wait() }()
	select {
	case err := <-waitResult:
		if err != nil {
			t.Fatalf("graceful process exit: %v\n%s", err, processLog.String())
		}
		stopped = true
	case <-time.After(5 * time.Second):
		t.Fatal("signaling process did not stop after SIGTERM")
	}
	logs := processLog.String()
	for _, secret := range []string{offerSDP, "PROCESS-OFFER-SECRET", "PROCESS-ANSWER-SECRET", "DEVICE-PRIVATE-ADDRESS", "HOST-PRIVATE-ADDRESS", created.HostToken, created.DeviceToken} {
		if strings.Contains(logs, secret) {
			t.Fatalf("process log leaked signaling content %q: %s", secret, logs)
		}
	}
}

func reserveAddress(t *testing.T) string {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	address := listener.Addr().String()
	if err := listener.Close(); err != nil {
		t.Fatal(err)
	}
	return address
}

func waitUntilHealthy(t *testing.T, url string) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		response, err := http.Get(url)
		if err == nil {
			_ = response.Body.Close()
			if response.StatusCode == http.StatusOK {
				return
			}
		}
		time.Sleep(25 * time.Millisecond)
	}
	t.Fatalf("process did not become healthy at %s", url)
}

func waitForMetric(t *testing.T, url, token, name string, expected int) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	wanted := fmt.Sprintf("%s %d", name, expected)
	lastStatus := 0
	var lastBody []byte
	var lastErr error
	for time.Now().Before(deadline) {
		lastStatus, lastBody, lastErr = requestStatus(http.MethodGet, url, token, "")
		if lastErr == nil && lastStatus == http.StatusOK {
			for _, line := range strings.Split(string(lastBody), "\n") {
				if line == wanted {
					return
				}
			}
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("metric %q did not reach %d: status=%d err=%v body=%s", name, expected, lastStatus, lastErr, lastBody)
}

func createSession(t *testing.T, baseURL, requestID string) sessionResponse {
	t.Helper()
	response := postJSON(t, baseURL+"/v1/sessions", integrationIssuer,
		fmt.Sprintf(`{"request_id":%q}`, requestID), http.StatusCreated)
	var created sessionResponse
	if err := json.Unmarshal(response, &created); err != nil {
		t.Fatal(err)
	}
	return created
}

func poll(t *testing.T, baseURL, sessionID, token string, cursor uint64) pollResponse {
	t.Helper()
	request, err := http.NewRequestWithContext(context.Background(), http.MethodGet,
		fmt.Sprintf("%s/v1/sessions/%s/events?after=%d&wait_seconds=1", baseURL, sessionID, cursor), nil)
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("Authorization", "Bearer "+token)
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != http.StatusOK {
		t.Fatalf("poll status=%d body=%s", response.StatusCode, body)
	}
	var result pollResponse
	if err := json.Unmarshal(body, &result); err != nil {
		t.Fatal(err)
	}
	return result
}

func postJSON(t *testing.T, url, token, body string, expectedStatus int) []byte {
	t.Helper()
	request, err := http.NewRequest(http.MethodPost, url, strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("Authorization", "Bearer "+token)
	request.Header.Set("Content-Type", "application/json")
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	responseBody, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != expectedStatus {
		t.Fatalf("POST %s status=%d want=%d body=%s", url, response.StatusCode, expectedStatus, responseBody)
	}
	return responseBody
}

func requestStatus(method, url, token, body string) (int, []byte, error) {
	request, err := http.NewRequest(method, url, strings.NewReader(body))
	if err != nil {
		return 0, nil, err
	}
	request.Header.Set("Authorization", "Bearer "+token)
	if body != "" {
		request.Header.Set("Content-Type", "application/json")
	}
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		return 0, nil, err
	}
	defer response.Body.Close()
	responseBody, err := io.ReadAll(response.Body)
	return response.StatusCode, responseBody, err
}
