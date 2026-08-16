package authority

import (
	"testing"
	"time"
)

func TestValidateDatabaseClockUsesConservativeRequestWindow(t *testing.T) {
	base := time.Date(2026, time.August, 16, 12, 0, 0, 0, time.UTC)
	hostBefore := base
	hostAfter := base.Add(2 * time.Second)
	maximumSkew := 5 * time.Second

	tests := []struct {
		name        string
		databaseNow time.Time
		wantError   bool
	}{
		{name: "zero skew", databaseNow: base.Add(time.Second)},
		{name: "negative boundary", databaseNow: hostAfter.Add(-maximumSkew)},
		{name: "positive boundary", databaseNow: hostBefore.Add(maximumSkew)},
		{name: "negative beyond boundary", databaseNow: hostAfter.Add(-maximumSkew - time.Nanosecond), wantError: true},
		{name: "positive beyond boundary", databaseNow: hostBefore.Add(maximumSkew + time.Nanosecond), wantError: true},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			err := validateDatabaseClock(test.databaseNow, hostBefore, hostAfter, maximumSkew)
			if (err != nil) != test.wantError {
				t.Fatalf("validateDatabaseClock() error=%v, wantError=%t", err, test.wantError)
			}
		})
	}
}

func TestValidateDatabaseClockRejectsUntrustworthySamples(t *testing.T) {
	base := time.Date(2026, time.August, 16, 12, 0, 0, 0, time.UTC)
	tests := []struct {
		name                               string
		databaseNow, hostBefore, hostAfter time.Time
		maximumSkew                        time.Duration
	}{
		{name: "zero database sample", hostBefore: base, hostAfter: base, maximumSkew: time.Second},
		{name: "zero host before sample", databaseNow: base, hostAfter: base, maximumSkew: time.Second},
		{name: "zero host after sample", databaseNow: base, hostBefore: base, maximumSkew: time.Second},
		{name: "non-positive limit", databaseNow: base, hostBefore: base, hostAfter: base},
		{name: "host clock moved backwards", databaseNow: base, hostBefore: base, hostAfter: base.Add(-time.Nanosecond), maximumSkew: time.Second},
		{name: "request window wider than tolerance", databaseNow: base.Add(time.Second), hostBefore: base, hostAfter: base.Add(3 * time.Second), maximumSkew: time.Second},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if err := validateDatabaseClock(test.databaseNow, test.hostBefore, test.hostAfter, test.maximumSkew); err == nil {
				t.Fatal("untrustworthy clock sample was accepted")
			}
		})
	}
}
