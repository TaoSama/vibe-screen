# 2026-08-08 fuxi 下拉胶囊真机验证（稳定签名 + Protocol v1 能力协商）

设备：Xiaomi 12 (fuxi, Android 16, USB) adb=8a023e3a（电量 100% 那台，唯一使用）
Host：/Applications/Telemachus.app，稳定自签 Telemachus Dev，CDHash d0679aec（重建不变）
分支：codex/phase1-display-selection-capsule

## 已验证（硬证据）

### 1. 屏幕录制授权 + 60fps 串流
host 日志 ~/Library/Logs/Telemachus/telemachus.log：
    2026-08-08T12:30:39Z Screen recording permission granted (CGPreflight)
    2026-08-08T12:31:57Z Pipeline: 60.0fps, 0.5Mbps, avg frame age: 5.9ms, dropped: 0
稳定 60fps、0 丢帧、帧龄 ~5.8ms。

### 2. 下拉胶囊真机可见（新交互）
adb -s 8a023e3a shell dumpsys activity top（controlBar/胶囊几何）：
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

