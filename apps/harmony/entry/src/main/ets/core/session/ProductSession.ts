import { MediaPacket } from '../media/MediaPacketParser';
import { DecodedEnvelope, ProtocolDecoder } from '../protocol/ProtocolDecoder';
import { OutboundControlIntent } from '../protocol/ProtocolEncoder';
import { Capability, ClientHello, Codec, ColorPrimaries, InputPhase, InputTarget, KeyInput, MatrixCoefficients,
  NormalizedInput, PROTOCOL_VERSION, ScrollInput, TransferFunction, TransportKind, VideoConfig } from '../protocol/ProtocolModels';
import { OutboundControlScope } from '../protocol/OutboundControlWriter';
import { ClientCapabilities, HARMONY_REQUIRED_CAPABILITIES } from './ClientCapabilities';
import { HeartbeatMonitor } from './HeartbeatMonitor';

export const MAX_VIDEO_WIDTH: number = 1920;
export const MAX_VIDEO_HEIGHT: number = 1200;
export const MAX_VIDEO_FPS: number = 60;
const MIN_VIDEO_DIMENSION: number = 16;
const MIN_HEARTBEAT_MS: number = 250;
const MAX_HEARTBEAT_MS: number = 30000;
const MAX_VIDEO_BITRATE_KBPS: number = 100000;

export function isSupportedVideoConfig(config: VideoConfig, streamId: bigint, configEpoch: bigint,
  codecs: Codec[], hostCodecs: Set<number>): boolean {
  const colorSupported: boolean = config.colorDescription === undefined ||
    (config.colorDescription.bitDepth === 8 && config.colorDescription.primaries === ColorPrimaries.BT709 &&
      (config.colorDescription.transferFunction === TransferFunction.BT709 ||
        config.colorDescription.transferFunction === TransferFunction.SRGB) &&
      config.colorDescription.matrixCoefficients === MatrixCoefficients.BT709);
  return config.streamId === streamId && config.configEpoch > configEpoch &&
    config.width >= MIN_VIDEO_DIMENSION && config.width <= MAX_VIDEO_WIDTH &&
    config.height >= MIN_VIDEO_DIMENSION && config.height <= MAX_VIDEO_HEIGHT &&
    config.framesPerSecond >= 1 && config.framesPerSecond <= MAX_VIDEO_FPS &&
    config.bitrateKbps >= 1 && config.bitrateKbps <= MAX_VIDEO_BITRATE_KBPS && colorSupported &&
    [0, 90, 180, 270].includes(config.rotationDegrees) && codecs.includes(config.codec) && hostCodecs.has(config.codec);
}

export enum ProductSessionState {
  IDLE = 'idle', AWAITING_RESUME = 'awaiting_resume', AWAITING_HOST = 'awaiting_host', AWAITING_SESSION = 'awaiting_session',
  SELECTING_DISPLAY = 'selecting_display', STARTING_DISPLAY = 'starting_display',
  AWAITING_VIDEO = 'awaiting_video', CONFIGURING_VIDEO = 'configuring_video', STREAMING = 'streaming', CLOSED = 'closed'
}

export interface VideoConfigurationToken { id: bigint; config: VideoConfig; correlationId: bigint; }
export interface SessionResumeSnapshot {
  sessionId: Uint8Array;
  sessionEpoch: bigint;
  lastReceivedMessageId: bigint;
  nextOutboundMessageId: bigint;
  heartbeatIntervalMs: number;
  hostCapabilities: Capability[];
  negotiatedCapabilities: Capability[];
  hostCodecs: Codec[];
}
export type SessionControlAssignment =
  | { kind: 'heartbeat'; sequence: bigint }
  | { kind: 'request'; request: 'resume' | 'clientHello' | 'listDisplays' | 'startDisplay' };
export type SessionSendCompletion =
  { kind: 'videoConfiguration'; token: VideoConfigurationToken; accepted: boolean };

export type SessionSendAction =
  { kind: 'send'; intent: OutboundControlIntent; onAssigned?: SessionControlAssignment; afterSend?: SessionSendCompletion };
