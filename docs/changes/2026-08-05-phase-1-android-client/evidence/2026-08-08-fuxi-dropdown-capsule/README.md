# 2026-08-08 fuxi 下拉胶囊真机验证（稳定签名 + Protocol v1 能力协商）

设备：小米 13 (2211133C, fuxi, Android 16, USB) adb=<redacted-xiaomi-adb-serial>（电量 100% 那台，唯一使用）
Host：/Applications/Telemachus.app，稳定自签 Telemachus Dev，CDHash d0679aec（重建不变）
分支：codex/phase1-display-selection-capsule

## 已验证（硬证据）

### 1. 屏幕录制授权 + 60fps 串流
host 日志 ~/Library/Logs/Telemachus/telemachus.log：
    2026-08-08T12:30:39Z Screen recording permission granted (CGPreflight)
    2026-08-08T12:31:57Z Pipeline: 60.0fps, 0.5Mbps, avg frame age: 5.9ms, dropped: 0
稳定 60fps、0 丢帧、帧龄 ~5.8ms。

### 2. 下拉胶囊真机可见（新交互）
adb -s <redacted-xiaomi-adb-serial> shell dumpsys activity top（controlBar/胶囊几何）：
    CardView ... 851,53-1550,185 app:id/controlBar
      LinearLayout ... 8,8-486,124 app:id/displayCapsuleGroup   (V = 可见)
        AppCompatImageView ... 21,31-74,84  app:id/controlDisplaysButton (显示器图标)
        MaterialTextView   ... 90,35-394,81 app:id/controlDisplaysLabel  (当前显示器名)
        AppCompatImageView ... 410,34-457,81 app:id/controlDisplaysChevron (下拉箭头)
胶囊为"图标 + 当前显示器名 + chevron"的整行下拉选择器，居中于顶部，整行 44dp+ 为点击目标。
点击胶囊后 PopupMenu 弹出，抓到条目文字 "1512x982"（当前 primary 屏）。

### 3. 显示器协商 count=2 + 键鼠能力全开
客户端 logcat（MA）：
    onDisplaysAvailable: count=2 selected=1
      negotiated=[CAPABILITY_TOUCH, CAPABILITY_KEYBOARD, CAPABILITY_POINTER, CAPABILITY_MULTI_DISPLAY]
      displays=1:Telemachus Display:1512x982:primary=true,
               telemachus-virtual-extended:Telemachus Virtual (扩展屏):1920x1080:primary=false
    session binding promoted: displaySelection=true keyboard=true nativePointer=true
证明：胶囊在协商到 MULTI_DISPLAY 且 display 数=2 时可见可切；键盘/原生指针能力已协商成功（不再是桩代码）。

## 待补（下一步）
- 用户在真机点下拉选"Telemachus Virtual (扩展屏)" -> host in-place 切换到 .extended 捕获虚拟屏，
  logcat 出现 "capsule selectDisplay target=telemachus-virtual-extended"，host 日志出现虚拟屏创建/重捕获，
  往返回物理屏无 INVALID_MEDIA_HEADER、无断连。
- 键鼠注入端到端：手机接外设 -> host CGEvent 注入 -> Mac 指针/键入可见（需辅助功能授权）。



## 2026-08-08 真机切换往返验证（发现方向不对称断连 bug）

真机 <redacted-xiaomi-adb-serial>，唤出控制条后点胶囊弹 PopupMenu（窗口几何 mAttrs=(880,145)(853x252)，两项各 126px 高）。

### 物理屏 -> 虚拟扩展屏：成功
客户端 logcat：capsule selectDisplay target=telemachus-virtual-extended from=1
host 日志：
    Runtime display switch: source=extended captureID=10 stream=2000x1200
    Display source changed to extended — scheduling capture reconfiguration
    Pipeline: 60.4fps ... dropped: 0
in-place 切到虚拟屏，无断连，瞬时 54.6fps 后恢复 60fps 零丢帧。

