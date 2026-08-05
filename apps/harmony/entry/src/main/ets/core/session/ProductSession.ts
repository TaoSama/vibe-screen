import { MediaPacket } from '../media/MediaPacketParser';
import { DecodedEnvelope, ProtocolDecoder } from '../protocol/ProtocolDecoder';
import { ProtocolEncoder } from '../protocol/ProtocolEncoder';
import { Capability, ClientHello, Codec, EnvelopeMetadata, InputTarget, PROTOCOL_VERSION,
  TransportKind, VideoConfig } from '../protocol/ProtocolModels';

export const MAX_VIDEO_WIDTH: number = 1920;
export const MAX_VIDEO_HEIGHT: number = 1200;
export const MAX_VIDEO_FPS: number = 60;
const MIN_VIDEO_DIMENSION: number = 16;
const MIN_HEARTBEAT_MS: number = 250;
const MAX_HEARTBEAT_MS: number = 30000;

export function isSupportedVideoConfig(config: VideoConfig, streamId: bigint, configEpoch: bigint,
  codecs: Codec[], hostCodecs: Set<number>): boolean {
  return config.streamId === streamId && config.configEpoch > configEpoch &&
    config.width >= MIN_VIDEO_DIMENSION && config.width <= MAX_VIDEO_WIDTH &&
    config.height >= MIN_VIDEO_DIMENSION && config.height <= MAX_VIDEO_HEIGHT &&
    config.framesPerSecond >= 1 && config.framesPerSecond <= MAX_VIDEO_FPS &&
    [0, 90, 180, 270].includes(config.rotationDegrees) && codecs.includes(config.codec) && hostCodecs.has(config.codec);
}

export enum ProductSessionState {
  IDLE = 'idle', AWAITING_HOST = 'awaiting_host', AWAITING_SESSION = 'awaiting_session',
  SELECTING_DISPLAY = 'selecting_display', AWAITING_VIDEO = 'awaiting_video', STREAMING = 'streaming', CLOSED = 'closed'
}

export type SessionAction =
  | { kind: 'send'; bytes: Uint8Array }
  | { kind: 'configureVideo'; config: VideoConfig; acceptedResponse: Uint8Array }
  | { kind: 'heartbeat'; intervalMs: number }
  | { kind: 'displayChanged'; width: number; height: number; rotationDegrees: number }
  | { kind: 'media'; packet: MediaPacket }
  | { kind: 'disconnect'; reason: string; retryable: boolean };

export class ProductSession {
  private current: ProductSessionState = ProductSessionState.IDLE;
  private nextMessageId: bigint = 1n;
  private lastInboundMessageId: bigint = 0n;
  private sessionId: Uint8Array = new Uint8Array();
  private sessionEpoch: bigint = 0n;
  private streamId: bigint = 0n;
  private configEpoch: bigint = 0n;
  private lastFrameId: bigint = 0n;
  private displayId: string = '';
  private configuredCodec: Codec = Codec.UNSPECIFIED;
  private heartbeatIntervalMs: number = 0;
  private hostCapabilities: Set<number> = new Set();
  private hostCodecs: Set<number> = new Set();
  private decoder: ProtocolDecoder = new ProtocolDecoder();
  private encoder: ProtocolEncoder = new ProtocolEncoder();

  constructor(private deviceId: string, private deviceName: string,
    private capabilities: Capability[], private codecs: Codec[]) {
    if (deviceId.length === 0 || deviceName.length === 0 || codecs.length === 0) throw new Error('Invalid client identity or codecs');
  }

  state(): ProductSessionState { return this.current; }
  epoch(): bigint { return this.sessionEpoch; }
  heartbeatMs(): number { return this.heartbeatIntervalMs; }
  target(): InputTarget { return { displayId: this.displayId, streamId: this.streamId }; }