export type SessionAction =
  | SessionSendAction
  | { kind: 'configureVideo'; config: VideoConfig; token: VideoConfigurationToken }
  | { kind: 'heartbeat'; intervalMs: number }
  | { kind: 'displayChanged'; width: number; height: number; rotationDegrees: number }
  | { kind: 'media'; packet: MediaPacket }
  | { kind: 'disconnect'; reason: string; retryable: boolean };

export class ProductSession {
  private current: ProductSessionState = ProductSessionState.IDLE;
  private lastInboundMessageId: bigint = 0n;
  private sessionId: Uint8Array = new Uint8Array();
  private sessionEpoch: bigint = 0n;
  private streamId: bigint = 0n;
  private configEpoch: bigint = 0n;
  private lastFrameId: bigint = 0n;
  private displayId: string = '';
  private configuredCodec: Codec = Codec.UNSPECIFIED;
  private heartbeatIntervalMs: number = 0;
  private hostCodecs: Set<number> = new Set();
  private capabilityState: ClientCapabilities;
  private heartbeatMonitor: HeartbeatMonitor = new HeartbeatMonitor();
  private nextVideoTokenId: bigint = 1n;
  private pendingVideo: VideoConfigurationToken | undefined;
  private videoResultPrepared: boolean = false;
  private clientHelloMessageId: bigint = 0n;
  private resumeMessageId: bigint = 0n;
  private resumeSnapshot: SessionResumeSnapshot | undefined;
  private listDisplaysMessageId: bigint = 0n;
  private startDisplayMessageId: bigint = 0n;
  private decoder: ProtocolDecoder = new ProtocolDecoder();

  constructor(private deviceId: string, private deviceName: string,
    private capabilities: Capability[], private codecs: Codec[]) {
    if (deviceId.length === 0 || deviceName.length === 0 || codecs.length === 0) throw new Error('Invalid client identity or codecs');
    this.capabilityState = new ClientCapabilities(capabilities, HARMONY_REQUIRED_CAPABILITIES);
  }

  state(): ProductSessionState { return this.current; }
  epoch(): bigint { return this.sessionEpoch; }
  heartbeatMs(): number { return this.heartbeatIntervalMs; }
  target(): InputTarget { return { displayId: this.displayId, streamId: this.streamId }; }
  outboundScope(): OutboundControlScope { return { sessionId: this.sessionId.slice(), sessionEpoch: this.sessionEpoch }; }
  canSend(capability: Capability): boolean { return this.capabilityState.has(capability); }
  negotiatedCapabilities(): Capability[] { return this.capabilityState.values(); }

  resumableSnapshot(nextOutboundMessageId: bigint): SessionResumeSnapshot | undefined {
    if (this.current !== ProductSessionState.STREAMING || this.pendingVideo !== undefined || nextOutboundMessageId <= 0n ||
      this.sessionEpoch <= 0n || !this.capabilityState.has(Capability.SESSION_RESUME) || this.heartbeatIntervalMs <= 0) return undefined;
    return { sessionId: this.sessionId.slice(), sessionEpoch: this.sessionEpoch,
      lastReceivedMessageId: this.lastInboundMessageId, nextOutboundMessageId, heartbeatIntervalMs: this.heartbeatIntervalMs,
      hostCapabilities: this.capabilityState.hostValues(), negotiatedCapabilities: this.capabilityState.values(),
      hostCodecs: [...this.hostCodecs] as Codec[] };
  }

  start(nowNs: bigint, resume?: SessionResumeSnapshot): SessionAction[] {
    if (this.current !== ProductSessionState.IDLE && this.current !== ProductSessionState.CLOSED) throw new Error('Session already started');
    this.resetRuntime();
    if (resume !== undefined) {
      this.validateResumeSnapshot(resume);
      this.resumeSnapshot = { ...resume, sessionId: resume.sessionId.slice(), hostCapabilities: [...resume.hostCapabilities],
        negotiatedCapabilities: [...resume.negotiatedCapabilities], hostCodecs: [...resume.hostCodecs] };
      this.sessionId = resume.sessionId.slice(); this.sessionEpoch = resume.sessionEpoch;
      this.lastInboundMessageId = resume.lastReceivedMessageId;
      this.current = ProductSessionState.AWAITING_RESUME;
      return [{ kind: 'send', intent: { kind: 'resume', previousEpoch: resume.sessionEpoch,
        lastMessageId: resume.lastReceivedMessageId }, onAssigned: { kind: 'request', request: 'resume' } }];
    }
    this.current = ProductSessionState.AWAITING_HOST;
    return this.clientHelloAction();
  }

