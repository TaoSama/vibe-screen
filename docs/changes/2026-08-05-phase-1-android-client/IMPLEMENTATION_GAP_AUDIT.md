# Phase 1 实现缺口审计（README 承诺 vs 当前工作树源码）

- 审计日期：2026-08-08
- 分支：codex/phase1-display-selection-capsule
- 审计范围：只读源码核对，未构建、未连设备、未改动任何源码
- 结论定级：已实现并有测试 / 已实现但未验证 / 部分实现 / 桩代码 / 完全缺失

## 2026-08-08 晚间更新（键盘/鼠标输入已接线）

本报告初版写于键鼠输入接线之前。此后分支已提交 `dab844f` / `ee617ae`，把下文
"缺口 2"描述的三层写死全部改掉，键盘/原生鼠标/滚轮输入在代码层已端到端接通：

- host 生产能力不再写死 touch-only：ProtocolV1Session.swift:17-23
  productionHostCapabilities 现返回 `[.touch, .keyboard, .pointer, .multiDisplay]`，
  并在 :393/:410/:418 分别处理 pointerEvent/scrollEvent/keyEvent（校验 .pointer/.keyboard 已协商）。
- host 回调已接线：AppDelegate.swift:2064/2080/2094 分别 assign onPointerEvent /
  onScrollEvent / onKeyEvent，注入走 CGEvent。
- client 已 advertise 全套：protocol/ProtocolV1Session.kt:134-139
  advertisedCapabilities 含 CAPABILITY_TOUCH/KEYBOARD/POINTER/MULTI_DISPLAY；
  MainActivity.kt:2300 起按协商结果提升 session binding（keyboard/nativePointer）。

因此下文"缺口 2"及对照表中键盘/原生鼠标两行的"桩代码（生产永不触发）"定级已过时。
当前应视为**Protocol v1 已实现，legacy 仍按设计保持 touch-only**：键盘、原生鼠标、
native wheel wire payload、stylus、controller 和 generic peripheral 输入必须完成 Protocol v1
能力协商后才可发送；legacy 或未协商 peer 必须 fail closed，不能收到新增输入字节。
legacy wheel-to-touch 和 secondary-button long-press adapter 是保留的 touch-compatible 例外，
不是 native wheel/button wire payload。键盘和滚轮已有真机端到端证据；native pointer
move/click、controller runtime、physical stylus 和具体 peripheral hardware 仍是 open gate，
需对应物理设备证据后才能关闭。

## 概述

README 在措辞上整体是克制且诚实的：它反复用 "verified / offline gates pass /
real-device acceptance pending / open gate" 区分"写了代码"和"真机验证过"。逐条核对源码后，
**没有发现"代码根本不存在却声称已实现"的硬造假**。当前仍需要按协议边界区分两类落差：

1. **输入能力只属于 Protocol v1 negotiated session**：键盘、原生鼠标、native wheel wire payload、
   stylus、controller 和 generic peripheral 输入在 Protocol v1 production path 已接线或定义了
   fail-closed admission；legacy compatibility session 仍按设计保持 touch-compatible，不新增
   keyboard/native-mouse/controller/peripheral wire type。legacy wheel-to-touch 和 secondary-button
   long-press adapter 是保留的 touch-compatible 例外。键盘和滚轮已有真机端到端证据，native
   pointer move/click、controller runtime、physical stylus 和具体 peripheral hardware 仍需物理设备证据。

2. **大量能力停留在 self-test / JVM 单测 / 离线门，真机未过**：镜像、HiDPI、旋转、
   虚拟扩展显示的实际抓取切换、window migration 的 AX 真实效果等，代码是真的，但只被
   纯逻辑自测覆盖，真机行为仍是 open gate。README 对这些多数已如实标注 gate，属"已实现但未验证"，
   谈不上夸大，但用户"感觉功能缩水"主要来源于此——写了不等于能用。

下面按能力逐条给证据。

## 能力对照表

