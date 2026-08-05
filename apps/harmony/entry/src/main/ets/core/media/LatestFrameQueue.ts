export interface EncodedFrame {
  frameId: bigint;
  epoch: bigint;
  timestampNs: bigint;
  keyframe: boolean;
  payload: Uint8Array;
}

export enum FrameQueueState {
  WAITING_FOR_KEYFRAME = 'waiting_for_keyframe',
  KEYFRAME_PENDING = 'keyframe_pending',
  DECODABLE = 'decodable'
}

export interface FrameQueueEffect {
  accepted: boolean;
  dropped: number;
  requestKeyframe: boolean;
}

/**
 * Capacity-one ingress queue that never submits a frame after losing one of
 * its references. A frame remains in flight until the decoder confirms that
 * pushInputData accepted it.
 */
export class LatestFrameQueue {
  private pending: EncodedFrame | undefined;
  private inFlight: EncodedFrame | undefined;
  private expectedEpoch: bigint = 0n;
  private currentState: FrameQueueState = FrameQueueState.WAITING_FOR_KEYFRAME;
  private lastCommittedFrameId: bigint | undefined;
  private requestOutstanding: boolean = false;
  private dropped: number = 0;

  reset(expectedEpoch: bigint): FrameQueueEffect {
    const dropped: number = this.clearFrames();
    this.expectedEpoch = expectedEpoch;
    this.currentState = FrameQueueState.WAITING_FOR_KEYFRAME;
    this.lastCommittedFrameId = undefined;
    this.requestOutstanding = false;
    return this.waitEffect(false, dropped);
  }

  offer(frame: EncodedFrame): FrameQueueEffect {
    if (frame.epoch !== this.expectedEpoch) return this.dropIncoming(false);

    if (frame.keyframe) {
      const dropped: number = this.pending === undefined ? 0 : 1;
      this.dropped += dropped;
      this.pending = frame;
      this.currentState = FrameQueueState.KEYFRAME_PENDING;
      this.requestOutstanding = false;
      return { accepted: true, dropped, requestKeyframe: false };
    }

    if (this.currentState === FrameQueueState.WAITING_FOR_KEYFRAME) {
      return this.dropIncoming(true);
    }
    if (this.currentState === FrameQueueState.KEYFRAME_PENDING) {
      if (this.pending?.keyframe === true) return this.dropIncoming(false);
      const keyframeInFlight: EncodedFrame | undefined = this.inFlight?.keyframe === true ? this.inFlight : undefined;
      if (keyframeInFlight === undefined || frame.frameId !== keyframeInFlight.frameId + 1n) {
        return this.loseReference();
      }
      this.pending = frame;
      return { accepted: true, dropped: 0, requestKeyframe: false };
    }

    const predecessor: EncodedFrame | undefined = this.pending ?? this.inFlight;
    const predecessorId: bigint | undefined = predecessor?.frameId ?? this.lastCommittedFrameId;
    if (predecessorId === undefined || frame.frameId !== predecessorId + 1n) {
      return this.loseReference();
    }
    if (this.pending !== undefined) return this.loseReference();

    this.pending = frame;
    return { accepted: true, dropped: 0, requestKeyframe: false };
  }

  beginPush(): EncodedFrame | undefined {
    if (this.inFlight !== undefined || this.pending === undefined) return undefined;
    this.inFlight = this.pending;
    this.pending = undefined;
    return this.inFlight;
  }

  completePush(succeeded: boolean): FrameQueueEffect {
    const completed: EncodedFrame | undefined = this.inFlight;
    if (completed === undefined) throw new Error('No decoder input push is in flight');
    this.inFlight = undefined;

    if (!succeeded) {
      const dropped: number = 1 + (this.pending === undefined ? 0 : 1);
      this.pending = undefined;
      this.dropped += dropped;
      this.currentState = FrameQueueState.WAITING_FOR_KEYFRAME;
      this.lastCommittedFrameId = undefined;
      return this.waitEffect(false, dropped);
    }

    this.lastCommittedFrameId = completed.frameId;
    if (completed.keyframe) {
      this.requestOutstanding = false;
      this.currentState = this.pending?.keyframe === true
        ? FrameQueueState.KEYFRAME_PENDING : FrameQueueState.DECODABLE;
    }
    return { accepted: true, dropped: 0, requestKeyframe: false };
  }

  clear(): number {
    const dropped: number = this.clearFrames();
    this.currentState = FrameQueueState.WAITING_FOR_KEYFRAME;
    this.lastCommittedFrameId = undefined;
    this.requestOutstanding = false;
    return dropped;
  }

  state(): FrameQueueState { return this.currentState; }
  depth(): number { return this.pending === undefined ? 0 : 1; }
  hasPushInFlight(): boolean { return this.inFlight !== undefined; }
  droppedCount(): number { return this.dropped; }

  private loseReference(): FrameQueueEffect {
    let dropped: number = 1;
    if (this.pending !== undefined) { this.pending = undefined; dropped += 1; }
    this.dropped += dropped;
    this.currentState = FrameQueueState.WAITING_FOR_KEYFRAME;
    this.lastCommittedFrameId = undefined;
    return this.waitEffect(false, dropped);
  }

  private dropIncoming(requestKeyframe: boolean): FrameQueueEffect {
    this.dropped += 1;
    return this.waitEffect(false, 1, requestKeyframe);
  }

  private waitEffect(accepted: boolean, dropped: number, allowRequest: boolean = true): FrameQueueEffect {
    const requestKeyframe: boolean = allowRequest && !this.requestOutstanding;
    if (requestKeyframe) this.requestOutstanding = true;
    return { accepted, dropped, requestKeyframe };
  }

  private clearFrames(): number {
    const dropped: number = (this.pending === undefined ? 0 : 1) + (this.inFlight === undefined ? 0 : 1);
    this.pending = undefined;
    this.inFlight = undefined;
    this.dropped += dropped;
    return dropped;
  }
}