  private clientHelloAction(): SessionAction[] {
    const hello: ClientHello = {
      minimumProtocol: PROTOCOL_VERSION, maximumProtocol: PROTOCOL_VERSION, deviceId: this.deviceId,
      deviceName: this.deviceName, capabilities: this.capabilities, codecs: this.codecs, transports: [TransportKind.LAN],
      requiredCapabilities: HARMONY_REQUIRED_CAPABILITIES,
      resourceLimits: { maximumClients: 1, maximumDisplays: 1, maximumVideoStreams: 1 },
      videoDecodeCapabilities: this.codecs.map((codec: Codec) => ({ codec, maximumWidth: MAX_VIDEO_WIDTH,
        maximumHeight: MAX_VIDEO_HEIGHT, maximumFramesPerSecond: MAX_VIDEO_FPS, bitDepths: [8] }))
    };
    return [{ kind: 'send', intent: { kind: 'clientHello', hello },
      onAssigned: { kind: 'request', request: 'clientHello' } }];
  }

  receive(bytes: Uint8Array, nowNs: bigint): SessionAction[] {
    const envelope: DecodedEnvelope = this.decoder.envelope(bytes);
    this.validateEnvelope(envelope);
    if (this.current === ProductSessionState.AWAITING_RESUME && envelope.payloadField !== 27) {
      throw new Error('Only ResumeSessionResult is valid while resuming');
    }
    this.lastInboundMessageId = envelope.messageId;
    if (envelope.payloadField === 21) return this.onHostHello(envelope);
    if (envelope.payloadField === 22) return this.onSessionAccepted(envelope, nowNs);
    if (envelope.payloadField === 27) return this.onResumeResult(envelope);
    if (envelope.payloadField === 23) {
      if (this.current !== ProductSessionState.AWAITING_SESSION) throw new Error('Unexpected SessionRejected');
      this.requireCorrelation(envelope, this.clientHelloMessageId, false);
      return this.onFailure(envelope, false);
    }
    if (envelope.payloadField === 24) return [{ kind: 'send', intent: { kind: 'pong',
      correlationId: envelope.messageId, sequence: this.decoder.sequence(envelope.payload) } }];
    if (envelope.payloadField === 25) {
      if (!this.heartbeatMonitor.acceptPong(this.decoder.sequence(envelope.payload), envelope.correlationId)) {
        throw new Error('Pong does not match the pending heartbeat');
      }
      return [];
    }
    if (envelope.payloadField === 64) return [];
    if (envelope.payloadField === 28) {
      const notice = this.decoder.disconnectNotice(envelope.payload);
      return [{ kind: 'disconnect', reason: notice.reason || 'host_disconnect', retryable: notice.mayResume }];
    }
    if (envelope.payloadField === 41) return this.onDisplays(envelope, nowNs);
    if (envelope.payloadField === 43) return this.onStartDisplay(envelope);
    if (envelope.payloadField === 45) return this.onDisplayChanged(envelope);
    if (envelope.payloadField === 50) return this.onVideoConfig(envelope, nowNs);
    if (envelope.payloadField === 53) return [{ kind: 'disconnect', reason: 'video_stream_ended', retryable: true }];
    if (envelope.payloadField === 80) return this.onFailure(envelope, true);
    throw new Error(`Unexpected Protocol v1 payload ${envelope.payloadField} in ${this.current}`);
  }

  acceptMedia(packet: MediaPacket): SessionAction[] {
    const header = packet.header;
    if (this.current !== ProductSessionState.STREAMING) throw new Error('Media arrived before video configuration');
    if (header.sessionEpoch < this.sessionEpoch || header.frameId <= this.lastFrameId) return [];
    if (header.sessionEpoch > this.sessionEpoch) throw new Error('Media belongs to a future session epoch');
    if (header.configEpoch < this.configEpoch) return [];
    if (header.streamId !== this.streamId || header.configEpoch > this.configEpoch) throw new Error('Cross-stream media');
    if (header.codec !== this.configuredCodec || header.fragmentCount !== 1 || header.fragmentIndex !== 0) {
      throw new Error('Unsupported media packet');
    }
    this.lastFrameId = header.frameId;
    return [{ kind: 'media', packet }];
  }

