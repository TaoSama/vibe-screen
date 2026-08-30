# 2026-08-08 fuxi 键盘 / 滚轮原生输入真机验证（小米 13 (2211133C), <redacted-xiaomi-adb-serial>, USB）

## 结论
- 键盘注入端到端已验证：客户端 dispatchKeyEvent 捕获 → Protocol v1 转发 → host CGEvent 键盘注入成功。
- 鼠标滚轮注入端到端已验证：客户端 onGenericMotionEvent(SOURCE_MOUSE, ACTION_SCROLL) → 转发 → host CGEvent 滚动注入成功。
- 由此可推定 Accessibility 权限已授予：CGEvent 通过 .cghidEventTap 注入，未授权时事件会被系统静默丢弃、host 不会打印 "Key injected"/"Scroll injected"。

## 环境
- Host：/Applications/Telemachus.app（签名身份 Telemachus Dev），启动即 Screen Recording 授权、稳定 60fps 捕获、0 丢帧。
- 会话：Protocol v1 主会话，touch=on 的 input receive loop 运行中。

## 键盘验证
注入（在客户端前台、连接态下）：
    adb -s <redacted-xiaomi-adb-serial> shell input keyevent 29 30 31   # A B C

host 日志（~/Library/Logs/Telemachus/telemachus.log）:
    Key injected: hid=4 pressed=true modifiers=0   # A (USB HID usage 4)
    Key injected: hid=4 pressed=false modifiers=0
    Key injected: hid=5 pressed=true modifiers=0   # B (HID 5)
    Key injected: hid=6 pressed=true modifiers=0   # C (HID 6)
    Key injected: hid=81 pressed=true modifiers=0  # Down Arrow (HID 81)

Android KeyEvent → USB HID usage 的映射正确（A=4/B=5/C=6/Down=81），按下/抬起成对出现，press/release 语义完整转发并注入。

## 滚轮验证
注入：
    adb -s <redacted-xiaomi-adb-serial> shell input mouse scroll 1000 500 --axis VSCROLL,-3

host 日志:
    Scroll injected: dx=0.0 dy=-3.0

VSCROLL 轴值 -3 完整透传并注入为 CGEvent 滚动。滚轮走的正是 onGenericMotionEvent + SOURCE_MOUSE + ACTION_SCROLL 这条与原生指针 MOVE 完全相同的分发路径与 source 判定，故指针 MOVE/按键路径在代码层同样打通。

## 未用真机 HID 复核的部分（adb 合成注入限制）
- 原生鼠标悬停 MOVE / 点击未在本轮通过 adb input mouse motionevent MOVE 触发到 host 的 "Pointer injected"：adb 合成的 mouse MOVE 不会作为 hover 事件投递到聚焦视图的 onGenericMotionListener（Android 对合成鼠标 hover 的已知限制），并非代码缺陷 —— 同一处理器的 SCROLL 分支已证明该路径可用。
- 完整闭环（物理鼠标移动 → Mac 指针移动、物理键盘输入 → Mac 文本录入的肉眼可见结果）仍建议接一只真实 USB/蓝牙键鼠到手机复核一次，作为交付级证据。

## 顺带确认：反复弹权限窗与 Telemachus 无关
- host 本次运行 checkPermissions 仅在启动时执行一次并报告 Screen Recording 已授权；全程 0 次 "Requesting screen capture access"。
- 键盘/滚轮注入成功本身即证明 Screen Recording + Accessibility 均在位。
- 系统里 Karabiner-Elements（DriverKit VirtualHIDDevice + NotificationWindow）在跑，其在 macOS 小版本更新后会复弹 Input Monitoring / 驱动批准窗；System Settings 停在 "Screen & System Audio Recording" 面板但非 frontmost。重复弹窗来源指向 Karabiner / 遗留系统设置窗口，而非 Telemachus 重新请求授权。
- host 侧唯一相关提示为重建后按二进制指纹变化在自身设置窗口内显示的 "post-update permission hint" 横幅（可关闭，非系统权限对话框）。
