import Foundation
import ObjectiveC

struct VirtualDisplayRuntimeRequirement: Equatable {
    let className: String
    let selectors: [String]
}

protocol ObjectiveCRuntimeInspecting {
    func classExists(named className: String) -> Bool
    func instanceResponds(className: String, selector: String) -> Bool
}

struct SystemObjectiveCRuntimeInspector: ObjectiveCRuntimeInspecting {
    func classExists(named className: String) -> Bool {
        NSClassFromString(className) != nil
    }

    func instanceResponds(className: String, selector: String) -> Bool {
        guard let cls = NSClassFromString(className) else { return false }
        return class_getInstanceMethod(cls, NSSelectorFromString(selector)) != nil
    }
}

struct VirtualDisplayCapabilityReport: Equatable {
    let missingRequirements: [String]
    var isAvailable: Bool { missingRequirements.isEmpty }
}

enum VirtualDisplayPrivateAPICapability {
    static let requirements = [
        VirtualDisplayRuntimeRequirement(
            className: "CGVirtualDisplayDescriptor",
            selectors: [
                "init", "setName:", "setMaxPixelsWide:",
                "setMaxPixelsHigh:", "setSizeInMillimeters:",
                "setProductID:", "setVendorID:", "setSerialNum:"
            ]
        ),
        VirtualDisplayRuntimeRequirement(
            className: "CGVirtualDisplayMode",
            selectors: ["initWithWidth:height:refreshRate:"]
        ),
        VirtualDisplayRuntimeRequirement(
            className: "CGVirtualDisplaySettings",
            selectors: ["init", "setHiDPI:", "setModes:"]
        ),
        VirtualDisplayRuntimeRequirement(
            className: "CGVirtualDisplay",
            selectors: ["initWithDescriptor:", "applySettings:", "displayID"]
        )
    ]

    static func evaluate(
        inspector: ObjectiveCRuntimeInspecting = SystemObjectiveCRuntimeInspector()
    ) -> VirtualDisplayCapabilityReport {
        var missing: [String] = []
        for requirement in requirements {
            guard inspector.classExists(named: requirement.className) else {
                missing.append(requirement.className)
                continue
            }
            for selector in requirement.selectors where
                !inspector.instanceResponds(
                    className: requirement.className,
                    selector: selector
                ) {
                missing.append("\(requirement.className).\(selector)")
            }
        }
        return VirtualDisplayCapabilityReport(missingRequirements: missing)
    }
}
