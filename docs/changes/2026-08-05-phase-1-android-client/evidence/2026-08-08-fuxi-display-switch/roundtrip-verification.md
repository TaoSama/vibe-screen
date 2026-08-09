# 2026-08-08 小米 13 (2211133C, fuxi, 8a023e3a) — display 切换往返真机验证（主 Agent 独立复核）

设备：小米 13 (2211133C) fuxi，adb 8a023e3a，Android 16 LineageOS，USB。
Host：/Applications/Telemachus.app（ad-hoc，CDHash 21ba793849f5650cc905571d35cae2142ec281fb），open -a 前台 GUI 启动，屏幕录制已授权。
构建含四处修复：host in-place 切换(f9444ea) + 客户端 StartDisplay 重协商(f4c864a) + 客户端切换期丢帧(a8e8d4e) + host CGError/settle/mirror 容错(272bbc8)；客户端下拉菜单(2d8a843)。

## 判定：physical ↔ virtual ↔ physical 往返切换成功，全程无硬断连

### 胶囊几何（下拉改造后）
displayCapsuleGroup = 8,8-108,103（100px，仅显示器图标 controlDisplaysButton 0,0-95,95）。
对比改造前内联 chip 排 displayToggleGroup 溢出至 1540px（胶囊仅 824px）。下拉菜单 ListView 焦点 [1048,156][1901,408]，两行：
  "Telemachus Display · 1512×982" [1090,190][1859,247]
  "Telemachus Virtual (扩展屏) · 1920×1080" [1090,314][1859,376]

### 切到虚拟屏（physical→virtual）17:52:40
客户端 logcat：
  MA: capsule selectDisplay target=telemachus-virtual-extended from=1
  frame_dropped reason=drop_pending_configuration config_epoch=1   ← 客户端切换期丢帧修复生效（不再 fatal）
  MA: onVideoConfiguration: 1920x1080 @ 0° epoch=2
  MA: Decoder configuration committed 1920x1080 epoch=2
host log：
  verifyDisplayRegistered: displayID 8 NOT FOUND ... 随后 FOUND in online displays [1, 8]   ← settle/retry 生效
  disableMirrorMode did not complete but display 8 is not mirrored; proceeding with extended capture   ← mirror 容错
  Runtime display switch: source=extended captureID=8 stream=2000x1200   ← in-place 切换，未重建 server
  Capturing virtual display: 2000x1200 (ID: 8)
稳态：host Pipeline 60fps dropped:0；客户端 VD dropped=0。

### 切回物理屏（virtual→physical）17:53:40
客户端 logcat：
  MA: capsule selectDisplay target=1 from=telemachus-virtual-extended
  frame_dropped reason=drop_pending_configuration config_epoch=2
  MA: onVideoConfiguration: 1512x982 @ 0° epoch=3
  MA: Decoder configuration committed 1512x982 epoch=3
host log：
  Runtime display switch: source=selectedDisplay captureID=1 stream=1512x982
  Pipeline 短暂 dropped:3（epoch3 重配置瞬时）→ 随即 60fps dropped:0
稳态：host Pipeline 60fps dropped:0；客户端 VD dropped=0。

### 关键结论
- 两个方向切换均**无 INVALID_MEDIA_HEADER / 无 INVALID_STATE / 无 HOST_PROTOCOL_ERROR / 无 session 断连**。
- 仅有切换瞬间的预期性重配置丢帧（drop_pending_configuration / 3 帧），随即恢复 60fps/0-drop。
- 修复前症状（点虚拟屏 chip 闪断回主屏 / connection error）已消除。
- 下拉菜单替代溢出的内联 chip 排，胶囊收敛为 100px 单图标，避免误触与溢出。

验证人：主 Agent（Codex /root）独立在真机操作 + 读取 logcat/host log/dumpsys/uiautomator。

