import { ClientHello, Codec, defaultCapabilities, EnvelopeMetadata, InputPhase, NormalizedInput, TransportKind } from '../core/protocol/ProtocolModels';
import { ProtocolEncoder } from '../core/protocol/ProtocolEncoder';
import { ProtocolDecoder } from '../core/protocol/ProtocolDecoder';
import { CoordinateMapper, Rotation } from '../core/input/CoordinateMapper';
import { SessionStateMachine } from '../core/session/SessionStateMachine';
import { HarmonyTransport, TransportListener } from '../platform/HarmonyTransport';
import { systemDateTime } from '@kit.BasicServicesKit';

class PageTransportListener implements TransportListener {
  private connectedCallback: () => void;
  private messageCallback: (payload: Uint8Array) => void;
  private disconnectedCallback: (reason: string) => void;

  constructor(connected: () => void, message: (payload: Uint8Array) => void, disconnected: (reason: string) => void) {
    this.connectedCallback = connected;
    this.messageCallback = message;
    this.disconnectedCallback = disconnected;
  }
  onConnected(): void { this.connectedCallback(); }
  onControlMessage(payload: Uint8Array): void { this.messageCallback(payload); }
  onDisconnected(reason: string): void { this.disconnectedCallback(reason); }
}

@Entry
@Component
struct Index {
  @State host: string = '';
  @State port: string = '5900';
  @State status: string = '未连接';
  @State streaming: boolean = false;
  private session: SessionStateMachine = new SessionStateMachine();
  private encoder: ProtocolEncoder = new ProtocolEncoder();
  private decoder: ProtocolDecoder = new ProtocolDecoder();
  private transport: HarmonyTransport = new HarmonyTransport();
  private mapper: CoordinateMapper = new CoordinateMapper();
  private nextInputId: bigint = 1n;
  private sessionId: Uint8Array = new Uint8Array();

  private metadata(messageId: bigint): EnvelopeMetadata {
    return ProtocolEncoder.metadata(messageId, this.sessionId, this.session.sessionEpoch(),
      BigInt(systemDateTime.getRealActiveTime(true)));
  }

  private async connect(): Promise<void> {
    if (this.host.trim().length === 0) { this.status = '请输入 Mac 地址'; return; }
    const targetPort: number = Number(this.port);
    if (!Number.isInteger(targetPort) || targetPort < 1 || targetPort > 65535) { this.status = '端口无效'; return; }
    this.session.beginConnect();
    this.status = '正在连接…';
    const hello: ClientHello = {
      minimumProtocol: 1, maximumProtocol: 1, deviceId: 'harmony-device', deviceName: 'HarmonyOS tablet',
      capabilities: defaultCapabilities(), codecs: [Codec.HEVC, Codec.H264], transports: [TransportKind.LAN]
    };
    const listener: PageTransportListener = new PageTransportListener(
      () => {
        this.session.transportReady();
        this.status = '正在协商 Protocol v1…';
        this.transport.sendControl(this.encoder.clientHello(this.metadata(1n), hello))
          .catch((error: Error) => this.onDisconnected(error.message));
      },
      (payload: Uint8Array) => this.onControlMessage(payload),
      (reason: string) => this.onDisconnected(reason)
    );
    try { await this.transport.connect(this.host.trim(), targetPort, listener); }
    catch (error) { this.onDisconnected((error as Error).message); }
  }

  private onControlMessage(payload: Uint8Array): void {
    try {
      const envelope = this.decoder.envelope(payload);
      if (envelope.protocolVersion !== 1) throw new Error('Mac 返回了不支持的协议版本');
      if (envelope.payloadField === 22) {
        const accepted = this.decoder.sessionAccepted(envelope.payload);
        this.sessionId = accepted.sessionId;
        this.session.accept(accepted.sessionEpoch);
        this.streaming = true;
        this.status = '已连接';
      } else if (envelope.payloadField === 23 || envelope.payloadField === 80) {
        throw new Error('Mac 拒绝了会话');
      }
    } catch (error) { this.onDisconnected((error as Error).message); }
  }

