package signaling

import (
	"fmt"
	"io"
	"sync/atomic"
)

type Metrics struct {
	sessionsCreated   atomic.Uint64
	messagesAccepted  atomic.Uint64
	idempotentReplays atomic.Uint64
	requestsRejected  atomic.Uint64
	pollTimeouts      atomic.Uint64
	expiredCleaned    atomic.Uint64
}

func (m *Metrics) WritePrometheus(w io.Writer, activeSessions int) error {
	values := []struct {
		name  string
		help  string
		value uint64
	}{
		{"vibescreen_signaling_sessions_created_total", "Signaling sessions created.", m.sessionsCreated.Load()},
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
	_, err := fmt.Fprintf(w, "# HELP vibescreen_signaling_active_sessions Current unexpired sessions.\n# TYPE vibescreen_signaling_active_sessions gauge\nvibescreen_signaling_active_sessions %d\n", activeSessions)
	return err
}
