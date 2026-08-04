import Foundation
import VibeScreenCore
import VibeScreenProtocol

@MainActor
final class ManagedConfigurationProvider: ObservableObject {
    static let managedConfigurationKey = "com.apple.configuration.managed"

    @Published private(set) var policy: ManagedPolicy = .unmanaged
    @Published private(set) var errorMessage: String?
    private var remotePolicy: ManagedPolicy?

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
                    forKey: Self.managedConfigurationKey
                )
            )
            policy = remotePolicy.map { local.applying(remote: $0) } ?? local
            errorMessage = nil
        } catch {
            policy = ManagedPolicy(
                isManaged: true,
                clipboardAllowed: false,
                fileTransferAllowed: false,
                audioAllowed: false,
                wakeAllowed: false,
                customGesturesAllowed: false,
                maximumFileBytes: 0,
                allowedHosts: []
            )
            errorMessage = error.localizedDescription
        }
    }

    func applyRemote(_ status: VSManagedPolicyStatus) {
        let remote = ManagedPolicy(
            isManaged: status.managed,
            clipboardAllowed: status.clipboardAllowed,
            fileTransferAllowed: status.fileTransferAllowed,
            audioAllowed: status.audioAllowed,
            wakeAllowed: status.wakeAllowed,
            customGesturesAllowed: status.customGesturesAllowed,
            maximumFileBytes: status.maximumFileBytes,
            allowedHosts: []
        )
        remotePolicy = remote
        policy = policy.applying(remote: remote)
    }
}
