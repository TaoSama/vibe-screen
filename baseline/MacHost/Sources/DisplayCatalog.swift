import AppKit

struct HostDisplayDescriptor: Identifiable, Equatable {
    let id: CGDirectDisplayID
    let name: String
    let width: Int
    let height: Int
    let isMain: Bool

    var label: String {
        "\(name) — \(width)×\(height)\(isMain ? " (Main)" : "")"
    }
}

enum DisplayCatalog {
    static func onlineDisplays() -> [HostDisplayDescriptor] {
        var count: UInt32 = 0
        guard CGGetOnlineDisplayList(0, nil, &count) == .success,
              count > 0 else { return [] }
        var displayIDs = [CGDirectDisplayID](repeating: 0, count: Int(count))
        guard CGGetOnlineDisplayList(count, &displayIDs, &count) == .success else {
            return []
        }

        let screenNamePairs: [(CGDirectDisplayID, String)] = NSScreen.screens.compactMap {
            screen in
            let key = NSDeviceDescriptionKey("NSScreenNumber")
            guard let number = screen.deviceDescription[key] as? NSNumber else {
                return nil
            }
            return (CGDirectDisplayID(number.uint32Value), screen.localizedName)
        }
        let screenNames = Dictionary(uniqueKeysWithValues: screenNamePairs)
        return displayIDs.prefix(Int(count)).map { displayID in
            HostDisplayDescriptor(
                id: displayID,
                name: screenNames[displayID] ?? "Display \(displayID)",
                width: CGDisplayPixelsWide(displayID),
                height: CGDisplayPixelsHigh(displayID),
                isMain: CGDisplayIsMain(displayID) != 0
            )
        }
    }

    static func resolve(_ requestedID: CGDirectDisplayID) -> CGDirectDisplayID {
        onlineDisplays().contains(where: { $0.id == requestedID })
            ? requestedID
            : CGMainDisplayID()
    }
}
