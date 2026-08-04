import Foundation

/// Destination for VideoToolbox output. Transport implementations own their
/// own queueing and stale-session rejection; ScreenCapture only produces the
/// newest encoded frame for the currently active session epoch.
protocol EncodedFrameSink: AnyObject {
    var currentSessionEpoch: UInt64 { get }

    func sendFrame(
        _ data: Data,
        timestamp: UInt64,
        isKeyframe: Bool,
        sessionEpoch: UInt64
    )
}
