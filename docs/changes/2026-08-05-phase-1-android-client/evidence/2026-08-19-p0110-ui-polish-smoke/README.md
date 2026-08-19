# P0110 Android UI polish smoke

Date: 2026-08-19

PR: [#141](https://github.com/TaoSama/vibe-screen/pull/141)
Commit: `893e6307775f6b17d401ba2af2b642b5b462d14f`

Device identity:

```text
nubia
P0110
pacific
16
36
```

This is Nubia P0110 / pacific / Android 16 evidence only. It must not be
reported as Xiaomi 13 / fuxi evidence.

## Scope

The debug APK built from PR #141 installed and launched on the connected P0110.
The retained screenshots show the stream surface UI before and after an ADB tap
near the top control-reveal region:

- [`initial.png`](initial.png)
- [`after-top-tap.png`](after-top-tap.png)
- [`diff-thumb.png`](diff-thumb.png)

The two screenshots are both `1264x2800` PNGs and differ by 2028 pixels in an
absolute-error image comparison. That proves the app was visible and the smoke
step produced a small rendered-state change, but it is intentionally treated as
weak UI smoke evidence rather than a full interaction acceptance run.

## Not proved

This record does not prove:

- an active Mac stream;
- display switching;
- video preference renegotiation;
- reconnect behavior;
- that tapping the hidden control region avoids forwarding a Mac touch event;
- full control-bar accessibility or menu interaction;
- any Xiaomi 13 / fuxi behavior.

Those gates require a connected Host session with retained Host/client logs or a
dedicated end-to-end device run.