  touch(event: NormalizedInput): SessionAction {
    this.requireInputCapability(Capability.TOUCH);
    this.validateNormalizedInput(event);
    return { kind: 'send', intent: { kind: 'touch', event, target: this.target() } };
  }

  pointer(event: NormalizedInput): SessionAction {
    this.requireInputCapability(Capability.POINTER);
    this.validateNormalizedInput(event);
    return { kind: 'send', intent: { kind: 'pointer', event, target: this.target() } };
  }

  scroll(event: ScrollInput): SessionAction {
    this.requireInputCapability(Capability.POINTER);
    if (event.inputId <= 0n || !Number.isFinite(event.deltaX) || !Number.isFinite(event.deltaY)) {
      throw new Error('Invalid scroll input');
    }
    return { kind: 'send', intent: { kind: 'scroll', event: { ...event, target: this.target() } } };
  }

  key(event: KeyInput): SessionAction {
    this.requireInputCapability(Capability.KEYBOARD);
    if (event.inputId <= 0n || !Number.isInteger(event.usbHidUsage) || event.usbHidUsage <= 0 ||
      event.usbHidUsage > 0xffff || !Number.isInteger(event.modifierMask) || event.modifierMask < 0) {
      throw new Error('Invalid keyboard input');
    }
    return { kind: 'send', intent: { kind: 'key', event: { ...event, target: this.target() } } };
  }

  heartbeat(sequence: bigint): SessionAction {
    if (this.current === ProductSessionState.IDLE || this.current === ProductSessionState.CLOSED) throw new Error('Heartbeat requires an active session');
    if (!this.heartbeatMonitor.canSend()) throw new Error('A heartbeat is already pending');
    this.heartbeatMonitor.reserve(sequence);
    return { kind: 'send', intent: { kind: 'ping', sequence }, onAssigned: { kind: 'heartbeat', sequence } };
  }

  confirmAssigned(assignment: SessionControlAssignment, messageId: bigint, nowNs: bigint): void {
    if (assignment.kind === 'heartbeat') {
      this.heartbeatMonitor.sent(assignment.sequence, messageId, nowNs);
      return;
    }
    if (messageId <= 0n) throw new Error('Request message id must be positive');
    if (assignment.request === 'resume') this.resumeMessageId = messageId;
    else if (assignment.request === 'clientHello') this.clientHelloMessageId = messageId;
    else if (assignment.request === 'listDisplays') this.listDisplaysMessageId = messageId;
    else this.startDisplayMessageId = messageId;
  }

  confirmSent(completion: SessionSendCompletion): void {
    const pending: VideoConfigurationToken | undefined = this.pendingVideo;
    if (pending === undefined || pending.id !== completion.token.id) throw new Error('Stale video configuration completion');
    this.pendingVideo = undefined;
    if (!completion.accepted) { this.current = ProductSessionState.AWAITING_VIDEO; return; }
    const config: VideoConfig = pending.config;
    this.configEpoch = config.configEpoch; this.configuredCodec = config.codec; this.lastFrameId = 0n;
    this.current = ProductSessionState.STREAMING;
  }

  heartbeatTimedOut(nowNs: bigint): boolean { return this.heartbeatMonitor.timedOut(nowNs); }

  heartbeatPending(): boolean { return this.heartbeatMonitor.hasPending(); }

  completeVideoConfiguration(token: VideoConfigurationToken, accepted: boolean = true,
    reason: string = ''): SessionAction[] {
    const pending: VideoConfigurationToken | undefined = this.pendingVideo;
    if (pending === undefined || pending.id !== token.id || pending.config.configEpoch !== token.config.configEpoch ||
      pending.config.streamId !== token.config.streamId) throw new Error('Stale video configuration token');
    if (this.videoResultPrepared) throw new Error('Video configuration result is already queued');
    this.videoResultPrepared = true;
    return [{ kind: 'send', intent: { kind: 'videoConfigResult', correlationId: token.correlationId,
      config: token.config, accepted, reason: accepted ? '' : reason },
      afterSend: { kind: 'videoConfiguration', token, accepted } }];
  }

