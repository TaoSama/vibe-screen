# Xiaomi 13 viewport and input evidence

Date: 2026-08-10  
Device: Xiaomi 13 (`2211133C`, `fuxi`, Android 16)  
Transport: USB / ADB reverse / Protocol v1  
Host PID during the eight-mode matrix: `24536`

## Artifacts

- `touch-matrix.txt` contains Debug-only `VibeScreenTouchMap` records for Fit
  and Fill with Follow Mac, 90, 180, and 270 degree client rotations. The
  records include viewport coordinates, video geometry, selected modes, host
  rotation, and the normalized point sent to the host.
- `settings-final.png` and `settings-window.xml` show the corrected Viewport
  description and Show Stats disabled. The overlay is now opt-in because its
  draggable surface consumes touches over the video.
- `host-rotation-90-client-follow.png` records the physical-display boundary:
  host rotation changes the Android orientation but does not rotate the source
  pixels. The client must therefore keep the Surface and input transform tied
  to client-local rotation only.

## Result

With host rotation fixed at zero, all eight Fit/Fill and client-rotation
combinations produced the expected inverse mapping. The center stayed at
`0.5,0.5`; corners followed the selected 0/90/180/270 transform; Fill retained
the expected cropped coordinate range. The exact bottom edge in Fill/270 was
claimed by the system/control hit region, so the retained record uses an inset
bottom-left sample rather than pretending the intercepted event reached the
video input view.

A separate host-rotation check rejected an incorrect combined-transform
hypothesis. With host=90 and client=Follow Mac, a build that applied the host
rotation to input sent the visible top-left to Mac bottom-left (`45,937`). The
final client-only build sent the same visible corner to Mac top-left (`70,70`).
The final source and installed APK retain client-only Surface/layout/input
transforms; host rotation is used only to choose Android orientation.

## Product hashes

- Android Debug APK:
  `dd8648a7ad1d5d5b3ef9ce4a3a7639ec5cbc1b322ecd7f0a238b66b2fe2bceff`
- Installed Android label: `Vibe Screen`
- macOS executable:
  `a1a656b7c53b99e8bcf91fc3432066055c2048b64a649ad53c95c1f02663878a`
- macOS bundle and display name: `Vibe Screen`

## Boundary

This closes the Xiaomi 13 client-local Fit/Fill and rotation mapping check for
`hostRotation=0`. It does not prove that rotating an existing physical Mac
display is an optimal portrait experience: that path preserves source pixels
and can letterbox heavily. Virtual portrait display creation and any future
host-side pixel rotation need their own visual and input evidence.
