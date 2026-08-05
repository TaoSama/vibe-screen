import Foundation

private enum OwnerGenerationSelfTestError: Error {
    case failed(String)
}

/// Deterministic coverage used by the release core self-test executable.
public func runOwnerGenerationSelfTests() throws {
    let firstConnection = ConnectionOwner()
    let secondConnection = ConnectionOwner()
    guard firstConnection != secondConnection else {
        throw OwnerGenerationSelfTestError.failed("connection owners were reused")
    }

    var gate = OwnedDeliveryGate(owner: firstConnection)
    let lateDelivery = OwnedDelivery(owner: firstConnection, payload: 1)
    let currentDelivery = OwnedDelivery(owner: secondConnection, payload: 2)
    gate.reset(to: secondConnection)
    guard !gate.accepts(lateDelivery), gate.accepts(currentDelivery) else {
        throw OwnerGenerationSelfTestError.failed("late connection delivery crossed reset")
    }
    gate.reset()
    guard !gate.accepts(currentDelivery) else {
        throw OwnerGenerationSelfTestError.failed("delivery passed a cleared gate")
    }

    let session = SessionOwner(connectionOwner: secondConnection)
    let replacementSession = SessionOwner(connectionOwner: secondConnection)
    guard session != replacementSession else {
        throw OwnerGenerationSelfTestError.failed("session owners were reused")
    }

    let decoder = DecoderOwner(sessionOwner: session, streamID: 7, configEpoch: 11)
    let replacementDecoder = DecoderOwner(sessionOwner: session, streamID: 7, configEpoch: 11)
    let nextConfiguration = DecoderOwner(sessionOwner: session, streamID: 7, configEpoch: 12)
    guard decoder != replacementDecoder,
          decoder != nextConfiguration,
          decoder.streamID == replacementDecoder.streamID,
          decoder.configEpoch == replacementDecoder.configEpoch else {
        throw OwnerGenerationSelfTestError.failed("same-stream decoder generation was reused")
    }
}