| 能力（README/Phase 1 清单） | 状态 | 支撑证据（file:line / 测试） | README 是否夸大 |
| --- | --- | --- | --- |
| macOS host + Android client 可构建运行 | 已实现并有测试 | 完整 Swift/Kotlin 应用源码；CI 202/202 XCTest（历史 commit）；Android 123 JVM 测试 | 否 |
| USB 传输（adb reverse 54321） | 已实现并有测试 | StreamingServer 主会话；真机小米 13 (2211133C) 记录 | 否 |
| Video（SCK/CGDisplayStream + VT HEVC/H.264 + MediaCodec） | 已实现并有测试 | ScreenCapture.swift、VideoEncoder.swift、Android VideoDecoder.kt；真机 60fps/6ms | 否 |
| Touch 转发到 CGEvent | 已实现并有测试 | AppDelegate.swift:2030 onTouchEvent -> handleTouch:2903；StreamInputMapper.swift | 否 |
| 手势派生的 scroll / 右键 / 拖拽 / 捏合 | 已实现但未验证 | AppDelegate.swift:2963-3233 手势状态机 + CGEvent 注入（本地合成，非独立 scroll 输入通道） | 轻微：这是 touch 手势合成，非真正外设输入 |
| Reconnect / 自动重连 | 已实现并有测试 | Android SessionAutomaticRetryCoordinator.kt；host UnattendedRecoveryPolicy.swift；ReconnectBackoffTest 等 | 否 |
| LAN（受信网络，认证不加密） | 已实现但未验证 | WirelessAuth.swift、StreamingServer.swift:74/249 wireless admission | 否（明确标注 experimental/未加密） |
| Protocol v1 主会话 | 已实现并有测试 | ProtocolV1Session.swift/.kt；StreamClientProtocolV1IntegrationTest（12/12）；ProtocolV1SessionTests.swift | 否 |
| **顶部胶囊选 display（真能切）** | 部分实现（物理多屏可切；虚拟屏切换真机未过） | 见"高优先级缺口 1" | 轻微夸大→README 已标注虚拟屏 on-device gate |
| 虚拟扩展显示 | 已实现但未验证（依赖私有 API） | VirtualDisplayManager.swift:38 私有 CGVirtualDisplay；capability 仅做 class/selector 存在性检查 | 否（README 明确"private API，未创建/抓取验证"） |
| 镜像（mirror main） | 已实现但未验证 | AppDelegate.swift:1681-1698 enableMirrorMode()；私有 API；真机未过 | 否（gate 已列） |
| HiDPI 配置 | 已实现但未验证 | VirtualDisplayManager.swift:26/49 hiDPI 2x 物理像素；仅在虚拟屏创建时生效，私有 API 未验证 | 否 |
| 旋转 | 已实现但未验证（真机视觉未过） | host settings.rotation -> updateRotation (AppDelegate.swift:534-542)；Android 客户端本地 Surface 旋转 + 逆变换（TEST.md 标注 device check pending） | 否 |
| 自适应码率 | 部分实现（手动档位，非自动自适应） | VideoEncoder.swift:36-89 bitrate/quality/gamingBoost 为手动设置；无基于网络的自动降码率（自动自适应仅存在于 Phase3 Internet 的 AdaptiveMediaPolicy） | 中等：Phase 1 的 "adaptive video configuration" 实为手动配置 |
| **键盘 / 快捷键输入** | 已实现但未验证（原桩代码定级已过时，见晚间更新） | host 能力+回调已接线，client 已 advertise；真机 open gate | 否（代码已接通，待真机） |
| **原生鼠标 / 外设输入** | 已实现但未验证（原桩代码定级已过时，见晚间更新） | 同上（pointer/scroll 经 CGEvent 注入） | 否（代码已接通，待真机） |
| Window migration（迁移窗口到 client 屏 / 断连恢复） | 已实现但未验证 | WindowRecoveryManager.swift:45 moveFocusedWindow / :92 restoreManagedWindows；AppDelegate.swift:1357/2539 调用；AX 真实效果为 open gate | 否 |
| 权限引导（Screen Recording / Accessibility） | 已实现但未验证（真机审批未过） | PermissionOnboardingView.swift；host self-test 覆盖策略 | 否 |
| 可操作错误 | 已实现并有测试 | ConnectionGuidance.kt + ConnectionGuidanceTest；真机 "Open Vibe Screen on your Mac" 提示 | 否 |
| 两小时无增长 soak | 完全缺失（未验证） | README/Phase0 明确 open gate；30 分钟 soak 内存有增长 | 否（如实标注） |

