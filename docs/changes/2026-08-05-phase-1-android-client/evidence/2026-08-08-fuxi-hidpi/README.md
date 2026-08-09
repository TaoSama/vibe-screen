# 2026-08-08 fuxi HiDPI 虚拟显示器真机验证（小米 13 (2211133C), 8a023e3a, USB）

## 结论
- HiDPI 虚拟扩展显示器已真机验证：host 通过私有 CGVirtualDisplay API 创建了
  一块 HiDPI(Retina) 虚拟显示器，物理像素 4000x2400、逻辑(UI) 2000x1200，
  scale factor = 2x；客户端以 60fps、0 丢帧解码呈现。
- 由此同时验证了原本仍开着的 gate：真实私有 API 虚拟显示器的创建 + 捕获。
- 稳定自签免重授权再次得到验证：改 hiDPI 默认值后重启 host（open
  /Applications/Telemachus.app），启动即报 "Screen recording permission granted"，
  0 次 "Requesting screen capture access"，无系统授权弹窗。

## 步骤
1. 开启 HiDPI 默认值并重启 host（stable signing，无需重新授权）：
       defaults write dev.telemachus.display Telemachus_hiDPI -bool true
       pkill -f '/Applications/Telemachus.app/Contents/MacOS/Telemachus'
       open /Applications/Telemachus.app
2. 客户端自动重连（USB loopback），从物理主屏(ID 1)起流。
3. 通过下拉胶囊切到"虚拟扩展屏"，host 创建虚拟显示器 ID 15 并就地切换捕获。

## 证据
- system_profiler（system_profiler_telemachus.txt）:
       Telemachus:
         Resolution: 4000 x 2400
         UI Looks like: 2000 x 1200 @ 60.00Hz
         Mirror: Off
         Online: Yes
         Rotation: Supported
  Resolution=物理像素、UI Looks like=逻辑像素，二者 2x 关系即 HiDPI/Retina 成立。
  关闭 HiDPI 时该显示器会直接报 Resolution: 2000 x 1200、无 "UI Looks like" 翻倍。
- host 日志（host_pipeline.txt）:
       Runtime display switch: source=extended captureID=15 stream=2000x1200
       Capturing virtual display: 2000x1200 (ID: 15)
       Pipeline: 60.0fps, 1.5Mbps, avg frame age: ~17.6ms, dropped: 0
  捕获逻辑分辨率 2000x1200（HiDPI 下编码逻辑面，帧龄较物理屏 ~6ms 略高到 ~17ms，
  但 60fps 稳定、0 丢帧）。

## 备注
- 该虚拟显示器 Rotation: Supported、Mirror: Off，为独立扩展屏（非镜像）。
- 帧龄升高来自 Retina 背衬表面的编码开销，属预期；如需压低可在设置内降 HiDPI 或分辨率。
