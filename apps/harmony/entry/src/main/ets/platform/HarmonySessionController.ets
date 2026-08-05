import { systemDateTime } from '@kit.BasicServicesKit';
import { CoordinateMapper, Rotation } from '../core/input/CoordinateMapper';
import { MediaPacketParser } from '../core/media/MediaPacketParser';
import { ProtocolEncoder } from '../core/protocol/ProtocolEncoder';
import { Capability, Codec, InputPhase, NormalizedInput, VideoConfig } from '../core/protocol/ProtocolModels';
import { ProductSession, ProductSessionState, SessionAction } from '../core/session/ProductSession';
import { ReconnectPolicy } from '../core/session/ReconnectPolicy';
import { HarmonyTransport, TransportListener } from './HarmonyTransport';
import { HarmonyVideoDecoder, VideoDecoderListener } from './HarmonyVideoDecoder';
import { PairingLink, PairingStore, PairingTarget, TrustedHostRecord } from './PairingStore';

const DEFAULT_PORT: number = 54321;
const MAX_RECONNECT_ATTEMPTS: number = 8;

export interface SessionUiListener {
  onStatus(status: string, streaming: boolean): void;
  onVideoGeometry(width: number, height: number, rotation: number): void;
}

class ControllerTransportListener implements TransportListener {
  constructor(private owner: HarmonySessionController, private generation: number) {}
  onConnected(): void { this.owner.onTransportReady(this.generation); }
  onControlMessage(payload: Uint8Array): void { this.owner.onControl(payload, this.generation); }
  onMediaMessage(payload: Uint8Array): void { this.owner.onMedia(payload, this.generation); }
  onDisconnected(reason: string): void { this.owner.onTransportLost(reason, true, this.generation); }
}

class ControllerDecoderListener implements VideoDecoderListener {
  constructor(private owner: HarmonySessionController, private decoderGeneration: number, private operationGeneration: number) {}
  onDecoderError(message: string): void { this.owner.onDecoderFailure(message, this.decoderGeneration, this.operationGeneration); }
  onFrameRendered(): void { this.owner.onFrameRendered(this.decoderGeneration, this.operationGeneration); }
}

export class HarmonySessionController {
  private transport: HarmonyTransport = new HarmonyTransport();
  private videoDecoder: HarmonyVideoDecoder = new HarmonyVideoDecoder();
  private mediaParser: MediaPacketParser = new MediaPacketParser();
  private encoder: ProtocolEncoder = new ProtocolEncoder();
  private reconnectPolicy: ReconnectPolicy = new ReconnectPolicy();
  private pairingStore: PairingStore = new PairingStore();
  private coordinateMapper: CoordinateMapper = new CoordinateMapper();
  private session: ProductSession | undefined;
  private ui: SessionUiListener | undefined;
  private surfaceId: string = '';
  private host: string = '';
  private port: number = DEFAULT_PORT;
  private reconnectAttempt: number = 0;
  private reconnectTimer: number = -1;
  private heartbeatTimer: number = -1;
  private heartbeatSequence: bigint = 1n;
  private foreground: boolean = true;
  private userStopped: boolean = false;
  private renderedFirstFrame: boolean = false;
  private nextInputId: bigint = 1n;
  private pendingVideo: VideoConfig | undefined;
  private pendingVideoResponse: Uint8Array | undefined;
  private pendingVideoOwner: number = 0;
  private operationGeneration: number = 0;
  private decoderGeneration: number = 0;

  attachUi(listener: SessionUiListener): void { this.ui = listener; }

  async restoreHost(): Promise<TrustedHostRecord | undefined> { return this.pairingStore.loadTrustedHost(); }

  async importPairingLink(value: string): Promise<TrustedHostRecord> {
    const target: PairingTarget = PairingLink.parse(value);
    await this.pairingStore.saveTrustedHost(target);
    return { version: 1, host: target.host, port: target.port, offerId: target.offerId };
  }

