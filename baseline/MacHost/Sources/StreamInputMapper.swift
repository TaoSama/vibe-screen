import CoreGraphics

/// The legacy Android client removes viewport letterboxing before sending
/// source-frame-normalized coordinates. Rotation is represented by the stream
/// dimensions/client orientation, so applying another rotation here would
/// rotate input twice.
enum StreamInputMapper {
    static func point(
        normalizedX: Float,
        normalizedY: Float,
        in displayBounds: CGRect
    ) -> CGPoint? {
        guard normalizedX.isFinite,
              normalizedY.isFinite,
              (0...1).contains(normalizedX),
              (0...1).contains(normalizedY),
              displayBounds.width > 0,
              displayBounds.height > 0 else {
            return nil
        }
        return CGPoint(
            x: displayBounds.minX + CGFloat(normalizedX) * displayBounds.width,
            y: displayBounds.minY + CGFloat(normalizedY) * displayBounds.height
        )
    }
}