### 虚拟扩展屏 -> 物理屏：断连（BUG）
客户端 logcat：
    capsule selectDisplay target=1 from=telemachus-virtual-extended
    session ended kind=INVALID_PEER_MESSAGE detail=invalid_peer_message:
      Protocol v1: StartDisplayResponse in state STREAMING
    Disconnected: INVALID_PEER_MESSAGE
host 日志：
    Runtime display switch: source=selectedDisplay captureID=1 stream=1512x982
    Display source changed to selectedDisplay — scheduling capture reconfiguration
host 切回物理屏成功，但客户端因收到"第二个"StartDisplayResponse 在 STREAMING 态而硬断连。

### 根因（源码定位）
客户端点选 -> ProtocolV1Session.kt:selectDisplay 发 StartDisplayRequest（state=REDISPLAY_REQUESTED）。
host 侧同一次选择触发两条会各发一个 StartDisplayResponse 的路径：
1. 客户端 StartDisplayRequest -> ProtocolV1Session.swift:282 in-place ->
   renegotiateSelectedDisplayLocked(:534/:552) 回 StartDisplayResponse+VideoConfig（第一个）。
   客户端 onStartDisplay 接受后回到 STREAMING。
2. 同时 onDisplaySelectionRequested -> AppDelegate.handleClientDisplaySelection ->
   switchCaptureSourceInPlace 末尾 server.selectProtocolV1Display(:2871) ->
   session.selectDisplayFromClient 又回一个 StartDisplayResponse（第二个）。
第二个到达时客户端已 STREAMING -> ProtocolV1Session.kt:onStartDisplay 抛
"StartDisplayResponse in state STREAMING" -> 断连。物理->虚拟因虚拟屏创建较慢时序侥幸未触发。

### 修复方向
区分"客户端发起"与"host(GUI)发起"的切换：客户端发起时，其 StartDisplayRequest 已由
renegotiateSelectedDisplayLocked 回应，host 主动路径不应再发第二个 StartDisplayResponse
（selectProtocolV1Display/selectDisplayFromClient 仅用于 GUI 端发起、无客户端请求的切换）。



## 2026-08-08 修复后真机复验（双向往返均不断连）+ 稳定签名免重授权验证

修复 commit 83243c7：删除 AppDelegate.switchCaptureSourceInPlace 末尾多余的
server.selectProtocolV1Display（客户端 StartDisplayRequest 已被 in-place 分支应答一次）。

### 稳定签名免重授权
host 源码改动后重新打包，二进制 cdhash 从 d0679aec 变为 e22f0f26，但签名身份仍是 Telemachus Dev。
安装新构建后 open 启动，日志直接 Pipeline: 60fps 捕获，无权限请求、无重新授权 —— TCC 按签名
designated requirement（而非 cdhash）匹配，证明稳定自签根治了"每次重建都要重新授权"。

### 双向往返（<redacted-xiaomi-adb-serial>，两轮均通过）
清爽会话 onDisplaysAvailable count=2（物理主屏 + 虚拟扩展屏），negotiated 含 KEYBOARD/POINTER/MULTI_DISPLAY。
Round 1:
  capsule selectDisplay target=telemachus-virtual-extended from=1
    host: Runtime display switch: source=extended captureID=13 -> Pipeline 60fps dropped:0，无 INVALID
  capsule selectDisplay target=1 from=telemachus-virtual-extended
    host: Runtime display switch: source=selectedDisplay captureID=1 -> Pipeline 60fps dropped:0
    客户端无 INVALID_PEER_MESSAGE / 无 session ended / 无 Disconnected（修复前必断连）
Round 2（同样两次切换）：全部干净，host Runtime display switch x2，客户端零断连。

结论：虚拟<->物理双向切换往返不再断连，修复有效且稳定（非时序侥幸）。

### 顺带定位（未改）
反复断连重连曾导致 onDisplaysAvailable count=3（残留虚拟屏 displayID 10/11/12 泄漏）+
键盘 toast "Update both apps" 误报（binding 在重连乱序后 sendKey 走 UNSUPPORTED）。host 重启清除残留虚拟屏后恢复 count=2。这些均为断连 bug 的连带效应；断连修复后重连不再发生，现场已消失。若后续仍复现残留虚拟屏，再单独收敛虚拟屏生命周期。