  start(nowNs: bigint): SessionAction[] {
    if (this.current !== ProductSessionState.IDLE && this.current !== ProductSessionState.CLOSED) throw new Error('Session already started');
    this.resetRuntime();
    this.current = ProductSessionState.AWAITING_HOST;
    const hello: ClientHello = {
      minimumProtocol: PROTOCOL_VERSION, maximumProtocol: PROTOCOL_VERSION, deviceId: this.deviceId,
      deviceName: this.deviceName, capabilities: this.capabilities, codecs: this.codecs, transports: [TransportKind.LAN],
      requiredCapabilities: [Capability.TOUCH], resourceLimits: { maximumClients: 1, maximumDisplays: 1, maximumVideoStreams: 1 },
      videoDecodeCapabilities: this.codecs.map((codec: Codec) => ({ codec, maximumWidth: MAX_VIDEO_WIDTH,
        maximumHeight: MAX_VIDEO_HEIGHT, maximumFramesPerSecond: MAX_VIDEO_FPS, bitDepths: [8] }))
    };
    return [{ kind: 'send', bytes: this.encoder.clientHello(this.metadata(nowNs), hello) }];
  }

  receive(bytes: Uint8Array, nowNs: bigint): SessionAction[] {
    const envelope: DecodedEnvelope = this.decoder.envelope(bytes);
    this.validateEnvelope(envelope);
    this.lastInboundMessageId = envelope.messageId;
    if (envelope.payloadField === 21) return this.onHostHello(envelope);
    if (envelope.payloadField === 22) return this.onSessionAccepted(envelope, nowNs);
    if (envelope.payloadField === 23) return this.onFailure(envelope, false);
    if (envelope.payloadField === 24) return [{ kind: 'send', bytes: this.encoder.pong(this.correlatedMetadata(nowNs, envelope.messageId), this.decoder.sequence(envelope.payload)) }];
    if (envelope.payloadField === 25 || envelope.payloadField === 64) return [];
    if (envelope.payloadField === 28) return [{ kind: 'disconnect', reason: 'host_disconnect', retryable: true }];
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
    if (header.streamId !== this.streamId || header.configEpoch !== this.configEpoch) throw new Error('Cross-stream media');
    if (header.codec !== this.configuredCodec || header.fragmentCount !== 1 || header.fragmentIndex !== 0) {
      throw new Error('Unsupported media packet');
    }
    this.lastFrameId = header.frameId;
    return [{ kind: 'media', packet }];
  }

  metadataForInput(nowNs: bigint): EnvelopeMetadata {
    if (this.current !== ProductSessionState.STREAMING) throw new Error('Input requires a streaming session');
    return this.metadata(nowNs);
  }

  heartbeat(nowNs: bigint, sequence: bigint): Uint8Array {
    if (this.current === ProductSessionState.IDLE || this.current === ProductSessionState.CLOSED) throw new Error('Heartbeat requires an active session');
    return this.encoder.ping(this.metadata(nowNs), sequence);
  }

  close(): void { this.current = ProductSessionState.CLOSED; }

  private onHostHello(envelope: DecodedEnvelope): SessionAction[] {
    if (this.current !== ProductSessionState.AWAITING_HOST) throw new Error('Unexpected HostHello');
    const hello = this.decoder.hostHello(envelope.payload);
    if (hello.selectedProtocol !== PROTOCOL_VERSION) throw new Error('Host selected an unsupported protocol');
    this.hostCapabilities = new Set(hello.capabilities); this.hostCodecs = new Set(hello.codecs);
    if (!this.hostCapabilities.has(Capability.TOUCH)) throw new Error('Host lacks required touch capability');
    if (!this.codecs.some((codec: Codec) => this.hostCodecs.has(codec))) throw new Error('Host and client share no codec');
    this.current = ProductSessionState.AWAITING_SESSION;
    return [];
  }

  private onSessionAccepted(envelope: DecodedEnvelope, nowNs: bigint): SessionAction[] {
    if (this.current !== ProductSessionState.AWAITING_SESSION) throw new Error('Unexpected SessionAccepted');
    const accepted = this.decoder.sessionAccepted(envelope.payload);
    if (envelope.sessionId.length > 0 && !this.equalBytes(envelope.sessionId, accepted.sessionId)) throw new Error('Session identity mismatch');
    if (envelope.sessionEpoch !== 0n && envelope.sessionEpoch !== accepted.sessionEpoch) throw new Error('Session epoch mismatch');
    if (!accepted.negotiatedCapabilities.includes(Capability.TOUCH)) throw new Error('Required touch capability was not negotiated');
    if (accepted.heartbeatIntervalMs < MIN_HEARTBEAT_MS || accepted.heartbeatIntervalMs > MAX_HEARTBEAT_MS) {
      throw new Error('Host heartbeat interval is outside the supported range');
    }
    this.sessionId = accepted.sessionId; this.sessionEpoch = accepted.sessionEpoch;
    this.heartbeatIntervalMs = accepted.heartbeatIntervalMs; this.current = ProductSessionState.SELECTING_DISPLAY;
    return [{ kind: 'heartbeat', intervalMs: accepted.heartbeatIntervalMs },
      { kind: 'send', bytes: this.encoder.listDisplays(this.metadata(nowNs)) }];
  }

