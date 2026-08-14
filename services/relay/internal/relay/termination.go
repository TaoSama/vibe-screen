package relay

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

type allocationTerminationRequest struct {
	RevocationID string `json:"revocation_id"`
	DeviceID     string `json:"device_id"`
}

type allocationTerminator interface {
	Terminate(context.Context, allocationTerminationRequest) error
}

type webhookAllocationTerminator struct {
	endpoint string
	token    string
	client   *http.Client
}

func newWebhookAllocationTerminator(cfg Config) allocationTerminator {
	if cfg.AllocationTerminationWebhookURL == "" {
		return nil
	}
	return &webhookAllocationTerminator{
		endpoint: cfg.AllocationTerminationWebhookURL,
		token:    cfg.TerminationToken,
		client: &http.Client{
			Timeout: time.Duration(cfg.AllocationTerminationTimeoutSeconds) * time.Second,
			CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
	}
}

func (t *webhookAllocationTerminator) Terminate(ctx context.Context, event allocationTerminationRequest) error {
	body, err := json.Marshal(event)
	if err != nil {
		return fmt.Errorf("encode termination request: %w", err)
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, t.endpoint, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("create termination request: %w", err)
	}
	request.Header.Set("Authorization", "Bearer "+t.token)
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Idempotency-Key", event.RevocationID)
	response, err := t.client.Do(request)
	if err != nil {
		return fmt.Errorf("call termination webhook: %w", err)
	}
	if _, err := io.Copy(io.Discard, io.LimitReader(response.Body, 4096)); err != nil {
		_ = response.Body.Close()
		return fmt.Errorf("read termination webhook response: %w", err)
	}
	if err := response.Body.Close(); err != nil {
		return fmt.Errorf("close termination webhook response: %w", err)
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return fmt.Errorf("termination webhook returned HTTP %d", response.StatusCode)
	}
	return nil
}
