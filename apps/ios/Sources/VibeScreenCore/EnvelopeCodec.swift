import Foundation
import VibeScreenProtocol

public enum EnvelopeCodec {
    public static func serialize(_ envelope: VSEnvelope) throws -> Data {
        try envelope.serializedData()
    }

    public static func deserialize(_ data: Data) throws -> VSEnvelope {
        try VSEnvelope(serializedBytes: data)
    }
}