  private onDisplays(envelope: DecodedEnvelope, nowNs: bigint): SessionAction[] {
    if (this.current !== ProductSessionState.SELECTING_DISPLAY) throw new Error('Unexpected display list');
    const displays = this.decoder.displays(envelope.payload);
    const display = displays.find((candidate) => candidate.primary) ?? displays[0];
    if (display === undefined || display.displayId.length === 0) throw new Error('Host reported no usable display');
    this.displayId = display.displayId; this.current = ProductSessionState.AWAITING_VIDEO;
    return [{ kind: 'send', bytes: this.encoder.startDisplay(this.metadata(nowNs), display.displayId) }];
  }

  private onStartDisplay(envelope: DecodedEnvelope): SessionAction[] {
    if (this.current !== ProductSessionState.AWAITING_VIDEO) throw new Error('Unexpected StartDisplayResponse');
    const response = this.decoder.startDisplayResponse(envelope.payload);
    if (!response.accepted || response.streamId === 0n) throw new Error(`Display start rejected: ${response.rejectionReason}`);
    this.streamId = response.streamId;
    if (response.displayId.length > 0) this.displayId = response.displayId;
    return [];
  }

  private onVideoConfig(envelope: DecodedEnvelope, nowNs: bigint): SessionAction[] {
    if (this.current !== ProductSessionState.AWAITING_VIDEO && this.current !== ProductSessionState.STREAMING) throw new Error('Unexpected VideoConfig');
    const config: VideoConfig = this.decoder.videoConfig(envelope.payload);
    const accepted: boolean = isSupportedVideoConfig(config, this.streamId, this.configEpoch, this.codecs, this.hostCodecs);
    const response: Uint8Array = this.encoder.videoConfigResult(this.metadata(nowNs), envelope.messageId,
      config, accepted, accepted ? '' : 'unsupported_video_config');
    if (!accepted) return [{ kind: 'send', bytes: response }];
    this.configEpoch = config.configEpoch; this.configuredCodec = config.codec; this.lastFrameId = 0n;
    this.current = ProductSessionState.STREAMING;
    return [{ kind: 'configureVideo', config, acceptedResponse: response }];
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
    if (this.sessionEpoch > 0n && (!this.equalBytes(envelope.sessionId, this.sessionId) || envelope.sessionEpoch !== this.sessionEpoch)) {
      throw new Error('Envelope belongs to another session epoch');
    }
  }

  private metadata(nowNs: bigint): EnvelopeMetadata {
    return ProtocolEncoder.metadata(this.nextMessageId++, this.sessionId, this.sessionEpoch, nowNs);
  }

  private correlatedMetadata(nowNs: bigint, correlationId: bigint): EnvelopeMetadata {
    const metadata: EnvelopeMetadata = this.metadata(nowNs); metadata.correlationId = correlationId; return metadata;
  }

  private resetRuntime(): void {
    this.nextMessageId = 1n; this.lastInboundMessageId = 0n; this.sessionId = new Uint8Array(); this.sessionEpoch = 0n;
    this.streamId = 0n; this.configEpoch = 0n; this.lastFrameId = 0n; this.displayId = ''; this.configuredCodec = Codec.UNSPECIFIED;
    this.heartbeatIntervalMs = 0; this.hostCapabilities.clear(); this.hostCodecs.clear();
  }

  private equalBytes(left: Uint8Array, right: Uint8Array): boolean {
    return left.length === right.length && left.every((value: number, index: number) => value === right[index]);
  }
}