  close(): void { this.current = ProductSessionState.CLOSED; }

  private onHostHello(envelope: DecodedEnvelope): SessionAction[] {
    if (this.current !== ProductSessionState.AWAITING_HOST) throw new Error('Unexpected HostHello');
    this.requireCorrelation(envelope, this.clientHelloMessageId, false);
    const hello = this.decoder.hostHello(envelope.payload);
    if (hello.selectedProtocol !== PROTOCOL_VERSION) throw new Error('Host selected an unsupported protocol');
    this.capabilityState.acceptHost(hello.capabilities); this.hostCodecs = new Set(hello.codecs);
    if (!this.codecs.some((codec: Codec) => this.hostCodecs.has(codec))) throw new Error('Host and client share no codec');
    this.current = ProductSessionState.AWAITING_SESSION;
    return [];
  }

  private onSessionAccepted(envelope: DecodedEnvelope, nowNs: bigint): SessionAction[] {
    if (this.current !== ProductSessionState.AWAITING_SESSION) throw new Error('Unexpected SessionAccepted');
    this.requireCorrelation(envelope, this.clientHelloMessageId, false);
    const accepted = this.decoder.sessionAccepted(envelope.payload);
    if (envelope.sessionId.length > 0 && !this.equalBytes(envelope.sessionId, accepted.sessionId)) throw new Error('Session identity mismatch');
    if (envelope.sessionEpoch !== 0n && envelope.sessionEpoch !== accepted.sessionEpoch) throw new Error('Session epoch mismatch');
    if (!accepted.negotiatedCapabilities.includes(Capability.TOUCH)) throw new Error('Required touch capability was not negotiated');
    this.capabilityState.acceptNegotiated(accepted.negotiatedCapabilities);
    if (accepted.heartbeatIntervalMs < MIN_HEARTBEAT_MS || accepted.heartbeatIntervalMs > MAX_HEARTBEAT_MS) {
      throw new Error('Host heartbeat interval is outside the supported range');
    }
    this.sessionId = accepted.sessionId; this.sessionEpoch = accepted.sessionEpoch;
    this.heartbeatIntervalMs = accepted.heartbeatIntervalMs; this.heartbeatMonitor.configure(accepted.heartbeatIntervalMs);
    this.current = ProductSessionState.SELECTING_DISPLAY;
    return [{ kind: 'heartbeat', intervalMs: accepted.heartbeatIntervalMs },
      { kind: 'send', intent: { kind: 'listDisplays' }, onAssigned: { kind: 'request', request: 'listDisplays' } }];
  }

  private onResumeResult(envelope: DecodedEnvelope): SessionAction[] {
    if (this.current !== ProductSessionState.AWAITING_RESUME || this.resumeSnapshot === undefined) {
      throw new Error('Unexpected ResumeSessionResult');
    }
    this.requireCorrelation(envelope, this.resumeMessageId, false);
    const snapshot: SessionResumeSnapshot = this.resumeSnapshot;
    if (!this.equalBytes(envelope.sessionId, snapshot.sessionId)) throw new Error('Resume session identity mismatch');
    const result = this.decoder.resumeSessionResult(envelope.payload);
    if (!result.accepted) {
      if (result.rejectionReason.length === 0 || envelope.sessionEpoch !== snapshot.sessionEpoch) {
        throw new Error('Invalid rejected ResumeSessionResult');
      }
      this.sessionId = new Uint8Array(); this.sessionEpoch = 0n; this.resumeSnapshot = undefined;
      this.capabilityState.reset(); this.hostCodecs.clear(); this.heartbeatMonitor.reset(); this.heartbeatIntervalMs = 0;
      this.current = ProductSessionState.CLOSED;
      return [{ kind: 'disconnect', reason: `resume_rejected:${result.rejectionReason}`, retryable: true }];
    }
    if (result.sessionEpoch <= snapshot.sessionEpoch || envelope.sessionEpoch !== result.sessionEpoch) {
      throw new Error('Resume result did not advance the session epoch');
    }
    this.capabilityState.restore(snapshot.hostCapabilities, snapshot.negotiatedCapabilities);
    this.hostCodecs = new Set(snapshot.hostCodecs); this.sessionId = snapshot.sessionId.slice();
    this.sessionEpoch = result.sessionEpoch; this.heartbeatIntervalMs = snapshot.heartbeatIntervalMs;
    this.heartbeatMonitor.configure(snapshot.heartbeatIntervalMs); this.resumeSnapshot = undefined;
    this.current = ProductSessionState.SELECTING_DISPLAY;
    return [{ kind: 'heartbeat', intervalMs: snapshot.heartbeatIntervalMs },
      { kind: 'send', intent: { kind: 'listDisplays' }, onAssigned: { kind: 'request', request: 'listDisplays' } }];
  }

