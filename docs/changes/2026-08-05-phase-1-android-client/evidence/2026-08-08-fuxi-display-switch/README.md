# 2026-08-08 fuxi 顶部胶囊切 display（单物理屏 → 物理屏 + 虚拟扩展屏）

设备：小米 12 (fuxi)，Android 16 LineageOS，USB。下文命令用占位符 `$ADB_SERIAL`
代表该机的 adb 序列号，`$REPO` 代表本仓库检出根目录；执行前先各自 export 实际值。
主机：macOS 26.4.1 (Build 25E253)，仅 1 块物理屏（Built-in Liquid Retina XDR）。

## 目标

单物理屏的 Mac 上，Host 额外提供一块可选的虚拟扩展显示（"Telemachus
Virtual (扩展屏)"），让顶部胶囊出现两枚 chip，客户端选择即可在物理主屏与
虚拟扩展屏之间实时切换真实捕获源，真正跑通「胶囊切 display」。

## 根因

Host 以 currentMain 捕获唯一的物理屏，ListDisplays 只回 1 个条目；客户端
capsule 在 <=1 个 display 时收起（GONE），无从切换。私有 CGVirtualDisplay
API 在本机可用（host-self-test 探针：available；任务侧 runtime 探针
VIRTUAL_DISPLAY_CAPABLE=YES）。

## 改了什么（仅 Host 侧，客户端无需改动）

文件：baseline/MacHost/Sources/AppDelegate.swift
- 新增常量：virtualExtendedDisplaySyntheticID = "telemachus-virtual-extended"
  （非数字，永不与真实 CGDirectDisplayID 冲突）、virtualExtendedDisplayName、
  virtualExtendedDefaultWidth/Height (1920x1080)。
- 新增 protocolV1DisplayCatalog(activeCaptureID:activeDisplaySource:configuredSize:)：
  枚举所有在线物理屏（真实数字 id）；当私有虚拟屏 API 可用时追加一个虚拟条目
  (isVirtual=true)。物理屏在捕获时该条目用合成 id；虚拟屏正在被捕获时改用其
  真实数字 id，从而让 active descriptor 与已推流身份一致。捕获虚拟屏时跳过它
  在 onlineDisplays() 里的物理重复项，避免同一 id 出现两次。
- setProtocolV1Displays 的喂料从「只喂物理屏」改为调用上述 catalog 构造器，
  单物理屏时 ListDisplays 现在返回 2 个条目。
- 重写 handleClientDisplaySelection：请求 id == 合成虚拟 id（或等于当前活跃虚拟
  屏的真实 id）→ 切 settings.displaySource=.extended，走既有 .extended 重配置
  路径（VirtualDisplayManager 创建/复用虚拟屏并重捕获），fail-safe：私有 API
  不可用时记日志并忽略，不吞异常；已在 .extended 时直接返回不重复切换。请求为
  物理数字 id → 走既有 .selectedDisplay 路径（同时能从 .extended 切回物理屏）。
  两个分支都复用既有 server.selectProtocolV1Display(id) 驱动协议重协商。
- 复用既有 startServer 的 .extended 分支（VirtualDisplayManager.createDisplay +
  disableMirrorMode）与 setupForDisplay 重捕获，未新造捕获链路；虚拟屏 hiDPI/
  分辨率取 settings 配置；切换后 setProtocolV1VideoConfiguration 的
  displayID=String(captureDisplayID)、isVirtual 与目录条目保持一致。

文件：baseline/MacHost/Sources/ProtocolV1SelfTest.swift
- 新增 testVirtualDisplayCatalog（并注册进 run()）：构造含合成虚拟条目的
  session，断言 ListDisplays 枚举出该虚拟条目 (isVirtual=true, isPrimary=false)、
  StartDisplay/运行时 selectDisplayFromClient(合成 id) 被接受、descriptor 反映
  虚拟身份、且 configEpoch 从 1 bump 到 2（客户端据此重协商视频）。

会话/协议层与客户端本身无需改动：多 display 目录、运行时切换 bump epoch、
客户端 selectDisplay 回传 id 的能力已就绪，虚拟条目只是目录里多出的一项。

## 离线证据（全绿）

- swift build -c release：Build complete。
- --protocol-v1-self-test：PASS（含新增 testVirtualDisplayCatalog）。
- --transport-self-test：PASS（前提：先移除 adb reverse tcp:54321，否则 54321
  被占用会导致 protocolV1Lifecycle=false 的环境性 FAIL，与本改动无关）。
- --host-self-test：PASS；探针确认私有虚拟屏 API available。
- Android 单测：:app:testDebugUnitTest --tests '*ProtocolV1SessionTest'
  --tests '*StreamClientProtocolV1IntegrationTest' → BUILD SUCCESSFUL。
