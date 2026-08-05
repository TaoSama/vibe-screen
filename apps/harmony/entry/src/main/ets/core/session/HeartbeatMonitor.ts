const NANOSECONDS_PER_MILLISECOND: bigint = 1000000n;
const MISSED_HEARTBEAT_LIMIT: bigint = 3n;

export interface PendingHeartbeat {
  sequence: bigint;
  messageId: bigint;
  deadlineNs: bigint;
}

export class HeartbeatMonitor {
  private intervalMs: number = 0;
  private pending: PendingHeartbeat | undefined;

  configure(intervalMs: number): void {
    if (!Number.isInteger(intervalMs) || intervalMs <= 0) throw new Error('Heartbeat interval must be positive');
    this.intervalMs = intervalMs;
    this.pending = undefined;
  }

  canSend(): boolean { return this.intervalMs > 0 && this.pending === undefined; }

  reserve(sequence: bigint): void {
    if (!this.canSend() || sequence <= 0n) throw new Error('A heartbeat is already pending');
    this.pending = { sequence, messageId: 0n, deadlineNs: 0n };
  }

  sent(sequence: bigint, messageId: bigint, nowNs: bigint): void {
    if (this.pending?.sequence !== sequence || this.pending.messageId !== 0n || messageId <= 0n) {
      throw new Error('Heartbeat send completion does not match the reservation');
    }
    const timeoutNs: bigint = BigInt(this.intervalMs) * MISSED_HEARTBEAT_LIMIT * NANOSECONDS_PER_MILLISECOND;
    this.pending = { sequence, messageId, deadlineNs: nowNs + timeoutNs };
  }

  acceptPong(sequence: bigint, correlationId: bigint): boolean {
    const pending: PendingHeartbeat | undefined = this.pending;
    if (pending === undefined || pending.sequence !== sequence || pending.messageId !== correlationId) return false;
    this.pending = undefined;
    return true;
  }

  timedOut(nowNs: bigint): boolean {
    return this.pending !== undefined && this.pending.messageId > 0n && nowNs >= this.pending.deadlineNs;
  }

  hasPending(): boolean { return this.pending !== undefined; }

  current(): PendingHeartbeat | undefined {
    return this.pending === undefined ? undefined : { ...this.pending };
  }

  reset(): void { this.intervalMs = 0; this.pending = undefined; }
}
