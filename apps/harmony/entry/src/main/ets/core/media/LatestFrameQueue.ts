export interface EncodedFrame { frameId: bigint; epoch: bigint; keyframe: boolean; payload: Uint8Array; }

export class LatestFrameQueue {
  private pending: EncodedFrame | undefined;
  private dropped: number = 0;

  offer(frame: EncodedFrame): void {
    if (this.pending !== undefined) this.dropped += 1;
    this.pending = frame;
  }

  poll(expectedEpoch: bigint): EncodedFrame | undefined {
    const frame: EncodedFrame | undefined = this.pending;
    this.pending = undefined;
    if (frame !== undefined && frame.epoch !== expectedEpoch) { this.dropped += 1; return undefined; }
    return frame;
  }

  clear(): void { if (this.pending !== undefined) this.dropped += 1; this.pending = undefined; }
  depth(): number { return this.pending === undefined ? 0 : 1; }
  droppedCount(): number { return this.dropped; }
}

