import Foundation
import UserNotifications

@MainActor
public final class NotificationService: NSObject, UNUserNotificationCenterDelegate {
    public var onOpenEvent: ((Int, Int?) -> Void)?
    private let center: UNUserNotificationCenter

    public override init() {
        center = .current()
        super.init()
        center.delegate = self
    }

    public func requestAuthorization() async -> Bool {
        (try? await center.requestAuthorization(options: [.alert, .sound, .badge])) ?? false
    }

    public func post(_ event: EventItem) async {
        let content = UNMutableNotificationContent()
        content.title = event.domain ?? "XD candidate update"
        content.body = notificationBody(for: event.eventType)
        content.sound = .default
        var userInfo: [String: Any] = ["event_id": event.id]
        if let candidateID = event.candidateId { userInfo["candidate_id"] = candidateID }
        content.userInfo = userInfo
        let request = UNNotificationRequest(
            identifier: "xd-event-\(event.id)",
            content: content,
            trigger: nil
        )
        try? await center.add(request)
    }

    public func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse
    ) async {
        let info = response.notification.request.content.userInfo
        guard let eventID = info["event_id"] as? Int else { return }
        onOpenEvent?(eventID, info["candidate_id"] as? Int)
    }

    public nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        [.banner, .sound]
    }

    private func notificationBody(for eventType: String) -> String {
        switch eventType {
        case "candidate.promoted": "Entered a qualifying asset lane."
        case "gate.changed": "A readiness gate changed."
        case "dossier.completed": "The evidence dossier is complete."
        case "availability.changed": "Availability or registration price changed."
        case "review.changed": "The candidate review changed."
        case "outcome.recorded": "A portfolio outcome was recorded."
        default: "Candidate evidence changed."
        }
    }
}
