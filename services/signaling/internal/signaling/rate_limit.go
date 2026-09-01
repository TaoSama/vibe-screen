package signaling

import "time"

const (
	createSessionAction      = "create_session"
	localDevelopmentDeviceID = "local_development"
	rateLimitRefillPeriod    = time.Minute
	rateLimitIdleRetention   = 2 * rateLimitRefillPeriod
	postgresRateCleanupLimit = 1000
)

type tokenBucket struct {
	refilledAt      time.Time
	tokensAvailable int
}

func allowFixedWindowRate(window *rateWindow, now time.Time, limit int) bool {
	if window.started.IsZero() || now.Sub(window.started) >= rateLimitRefillPeriod {
		*window = rateWindow{started: now}
	}
	if window.count >= limit {
		return false
	}
	window.count++
	return true
}

func consumeTokenBucket(bucket *tokenBucket, now time.Time, limit int) bool {
	if bucket.refilledAt.IsZero() {
		*bucket = tokenBucket{refilledAt: now, tokensAvailable: limit}
	}
	if now.Sub(bucket.refilledAt) >= rateLimitRefillPeriod {
		bucket.refilledAt = now
		bucket.tokensAvailable = limit
	}
	if bucket.tokensAvailable > limit {
		bucket.tokensAvailable = limit
	}
	if bucket.tokensAvailable <= 0 {
		return false
	}
	bucket.tokensAvailable--
	return true
}

func createRateDeviceIDs(request CreateSessionRequest) []string {
	hostDeviceID := request.HostDeviceID
	clientDeviceID := request.ClientDeviceID
	if hostDeviceID == "" && clientDeviceID == "" {
		return []string{localDevelopmentDeviceID}
	}
	if hostDeviceID == "" {
		return []string{clientDeviceID}
	}
	if clientDeviceID == "" || hostDeviceID == clientDeviceID {
		return []string{hostDeviceID}
	}
	if clientDeviceID < hostDeviceID {
		return []string{clientDeviceID, hostDeviceID}
	}
	return []string{hostDeviceID, clientDeviceID}
}