## 高优先级缺口（按用户可感知程度排序）

### 缺口 1：顶部胶囊选 display —— 物理多屏能切，单屏 Mac 上"虚拟扩展屏"切换真机未验证

链路是真实且端到端接好的，不是纯 UI 摆设：

- Android 胶囊仅在 CAPABILITY_MULTI_DISPLAY 协商成功且 display 数 > 1 时才可点，
  单屏会折叠为一个禁用 chip：MainActivity.kt:1254-1266、2268-2283。
- 点选后 client 发 StartDisplayRequest：ProtocolV1Session.kt:271-289（selectDisplay）。
- host 收到后走 handleClientDisplaySelection：AppDelegate.swift:2567 起。
  - 物理屏：设置 settings.selectedDisplayID 并重新抓取（AppDelegate.swift:2597-2612）——
    在真正多显示器 Mac 上可切换。
  - 虚拟扩展屏：设置 settings.displaySource = .extended，走私有 CGVirtualDisplay
    创建 + 重新抓取（AppDelegate.swift:2580-2595 -> VirtualDisplayManager.swift）。
- 协议层被 host self-test / XCTest 覆盖：ProtocolV1SessionTests.swift:148
  testMultiDisplayEnumerationAndSelection。

用户可感知的落差：单屏 Mac（最常见开发场景）上，胶囊里那个"虚拟扩展屏"选项的**实际抓取切换**
从未在真机跑通——README 已把它列为 open gate（需要重启 GUI host + 手动重新授权 Screen
Recording，无法脚本化）。所以"能不能真的切"取决于你有没有第二台物理显示器。这一条 README 定性
基本准确，但普通用户读"display selection negotiation verified on device"很容易误以为"切屏可用"。

建议后续任务：在有第二台物理显示器或可脚本化重授权的机器上，补一次虚拟扩展屏 select ->
首帧抓取的真机证据；在 README 的胶囊描述里明确"单屏 Mac 上虚拟屏切换尚未真机验证"。

### 缺口 2：键盘 / 原生鼠标 / 外设输入是"永不触发的桩代码"（历史状态）

当前状态：该缺口已被后续 Protocol v1 输入接线取代，不应再作为 legacy fallback
待办解读。legacy wire format 仍故意只保留 touch-compatible 行为；键盘、原生鼠标、
native wheel wire payload、stylus、controller 和 generic peripheral 输入只在 Protocol v1
能力协商后进入对应 session sink。legacy wheel-to-touch adapter 仍是保留的
touch-compatible 例外。缺少物理 HID 鼠标真机 move/click 证据仍是 open gate，但它属于
Protocol v1 native-pointer acceptance，不是给 legacy session 增加 keyboard/native-mouse
entry point 的需求。

历史判断记录：初版审计时，三层都能看到相关数据结构，但生产能力和回调还未全部接线，容易被误读为
"支持"。这段判断只适用于当时的工作树，不适用于当前 main。

当前用户可感知边界：legacy compatibility session 不会发送键盘、原生鼠标、native wheel wire
payload、stylus、controller 或 generic peripheral 的新 wire type；旧 peer 只能继续收到
touch-compatible 行为。Android 端物理键盘会显示 touch-only host 兼容提示，native pointer
move/primary click 在未协商 pointer capability 时也应 fail closed 并提示；secondary click 和
wheel 仍可通过既有 touch 手势 adapter 兼容旧 host。