  async connect(host: string, port: number): Promise<void> {
    if (host.trim().length === 0 || !Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Mac 地址或端口无效');
    this.host = host.trim(); this.port = port; this.userStopped = false; this.reconnectAttempt = 0;
    const owner: number = ++this.operationGeneration;
    await this.openFreshSession(owner);
  }

  async disconnect(): Promise<void> {
    const owner: number = ++this.operationGeneration; this.decoderGeneration += 1;
    this.userStopped = true; this.cancelReconnect(); this.cancelHeartbeat(); this.session?.close();
    await Promise.all([this.transport.close(), this.videoDecoder.release()]);
    if (owner === this.operationGeneration) this.ui?.onStatus('已断开', false);
  }

  setSurface(surfaceId: string): void {
    this.surfaceId = surfaceId;
    if (this.pendingVideo !== undefined && this.pendingVideoOwner === this.operationGeneration) {
      this.configureVideo(this.pendingVideo, this.pendingVideoResponse, this.pendingVideoOwner);
    }
  }

  clearSurface(): void {
    this.surfaceId = '';
    if (this.session?.state() === ProductSessionState.STREAMING) this.onTransportLost('video_surface_destroyed');
  }

  async onForeground(): Promise<void> {
    this.foreground = true;
    if (!this.userStopped && this.host.length > 0 && this.session?.state() === ProductSessionState.CLOSED) {
      const owner: number = ++this.operationGeneration;
      await this.openFreshSession(owner);
    }
  }

  async onBackground(): Promise<void> {
    const owner: number = ++this.operationGeneration; this.decoderGeneration += 1;
    this.foreground = false; this.cancelReconnect(); this.cancelHeartbeat(); this.session?.close();
    await Promise.all([this.transport.close(), this.videoDecoder.release()]);
    if (owner === this.operationGeneration) this.ui?.onStatus('已暂停，返回前台后重连', false);
  }

  async forgetHost(): Promise<void> { await this.disconnect(); await this.pairingStore.forgetHost(); }

  sendTouch(pointerId: number, phase: InputPhase, localX: number, localY: number, width: number, height: number,
    rotation: Rotation, pressure: number): void {
    const active: ProductSession | undefined = this.session;
    if (active?.state() !== ProductSessionState.STREAMING) return;
    const point = this.coordinateMapper.map(localX, localY, { left: 0, top: 0, width, height, rotation });
    const event: NormalizedInput = { inputId: this.nextInputId++, pointerId, phase, x: point.x, y: point.y,
      pressure: Math.min(Math.max(pressure, 0), 1), tiltX: 0, tiltY: 0, buttonMask: 0 };
    this.send(this.encoder.touch(active.metadataForInput(this.nowNs()), event, active.target()));
  }

  sendPointer(phase: InputPhase, x: number, y: number, width: number, height: number,
    rotation: Rotation, buttonMask: number): void {
    const active: ProductSession | undefined = this.session;
    if (active?.state() !== ProductSessionState.STREAMING) return;
    const point = this.coordinateMapper.map(x, y, { left: 0, top: 0, width, height, rotation });
    const event: NormalizedInput = { inputId: this.nextInputId++, pointerId: 0, phase, x: point.x, y: point.y,
      pressure: 0, tiltX: 0, tiltY: 0, buttonMask };
    this.send(this.encoder.pointer(active.metadataForInput(this.nowNs()), event, active.target()));
  }

  sendScroll(deltaX: number, deltaY: number): void {
    const active: ProductSession | undefined = this.session;
    if (active?.state() !== ProductSessionState.STREAMING) return;
    this.send(this.encoder.scroll(active.metadataForInput(this.nowNs()), {
      inputId: this.nextInputId++, deltaX, deltaY, target: active.target()
    }));
  }

  sendKey(usbHidUsage: number, pressed: boolean, modifierMask: number, text: string): void {
    const active: ProductSession | undefined = this.session;
    if (active?.state() !== ProductSessionState.STREAMING || usbHidUsage <= 0) return;
    this.send(this.encoder.key(active.metadataForInput(this.nowNs()), {
      inputId: this.nextInputId++, usbHidUsage, pressed, modifierMask, text, target: active.target()
    }));
  }

  onTransportReady(owner: number): void {
    if (owner !== this.operationGeneration) return;
    this.ui?.onStatus('正在协商 Protocol v1…', false);
    try { this.applyActions(this.requireSession().start(this.nowNs()), owner); }
    catch (error) { this.onTransportLost((error as Error).message, false, owner); }
  }

  onControl(payload: Uint8Array, owner: number): void {
    if (owner !== this.operationGeneration) return;
    try { this.applyActions(this.requireSession().receive(payload, this.nowNs()), owner); }
    catch (error) { this.onTransportLost((error as Error).message, false, owner); }
  }

  onMedia(payload: Uint8Array, owner: number): void {
    if (owner !== this.operationGeneration) return;
    try { this.applyActions(this.requireSession().acceptMedia(this.mediaParser.parse(payload)), owner); }
    catch (error) { this.onTransportLost((error as Error).message, false, owner); }
  }

  onTransportLost(reason: string, retryable: boolean = true, owner: number = this.operationGeneration): void {
    if (owner !== this.operationGeneration) return;
    const cleanupOwner: number = ++this.operationGeneration;
    this.decoderGeneration += 1; this.session?.close(); this.cancelHeartbeat(); this.cancelReconnect();
    this.renderedFirstFrame = false;
    this.cleanupLoss(cleanupOwner, reason, retryable).catch((error: Error) => {
      if (cleanupOwner === this.operationGeneration) this.ui?.onStatus(`连接清理失败：${error.message}`, false);
    });
  }

  onDecoderFailure(message: string, decoderOwner: number, operationOwner: number): void {
    if (decoderOwner !== this.decoderGeneration || operationOwner !== this.operationGeneration) return;
    this.onTransportLost(`硬件解码失败：${message}`, false, operationOwner);
  }

  onFrameRendered(decoderOwner: number, operationOwner: number): void {
    if (decoderOwner !== this.decoderGeneration || operationOwner !== this.operationGeneration) return;
    if (!this.renderedFirstFrame) { this.renderedFirstFrame = true; this.reconnectAttempt = 0; this.ui?.onStatus('正在串流', true); }
  }

  private async openFreshSession(owner: number): Promise<void> {
    try {
      this.cancelReconnect(); this.renderedFirstFrame = false; this.pendingVideo = undefined;
      this.pendingVideoResponse = undefined; this.pendingVideoOwner = 0; this.heartbeatSequence = 1n;
      const deviceId: string = await this.pairingStore.clientId();
      if (!this.isActive(owner)) return;
      this.session = new ProductSession(deviceId, 'HarmonyOS NEXT tablet',
        [Capability.TOUCH, Capability.KEYBOARD, Capability.POINTER, Capability.STYLUS], [Codec.HEVC, Codec.H264]);
      this.ui?.onStatus('正在连接 Mac…', false);
      await this.transport.connect(this.host, this.port, new ControllerTransportListener(this, owner));
    } catch (error) {
      if (owner === this.operationGeneration) this.onTransportLost((error as Error).message, true, owner);
    }
  }

  private applyActions(actions: SessionAction[], owner: number): void {
    actions.forEach((action: SessionAction) => {
      if (action.kind === 'send') this.send(action.bytes, owner);
      else if (action.kind === 'configureVideo') this.configureVideo(action.config, action.acceptedResponse, owner);
      else if (action.kind === 'heartbeat') this.startHeartbeat(action.intervalMs, owner);
      else if (action.kind === 'displayChanged') this.ui?.onVideoGeometry(action.width, action.height, action.rotationDegrees);
      else if (action.kind === 'media') this.videoDecoder.submit({ frameId: action.packet.header.frameId,
        epoch: action.packet.header.sessionEpoch, timestampNs: action.packet.header.captureTimestampNs,
        keyframe: action.packet.header.keyframe, payload: action.packet.payload });
      else this.onTransportLost(action.reason, action.retryable, owner);
    });
  }

  private configureVideo(config: VideoConfig, acceptedResponse: Uint8Array | undefined, owner: number): void {
    if (owner !== this.operationGeneration) return;
    if (this.surfaceId.length === 0) { this.pendingVideo = config; this.pendingVideoResponse = acceptedResponse;
      this.pendingVideoOwner = owner;
      this.ui?.onStatus('等待视频画面初始化…', false); return; }
    this.pendingVideo = undefined; this.pendingVideoResponse = undefined; this.pendingVideoOwner = 0;
    const active: ProductSession = this.requireSession();
    const epoch: bigint = active.epoch();
    const surface: string = this.surfaceId;
    const decoderOwner: number = ++this.decoderGeneration;
    this.videoDecoder.configure(config.codec, config.width, config.height, surface, epoch,
      new ControllerDecoderListener(this, decoderOwner, owner)).then(() => {
        if (!this.isCurrentVideoOperation(owner, decoderOwner, active, epoch, surface)) return;
        if (acceptedResponse !== undefined) this.send(acceptedResponse, owner);
        this.ui?.onVideoGeometry(config.width, config.height, config.rotationDegrees);
        this.send(this.encoder.requestKeyframe(active.metadataForInput(this.nowNs()), config.streamId, 'decoder_configured'), owner);
      }).catch((error: Error) => {
        if (this.isCurrentVideoOperation(owner, decoderOwner, active, epoch, surface)) {
          this.onDecoderFailure(error.message, decoderOwner, owner);
        }
      });
  }

  private send(bytes: Uint8Array, owner: number = this.operationGeneration): void {
    this.transport.sendControl(bytes).catch((error: Error) => this.onTransportLost(error.message, true, owner));
  }

  private scheduleReconnect(reason: string, owner: number): void {
    if (owner !== this.operationGeneration) return;
    if (this.reconnectTimer >= 0) return;
    if (this.reconnectAttempt >= MAX_RECONNECT_ATTEMPTS) { this.ui?.onStatus(`重连失败：${reason}`, false); return; }
    const delay: number = this.reconnectPolicy.delayMs(this.reconnectAttempt++);
    this.ui?.onStatus(`${delay} ms 后重连：${reason}`, false);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = -1;
      if (owner !== this.operationGeneration || this.userStopped || !this.foreground) return;
      const reconnectOwner: number = ++this.operationGeneration;
      this.openFreshSession(reconnectOwner);
    }, delay);
  }

  private cancelReconnect(): void {
    if (this.reconnectTimer >= 0) { clearTimeout(this.reconnectTimer); this.reconnectTimer = -1; }
  }

  private startHeartbeat(intervalMs: number, owner: number): void {
    this.cancelHeartbeat();
    if (intervalMs <= 0) return;
    this.heartbeatTimer = setInterval(() => {
      if (owner !== this.operationGeneration) { this.cancelHeartbeat(); return; }
      try { this.send(this.requireSession().heartbeat(this.nowNs(), this.heartbeatSequence++), owner); }
      catch (error) { this.onTransportLost((error as Error).message, true, owner); }
    }, intervalMs);
  }

  private cancelHeartbeat(): void {
    if (this.heartbeatTimer >= 0) { clearInterval(this.heartbeatTimer); this.heartbeatTimer = -1; }
  }

  private requireSession(): ProductSession {
    if (this.session === undefined) throw new Error('Session is not initialized'); return this.session;
  }

  private async cleanupLoss(owner: number, reason: string, retryable: boolean): Promise<void> {
    await Promise.all([this.transport.close(), this.videoDecoder.release()]);
    if (owner !== this.operationGeneration) return;
    if (this.userStopped || !this.foreground) { this.ui?.onStatus(`连接中断：${reason}`, false); return; }
    if (!retryable) { this.ui?.onStatus(`连接失败：${reason}`, false); return; }
    this.scheduleReconnect(reason, owner);
  }

  private isActive(owner: number): boolean {
    return owner === this.operationGeneration && this.foreground && !this.userStopped;
  }

  private isCurrentVideoOperation(owner: number, decoderOwner: number, session: ProductSession,
    epoch: bigint, surface: string): boolean {
    return this.isActive(owner) && decoderOwner === this.decoderGeneration && this.session === session &&
      session.epoch() === epoch && this.surfaceId === surface;
  }

  private nowNs(): bigint { return BigInt(systemDateTime.getUptime(systemDateTime.TimeType.ACTIVE, false)) * 1000000n; }
}
