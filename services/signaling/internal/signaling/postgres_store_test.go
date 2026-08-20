package signaling

import (
	"context"
	"errors"
	"testing"
)

func TestNotificationSlotLimitLeavesQueryCapacity(t *testing.T) {
	if got := notificationSlotLimit(8); got != 7 {
		t.Fatalf("notificationSlotLimit(8)=%d, want 7", got)
	}
	if got := notificationSlotLimit(2); got != 1 {
		t.Fatalf("notificationSlotLimit(2)=%d, want 1", got)
	}
	if got := notificationSlotLimit(1); got != 0 {
		t.Fatalf("notificationSlotLimit(1)=%d, want 0", got)
	}
	if got := notificationSlotLimit(0); got != 0 {
		t.Fatalf("notificationSlotLimit(0)=%d, want 0", got)
	}
}

func TestPostgresOpenNotificationListenerEnforcesProcessLimit(t *testing.T) {
	store := &PostgresStore{notificationSlots: make(chan struct{}, 1)}
	store.notificationSlots <- struct{}{}
	if _, err := store.openNotificationListener(context.Background()); !errors.Is(err, ErrTooManyWaiters) {
		t.Fatalf("openNotificationListener error=%v, want ErrTooManyWaiters", err)
	}
}
