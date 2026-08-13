import { systemDateTime } from '@kit.BasicServicesKit';
import { AdvancedPeripheralInputMapper, ControllerFullState, ControllerLifecycleSample,
  ControllerSessionState, HarmonyStylusSample } from '../core/input/AdvancedPeripheralInputMapper';
import { CoordinateMapper, Rotation } from '../core/input/CoordinateMapper';
import { MediaPacketParser } from '../core/media/MediaPacketParser';
import { OutboundControlWriter, OutboundControlReceipt } from '../core/protocol/OutboundControlWriter';
import { Capability, Codec, InputPhase, NormalizedInput, VideoConfig } from '../core/protocol/ProtocolModels';
import { ProductSession, ProductSessionState, SessionAction, SessionSendAction,
  VideoConfigurationToken } from '../core/session/ProductSession';
import { CleanupFailure, describeCleanupFailures, runAllCleanup } from '../core/session/CleanupCoordinator';
import { HARMONY_ADVERTISED_CAPABILITIES } from '../core/session/ClientCapabilities';
import { ReconnectPolicy } from '../core/session/ReconnectPolicy';
import { ProgressDeadlineAction, ProgressWatchdog } from '../core/session/ProgressWatchdog';
import { HarmonyTransport, TransportListener } from './HarmonyTransport';
import { HarmonyVideoDecoder, VideoDecoderListener } from './HarmonyVideoDecoder';
import { PairingLink, PairingStore, PairingTarget, TrustedHostRecord } from './PairingStore';

const DEFAULT_PORT: number = 54321;
const MAX_RECONNECT_ATTEMPTS: number = 8;

export interface SessionUiListener {
  onStatus(status: string, streaming: boolean): void;
  onVideoGeometry(width: number, height: number, rotation: number): void;
  onCapabilities(capabilities: Capability[]): void;
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
  onKeyframeRequired(reason: string): void {
    this.owner.onKeyframeRequired(reason, this.decoderGeneration, this.operationGeneration);
  }
  onDecoderWarning(message: string): void {
    this.owner.onDecoderWarning(message, this.decoderGeneration, this.operationGeneration);
  }
}

export class HarmonySessionController {
  private transport: HarmonyTransport = new HarmonyTransport();
  private videoDecoder: HarmonyVideoDecoder = new HarmonyVideoDecoder();
  private mediaParser: MediaPacketParser = new MediaPacketParser();
  private reconnectPolicy: ReconnectPolicy = new ReconnectPolicy();
  private progressWatchdog: ProgressWatchdog = new ProgressWatchdog();
  private pairingStore: PairingStore = new PairingStore();
  private coordinateMapper: CoordinateMapper = new CoordinateMapper();
  private advancedInputMapper: AdvancedPeripheralInputMapper = new AdvancedPeripheralInputMapper();
  private controllerState: ControllerSessionState = new ControllerSessionState();
  private session: ProductSession | undefined;
  private controlWriter: OutboundControlWriter | undefined;
  private ui: SessionUiListener | undefined;
  private surfaceId: string = '';
  private host: string = '';
  private port: number = DEFAULT_PORT;
  private reconnectAttempt: number = 0;
  private reconnectTimer: number = -1;
  private heartbeatTimer: number = -1;
  private sessionWatchdogTimer: number = -1;
  private heartbeatSequence: bigint = 1n;
  private foreground: boolean = true;
  private userStopped: boolean = false;
  private renderedFirstFrame: boolean = false;
  private nextInputId: bigint = 1n;
  private pendingVideo: VideoConfig | undefined;
  private pendingVideoToken: VideoConfigurationToken | undefined;
  private pendingVideoOwner: number = 0;
  private operationGeneration: number = 0;
  private decoderGeneration: number = 0;
  private capabilitiesReported: boolean = false;

  attachUi(listener: SessionUiListener): void { this.ui = listener; }
  detachUi(listener: SessionUiListener): void { if (this.ui === listener) this.ui = undefined; }

  async restoreHost(): Promise<TrustedHostRecord | undefined> { return this.pairingStore.loadTrustedHost(); }

