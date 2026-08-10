# Xiaomi 13 窄横屏连接页回退验收

## 结论

2026-08-10（Asia/Shanghai）在 Xiaomi 13 `bac5b092` 上安装提交 `21162a0` 的
debug APK。全屏横屏可用宽度 914dp 时，连接页保持 40/60 左右两栏；临时把验证
显示尺寸改为 `1080x1200` 后，横屏窗口为 1200x1080、可用宽度 457dp，连接页自动
回退为纵向单列。窄窗口没有横向挤压，向上滚动后模式选择、`Try Again`、状态和连接
详情均完整可达。

本记录验证 Android `w600dp-land` 资源断点和配置变更后的布局，不把显示尺寸覆盖声称
为真实分屏手势证据，也不证明 USB、LAN 或 Internet 会话建立。

## 环境

- 设备：Xiaomi 13，model `2211133C`，codename `fuxi`
- 系统：Android 16 / API 36
- 物理尺寸与密度：`1080x2400`，420 dpi
- APK SHA-256：`9f15246f6c61f4b7dc5dc6dd2b968b4ce208841e81eaa60605e2441708bfa4b8`
- 实现提交：`21162a0`

## 验收结果

| 场景 | 结果 | 证据 |
| --- | --- | --- |
| 914dp 全屏横屏 | 两栏；header `[402,205][1002,959]`，actions `[1076,189][1977,975]` | `wide-914dp.png/xml` |
| 457dp 窄横屏顶部 | 单列；header `[220,169][906,923]`，actions 从 y=923 接续，无水平挤压 | `narrow-457dp-top.png/xml` |
| 457dp 窄横屏滚动 | 模式选择 `[220,175][906,301]`，`Try Again` `[220,322][906,469]`，后续内容可达 | `narrow-457dp-scrolled.png/xml` |
| 编译后资源表 | default=false、land=false、w600dp-land=true | `resource-table.txt` |

确定性几何断言见 `bounds-check.txt`。Android 离线门禁通过 446/446 单测、lint 和
debug APK 构建。

## 清理

验证只操作 `bac5b092`。显示尺寸已恢复为物理 `1080x2400`，截图开关为 `0`，ADB
reverse 为空。持续串流设备 `8a023e3a` 和 MacHost PID 27437 未重启、未覆盖。
清理状态见 `device-cleanup.txt`。