建议后续任务：不要给 legacy wire format 增加 keyboard/native-mouse 入口。应继续补 Protocol v1
native pointer HID 真机证据（手机接物理 USB/蓝牙鼠标 -> Host Pointer injected 日志 -> Mac 端
可见移动/点击），并按各自 runbook 补 controller、stylus、generic peripheral 物理设备证据；
证据不足时保持 README gate open。

### 缺口 3："自适应视频"实为手动档位，Phase 1 无网络自适应

README Product Vision 写 "adaptive resolution"，Phase 1 写 "adaptive video configuration"。
实际 Phase 1 只有手动 bitrate/quality/gamingBoost（VideoEncoder.swift:25-37/84-89，
AppDelegate.swift:519-527 观察 settings.$bitrate/$quality）。真正基于网络状况自动调整的
AdaptiveMediaPolicy 只存在于 Phase 3 Internet 路径（Sources/Phase3/InternetTransport/
AdaptiveMediaPolicy.swift），不在 USB/LAN 主会话里。

用户可感知的落差：中等。用户可以手动改档，但不会"根据卡顿自动降码率"。建议在 Phase 1 语境把
"adaptive" 明确为"manual bitrate/quality presets"，把自动自适应归到 Phase 3/后续。

### 缺口 4：镜像 / HiDPI / 虚拟屏 / window migration —— 代码真实但真机零证据

- 镜像：AppDelegate.swift:1681-1698 走私有 enableMirrorMode()；
- HiDPI：VirtualDisplayManager.swift:26/49 仅在虚拟屏创建时以 2x 物理像素生效；
- window migration：WindowRecoveryManager.swift:45/92 用 AX 移动/恢复窗口，
  AppDelegate.swift:1357 菜单项 moveFocusedWindowToClientDisplay、:2539 断连恢复。

这些都依赖私有显示 API 或 AX 真实行为，当前只有 host self-test / XCTest 的纯几何与策略覆盖，
真机首帧/真镜像态/真窗口迁移都是 open gate（Phase 1 macOS TEST.md "Remaining gates" 已列）。
README 定性准确，属"已实现但未验证"，不算夸大，但同样构成"看着有、没跑通"的观感来源。

建议后续任务：按 macOS host TEST.md 的 Remaining gates 逐条补真机证据（私有虚拟屏首帧、
mirror 前后态、AX 真窗口迁移/恢复、Launch at Login 审批、热插拔），每补一条就把对应 README 措辞
从 "implemented" 收敛到 "verified"。

## 建议后续任务（汇总）

1. 输入能力证据补齐：保持 legacy touch-only 协议边界，不新增 keyboard/native-mouse/controller/
   peripheral wire type；针对 Protocol v1 native pointer move/click 补物理 HID 鼠标真机证据，
   并按各自 runbook 补 controller、stylus、generic peripheral 物理设备证据。证据不足时保持
   README gate open。
2. 显示切换真机证据：单屏 Mac 上补虚拟扩展屏 select -> 首帧抓取真机记录；在胶囊相关文案标注
   单屏场景的虚拟屏切换尚未真机验证。
3. "adaptive video" 降级措辞：Phase 1 明确为手动档位，自动自适应归后续 Phase。
4. 私有显示 / AX 真机门：按 Phase 1 macOS TEST.md Remaining gates 补齐镜像、HiDPI、
   window migration、Launch at Login、热插拔的真机证据。
5. 两小时无增长 soak：仍是 open gate（30 分钟内存有增长），保持 open 直到真机跑通。

## 审计纪律说明

全程只用 rg/sed/cat 读源码，唯一写入为本报告文件；未执行 swift build / gradle / adb，
未触碰 /Applications 与设备。所有结论均带 file:line 或测试名；未找到实现的项如实标注。
（说明：审计中 rg 在部分调用下把标识符归一化输出，相关结论已改用逐段直接读取源码复核，不影响
上述 file:line 证据。）
