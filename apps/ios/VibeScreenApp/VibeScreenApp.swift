import SwiftUI

@main
struct VibeScreenApp: App {
    @StateObject private var model = StreamViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView(model: model)
        }
    }
}
