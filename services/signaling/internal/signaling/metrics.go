package signaling

import (
	"fmt"
	"io"
	"sync/atomic"
)

type Metrics struct {
	sessionsCreated     atomic.Uint64
	sessionsInvalidated atomic.Uint64
	messagesAccepted    atomic.Uint64
	idempotentReplays   atomic.Uint64
	requestsRejected    atomic.Uint64
	pollTimeouts        atomic.Uint64
	expiredCleaned      atomic.Uint64
}

func (m *Metrics) WritePrometheus(w io.Writer, stats StoreStats) error {
	values := []struct {
		name  string
		help  string
		value uint64
	}{
		{"vibescreen_signaling_sessions_created_total", "Signaling sessions created.", m.sessionsCreated.Load()},
		{"vibescreen_signaling_sessions_invalidated_total", "Signaling sessions invalidated by the authority.", m.sessionsInvalidated.Load()},
		{"vibescreen_signaling_messages_accepted_total", "Validated SDP and ICE messages accepted.", m.messagesAccepted.Load()},
		{"vibescreen_signaling_idempotent_replays_total", "Requests served from idempotency state.", m.idempotentReplays.Load()},
		{"vibescreen_signaling_requests_rejected_total", "Requests rejected by authentication, validation, limits, or state.", m.requestsRejected.Load()},
		{"vibescreen_signaling_poll_timeouts_total", "Long polls that completed without a new sequence.", m.pollTimeouts.Load()},
		{"vibescreen_signaling_expired_cleaned_total", "Expired sessions deleted from memory.", m.expiredCleaned.Load()},
	}
	for _, item := range values {
		if _, err := fmt.Fprintf(w, "# HELP %s %s\n# TYPE %s counter\n%s %d\n", item.name, item.help, item.name, item.name, item.value); err != nil {
			return err
		}
	}
	gauges := []struct {
		name  string
		help  string
		value int
	}{
		{"vibescreen_signaling_active_sessions", "Current unexpired, non-invalidated sessions.", stats.ActiveSessions},
		{"vibescreen_signaling_invalidated_session_tombstones", "Invalidated request tombstones retained until original expiry.", stats.Tombstones},
		{"vibescreen_signaling_reserved_session_records", "Session records consuming max_active_sessions capacity.", stats.ReservedRecords},
		{"vibescreen_signaling_blocked_long_polls", "Long polls currently waiting for an event or session state change.", stats.BlockedWaiters},
	}
	for _, item := range gauges {
		if _, err := fmt.Fprintf(w, "# HELP %s %s\n# TYPE %s gauge\n%s %d\n", item.name, item.help, item.name, item.name, item.value); err != nil {
			return err
		}
	}
	return nil
}
