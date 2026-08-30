# 2026-08-08 fuxi 屏幕镜像真机验证（小米 13 (2211133C), <redacted-xiaomi-adb-serial>, USB）

## 结论
- 屏幕镜像（把 Mac 主屏显示到 Android）已真机验证可用。
- 原始 .mirrorMain 路径（建私有虚拟屏 + 硬件镜像主屏）在 macOS 26.4.1 上
  失败：CGConfigureDisplayMirrorOfDisplay 返回 CGError 1001，host 陷入
  unattended-recovery 死循环、无法出流。
- 已修复为优雅降级：镜像不可用时自动回退为直接捕获物理主屏，用户可见结果一致
  （Android 显示 Mac 主屏），60fps / 0 丢帧。

## 根因
VirtualDisplayManager.enableMirrorMode() 里 CGConfigureDisplayMirrorOfDisplay(
config, 虚拟屏, 主屏) 在本机 macOS 26.4.1 返回 CGError 1001（kCGErrorFailure）。
把私有虚拟显示器作为镜像目标去镜像物理主屏，在新版 macOS 上不被支持。
startServer 的 .mirrorMain 分支直接抛出 → 上层 unattended recovery 反复用同一失败
配置重试（1s/2s/4s… 退避），永远起不来。

## 修复
AppDelegate.startServer 的 .mirrorMain 分支包一层 do/catch：优先尝试虚拟屏硬件镜像，
失败则 debugLog 记录并回退 captureDisplayID = CGMainDisplayID()（等价 .currentMain 的
直接主屏捕获），virtualDisplayManager 置 nil。同时把广告给客户端的 isVirtual 从
"按请求模式" 改为 "按是否真的建了虚拟屏"（.extended 恒 true；.mirrorMain 仅在硬件镜像
成功时才 true，回退直捕主屏时为 false），避免向客户端谎报虚拟屏。

## 证据（host_log_excerpt.txt）
修复前（死循环）：
    Unattended startup failed: Mirror mode operation failed: Failed to configure mirror mode: CGError(rawValue: 1001)
    （多次退避重试，永不出流）
修复后：
    Virtual-display mirror unavailable (...CGError(rawValue: 1001)); falling back to direct main-display capture
    First frame received from SCStream
    Pipeline: 60.0fps, ..., dropped: 0
客户端 VibeScreenTelemetry stream_stats fps≈60.0、Decode dropped=0，确认镜像画面到达手机。

## 验证方式
1. swift build -c release + 三个离线 self-test（protocol-v1 / transport / host）全 PASS。
2. package_macos.py 重新打包签名并安装（稳定自签，免重授权）。
3. defaults write Telemachus_displaySource mirrorMain → open host → 观察回退日志与出流。
4. 恢复 selectedDisplay。

## 备注
- 若未来某版 macOS / GPU 恢复支持虚拟屏硬件镜像，优先路径会自动生效（未改其逻辑，仅加回退）。
- 真正的私有虚拟屏"扩展"（.extended）与 HiDPI 在本机是好的（见 2026-08-08-fuxi-hidpi），
  只有"镜像到虚拟屏"这一组合不被支持，故用直捕主屏达成等价镜像体验。
