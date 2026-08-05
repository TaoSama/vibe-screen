import { EnvelopeMetadata, PROTOCOL_VERSION } from './ProtocolModels';
import { OutboundControlIntent, ProtocolEncoder } from './ProtocolEncoder';

export const MAX_PENDING_CONTROLS: number = 128;

export interface OutboundControlScope {
  sessionId: Uint8Array;
  sessionEpoch: bigint;
}

export interface OutboundControlReceipt {
  messageId: bigint;
  bytes: Uint8Array;
}

interface PendingControl {
  intent: OutboundControlIntent;
  scope: OutboundControlScope;
  resolve: (receipt: OutboundControlReceipt) => void;
  reject: (error: Error) => void;
  onAssigned?: ControlAssignment;
}

export type ControlSender = (bytes: Uint8Array) => Promise<void>;
export type MonotonicClock = () => bigint;
export type ControlAssignment = (messageId: bigint, sentAtMonotonicNs: bigint) => void;

export class OutboundControlWriter {
  private readonly encoder: ProtocolEncoder = new ProtocolEncoder();
  private readonly criticalQueue: PendingControl[] = [];
  private readonly inputQueue: PendingControl[] = [];
  private nextMessageId: bigint = 1n;
  private draining: boolean = false;
  private failure: Error | undefined;
  private active: PendingControl | undefined;

  constructor(private sender: ControlSender, private clock: MonotonicClock) {}

  enqueue(intent: OutboundControlIntent, scope: OutboundControlScope,
    onAssigned?: ControlAssignment): Promise<OutboundControlReceipt> {
    if (this.failure !== undefined) return Promise.reject(this.failure);
    if (this.queuedCount() >= MAX_PENDING_CONTROLS) {
      const failure: Error = new Error('Control writer backlog exceeded its bounded capacity');
      this.fail(failure);
      return Promise.reject(failure);
    }
    return new Promise((resolve, reject) => {
      const pending: PendingControl = { intent,
        scope: { sessionId: scope.sessionId.slice(), sessionEpoch: scope.sessionEpoch }, resolve, reject, onAssigned };
      if (this.isInput(intent)) this.inputQueue.push(pending);
      else this.criticalQueue.push(pending);
      this.drain();
    });
  }

  close(reason: string = 'Control writer closed'): void {
    this.fail(new Error(reason));
  }

  private drain(): void {
    if (this.draining || this.failure !== undefined) return;
    const pending: PendingControl | undefined = this.criticalQueue.shift() ?? this.inputQueue.shift();
    if (pending === undefined) return;
    this.draining = true; this.active = pending;
    const messageId: bigint = this.nextMessageId++;
    const sentAtMonotonicNs: bigint = this.clock();
    const metadata: EnvelopeMetadata = {
      protocolVersion: PROTOCOL_VERSION,
      messageId,
      correlationId: 0n,
      sessionId: pending.scope.sessionId,
      sessionEpoch: pending.scope.sessionEpoch,
      sentAtMonotonicNs
    };
    let bytes: Uint8Array;
    try {
      pending.onAssigned?.(messageId, sentAtMonotonicNs);
      bytes = this.encoder.intent(metadata, pending.intent);
      this.sender(bytes).then(() => {
        this.draining = false; this.active = undefined;
        if (this.failure === undefined) pending.resolve({ messageId, bytes });
        this.drain();
      }).catch((error: Error) => {
        this.draining = false;
        this.fail(error);
        this.active = undefined;
      });
    } catch (error) {
      this.draining = false; this.active = undefined;
      const failure: Error = error instanceof Error ? error : new Error(String(error));
      pending.reject(failure);
      this.fail(failure);
    }
  }

  private fail(error: Error): void {
    if (this.failure !== undefined) return;
    this.failure = error;
    this.active?.reject(error);
    while (this.criticalQueue.length > 0) this.criticalQueue.shift()?.reject(error);
    while (this.inputQueue.length > 0) this.inputQueue.shift()?.reject(error);
  }

  private queuedCount(): number { return this.criticalQueue.length + this.inputQueue.length; }

  private isInput(intent: OutboundControlIntent): boolean {
    return intent.kind === 'touch' || intent.kind === 'pointer' || intent.kind === 'scroll' || intent.kind === 'key';
  }
}