  private onDisconnected(reason: string): void {
    this.streaming = false;
    this.session.disconnected(true);
    this.status = `连接中断：${reason}`;
  }

  private handleTouch(event: TouchEvent): void {
    if (!this.streaming || event.touches.length === 0) return;
    const touch: TouchObject = event.touches[0];
    const point = this.mapper.map(touch.x, touch.y, { left: 0, top: 0, width: 1000, height: 700, rotation: Rotation.DEG_0 });
    let phase: InputPhase = InputPhase.CHANGED;
    if (event.type === TouchType.Down) phase = InputPhase.BEGAN;
    if (event.type === TouchType.Up) phase = InputPhase.ENDED;
    if (event.type === TouchType.Cancel) phase = InputPhase.CANCELLED;
    const normalized: NormalizedInput = { inputId: this.nextInputId++, pointerId: touch.id, phase,
      x: point.x, y: point.y, pressure: touch.pressure, tiltX: 0, tiltY: 0, buttonMask: 0 };
    const bytes: Uint8Array = this.encoder.touch(this.metadata(this.nextInputId), normalized);
    this.transport.sendControl(bytes).catch((error: Error) => this.onDisconnected(error.message));
  }

  build() {
    Column({ space: 20 }) {
      Row() {
        Column() {
          Text('VIBE SCREEN').fontSize(12).fontWeight(FontWeight.Bold).fontColor('#6CE5B1').letterSpacing(2)
          Text('让平板成为 Mac 的第二块屏幕').fontSize(28).fontWeight(FontWeight.Bold).fontColor(Color.White)
          Text('HarmonyOS NEXT 原生客户端 · Protocol v1').fontSize(14).fontColor('#A7B0C0').margin({ top: 6 })
        }.alignItems(HorizontalAlign.Start).layoutWeight(1)
        Text(this.status).fontSize(13).fontColor(this.streaming ? '#6CE5B1' : '#F2B84B')
          .backgroundColor('#202B3C').padding({ left: 14, right: 14, top: 8, bottom: 8 }).borderRadius(18)
      }.width('100%')

      Stack() {
        if (this.streaming) {
          XComponent({ id: 'video-surface', type: XComponentType.SURFACE }).width('100%').height('100%')
        } else {
          Column({ space: 12 }) {
            Text('连接 Mac').fontSize(22).fontWeight(FontWeight.Medium).fontColor(Color.White)
            TextInput({ placeholder: 'Mac 的局域网地址', text: this.host }).onChange((value: string) => this.host = value)
              .height(52).backgroundColor('#202B3C').fontColor(Color.White).borderRadius(12)
            TextInput({ placeholder: '端口', text: this.port }).type(InputType.Number).onChange((value: string) => this.port = value)
              .height(52).backgroundColor('#202B3C').fontColor(Color.White).borderRadius(12)
            Button('连接').width('100%').height(52).backgroundColor('#6CE5B1').fontColor('#101828').fontWeight(FontWeight.Bold)
              .onClick(() => { this.connect(); })
            Text('首次连接请扫描 Mac 上的一次性配对码；手动地址仅用于已配对设备。').fontSize(13).fontColor('#A7B0C0')
          }.width(420).padding(28).backgroundColor('#172235').borderRadius(20)
        }
      }.width('100%').layoutWeight(1).backgroundColor('#090F1A').borderRadius(22).onTouch((event: TouchEvent) => this.handleTouch(event))

      Row({ space: 20 }) {
        Text('触控 · 键鼠 · 手写笔').fontSize(13).fontColor('#A7B0C0')
        Blank()
        Text('HEVC / H.264 硬解').fontSize(13).fontColor('#A7B0C0')
      }.width('100%')
    }.width('100%').height('100%').padding({ left: 36, right: 36, top: 28, bottom: 24 }).backgroundColor('#101828')
  }
}
