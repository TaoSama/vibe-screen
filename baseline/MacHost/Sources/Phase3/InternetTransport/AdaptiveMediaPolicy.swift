import Foundation

struct InternetNetworkQualitySample: Equatable {
    let roundTripTimeMilliseconds: Double
    let packetLossFraction: Double
    let availableOutgoingBitrateBps: UInt64
}

struct AdaptiveMediaProfile: Equatable {
    let targetBitrateBps: UInt64
    let resolutionScale: Double
    let framesPerSecond: Int
}

final class AdaptiveMediaPolicy {
    private(set) var currentProfile: AdaptiveMediaProfile
    private(set) var acknowledgedProfile: AdaptiveMediaProfile
    private var pendingProfile: AdaptiveMediaProfile?
    private var pendingObservationCount = 0
    private let observationsBeforeDowngrade: Int
    private let observationsBeforeUpgrade: Int

    init(
        initialProfile: AdaptiveMediaProfile = AdaptiveMediaPolicy.highQuality,
        observationsBeforeDowngrade: Int = 2,
        observationsBeforeUpgrade: Int = 4
    ) {
        self.currentProfile = initialProfile
        self.acknowledgedProfile = initialProfile
        self.observationsBeforeDowngrade = observationsBeforeDowngrade
        self.observationsBeforeUpgrade = observationsBeforeUpgrade
    }

    func observe(_ sample: InternetNetworkQualitySample) -> AdaptiveMediaProfile? {
        let candidate = Self.profile(for: sample)
        guard candidate != currentProfile else {
            pendingProfile = nil
            pendingObservationCount = 0
            return nil
        }

        if pendingProfile == candidate {
            pendingObservationCount += 1
        } else {
            pendingProfile = candidate
            pendingObservationCount = 1
        }

        let isDowngrade = candidate.targetBitrateBps < currentProfile.targetBitrateBps
        let requiredObservations = isDowngrade ? observationsBeforeDowngrade : observationsBeforeUpgrade
        guard pendingObservationCount >= requiredObservations else { return nil }

        currentProfile = candidate
        pendingProfile = nil
        pendingObservationCount = 0
        return candidate
    }

    func commit(_ profile: AdaptiveMediaProfile) {
        acknowledgedProfile = profile
    }

    func reject(_ profile: AdaptiveMediaProfile) {
        guard currentProfile == profile else { return }
        currentProfile = acknowledgedProfile
        pendingProfile = nil
        pendingObservationCount = 0
    }

    static func profile(for sample: InternetNetworkQualitySample) -> AdaptiveMediaProfile {
        let loss = sample.packetLossFraction
        let rtt = sample.roundTripTimeMilliseconds
        let bitrate = sample.availableOutgoingBitrateBps

        // Non-finite loss or RTT means the telemetry sample is unusable. Fall
        // back to the most conservative profile instead of letting NaN
        // comparisons silently skip every threshold and land on highQuality.
        guard loss.isFinite, loss >= 0,
              rtt.isFinite, rtt >= 0 else {
            return constrained
        }

        let clampedLoss = max(0, min(loss, 1))
        let clampedRTT = max(0, rtt)

        // A zero bitrate estimate carries no usable bandwidth signal; stay
        // constrained rather than treating it as an abundant link.
        if bitrate == 0 {
            return constrained
        }

        if clampedLoss >= 0.12 || clampedRTT >= 450 || bitrate < 3_000_000 {
            return constrained
        }
        if clampedLoss >= 0.05 || clampedRTT >= 250 || bitrate < 7_000_000 {
            return balanced
        }
        if clampedLoss >= 0.02 || clampedRTT >= 150 || bitrate < 14_000_000 {
            return good
        }

        // A zero RTT is treated as a missing measurement. Without a real
        // latency signal we must not promote to highQuality.
        if clampedRTT == 0 {
            return good
        }

        return highQuality
    }

    static let highQuality = AdaptiveMediaProfile(
        targetBitrateBps: 20_000_000,
        resolutionScale: 1,
        framesPerSecond: 60
    )
    static let good = AdaptiveMediaProfile(
        targetBitrateBps: 12_000_000,
        resolutionScale: 0.85,
        framesPerSecond: 45
    )
    static let balanced = AdaptiveMediaProfile(
        targetBitrateBps: 6_000_000,
        resolutionScale: 0.67,
        framesPerSecond: 30
    )
    static let constrained = AdaptiveMediaProfile(
        targetBitrateBps: 2_500_000,
        resolutionScale: 0.5,
        framesPerSecond: 20
    )
}
