# 2026-08-08 fuxi Phase 1 真机验证批次汇总（Xiaomi 12/13, codename fuxi, 8a023e3a, USB）

本批次在真机上关闭/确认的 README Phase 1 gate（每项单独有证据目录或已在 README 引用）：

## 已真机验证
- 键盘 + 鼠标滚轮输入：host CGEvent 注入成功（见 2026-08-08-fuxi-input）。
- HiDPI 私有虚拟显示器创建+捕获：4000x2400 物理 / 2000x1200 逻辑，60fps 0 丢帧
  （见 2026-08-08-fuxi-hidpi）。
- 屏幕镜像：修复虚拟屏硬件镜像 CGError 1001 死循环 → 优雅降级直捕主屏，60fps 0 丢帧
  （见 2026-08-08-fuxi-mirroring 及 host 代码修复 commit）。
- 物理<->虚拟<->物理 显示切换往返：见 2026-08-08-fuxi-dropdown-capsule。
- 自动重连 / 断连恢复：本批次多次重启 host（改配置/装新构建），客户端每次自动重连、
  session_epoch 递增、恢复 60fps；最后一次 14:05 杀 host 后客户端在数秒内重连并出流。
- 稳定自签免重授权：改 host 源码/配置后重建（cdhash 变化）+ open 启动，均直接
  "Screen recording permission granted"、0 次授权请求、无系统弹窗。

## 逻辑已验证、实时点击未脚本化（FLAG_SECURE 限制）
- 客户端旋转：ViewportPolicy.effectiveRotation/normalizeRotation 单测通过，
  设置里 rotationButton 已发货；串流界面 FLAG_SECURE 导致截图/uiautomator 不可用，
  实时点击切换未脚本化。

## 仍需物理硬件/时间的开放项
- 原生鼠标指针移动/点击：需给手机接真实 USB/蓝牙鼠标（adb 合成 mouse hover 投递不到
  聚焦视图；同处理器的 SCROLL 分支已证明该路径可用）。
- 两小时无增长 soak：需时间，属 Phase 0 协调运行。
- 真正的虚拟屏硬件镜像（非降级）：本机 macOS 26.4.1 不支持，等未来 OS/GPU 支持自动生效。
- window migration（把 Mac 窗口移到客户端屏再收回）：几何逻辑由 host self-test 覆盖，
  状态栏菜单动作未脚本化点击。
