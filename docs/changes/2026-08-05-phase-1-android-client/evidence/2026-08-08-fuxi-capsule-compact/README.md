# fuxi 控制胶囊紧凑化 — 2026-08-08

## 目标
用户反馈「胶囊感觉需要小一点，居中，不然容易误触」。本次让顶部 tap-to-reveal
控制胶囊更紧凑、稳定水平居中，并显著降低静息态误触面。

## 改了什么（旧 → 新）
布局 baseline/AndroidClient/app/src/main/res/layout/activity_main.xml 的 @+id/controlBar：
- layout_constraintWidth_max: 420dp → 320dp（并新增 dimens 承载）
- cardCornerRadius: 20dp → 18dp
- marginTop: 28dp → 20dp；去掉 marginStart/marginEnd=12dp（改由 wrap_content + start/end→parent 居中）
- 内层 LinearLayout: match_parent → wrap_content（胶囊贴合内容，不再撑满约束宽度）
- padding: 4dp（四边） → 3dp（control_bar_content_padding）
- 三个 ImageButton: 40dp → 36dp（control_bar_button_size），相邻按钮加 2dp 间距（control_bar_button_margin）平衡触达
- 新增容器 @+id/displayCapsuleGroup 包住「显示选择按钮 + display chips」，默认 android:visibility="gone"

新增 baseline/AndroidClient/app/src/main/res/values/dimens.xml：
- control_bar_margin_top=20dp, control_bar_max_width=320dp, control_bar_corner_radius=18dp,
  control_bar_content_padding=3dp, control_bar_button_size=36dp, control_bar_button_margin=2dp

代码 baseline/AndroidClient/app/src/main/java/dev/telemachus/display/MainActivity.kt
populateDisplayCapsule()：
- 新增：selectable 时 displayCapsuleGroup 可见，否则整段 GONE 并 early-return（单屏/未协商多屏时
  不再渲染一枚 disabled chip，消除大段无效可点区域）。多屏协商成功仍照常渲染 chips + 监听。

未改动：轻触唤出、3s 自动淡出（CONTROL_BAR_AUTO_HIDE_MS=3000）、设置/断开点击、自动连接、
输入转发路径（dispatchTouch/mapInputPoint/inputViewport 全未动）。未新增字符串（复用既有
control_displays/control_settings/control_disconnect/display_option_format）。

## 量了什么（真机 小米 13 (2211133C) fuxi, adb <redacted-xiaomi-adb-serial>, Android 16 LineageOS, USB）
屏幕 1080x2400, density 420 → 2.625 px/dp。测量时为横屏（窗口 2400x1080）。
证据文件 dumpsys-controlbar-landscape.txt（dumpsys activity top，无需 idle，FLAG_SECURE 下仍可读几何）：
- controlBar bounds = [1090,53]-[1311,164] → 宽 221px ≈ 84.2dp（单屏静息形态：仅 设置+断开 两枚图标）
- 水平居中：左边距 1090px，右边距 2400-1311=1089px，偏移 |1090-1089| = 1px（≈0.4dp），实测居中
- displayCapsuleGroup: 状态 G(GONE), bounds 0,0-0,0 —— 单屏时整段显示选择已收起，无死区
- controlSettingsButton: 13,8-108,103 → 95px ≈ 36.2dp
- controlDisconnectButton: 118,8-213,103 → 95px ≈ 36.2dp
对照：改前 max 420dp、40dp 图标、单屏仍有 1 枚 disabled chip 占位。

出流不回归（uiautomator dump 因 FLAG_SECURE+3s 淡出+60fps SurfaceView 无法取到 controlBar 节点，
故几何证据改用 dumpsys activity top；出流证据用日志）：
- logcat-decode-stats.txt: VD Decode stats 持续 dropped=0，decoder latency avg ~6ms；stream_stats fps ~60
- host-pipeline-fps.txt: ~/Library/Logs/Telemachus/telemachus.log "Pipeline: 60.0fps ... dropped: 0"
- 全程在视频上反复点击（转发到 Mac 指针）后仍 input=17580/dropped=0、App 前台无崩溃 → 触控转发不回归

## 单测 / 构建
- ./gradlew :app:testDebugUnitTest --tests *ProtocolV1SessionTest --tests *StreamClientProtocolV1IntegrationTest → BUILD SUCCESSFUL
- ./gradlew :app:assembleDebug → BUILD SUCCESSFUL
- adb -s <redacted-xiaomi-adb-serial> install -r -g → Success

## 仍未证明的 gate
- 多屏真机切换：Mac 现仅单块内建 Retina 屏，displayCapsuleGroup 展开态（chips + 选择）无法在真机
  验证，需第二块物理屏/虚拟屏协商 CAPABILITY_MULTI_DISPLAY。展开态几何仅经离线单测与代码审查。
- 竖屏几何未单独取数（本次测量为横屏）；居中依赖 start/end→parent 约束，竖屏同理成立但未落盘像素。
- FLAG_SECURE 下无法截图佐证视觉；几何以 dumpsys 节点 bounds 为准，非像素截图。

