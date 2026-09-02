import Foundation
import VibeScreenCore
import VibeScreenProtocol

@MainActor
final class ManagedConfigurationProvider: ObservableObject {
    @Published private(set) var policy: ManagedPolicy = .unmanaged
    @Published private(set) var errorMessage: String?
    private var resolver = ManagedPolicyResolver()

    init() {
        reload()
        NotificationCenter.default.addObserver(
            forName: UserDefaults.didChangeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.reload() }
        }
    }

    func reload() {
        do {
            let local = try ManagedPolicy(
                managedConfiguration: UserDefaults.standard.dictionary(
                    forKey: ManagedPolicy.ManagedConfigurationSchema.managedConfigurationKey
                )
            )
            resolver.setLocal(local)
            policy = resolver.effectivePolicy
            errorMessage = nil
        } catch {
            resolver.setLocal(.failClosed)
            policy = resolver.effectivePolicy
            errorMessage = error.localizedDescription
        }
    }

    func applyRemote(_ status: VSManagedPolicyStatus, localSnapshot: ManagedPolicy) -> ManagedPolicy {
        var snapshotResolver = ManagedPolicyResolver(localPolicy: localSnapshot)
        snapshotResolver.setRemote(ManagedPolicy(remoteStatus: status))
        return snapshotResolver.effectivePolicy
    }

    /// Drops the remote policy so the effective policy reverts to the local
    /// (MDM) policy only. Must be called when a session ends so a stale remote
    /// policy from a previous peer is never applied to the next session.
    func clearRemotePolicy() {
        resolver.clearRemote()
        policy = resolver.effectivePolicy
    }
}
