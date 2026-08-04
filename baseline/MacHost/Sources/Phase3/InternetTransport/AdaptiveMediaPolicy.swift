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

    private static func profile(for sample: InternetNetworkQualitySample) -> AdaptiveMediaProfile {
        let loss = max(0, min(sample.packetLossFraction, 1))
        let rtt = max(0, sample.roundTripTimeMilliseconds)
        let bitrate = sample.availableOutgoingBitrateBps

        if loss >= 0.12 || rtt >= 450 || bitrate < 3_000_000 {
            return constrained
        }
        if loss >= 0.05 || rtt >= 250 || bitrate < 7_000_000 {
            return balanced
        }
        if loss >= 0.02 || rtt >= 150 || bitrate < 14_000_000 {
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
