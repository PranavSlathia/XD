import Foundation
import SwiftData

@Model
public final class CacheRecord {
    @Attribute(.unique) public var key: String
    public var payload: Data
    public var updatedAt: Date

    public init(key: String, payload: Data, updatedAt: Date = Date()) {
        self.key = key
        self.payload = payload
        self.updatedAt = updatedAt
    }
}

@MainActor
public final class CacheRepository {
    private let context: ModelContext

    public init(container: ModelContainer) {
        context = ModelContext(container)
        context.autosaveEnabled = true
    }

    public func save<Value: Encodable>(_ value: Value, key: String) throws {
        let payload = try APICodec.encoder().encode(value)
        let requestedKey = key
        let descriptor = FetchDescriptor<CacheRecord>(
            predicate: #Predicate { $0.key == requestedKey }
        )
        if let existing = try context.fetch(descriptor).first {
            existing.payload = payload
            existing.updatedAt = Date()
        } else {
            context.insert(CacheRecord(key: key, payload: payload))
        }
        try context.save()
    }

    public func load<Value: Decodable>(_ type: Value.Type, key: String) throws -> (Value, Date)? {
        let requestedKey = key
        let descriptor = FetchDescriptor<CacheRecord>(
            predicate: #Predicate { $0.key == requestedKey }
        )
        guard let record = try context.fetch(descriptor).first else { return nil }
        return (try APICodec.decoder().decode(type, from: record.payload), record.updatedAt)
    }

    public func clear() throws {
        try context.delete(model: CacheRecord.self)
        try context.save()
    }
}

