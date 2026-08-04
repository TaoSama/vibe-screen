import Foundation

enum WebRTCDataChannelBackpressurePolicy {
    static func canAdmit(
        bufferedAmount: UInt64,
        payloadBytes: UInt64,
        maximumBufferedAmount: UInt64
    ) -> Bool {
        bufferedAmount <= maximumBufferedAmount
            && payloadBytes <= maximumBufferedAmount - bufferedAmount
    }

    static func hasDrained(
        currentBufferedAmount: UInt64,
        baselineBufferedAmount: UInt64
    ) -> Bool {
        currentBufferedAmount <= baselineBufferedAmount
    }
}
