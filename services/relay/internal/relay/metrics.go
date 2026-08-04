package relay

import (
	"fmt"
	"io"
	"sync/atomic"
)

type Metrics struct {
	credentialIssued atomic.Uint64
	requestRejected  atomic.Uint64
	revokedRejected  atomic.Uint64
	usageAccepted    atomic.Uint64
	ingressBytes     atomic.Uint64
	egressBytes      atomic.Uint64
}

func (m *Metrics) WritePrometheus(w io.Writer, activeSessions int64, estimatedMicrocents uint64) error {
	lines := []struct {
		name, help string
		value      uint64
	}{
		{"vibescreen_relay_credentials_issued_total", "TURN credentials issued.", m.credentialIssued.Load()},
		{"vibescreen_relay_requests_rejected_total", "Requests rejected by authentication, validation, quota, or abuse controls.", m.requestRejected.Load()},
		{"vibescreen_relay_revoked_device_requests_rejected_total", "Credential and usage requests rejected because the device is revoked.", m.revokedRejected.Load()},
		{"vibescreen_relay_usage_events_total", "Accepted usage events.", m.usageAccepted.Load()},
		{"vibescreen_relay_ingress_bytes_total", "Reported relay ingress bytes.", m.ingressBytes.Load()},
		{"vibescreen_relay_egress_bytes_total", "Reported relay egress bytes.", m.egressBytes.Load()},
	}
	for _, line := range lines {
		if _, err := fmt.Fprintf(w, "# HELP %s %s\n# TYPE %s counter\n%s %d\n", line.name, line.help, line.name, line.name, line.value); err != nil {
			return err
		}
	}
	if _, err := fmt.Fprintf(w, "# HELP vibescreen_relay_estimated_daily_egress_microcents Estimated current UTC-day egress cost in millionths of a cent.\n# TYPE vibescreen_relay_estimated_daily_egress_microcents gauge\nvibescreen_relay_estimated_daily_egress_microcents %d\n", estimatedMicrocents); err != nil {
		return err
	}
	if _, err := fmt.Fprintf(w, "# HELP vibescreen_relay_active_sessions Current reported relay sessions.\n# TYPE vibescreen_relay_active_sessions gauge\nvibescreen_relay_active_sessions %d\n", activeSessions); err != nil {
		return err
	}
	return nil
}
