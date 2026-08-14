import { Capability, InputPhase, StylusContactState, StylusToolKind } from '../core/protocol/ProtocolModels';
import { PeripheralInputMapper } from '../core/input/PeripheralInputMapper';
import { Rotation } from '../core/input/CoordinateMapper';
import { SessionUiListener } from '../platform/HarmonySessionController';
import { sessionRuntime } from '../platform/SessionRuntime';
import { TrustedHostRecord } from '../platform/PairingStore';

const DEFAULT_PORT: string = '54321';
const SURFACE_ID: string = 'video-surface';

class PageSessionListener implements SessionUiListener {
  constructor(private statusCallback: (status: string, streaming: boolean) => void,
    private geometryCallback: (width: number, height: number, rotation: number) => void,
    private capabilityCallback: (capabilities: Capability[]) => void) {}
  onStatus(status: string, streaming: boolean): void { this.statusCallback(status, streaming); }
  onVideoGeometry(width: number, height: number, rotation: number): void { this.geometryCallback(width, height, rotation); }
  onCapabilities(capabilities: Capability[]): void { this.capabilityCallback(capabilities); }
}

@Entry
@Component
struct Index {
  @State host: string = '';
  @State port: string = DEFAULT_PORT;
  @State pairingLink: string = '';
  @State status: string = '未连接';
  @State streaming: boolean = false;
  @State busy: boolean = false;
  @State videoWidth: number = 1920;
  @State videoHeight: number = 1080;
  @State viewportWidth: number = 1;
  @State viewportHeight: number = 1;
  @State rotation: Rotation = Rotation.DEG_0;
  @State inputSummary: string = '等待能力协商';
  private surfaceController: XComponentController = new XComponentController();
  private keyMapper: PeripheralInputMapper = new PeripheralInputMapper();
  private sessionListener: PageSessionListener | undefined;

  aboutToAppear(): void {
    this.sessionListener = new PageSessionListener(
      (status: string, streaming: boolean) => {
        this.status = status; this.streaming = streaming;
        this.busy = status.startsWith('正在') || status.startsWith('等待') || status.includes('后重连');
      },
      (width: number, height: number, rotation: number) => {
        this.videoWidth = width; this.videoHeight = height; this.rotation = rotation as Rotation;
      },
      (capabilities: Capability[]) => {
        const inputs: string[] = ['触控'];
        if (capabilities.includes(Capability.KEYBOARD)) inputs.push('硬件键盘');
        if (capabilities.includes(Capability.POINTER)) inputs.push('鼠标');
        if (capabilities.includes(Capability.STYLUS_EXTENDED)) inputs.push('高级手写笔');
        else if (capabilities.includes(Capability.STYLUS)) inputs.push('手写笔');
        if (capabilities.includes(Capability.CONTROLLER)) inputs.push('控制器');
        this.inputSummary = inputs.join(' · ');
      });
    sessionRuntime.attachUi(this.sessionListener);
    sessionRuntime.restoreHost().then((record: TrustedHostRecord | undefined) => {
      if (record !== undefined) { this.host = record.host; this.port = record.port.toString(); }
    }).catch((error: Error) => { this.status = `读取主机记录失败：${error.message}`; });
  }

  aboutToDisappear(): void {
    this.pairingLink = '';
    if (this.sessionListener !== undefined) sessionRuntime.detachUi(this.sessionListener);
    this.sessionListener = undefined;
  }

  private async connect(): Promise<void> {
    const targetPort: number = Number(this.port);
    this.busy = true;
    try { await sessionRuntime.connect(this.host, targetPort); }
    catch (error) { this.status = (error as Error).message; this.busy = false; }
  }

  private async importLink(): Promise<void> {
    if (this.pairingLink.trim().length === 0) { this.status = '请粘贴 Mac 显示的主机链接'; return; }
    this.busy = true;
    try {
      const record: TrustedHostRecord = await sessionRuntime.importPairingLink(this.pairingLink);
      this.host = record.host; this.port = record.port.toString();
      this.status = '已导入地址；当前仅用于可信局域网开发模式';
    } catch (error) { this.status = (error as Error).message; }
    this.pairingLink = '';
    this.busy = false;
  }

  private handleTouch(event: TouchEvent): void {
    if (!this.streaming) return;
    const touches: TouchObject[] = event.changedTouches.length > 0 ? event.changedTouches : event.touches;
    let phase: InputPhase = InputPhase.CHANGED;
    if (event.type === TouchType.Down) phase = InputPhase.BEGAN;
    else if (event.type === TouchType.Up) phase = InputPhase.ENDED;
    else if (event.type === TouchType.Cancel) phase = InputPhase.CANCELLED;
    touches.forEach((touch: TouchObject) => {
      if (event.sourceTool === SourceTool.Pen) {
        sessionRuntime.sendStylus({ pointerId: touch.id, phase, x: 0, y: 0, pressure: event.pressure,
          tiltXDegrees: event.tiltX, tiltYDegrees: event.tiltY, toolKind: StylusToolKind.PEN,
          buttonMask: 0, contactState: StylusContactState.CONTACT }, touch.x, touch.y,
        this.viewportWidth, this.viewportHeight, this.rotation);
      } else {
        sessionRuntime.sendTouch(touch.id, phase, touch.x, touch.y,
          this.viewportWidth, this.viewportHeight, this.rotation, event.pressure);
      }
    });
  }

  private handleMouse(event: MouseEvent): void {
    if (!this.streaming) return;
    let phase: InputPhase = InputPhase.CHANGED;
    if (event.action === MouseAction.Press) phase = InputPhase.BEGAN;
    else if (event.action === MouseAction.Release) phase = InputPhase.ENDED;
    sessionRuntime.sendPointer(phase, event.x, event.y, this.viewportWidth, this.viewportHeight, this.rotation,
      event.button === MouseButton.None ? 0 : this.keyMapper.buttonMask(event.button));
  }

