# Xiaomi 13 横竖屏连接页验收

## 结论

在第二台 Xiaomi 13 `bac5b092` 上安装提交 `c4f6800` 的 debug APK，验证离线连接页。
横屏 `2400x1080` 下 USB、LAN、Internet 三种模式均为左右两栏，主操作完整出现在首屏，
没有文本溢出或控件重叠；USB 首连指引完整显示为三行，不再被单行省略号截断。竖屏恢复
单列，竖屏再转回横屏后两栏几何正常恢复。

本记录只证明连接页布局与交互可达性，不证明 LAN 或 Internet 会话建立。验证前移除了
`bac5b092` 自身的 ADB reverse，未操作持续串流设备 `8a023e3a`，也未重启长期运行的
MacHost PID 27437。

## 环境

- 设备：Xiaomi 13，model `2211133C`，codename `fuxi`
- 系统：Android 16 / API 36
- 物理尺寸与密度：`1080x2400`，420 dpi
- APK SHA-256：`c0897dda34f54af20c6690bee506e2bb57170efa852d83044d906099f5b56ccd`
- 横屏 cutout：左侧 104 px；布局还保留了隐藏系统栏的稳定 inset

## 验收结果

| 场景 | 结果 | 证据 |
| --- | --- | --- |
| 横屏 USB | 两栏；首连指引完整显示；`Try again`、状态与连接详情首屏可见 | `landscape-usb-guidance-final.png/xml` |
| 横屏 LAN | 两栏；安全提示与 `Scan QR code` 首屏可见 | `landscape-wireless-final.png/xml` |
| 横屏 Internet | 两栏；Direct/TURN、Scan QR、Import、Connect 首屏可见 | `landscape-internet-final.png/xml` |
| 竖屏 USB | 单列；卡片位于 cutout/导航安全区内 | `portrait-usb-final.png/xml` |
| 竖屏到横屏 | 不重建会话即可恢复两栏，USB 选择保持 | `landscape-usb-roundtrip-final.png/xml` |

`bounds-check.txt` 对最终 UI dump 执行了确定性边界断言：横屏卡片
`[297,137][2082,1027]` 位于安全矩形 `[104,85][2274,1080]` 内；竖屏卡片
`[63,163][1017,2221]` 位于 `[0,104][1080,2274]` 内。LAN 与 Internet 的主操作
也全部位于卡片边界内。

修复后的 USB 指引 bounds 为 `[402,637][1002,790]`，高度从旧证据的 51 px 增至
153 px，完整显示“保持 USB 连接、打开 Mac 端 Vibe Screen、设备会自动连接”三项信息；
左栏 `[402,205][1002,959]` 与右栏 `[1076,189][1977,975]` 仍互不重叠。

## 清理

截图时仅在 `bac5b092` 临时设置 `debug.vibescreen.allow_capture=1`。完成后已恢复：
新增的 `landscape-usb-guidance-final.png/xml` 在恢复为 `0` 后采集，连接页本身仍可取证。

- `debug.vibescreen.allow_capture=0`
- 自动旋转开启，`user_rotation=0`
- `fixed-to-user-rotation=default`
- `ignoreOrientationRequest=false`
- `adb reverse` 为空

原始清理输出见 `device-cleanup.txt`；未受影响的串流设备与 MacHost 进程快照见
`unaffected-runtime.txt`。