  private onDisplays(envelope: DecodedEnvelope, nowNs: bigint): SessionAction[] {
    if (this.current !== ProductSessionState.SELECTING_DISPLAY) throw new Error('Unexpected display list');
    this.requireCorrelation(envelope, this.listDisplaysMessageId, false);
    const displays = this.decoder.displays(envelope.payload);
    const display = displays.find((candidate) => candidate.primary) ?? displays[0];
    if (display === undefined || display.displayId.length === 0) throw new Error('Host reported no usable display');
    this.displayId = display.displayId; this.current = ProductSessionState.STARTING_DISPLAY;
    return [{ kind: 'send', intent: { kind: 'startDisplay', displayId: display.displayId },
      onAssigned: { kind: 'request', request: 'startDisplay' } }];
  }

  private onStartDisplay(envelope: DecodedEnvelope): SessionAction[] {
    if (this.current !== ProductSessionState.STARTING_DISPLAY) throw new Error('Unexpected StartDisplayResponse');
    this.requireCorrelation(envelope, this.startDisplayMessageId, false);
    const response = this.decoder.startDisplayResponse(envelope.payload);
    if (!response.accepted || response.streamId === 0n) throw new Error(`Display start rejected: ${response.rejectionReason}`);
    this.streamId = response.streamId;
    if (response.displayId.length > 0) this.displayId = response.displayId;
    this.current = ProductSessionState.AWAITING_VIDEO;
    return [];
  }

  private onVideoConfig(envelope: DecodedEnvelope, nowNs: bigint): SessionAction[] {
    if (this.current !== ProductSessionState.AWAITING_VIDEO && this.current !== ProductSessionState.STREAMING) throw new Error('Unexpected VideoConfig');
    this.requireCorrelation(envelope, this.startDisplayMessageId, true);
    const config: VideoConfig = this.decoder.videoConfig(envelope.payload);
    const accepted: boolean = isSupportedVideoConfig(config, this.streamId, this.configEpoch, this.codecs, this.hostCodecs);
    if (!accepted) return [{ kind: 'send', intent: { kind: 'videoConfigResult', correlationId: envelope.messageId,
      config, accepted: false, reason: 'unsupported_video_config' } }];
    const token: VideoConfigurationToken = { id: this.nextVideoTokenId++, config, correlationId: envelope.messageId };
    this.pendingVideo = token; this.videoResultPrepared = false; this.current = ProductSessionState.CONFIGURING_VIDEO;
    return [{ kind: 'configureVideo', config, token }];
  }

  private onFailure(envelope: DecodedEnvelope, protocolError: boolean): SessionAction[] {
    const failure = this.decoder.failure(envelope.payload, protocolError); this.current = ProductSessionState.CLOSED;
    return [{ kind: 'disconnect', reason: failure.message || failure.reason || 'session_rejected', retryable: failure.retryable }];
  }

  private onDisplayChanged(envelope: DecodedEnvelope): SessionAction[] {
    if (this.current !== ProductSessionState.STREAMING) throw new Error('Unexpected DisplayChanged');
    const changed = this.decoder.displayChanged(envelope.payload);
    if (changed.display.displayId !== this.displayId || changed.display.width < 16 || changed.display.height < 16 ||
      ![0, 90, 180, 270].includes(changed.rotationDegrees)) throw new Error('Invalid DisplayChanged');
    return [{ kind: 'displayChanged', width: changed.display.width, height: changed.display.height,
      rotationDegrees: changed.rotationDegrees }];
  }