  async importPairingLink(value: string): Promise<TrustedHostRecord> {
    const target: PairingTarget = PairingLink.parse(value);
    await this.pairingStore.saveTrustedHost(target);
    return { version: 1, host: target.host, port: target.port, offerId: target.offerId };
  }

  async connect(host: string, port: number): Promise<void> {
    if (host.trim().length === 0 || !Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Mac 地址或端口无效');
    const owner: number = ++this.operationGeneration; this.decoderGeneration += 1;
    this.cancelReconnect(); this.cancelHeartbeat(); this.cancelSessionWatchdog();
    const releaseFailures: CleanupFailure[] = await this.releaseAdvancedInputs();
    if (owner !== this.operationGeneration) return;
    this.session?.close(); this.closeWriter();
    const failures: CleanupFailure[] = [...releaseFailures, ...await this.cleanupResources()];
    if (owner !== this.operationGeneration) return;
    if (failures.length > 0) this.ui?.onStatus(`重新连接前清理警告：${describeCleanupFailures(failures)}`, false);
    this.host = host.trim(); this.port = port; this.userStopped = false; this.reconnectAttempt = 0;
    await this.openFreshSession(owner);
  }

  async disconnect(): Promise<void> {
    const owner: number = ++this.operationGeneration; this.decoderGeneration += 1;
    this.userStopped = true; this.cancelReconnect(); this.cancelHeartbeat(); this.cancelSessionWatchdog();
    const releaseFailures: CleanupFailure[] = await this.releaseAdvancedInputs();
    if (owner !== this.operationGeneration) return;
    this.session?.close(); this.closeWriter();
    const failures: CleanupFailure[] = [...releaseFailures, ...await this.cleanupResources()];
    if (owner === this.operationGeneration) this.ui?.onStatus(this.cleanupStatus('已断开', failures), false);
  }

  setSurface(surfaceId: string): void {
    this.surfaceId = surfaceId;
    if (this.pendingVideo !== undefined && this.pendingVideoOwner === this.operationGeneration) {
      this.configureVideo(this.pendingVideo, this.pendingVideoToken, this.pendingVideoOwner);
    }
  }

  clearSurface(): void {
    this.surfaceId = '';
    const state: ProductSessionState | undefined = this.session?.state();
    if (state === ProductSessionState.STREAMING || state === ProductSessionState.CONFIGURING_VIDEO) {
      this.onTransportLost('video_surface_destroyed');
    }
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
    this.foreground = false; this.cancelReconnect(); this.cancelHeartbeat(); this.cancelSessionWatchdog();
    const releaseFailures: CleanupFailure[] = await this.releaseAdvancedInputs();
    if (owner !== this.operationGeneration) return;
    this.session?.close(); this.closeWriter();
    const failures: CleanupFailure[] = [...releaseFailures, ...await this.cleanupResources()];
    if (owner === this.operationGeneration) this.ui?.onStatus(this.cleanupStatus('已暂停，返回前台后重连', failures), false);
  }

  async forgetHost(): Promise<void> { await this.disconnect(); await this.pairingStore.forgetHost(); }

  sendTouch(pointerId: number, phase: InputPhase, localX: number, localY: number, width: number, height: number,
    rotation: Rotation, pressure: number): void {
    const active: ProductSession | undefined = this.session;
    if (active?.state() !== ProductSessionState.STREAMING || !active.canSend(Capability.TOUCH) ||
      !this.finite(localX, localY, width, height, pressure) || width <= 0 || height <= 0) return;
    const point = this.coordinateMapper.map(localX, localY, { left: 0, top: 0, width, height, rotation });
    const event: NormalizedInput = { inputId: this.nextInputId++, pointerId, phase, x: point.x, y: point.y,
      pressure: 0, tiltX: 0, tiltY: 0, buttonMask: 0 };
    this.applyActions([active.touch(event)], this.operationGeneration);
  }

  sendStylus(sample: HarmonyStylusSample, localX: number, localY: number, width: number, height: number,
    rotation: Rotation): void {
    const active: ProductSession | undefined = this.session;
    if (active?.state() !== ProductSessionState.STREAMING || !active.canSend(Capability.STYLUS) ||
      !this.finite(localX, localY, width, height) || width <= 0 || height <= 0) return;
    try {
      const point = this.coordinateMapper.map(localX, localY, { left: 0, top: 0, width, height, rotation });
      const extended: boolean = active.canSend(Capability.STYLUS_EXTENDED);
      const event = this.advancedInputMapper.stylus(this.nextInputId++, { ...sample, x: point.x, y: point.y }, extended);
      this.applyActions([active.stylus(event)], this.operationGeneration);
    } catch (error) {
      this.ui?.onStatus(`手写笔输入被拒绝：${(error as Error).message}`, true);
    }
  }

  controllerConnected(deviceId: number): void {
    const active: ProductSession | undefined = this.session;
    if (active?.state() !== ProductSessionState.STREAMING || !active.canSend(Capability.CONTROLLER)) return;
    try { this.sendControllerSamples(this.controllerState.connect(this.advancedInputMapper.stableControllerId(deviceId))); }
    catch (error) { this.ui?.onStatus(`控制器连接被拒绝：${(error as Error).message}`, true); }
  }

  sendControllerState(deviceId: number, state: ControllerFullState): void {
    const active: ProductSession | undefined = this.session;
    if (active?.state() !== ProductSessionState.STREAMING || !active.canSend(Capability.CONTROLLER)) return;
    try { this.sendControllerSamples(this.controllerState.update(this.advancedInputMapper.stableControllerId(deviceId), state)); }
    catch (error) { this.ui?.onStatus(`控制器状态被拒绝：${(error as Error).message}`, true); }
  }

  controllerDisconnected(deviceId: number): void {
    const active: ProductSession | undefined = this.session;
    if (active?.state() !== ProductSessionState.STREAMING || !active.canSend(Capability.CONTROLLER)) return;
    try { this.sendControllerSamples(this.controllerState.disconnect(this.advancedInputMapper.stableControllerId(deviceId))); }
    catch (error) { this.ui?.onStatus(`控制器断开被拒绝：${(error as Error).message}`, true); }
  }

  sendPointer(phase: InputPhase, x: number, y: number, width: number, height: number,
    rotation: Rotation, buttonMask: number): void {
    const active: ProductSession | undefined = this.session;
    if (active?.state() !== ProductSessionState.STREAMING || !active.canSend(Capability.POINTER) ||
      !this.finite(x, y, width, height) || width <= 0 || height <= 0 || !Number.isInteger(buttonMask)) return;
    const point = this.coordinateMapper.map(x, y, { left: 0, top: 0, width, height, rotation });
    const event: NormalizedInput = { inputId: this.nextInputId++, pointerId: 0, phase, x: point.x, y: point.y,
      pressure: 0, tiltX: 0, tiltY: 0, buttonMask };
    this.applyActions([active.pointer(event)], this.operationGeneration);
  }

  sendScroll(deltaX: number, deltaY: number): void {
    const active: ProductSession | undefined = this.session;
    if (active?.state() !== ProductSessionState.STREAMING || !active.canSend(Capability.POINTER) ||
      !this.finite(deltaX, deltaY)) return;
    this.applyActions([active.scroll({ inputId: this.nextInputId++, deltaX, deltaY })], this.operationGeneration);
  }

  sendKey(usbHidUsage: number, pressed: boolean, modifierMask: number, text: string): void {
    const active: ProductSession | undefined = this.session;
    if (active?.state() !== ProductSessionState.STREAMING || !active.canSend(Capability.KEYBOARD) ||
      !Number.isInteger(usbHidUsage) || usbHidUsage <= 0 || !Number.isInteger(modifierMask)) return;
    this.applyActions([active.key({ inputId: this.nextInputId++, usbHidUsage, pressed, modifierMask, text })],
      this.operationGeneration);
  }

  onTransportReady(owner: number): void {
    if (owner !== this.operationGeneration) return;
    this.ui?.onStatus('正在协商 Protocol v1…', false);
    try { this.applyActions(this.requireSession().start(this.nowNs()), owner); this.armSessionWatchdog(owner); }
    catch (error) { this.onTransportLost((error as Error).message, false, owner); }
  }

  onControl(payload: Uint8Array, owner: number): void {
    if (owner !== this.operationGeneration) return;
    try {
      const active: ProductSession = this.requireSession();
      const previousState: ProductSessionState = active.state();
      this.applyActions(active.receive(payload, this.nowNs()), owner);
      if (!this.capabilitiesReported && active.state() === ProductSessionState.SELECTING_DISPLAY) {
        this.capabilitiesReported = true; this.ui?.onCapabilities(active.negotiatedCapabilities());
      }
      if (this.progressWatchdog.shouldRearm(previousState, active.state())) this.armSessionWatchdog(owner);
    }
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
    this.decoderGeneration += 1; this.session?.close(); this.controllerState.resetSession();
    this.closeWriter(); this.cancelHeartbeat();
    this.cancelSessionWatchdog(); this.cancelReconnect();
    this.renderedFirstFrame = false;
    this.cleanupLoss(cleanupOwner, reason, retryable).catch((error: Error) => {
      if (cleanupOwner === this.operationGeneration) this.ui?.onStatus(`连接清理失败：${error.message}`, false);
    });
  }

  onDecoderFailure(message: string, decoderOwner: number, operationOwner: number): void {
    if (decoderOwner !== this.decoderGeneration || operationOwner !== this.operationGeneration) return;
    this.onTransportLost(`硬件解码失败：${message}`, true, operationOwner);
  }

  onFrameRendered(decoderOwner: number, operationOwner: number): void {
    if (decoderOwner !== this.decoderGeneration || operationOwner !== this.operationGeneration) return;
    if (!this.renderedFirstFrame) {
      this.renderedFirstFrame = true; this.reconnectAttempt = 0; this.cancelSessionWatchdog();
      this.ui?.onStatus('正在串流', true);
    }
  }

  onDecoderWarning(message: string, decoderOwner: number, operationOwner: number): void {
    if (decoderOwner !== this.decoderGeneration || operationOwner !== this.operationGeneration) return;
    this.ui?.onStatus(`解码恢复中：${message}`, this.renderedFirstFrame);
  }

  onKeyframeRequired(reason: string, decoderOwner: number, operationOwner: number): void {
    if (decoderOwner !== this.decoderGeneration || operationOwner !== this.operationGeneration) return;
    const active: ProductSession | undefined = this.session;
    if (active?.state() !== ProductSessionState.STREAMING) return;
    this.applyActions([{ kind: 'send', intent: { kind: 'requestKeyframe',
      streamId: active.target().streamId, reason } }], operationOwner);
  }

  private async openFreshSession(owner: number): Promise<void> {
    try {
      this.cancelReconnect(); this.cancelSessionWatchdog(); this.renderedFirstFrame = false;
      this.progressWatchdog.configurationStarted();
      this.capabilitiesReported = false; this.pendingVideo = undefined;
      this.pendingVideoToken = undefined; this.pendingVideoOwner = 0; this.heartbeatSequence = 1n;
      const deviceId: string = await this.pairingStore.clientId();
      if (!this.isActive(owner)) return;
      this.session = new ProductSession(deviceId, 'HarmonyOS NEXT tablet',
        HARMONY_ADVERTISED_CAPABILITIES, [Codec.HEVC, Codec.H264]);
      this.controlWriter = new OutboundControlWriter((bytes: Uint8Array) => this.transport.sendControl(bytes),
        () => this.nowNs());
      this.ui?.onStatus('正在连接 Mac…', false);
      await this.transport.connect(this.host, this.port, new ControllerTransportListener(this, owner));
    } catch (error) {
      if (owner === this.operationGeneration) this.onTransportLost((error as Error).message, true, owner);
    }
  }

  private applyActions(actions: SessionAction[], owner: number): void {
    actions.forEach((action: SessionAction) => {
      if (action.kind === 'send') this.sendAction(action, owner);
      else if (action.kind === 'configureVideo') this.configureVideo(action.config, action.token, owner);
      else if (action.kind === 'heartbeat') this.startHeartbeat(action.intervalMs, owner);
      else if (action.kind === 'displayChanged') this.ui?.onVideoGeometry(action.width, action.height, action.rotationDegrees);
      else if (action.kind === 'media') this.videoDecoder.submit({ frameId: action.packet.header.frameId,
        epoch: action.packet.header.sessionEpoch, timestampNs: action.packet.header.captureTimestampNs,
        keyframe: action.packet.header.keyframe, payload: action.packet.payload });
      else this.onTransportLost(action.reason, action.retryable, owner);
    });
  }

  private configureVideo(config: VideoConfig, token: VideoConfigurationToken | undefined, owner: number): void {
    if (owner !== this.operationGeneration) return;
    if (token === undefined) throw new Error('Video configuration token is missing');
    this.renderedFirstFrame = false; this.progressWatchdog.configurationStarted();
    this.ui?.onStatus('正在配置视频…', false);
    if (this.surfaceId.length === 0) { this.pendingVideo = config; this.pendingVideoToken = token;
      this.pendingVideoOwner = owner;
      this.ui?.onStatus('等待视频画面初始化…', false); return; }
    this.pendingVideo = undefined; this.pendingVideoToken = undefined; this.pendingVideoOwner = 0;
    const active: ProductSession = this.requireSession();
    const epoch: bigint = active.epoch();
    const surface: string = this.surfaceId;
    const decoderOwner: number = ++this.decoderGeneration;
    this.videoDecoder.configure(config.codec, config.width, config.height, surface, epoch,
      new ControllerDecoderListener(this, decoderOwner, owner)).then(() => {
        if (!this.isCurrentVideoOperation(owner, decoderOwner, active, epoch, surface)) return;
        this.ui?.onVideoGeometry(config.width, config.height, config.rotationDegrees);
        this.applyActions(active.completeVideoConfiguration(token), owner);
      }).catch((error: Error) => {
        if (this.isCurrentVideoOperation(owner, decoderOwner, active, epoch, surface)) {
          this.ui?.onStatus(`硬件解码配置被拒绝：${error.message}`, false);
          try { this.applyActions(active.completeVideoConfiguration(token, false, 'decoder_configuration_failed'), owner); }
          catch (completionError) { this.onDecoderFailure((completionError as Error).message, decoderOwner, owner); }
        }
      });
  }

  private sendAction(action: SessionSendAction, owner: number): void {
    const active: ProductSession = this.requireSession();
    const writer: OutboundControlWriter | undefined = this.controlWriter;
    if (writer === undefined) { this.onTransportLost('Control writer is not initialized', true, owner); return; }
    writer.enqueue(action.intent, active.outboundScope(), action.onAssigned === undefined ? undefined :
      (messageId: bigint, nowNs: bigint) => active.confirmAssigned(action.onAssigned!, messageId, nowNs))
      .then((_receipt: OutboundControlReceipt) => {
        if (owner !== this.operationGeneration || this.session !== active) return;
        if (action.afterSend !== undefined) {
          active.confirmSent(action.afterSend);
          if (action.afterSend.kind === 'videoConfiguration' && action.afterSend.accepted) {
            this.applyActions([{ kind: 'send', intent: { kind: 'requestKeyframe',
              streamId: active.target().streamId, reason: 'decoder_configured' } }], owner);
            this.armSessionWatchdog(owner);
          }
        }
      }).catch((error: Error) => this.onTransportLost(error.message, true, owner));
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
      try {
        const active: ProductSession = this.requireSession();
        const nowNs: bigint = this.nowNs();
        if (active.heartbeatTimedOut(nowNs)) { this.onTransportLost('host_pong_timeout', true, owner); return; }
        if (!active.heartbeatPending()) this.applyActions([active.heartbeat(this.heartbeatSequence++)], owner);
      }
      catch (error) { this.onTransportLost((error as Error).message, true, owner); }
    }, intervalMs);
  }

  private cancelHeartbeat(): void {
    if (this.heartbeatTimer >= 0) { clearInterval(this.heartbeatTimer); this.heartbeatTimer = -1; }
  }

  private armSessionWatchdog(owner: number): void {
    if (owner !== this.operationGeneration) return;
    this.cancelSessionWatchdog();
    const active: ProductSession | undefined = this.session;
    if (active === undefined || active.state() === ProductSessionState.CLOSED || this.renderedFirstFrame) return;
    const delay: number = this.progressWatchdog.delayMs(active.state());
    this.sessionWatchdogTimer = setTimeout(() => {
      this.sessionWatchdogTimer = -1;
      if (owner !== this.operationGeneration) return;
      const current: ProductSession | undefined = this.session;
      const action: ProgressDeadlineAction = current === undefined ? 'reconnect' :
        this.progressWatchdog.deadlineAction(current.state(), this.renderedFirstFrame);
      if (action === 'requestKeyframe') {
        this.onKeyframeRequired('first_frame_timeout', this.decoderGeneration, owner);
        this.armSessionWatchdog(owner);
        return;
      }
      if (action === 'none') return;
      this.onTransportLost(`session_progress_timeout:${current?.state() ?? 'missing'}`, true, owner);
    }, delay);
  }

  private cancelSessionWatchdog(): void {
    if (this.sessionWatchdogTimer >= 0) { clearTimeout(this.sessionWatchdogTimer); this.sessionWatchdogTimer = -1; }
  }

  private closeWriter(): void {
    this.controlWriter?.close('Session generation ended');
    this.controlWriter = undefined;
  }

  private sendControllerSamples(samples: ControllerLifecycleSample[]): void {
    const active: ProductSession | undefined = this.session;
    if (active?.state() !== ProductSessionState.STREAMING || !active.canSend(Capability.CONTROLLER)) return;
    try {
      samples.forEach((sample) => this.applyActions([
        active.controller(this.advancedInputMapper.controller(this.nextInputId++, sample))
      ], this.operationGeneration));
    } catch (error) {
      this.ui?.onStatus(`控制器输入被拒绝：${(error as Error).message}`, true);
    }
  }

  private async releaseAdvancedInputs(): Promise<CleanupFailure[]> {
    const active: ProductSession | undefined = this.session;
    const writer: OutboundControlWriter | undefined = this.controlWriter;
    const actions: SessionAction[] = active?.releaseAdvancedInputs(() => this.nextInputId++) ?? [];
    this.controllerState.resetSession();
    if (active === undefined || writer === undefined || actions.length === 0) return [];
    return runAllCleanup([{ name: 'advanced-input.release', run: async () => {
      for (const action of actions) {
        if (action.kind !== 'send') throw new Error('Unexpected advanced input release action');
        await writer.enqueue(action.intent, active.outboundScope());
      }
    } }]);
  }

  private requireSession(): ProductSession {
    if (this.session === undefined) throw new Error('Session is not initialized'); return this.session;
  }

  private async cleanupLoss(owner: number, reason: string, retryable: boolean): Promise<void> {
    const failures: CleanupFailure[] = await this.cleanupResources();
    if (owner !== this.operationGeneration) return;
    const observableReason: string = failures.length === 0 ? reason :
      `${reason}；清理警告：${describeCleanupFailures(failures)}`;
    if (this.userStopped || !this.foreground) { this.ui?.onStatus(`连接中断：${observableReason}`, false); return; }
    if (!retryable) { this.ui?.onStatus(`连接失败：${observableReason}`, false); return; }
    this.scheduleReconnect(observableReason, owner);
  }

  private async cleanupResources(): Promise<CleanupFailure[]> {
    return runAllCleanup([
      { name: 'transport.close', run: () => this.transport.close() },
      { name: 'decoder.release', run: () => this.videoDecoder.release() }
    ]);
  }

  private cleanupStatus(status: string, failures: CleanupFailure[]): string {
    return failures.length === 0 ? status : `${status}；清理警告：${describeCleanupFailures(failures)}`;
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

  private finite(...values: number[]): boolean { return values.every((value: number) => Number.isFinite(value)); }
}
