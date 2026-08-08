# 2026-08-08 fuxi 客户端 UI 真机截图 + 调试期截屏开关（Xiaomi 12/13, 8a023e3a, USB）

## 背景
串流界面用 FLAG_SECURE 防止 Mac 画面被截图，导致真机 UI 无法用截图/uiautomator 验证。
新增仅 debug 生效的截屏开关，解锁真机 UI/UX 目检。

## 调试期截屏开关（仅 debuggable 构建）
- MainActivity.screenCaptureAllowedForDebug()：仅当 ApplicationInfo.FLAG_DEBUGGABLE 为真、
  且系统属性 debug.vibescreen.allow_capture == "1" 时返回 true；release 构建恒 false，
  FLAG_SECURE 行为不变。
- 用法：adb shell setprop debug.vibescreen.allow_capture 1，再启动 debug APK。
- 验证：串流中 dumpsys window 显示 MainActivity 窗口 fl=KEEP_SCREEN_ON …（无 FLAG_SECURE），
  screencap 拿到真实 2400x1080 非黑帧。

## 真机 UI 截图（本目录）
- 01-stream-stats-overlay.png：串流中右下角统计浮层 FPS 60.2 / BITRATE 0.7Mbps /
  RESOLUTION 1512x982 / RTT 5.2ms，画面填充视口、字号清晰、不遮挡主要内容。
- 02-control-bar.png：点触唤出的控制条——小而居中的深色圆角胶囊，含
  [显示器图标 + "Telemachus Display" + 下拉箭头] 选择器、齿轮设置、红色断连按钮。
  正是"小、居中、下拉选择器"的目标交互。
- 03-display-dropdown.png：点胶囊弹出的下拉，列出两块屏
  "Telemachus Display · 1512×982" 与 "Telemachus Virtual (扩展屏) · 1920×1080"，
  当前项可选、分辨率随行显示，可读性好。

## UX 观察
- 控制条 3s 自动隐藏、点视频唤出，避免持续遮挡 Mac 画面。
- 下拉选择器整行可点（44dp 目标），触屏友好，符合用户此前"胶囊应为下拉、别误触"的要求。

## 备注
- 旋转控件位于设置弹窗（FLAG_SECURE 对话框），其逻辑由 ViewportPolicy 单测覆盖；
  实时点击切换未脚本化（设置齿轮的盲点坐标不稳定，且不值得为此扰动会话）。