  private validateEnvelope(envelope: DecodedEnvelope): void {
    if (envelope.protocolVersion !== PROTOCOL_VERSION || envelope.messageId <= this.lastInboundMessageId) throw new Error('Invalid envelope metadata');
    if (this.current === ProductSessionState.AWAITING_RESUME) {
      if (!this.equalBytes(envelope.sessionId, this.sessionId) || envelope.sessionEpoch < this.sessionEpoch) {
        throw new Error('Resume envelope belongs to another session');
      }
      return;
    }
    if (this.sessionEpoch > 0n && (!this.equalBytes(envelope.sessionId, this.sessionId) || envelope.sessionEpoch !== this.sessionEpoch)) {
      throw new Error('Envelope belongs to another session epoch');
    }
  }

  private requireInputCapability(capability: Capability): void {
    if (this.current !== ProductSessionState.STREAMING) throw new Error('Input requires a streaming session');
    if (!this.capabilityState.has(capability)) throw new Error(`Input capability ${capability} was not negotiated`);
  }

  private validateNormalizedInput(event: NormalizedInput): void {
    const phaseValid: boolean = event.phase === InputPhase.BEGAN || event.phase === InputPhase.CHANGED ||
      event.phase === InputPhase.ENDED || event.phase === InputPhase.CANCELLED;
    if (event.inputId <= 0n || !Number.isInteger(event.pointerId) || event.pointerId < 0 || !phaseValid ||
      !Number.isFinite(event.x) || event.x < 0 || event.x > 1 || !Number.isFinite(event.y) || event.y < 0 || event.y > 1 ||
      !Number.isFinite(event.pressure) || event.pressure < 0 || event.pressure > 1 || !Number.isFinite(event.tiltX) ||
      !Number.isFinite(event.tiltY) || !Number.isInteger(event.buttonMask) || event.buttonMask < 0) {
      throw new Error('Invalid normalized input');
    }
  }

  private requireCorrelation(envelope: DecodedEnvelope, expected: bigint, allowUncorrelated: boolean): void {
    if (expected <= 0n || (envelope.correlationId !== expected && !(allowUncorrelated && envelope.correlationId === 0n))) {
      throw new Error('Response correlation does not match the pending request');
    }
  }

  private resetRuntime(): void {
    this.lastInboundMessageId = 0n; this.sessionId = new Uint8Array(); this.sessionEpoch = 0n;
    this.streamId = 0n; this.configEpoch = 0n; this.lastFrameId = 0n; this.displayId = ''; this.configuredCodec = Codec.UNSPECIFIED;
    this.heartbeatIntervalMs = 0; this.capabilityState.reset(); this.hostCodecs.clear(); this.heartbeatMonitor.reset();
    this.nextVideoTokenId = 1n; this.pendingVideo = undefined; this.videoResultPrepared = false;
    this.resumeMessageId = 0n; this.resumeSnapshot = undefined; this.clientHelloMessageId = 0n;
    this.listDisplaysMessageId = 0n; this.startDisplayMessageId = 0n;
  }

  private validateResumeSnapshot(snapshot: SessionResumeSnapshot): void {
    if (snapshot.sessionId.length === 0 || snapshot.sessionEpoch <= 0n || snapshot.lastReceivedMessageId <= 0n ||
      snapshot.nextOutboundMessageId <= 0n ||
      snapshot.heartbeatIntervalMs < MIN_HEARTBEAT_MS || snapshot.heartbeatIntervalMs > MAX_HEARTBEAT_MS ||
      !snapshot.negotiatedCapabilities.includes(Capability.SESSION_RESUME) ||
      !snapshot.negotiatedCapabilities.includes(Capability.TOUCH) || snapshot.hostCodecs.length === 0) {
      throw new Error('Invalid resume snapshot');
    }
  }

  private equalBytes(left: Uint8Array, right: Uint8Array): boolean {
    return left.length === right.length && left.every((value: number, index: number) => value === right[index]);
  }
}
