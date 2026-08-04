export enum SessionState { IDLE = 'idle', CONNECTING = 'connecting', NEGOTIATING = 'negotiating', STREAMING = 'streaming', SUSPENDED = 'suspended', RECONNECTING = 'reconnecting', FAILED = 'failed' }

export class SessionStateMachine {
  private current: SessionState = SessionState.IDLE;
  private epoch: bigint = 0n;

  state(): SessionState { return this.current; }
  sessionEpoch(): bigint { return this.epoch; }

  beginConnect(): void {
    if (this.current !== SessionState.IDLE && this.current !== SessionState.RECONNECTING && this.current !== SessionState.FAILED) {
      throw new Error(`Cannot connect from ${this.current}`);
    }
    this.current = SessionState.CONNECTING;
  }

  transportReady(): void {
    if (this.current !== SessionState.CONNECTING && this.current !== SessionState.RECONNECTING) throw new Error('Transport is not connecting');
    this.current = SessionState.NEGOTIATING;
  }

  accept(epoch: bigint): void {
    if (this.current !== SessionState.NEGOTIATING || epoch <= this.epoch) throw new Error('Invalid session epoch');
    this.epoch = epoch;
    this.current = SessionState.STREAMING;
  }

  suspend(): void { if (this.current === SessionState.STREAMING) this.current = SessionState.SUSPENDED; }
  resumeForeground(): void { if (this.current === SessionState.SUSPENDED) this.current = SessionState.RECONNECTING; }
  disconnected(retryable: boolean): void { this.current = retryable ? SessionState.RECONNECTING : SessionState.FAILED; }
  stop(): void { this.current = SessionState.IDLE; }
  acceptsEpoch(candidate: bigint): boolean { return this.current === SessionState.STREAMING && candidate === this.epoch; }
}

