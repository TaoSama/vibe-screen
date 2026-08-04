import Foundation
import ServiceManagement
import os.log

@available(macOS 13.0, *)
class DaemonManager {
    enum RegistrationStatus: Equatable {
        case notRegistered
        case enabled
        case requiresApproval
        case unavailable
    }

    static let shared = DaemonManager()
    
    private var appService: SMAppService {
        return SMAppService.mainApp
    }
    
    var isEnabled: Bool {
        status == .enabled
    }

    var status: RegistrationStatus {
        switch appService.status {
        case .notRegistered: return .notRegistered
        case .enabled: return .enabled
        case .requiresApproval: return .requiresApproval
        case .notFound: return .unavailable
        @unknown default: return .unavailable
        }
    }

    var statusGuidance: String? {
        switch status {
        case .requiresApproval:
            return "Approval required in System Settings → General → Login Items."
        case .unavailable:
            return "Launch at Login is unavailable for this app installation."
        case .notRegistered, .enabled:
            return nil
        }
    }
    
    func enable() throws {
        let service = appService
        guard status != .enabled else { return }
        
        do {
            try service.register()
            os_log("Successfully registered login item.")
        } catch {
            os_log("Failed to register login item: %{public}@", error.localizedDescription)
            throw error
        }
    }
    
    func disable() throws {
        let service = appService
        guard status != .notRegistered else { return }
        
        do {
            try service.unregister()
            os_log("Successfully unregistered login item.")
        } catch {
            os_log("Failed to unregister login item: %{public}@", error.localizedDescription)
            throw error
        }
    }
}