  private handleKey(event: KeyEvent): boolean {
    if (!this.streaming) return false;
    const usage: number | undefined = this.keyMapper.usbHidUsage(event.keyText);
    if (usage === undefined) return false;
    let modifierMask: number = event.metaKey === 1 ? 8 : 0;
    if (event.getModifierKeyState?.(['ctrl'])) modifierMask |= 1;
    if (event.getModifierKeyState?.(['shift'])) modifierMask |= 2;
    if (event.getModifierKeyState?.(['alt'])) modifierMask |= 4;
    sessionRuntime.sendKey(usage, event.type === KeyType.Down, modifierMask, event.keyText.length === 1 ? event.keyText : '');
    return true;
  }

  @Builder
  private connectionPanel() {
    Column({ space: 12 }) {
      Text('连接 Mac').fontSize(22).fontWeight(FontWeight.Medium).fontColor('#F8FAFC').width('100%')
      Text('Mac 地址').fontSize(14).fontColor('#CBD5E1').width('100%')
      TextInput({ text: this.host }).onChange((value: string) => this.host = value)
        .height(52).backgroundColor('#202B3C').fontColor('#F8FAFC').borderRadius(12)
      Text('端口').fontSize(14).fontColor('#CBD5E1').width('100%')
      TextInput({ text: this.port }).type(InputType.Number).onChange((value: string) => this.port = value)
        .height(52).backgroundColor('#202B3C').fontColor('#F8FAFC').borderRadius(12)
      Button(this.busy ? '正在处理…' : '连接').enabled(!this.busy).width('100%').height(52)
        .backgroundColor(this.busy ? '#64748B' : '#6CE5B1').fontColor('#101828').fontWeight(FontWeight.Bold)
        .onClick(() => this.connect())
      Divider().color('#334155').margin({ top: 8, bottom: 4 })
      Text('导入主机链接（可信 LAN 开发模式）').fontSize(14).fontColor('#CBD5E1').width('100%')
      TextInput({ text: this.pairingLink }).type(InputType.Password).onChange((value: string) => this.pairingLink = value)
        .height(52).backgroundColor('#202B3C').fontColor('#F8FAFC').borderRadius(12)
      Button('导入地址').enabled(!this.busy).width('100%').height(48).backgroundColor('#334155').fontColor('#F8FAFC')
        .onClick(() => this.importLink())
      Button('忘记已保存主机').enabled(!this.busy).width('100%').height(48).backgroundColor('#3B2530').fontColor('#FCA5A5')
        .onClick(() => {
          this.busy = true;
          sessionRuntime.forgetHost().then(() => { this.host = ''; this.port = DEFAULT_PORT; this.status = '已忘记主机'; this.busy = false; })
            .catch((error: Error) => { this.status = `删除主机失败：${error.message}`; this.busy = false; });
        })
      Text('链接中的一次性凭据不会写入本地。完整认证配对仍需 Mac 端协议接线与真机验证。')
        .fontSize(13).fontColor('#AEB9CB').lineHeight(20).width('100%')
    }.width('100%').constraintSize({ maxWidth: 520 }).padding(28).backgroundColor('#172235').borderRadius(20)
  }

  build() {
    Column({ space: 20 }) {
      Row() {
        Column() {
          Text('VIBE SCREEN').fontSize(12).fontWeight(FontWeight.Bold).fontColor('#6CE5B1').letterSpacing(2)
          Text('让平板成为 Mac 的第二块屏幕').fontSize(28).fontWeight(FontWeight.Bold).fontColor('#F8FAFC')
          Text('HarmonyOS NEXT 原生客户端 · Protocol v1').fontSize(14).fontColor('#AEB9CB').margin({ top: 6 })
        }.alignItems(HorizontalAlign.Start).layoutWeight(1)
        Text(this.status).fontSize(13).fontColor(this.streaming ? '#6CE5B1' : '#F5C76B')
          .backgroundColor('#202B3C').padding({ left: 14, right: 14, top: 10, bottom: 10 }).borderRadius(18)
      }.width('100%')

      Stack() {
        XComponent({ id: SURFACE_ID, type: XComponentType.SURFACE, controller: this.surfaceController })
          .width('100%').height('100%').opacity(this.streaming ? 1 : 0).focusable(this.streaming)
          .onLoad(() => sessionRuntime.setSurface(this.surfaceController.getXComponentSurfaceId()))
          .onDestroy(() => sessionRuntime.clearSurface())
          .onAreaChange((_oldValue: Area, newValue: Area) => {
            this.viewportWidth = Number(newValue.width); this.viewportHeight = Number(newValue.height);
          }).onTouch((event: TouchEvent) => this.handleTouch(event))
          .onMouse((event: MouseEvent) => this.handleMouse(event)).onKeyEvent((event: KeyEvent) => this.handleKey(event))
        if (!this.streaming) {
          this.connectionPanel()
        }
      }.width('100%').layoutWeight(1).backgroundColor('#090F1A').borderRadius(22)
        .alignContent(Alignment.Center).padding(this.streaming ? 0 : 24)

      Row({ space: 20 }) {
        Text(this.inputSummary).fontSize(13).fontColor('#AEB9CB')
        Blank()
        Text(`${this.videoWidth}×${this.videoHeight} · HEVC / H.264`).fontSize(13).fontColor('#AEB9CB')
      }.width('100%')
    }.width('100%').height('100%').padding({ left: 36, right: 36, top: 28, bottom: 24 }).backgroundColor('#101828')
  }
}
