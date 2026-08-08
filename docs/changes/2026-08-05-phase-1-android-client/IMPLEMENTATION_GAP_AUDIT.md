# Phase 1 实现缺口审计（README 承诺 vs 当前工作树源码）

- 审计日期：2026-08-08
- 分支：codex/phase1-display-selection-capsule
- 审计范围：只读源码核对，未构建、未连设备、未改动任何源码
- 结论定级：已实现并有测试 / 已实现但未验证 / 部分实现 / 桩代码 / 完全缺失

## 概述

README 在措辞上整体是克制且诚实的：它反复用 "verified / offline gates pass /
real-device acceptance pending / open gate" 区分"写了代码"和"真机验证过"。逐条核对源码后，
**没有发现"代码根本不存在却声称已实现"的硬造假**。真正的落差集中在两类：

1. **产品输入能力被永久关闭**：键盘 / 原生鼠标 / 外设输入在协议、host、client 三层都存在
   数据结构与解析代码，但生产路径的能力协商写死为"仅 touch + multiDisplay"，且 host 侧
   从未把 onKeyEvent/onPointerEvent/onScrollEvent 回调接到 CGEvent。这部分是"桩代码 +
   永不触发的分支"，README 的 Phase 1 清单把它们并列为交付项，容易让读者以为可用（README
   自己在 macOS host 段落已承认 legacy 只有 touch-derived pointer，但 "Current
   capabilities" 与 Phase 1 列表未同等醒目地标注键盘/鼠标不可用）。

2. **大量能力停留在 self-test / JVM 单测 / 离线门，真机未过**：镜像、HiDPI、旋转、
   虚拟扩展显示的实际抓取切换、window migration 的 AX 真实效果等，代码是真的，但只被
   纯逻辑自测覆盖，真机行为仍是 open gate。README 对这些多数已如实标注 gate，属"已实现但未验证"，
   谈不上夸大，但用户"感觉功能缩水"主要来源于此——写了不等于能用。

下面按能力逐条给证据。

## 能力对照表

| 能力（README/Phase 1 清单） | 状态 | 支撑证据（file:line / 测试） | README 是否夸大 |
| --- | --- | --- | --- |
| macOS host + Android client 可构建运行 | 已实现并有测试 | 完整 Swift/Kotlin 应用源码；CI 202/202 XCTest（历史 commit）；Android 123 JVM 测试 | 否 |
| USB 传输（adb reverse 54321） | 已实现并有测试 | StreamingServer 主会话；真机 Xiaomi 12 记录 | 否 |
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
| **键盘 / 快捷键输入** | 桩代码（生产永不触发） | 见"高优先级缺口 2" | 是（清单并列为交付，实际不可用） |
| **原生鼠标 / 外设输入** | 桩代码（生产永不触发） | 见"高优先级缺口 2" | 是（同上） |
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

### 缺口 2：键盘 / 原生鼠标 / 外设输入是"永不触发的桩代码"

三层都能看到相关代码，但生产路径被写死关闭，任何一层单独看都像"支持"，合起来则完全不可用：

- 协议 & 数据结构存在：ProtocolV1Session.swift:57-58（.key/.scroll/.pointer action）、
  ProtocolV1Session.swift:358-363（解析 KeyEvent）；Android ClientInputDispatch.kt 全套
  ClientKeyInput/ClientPointerInput/sendKey/sendPointer；AndroidKeyInputMapper.kt。
- **host 生产能力写死只有 touch + multiDisplay**：ProtocolV1Session.swift:17-18
  productionHostCapabilities = touchEnabled ? [.touch, .multiDisplay] : [.multiDisplay]。
  于是 negotiatedCapabilities 永不含 .keyboard/.pointer，KeyEvent/PointerEvent/ScrollEvent
  在 session 里必然走 unsupportedCapability 分支。
- **client 生产也只 advertise touch + multiDisplay**：ProtocolV1Session.kt:131-133。
  运行时唯一构造的 binding 是 LEGACY_TOUCH_ONLY.copy(displaySelection = true)：
  MainActivity.kt:2277；全仓 main 源码搜不到任何 keyboard = true / nativePointer = true。
- **host 侧回调根本没接线**：StreamingServer.swift:151-153 声明了 onPointerEvent /
  onScrollEvent / onKeyEvent，但 AppDelegate 只 assign 了 onTouchEvent / onInputCancelled /
  onDisplaySelectionRequested / onKeyframeRequested / onCodecNegotiated / onClientConnected /
  onServerFailed（AppDelegate.swift:1904/1969/2030/2049 等），三个输入回调从未赋值——
  即使协商开了也会被丢弃。

用户可感知的落差：Android 上就算插实体键盘/鼠标，也没有任何字节能被 host 消费。Phase 1 TEST.md
其实已诚实写明 "forwarding blocked by legacy host" / "native pointer/keyboard protocol
required"，但 README 顶部 "Product Vision" 与 Phase 1 "Complete … input" 清单把 keyboard /
mouse / peripheral 与 touch 并列，未在同等显眼处标注"当前完全不可用"。这是最容易被理解为"缩水"的点。

建议后续任务：要么让 host 在真正实现 CGEvent 键盘/指针注入后再把能力打开并接线（onKeyEvent ->
CGEvent keyboard、onPointerEvent -> mouse），要么在 README "Current capabilities" 显式加一行
"Keyboard/native mouse/peripheral input: not wired (scaffolding only)"，与 macOS host 段落
保持一致口径。

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

1. 输入能力口径对齐：README "Current capabilities" 明确加注键盘/原生鼠标/外设"仅脚手架、
   未接线"，与 macOS host 段落一致；或实装 host CGEvent 键盘/指针注入 + 打开能力协商 +
   接 onKeyEvent/onPointerEvent/onScrollEvent 回调。
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