详见 offline-selftests.txt、machost.diff。

## before 证据（复现了用户报告的 bug）

见 before-capsule-dumpsys.txt：出流态下 displayCapsuleGroup 与 displayToggleGroup
的 dumpsys 标志为 G（GONE）、bounds 0,0-0,0 —— 单 display 时胶囊收起，无从切换。
before-host-pipeline.txt：切换前旧 Host 稳定 60.0fps、dropped=0。

## 被 GATE 的真机切换验证（未完成，原因如实记录）

阻断原因：
1. Host 是 .regular NSApplication，需要 Aqua/WindowServer 会话；从 exec/后台
   shell detached 启动会立即退出（环境限制，非代码 bug）。
2. 重新编译已覆盖 .build/release/Telemachus，原持有 TCC 屏幕录制授权的进程
   （PID 43970）已被 kill，无法脚本恢复；新二进制需在系统设置里重新授权，
   该操作无法脚本化。

因此虚拟屏「真机上真实创建 + 捕获切换」这一步未取得设备证据，标记为待用户
执行的 open gate。切勿据离线结果外推真机行为。

## 给用户的精确复现步骤（重启 + 重授 + 抓证据）

1. 从 GUI 启动新 Host（不要产 .app、不要重签）：
   - Finder：前往 $REPO/baseline/MacHost/.build/release/
     ，双击 Telemachus；或 Spotlight/终端里用 open 之外的 GUI 方式启动。
   - 也可在有图形会话的终端里直接运行：
       $REPO/baseline/MacHost/.build/release/Telemachus
2. 重新授权屏幕录制：系统设置 → 隐私与安全性 → 屏幕录制 → 打开 Telemachus 的
   开关（若已存在旧条目，先移除再重新添加/勾选）；按提示可能需要退出并重开
   Telemachus 一次使授权生效。需要触控则同时在「辅助功能」里勾选 Telemachus。
3. USB 桥接：
       adb -s "$ADB_SERIAL" reverse tcp:54321 tcp:54321
4. 启动 Android 客户端并连接（自动 USB 连接开启即可）。
5. 观察两枚 chip 并切换：
   - 顶部胶囊应出现 2 枚 chip：物理屏 + "Telemachus Virtual (扩展屏)"。
   - 点第二枚 → Host 切到 .extended、创建/捕获虚拟屏、bump configEpoch、下发新
     VideoConfig；客户端重协商后继续出流。再点第一枚切回物理屏。

## 抓哪些日志作为权威证据（FLAG_SECURE 下 screencap 抓不到视频，用日志）

- ListDisplays count=2 与虚拟条目：客户端 logcat
    adb -s "$ADB_SERIAL" logcat | grep -i onDisplaysAvailable
  应出现 count=2，displays 里含 telemachus-virtual-extended:...:isVirtual 与
  negotiated 含 CAPABILITY_MULTI_DISPLAY。
- 胶囊两枚可点 chip：
    adb -s "$ADB_SERIAL" shell dumpsys activity top | grep -Ei 'displayToggleGroup|displayCapsuleGroup'
  displayCapsuleGroup 变 V（VISIBLE），displayToggleGroup 下含 2 个
  MaterialButton 且 bounds 非 0。
- 切换动作与重协商：客户端 logcat 出现 "capsule selectDisplay target=..."、
  selectDisplay、随后新的 onVideoConfiguration；Host 日志出现虚拟屏创建/捕获切换
  （"Virtual display created" / "Client selected the virtual extended display"）。
- 切换前后仍 60fps、dropped=0：
    Host  ~/Library/Logs/Telemachus/telemachus.log 里 "Pipeline: 60.0fps ... dropped: 0"
    客户端 logcat 里解码统计 dropped=0（"Decode stats"）。
- configEpoch bump：切换后新 VideoConfig 的 configEpoch 相对上一次 +1（离线
  self-test 已证明 1→2；真机上应随每次切换递增）。

证据落盘：把上述 Host 日志片段、客户端 logcat 片段、dumpsys（含 2 枚 chip 的
bounds）保存到本目录，命名如 after-*.txt，并在本 README 追加 after 小节。

## 交接摘要

- 已完成：Host 侧代码改动 + 新增 self-test；离线 build/self-test/Android 单测全绿；
  before 证据已抓（胶囊 GONE，证明 bug）。
- 未完成（GATE，需用户操作）：真机上虚拟屏真实创建/捕获切换与两枚 chip 的
  设备证据 —— 被 GUI/WindowServer 会话限制 + TCC 屏幕录制需手动重授阻断。
- 环境已清理：无残留 Telemachus/setsid/swift build 进程；54321 无监听；
  为跑 transport self-test 已移除 adb reverse，如需联调请按上面步骤重建。
