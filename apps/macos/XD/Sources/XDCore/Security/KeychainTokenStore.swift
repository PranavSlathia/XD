import Foundation
import Security

public enum KeychainTokenError: LocalizedError, Sendable {
    case status(OSStatus)

    public var errorDescription: String? {
        switch self {
        case let .status(status):
            if let message = SecCopyErrorMessageString(status, nil) as String? {
                return message
            }
            return "Keychain error \(status)"
        }
    }
}

public struct SecureTokenStore: Sendable {
    public var load: @Sendable () throws -> String?
    public var save: @Sendable (String) throws -> Void
    public var remove: @Sendable () throws -> Void

    public static let keychain = SecureTokenStore(
        load: { try KeychainTokenStore.load() },
        save: { try KeychainTokenStore.save($0) },
        remove: { try KeychainTokenStore.remove() }
    )

    public static func memory(initial: String? = nil) -> SecureTokenStore {
        let box = TokenBox(value: initial)
        return SecureTokenStore(
            load: { box.value },
            save: { box.value = $0 },
            remove: { box.value = nil }
        )
    }
}

private final class TokenBox: @unchecked Sendable {
    private let lock = NSLock()
    private var stored: String?

    init(value: String?) { stored = value }

    var value: String? {
        get { lock.withLock { stored } }
        set { lock.withLock { stored = newValue } }
    }
}

private enum KeychainTokenStore {
    static let service = "com.pranav.xd.device"
    static let account = "device-token"

    static func load() throws -> String? {
        var query = baseQuery
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else { throw KeychainTokenError.status(status) }
        guard let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func save(_ token: String) throws {
        try remove(ignoreMissing: true)
        var item = baseQuery
        item[kSecValueData as String] = Data(token.utf8)
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(item as CFDictionary, nil)
        guard status == errSecSuccess else { throw KeychainTokenError.status(status) }
    }

    static func remove() throws {
        try remove(ignoreMissing: false)
    }

    private static func remove(ignoreMissing: Bool) throws {
        let status = SecItemDelete(baseQuery as CFDictionary)
        if status == errSecItemNotFound, ignoreMissing { return }
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw KeychainTokenError.status(status)
        }
    }

    private static var baseQuery: [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }
}

