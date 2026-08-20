import AppKit
import SwiftUI
import XDCore

@MainActor
final class WindowManager: NSObject, NSWindowDelegate {
    static let shared = WindowManager()
    private var window: NSWindow?

    func open(store: XDStore, theme: InstrumentTheme) {
        if let window {
            NSApp.activate(ignoringOtherApps: true)
            window.makeKeyAndOrderFront(nil)
            return
        }

        let root = ReviewWindowRoot()
            .environment(store)
            .environment(theme)
        let controller = NSHostingController(rootView: root)
        let window = NSWindow(contentViewController: controller)
        window.title = "XD"
        // Option 3's evidence-instrument composition is intentionally taller
        // than a generic dashboard. Keep this ratio so the three columns and
        // fixed decision rail retain the same visual balance on either Mac.
        window.setContentSize(NSSize(width: 1_400, height: 996))
        window.minSize = NSSize(width: 1_080, height: 700)
        window.styleMask = [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView]
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.backgroundColor = NSColor(red: 0.063, green: 0.071, blue: 0.067, alpha: 1)
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.center()
        self.window = window
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
    }

    func windowWillClose(_ notification: Notification) {
        // Keep the controller alive so reopening is immediate and preserves state.
    }
}
