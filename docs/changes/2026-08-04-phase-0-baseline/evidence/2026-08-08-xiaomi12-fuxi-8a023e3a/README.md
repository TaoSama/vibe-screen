# 小米 13 (2211133C, fuxi) 真机验收 + 根因修复证据

- 日期: 2026-08-08 (Asia/Shanghai)
- 设备: Xiaomi 2211133C / 代号 fuxi / Android 16 / SDK 36 / LineageOS
  fingerprint Xiaomi/fuxi/fuxi:16/BP2A.250605.031.A3/OS3.0.2.0.WMCCNXM:user/release-keys
- ADB endpoint / 硬件序列号: 8a023e3a (USB)
- 显示: Physical size 1080x2400, density 420
- Host: baseline/MacHost/.build/release/Telemachus (macOS 26.4.1), 监听 127.0.0.1:54321
- 客户端: dev.telemachus.display, versionName 0.0.0, debug 签名 (CN=Android Debug,
  SHA-256 b108fb9e0c8e5544171d57eb3be57d9fb93f332fc4954e26d5f51b20b876aa0b)

## 根因 (surface <-> video-config 死锁)

- videoViewport(含 SurfaceView)在断开态被设 View.GONE
  (MainActivity.kt showDisconnectedStreamUi, 原 line 1190;
   activity_main.xml videoViewport 原 visibility="gone")。
- SurfaceView 在 GONE 容器内不创建 surface, 因此不会触发 surfaceCreated/Changed,
  也不会调用 MainSessionDisplayLifecycle.onSurfaceReady()。
- Host 连接后立即下发 video config -> onVideoConfiguration ->
  configureDecoder 检查 currentSurfaceHolder.surface.isValid == false ->
  beginSurfaceWait (MainSessionDisplayLifecycle.kt:124,269) 1500ms 超时 ->
  decoder_surface_timeout -> 断链重连。
- showConnectedStreamUi()(把 videoViewport 变 VISIBLE 从而创建 surface)只在
  updateDisplayGeometry 回调里被调 (MainActivity.kt:2035); 但 geometry 消息在
  video-config 被 accept 之后才走到, 于是形成死锁: config 等 surface,
  surface 等 UI 切换, UI 切换等 config。
- 修复前 logcat (03-logcat-video.txt) 硬证据:
  onVideoConfiguration=10, waiting-for-valid-surface=10, decoder_surface_timeout=30,
  surfaceCreated/Changed=0, onDisplayGeometry=0, Selected-decoder=0, First-frame=0。

## 修复 (最小, 根因导向) — 见 10-fix.diff

- activity_main.xml: videoViewport 初始 visibility gone -> visible。
- MainActivity.kt showDisconnectedStreamUi: videoViewport 保持 VISIBLE(不再 GONE),
  由不透明的 disconnectedBackdrop(z 序在上)遮挡等待态残帧。
- 效果: SurfaceView 始终持有活动 surface, video config 到达即可绑定解码器;
  断开态触摸已有 !isConnected 早退保护 (handleTouch/handleGenericMotion), 无副作用。

## 修复后证据 (05-logcat-video-after-fix.txt)

- surfaceCreated + surfaceChanged 1080x2400
- Selected decoder: c2.qti.hevc.decoder (rateSupported=true)  ← 高通硬件 HEVC
- First frame: keyframe=true, surface valid=true, HEVC 头 00 00 00 01 40 01 ...
- onDisplayGeometry: 1512x982 @ 0°
- Decode stats 持续 input/output 递增到 1920/1919, dropped=0, 无 Codec error
- Host: Pipeline 60fps, dropped:0, avg frame age ~5ms

## Pass criteria 结论

1. APK 安装 + 冷启动无致命异常: PASS (LaunchState COLD, Status ok, 无 FATAL) — 见 03/05
2. 真实流到达硬件解码器并出帧: PASS (c2.qti.hevc.decoder, 首帧, 持续帧 0 丢) — 见 05
3. 两点触控驱动 Mac 指针: PASS — 见 07-touch-pointer.txt
4. 断链产生全新 connected 会话且 Host PID 存活: PASS (host 89286 不变;
   client 10641->11143; epoch 214->215; 新会话持续出流) — 见 08

## 文件

- 01 设备基线  02 Host 监听/reverse  03 修复前 logcat  04 修复前截图
- 05 修复后 logcat  06 修复后截图(SurfaceView 层 screencap 为黑属正常)
- 07 触控->指针  08 重连 logcat  09 前后对照  10 修复 diff
