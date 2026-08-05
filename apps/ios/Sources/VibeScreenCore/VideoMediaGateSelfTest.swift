import VibeScreenProtocol

public func runVideoMediaGateSelfTest() throws {
    var gate = VideoMediaGate()
    let firstOwner = SessionOwner(connectionOwner: ConnectionOwner())
    try gate.reset(owner: firstOwner, sessionEpoch: 7)
    try gate.bindStream(10, owner: firstOwner)
    try gate.bindStream(11, owner: firstOwner)

    let firstToken = try gate.beginConfiguration(
        videoConfig(streamID: 10, epoch: 3, codec: .h264),
        owner: firstOwner
    )
    try requireMediaGateFailure(
        gate.admit(videoHeader(streamID: 10, sessionEpoch: 7, configEpoch: 3, frameID: 1), owner: firstOwner),
        equals: .configurationAcknowledgementPending(10),
        "pre-ack media was admitted"
    )
    try gate.acknowledgementSent(firstToken, streamID: 10, owner: firstOwner)

    try requireMediaGateSuccess(
        gate.admit(videoHeader(streamID: 10, sessionEpoch: 7, configEpoch: 3, frameID: 2), owner: firstOwner),
        "valid media was rejected"
    )
    try requireMediaGateFailure(
        gate.admit(videoHeader(streamID: 10, sessionEpoch: 6, configEpoch: 3, frameID: 3), owner: firstOwner),
        equals: .sessionEpochMismatch(expected: 7, received: 6),
        "stale session media was admitted"
    )
    try requireMediaGateFailure(
        gate.admit(videoHeader(streamID: 10, sessionEpoch: 7, configEpoch: 2, frameID: 3), owner: firstOwner),
        equals: .configEpochMismatch(expected: 3, received: 2),
        "stale configuration media was admitted"
    )
    try requireMediaGateFailure(
        gate.admit(videoHeader(streamID: 10, sessionEpoch: 7, configEpoch: 3, frameID: 3, codec: .hevc), owner: firstOwner),
        equals: .codecMismatch(expected: .h264, received: .hevc),
        "wrong-codec media was admitted"
    )
    try requireMediaGateFailure(
        gate.admit(videoHeader(streamID: 10, sessionEpoch: 7, configEpoch: 3, frameID: 2), owner: firstOwner),
        equals: .nonIncreasingFrameID(previous: 2, received: 2),
        "replayed frame was admitted"
    )
    try requireMediaGateFailure(
        gate.admit(videoHeader(streamID: 10, sessionEpoch: 7, configEpoch: 3, frameID: 1), owner: firstOwner),
        equals: .nonIncreasingFrameID(previous: 2, received: 1),
        "lower frame was admitted"
    )
    try requireMediaGateFailure(
        gate.admit(videoHeader(streamID: 10, sessionEpoch: 7, configEpoch: 3, frameID: 0), owner: firstOwner),
        equals: .invalidFrameID,
        "frame zero was admitted"
    )
    try requireMediaGateFailure(
        gate.admit(videoHeader(streamID: 10, sessionEpoch: 7, configEpoch: 3, frameID: 3, fragmentIndex: 0, fragmentCount: 2), owner: firstOwner),
        equals: .unsupportedFragment(index: 0, count: 2),
        "fragmented frame was admitted"
    )
    try requireMediaGateFailure(
        gate.admit(videoHeader(streamID: 10, sessionEpoch: 7, configEpoch: 3, frameID: 3, fragmentIndex: 1, fragmentCount: 1), owner: firstOwner),
        equals: .unsupportedFragment(index: 1, count: 1),
        "nonzero fragment index was admitted"
    )
    try requireMediaGateFailure(
        gate.admit(videoHeader(streamID: 10, sessionEpoch: 7, configEpoch: 3, frameID: 3, fragmentIndex: 0, fragmentCount: 0), owner: firstOwner),
        equals: .unsupportedFragment(index: 0, count: 0),
        "zero fragment count was admitted"
    )
    try requireMediaGateSuccess(
        gate.admit(videoHeader(streamID: 10, sessionEpoch: 7, configEpoch: 3, frameID: 3), owner: firstOwner),
        "rejected headers advanced the frame watermark"
    )

    let secondStreamToken = try gate.beginConfiguration(
        videoConfig(streamID: 11, epoch: 1, codec: .hevc),
        owner: firstOwner
    )
    try gate.acknowledgementSent(secondStreamToken, streamID: 11, owner: firstOwner)
    try requireMediaGateSuccess(
        gate.admit(videoHeader(streamID: 11, sessionEpoch: 7, configEpoch: 1, frameID: 1, codec: .hevc), owner: firstOwner),
        "independent second stream was rejected"
    )

    let replacementToken = try gate.beginConfiguration(
        videoConfig(streamID: 10, epoch: 4, codec: .hevc),
        owner: firstOwner
    )
    do {
        try gate.acknowledgementSent(firstToken, streamID: 10, owner: firstOwner)
        throw VideoMediaGateSelfTestError.failed("old reconfiguration token was accepted")
    } catch VideoMediaGateError.staleConfigurationToken(10) {
        // Expected.
    }
    try requireMediaGateFailure(
        gate.admit(videoHeader(streamID: 10, sessionEpoch: 7, configEpoch: 4, frameID: 4, codec: .hevc), owner: firstOwner),
        equals: .configurationAcknowledgementPending(10),
        "reconfigured stream admitted media before ack"
    )
    try gate.acknowledgementSent(replacementToken, streamID: 10, owner: firstOwner)
    try requireMediaGateSuccess(
        gate.admit(videoHeader(streamID: 10, sessionEpoch: 7, configEpoch: 4, frameID: 4, codec: .hevc), owner: firstOwner),
        "reconfigured stream rejected increasing frame"
    )

    let secondOwner = SessionOwner(connectionOwner: ConnectionOwner())
    try gate.reset(owner: secondOwner, sessionEpoch: 7)
    try requireMediaGateFailure(
        gate.admit(videoHeader(streamID: 10, sessionEpoch: 7, configEpoch: 4, frameID: 5, codec: .hevc), owner: firstOwner),
        equals: .sessionOwnerMismatch,
        "old owner media survived reset"
    )
    try requireMediaGateFailure(
        gate.admit(videoHeader(streamID: 10, sessionEpoch: 7, configEpoch: 4, frameID: 5, codec: .hevc), owner: secondOwner),
        equals: .unboundStream(10),
        "old stream survived reset"
    )
    try gate.bindStream(10, owner: secondOwner)
    let newSessionToken = try gate.beginConfiguration(
        videoConfig(streamID: 10, epoch: 1, codec: .h264),
        owner: secondOwner
    )
    do {
        try gate.acknowledgementSent(replacementToken, streamID: 10, owner: secondOwner)
        throw VideoMediaGateSelfTestError.failed("configuration token survived session reset")
    } catch VideoMediaGateError.staleConfigurationToken(10) {
        // Expected.
    }
    try gate.acknowledgementSent(newSessionToken, streamID: 10, owner: secondOwner)
    try requireMediaGateSuccess(
        gate.admit(videoHeader(streamID: 10, sessionEpoch: 7, configEpoch: 1, frameID: 1), owner: secondOwner),
        "fresh session did not reset frame watermark"
    )
    guard !gate.endSession(owner: firstOwner) else {
        throw VideoMediaGateSelfTestError.failed("old owner ended replacement session")
    }
    guard gate.endSession(owner: secondOwner) else {
        throw VideoMediaGateSelfTestError.failed("current owner could not end session")
    }
}

private enum VideoMediaGateSelfTestError: Error {
    case failed(String)
}

private func requireMediaGateSuccess(
    _ result: Result<VideoMediaGate.AcceptedFrame, VideoMediaGateError>,
    _ message: String
) throws {
    guard case .success = result else {
        throw VideoMediaGateSelfTestError.failed(message)
    }
}

private func requireMediaGateFailure(
    _ result: Result<VideoMediaGate.AcceptedFrame, VideoMediaGateError>,
    equals expected: VideoMediaGateError,
    _ message: String
) throws {
    guard case let .failure(actual) = result, actual == expected else {
        throw VideoMediaGateSelfTestError.failed(message)
    }
}

private func videoConfig(streamID: UInt64, epoch: UInt64, codec: VSCodec) -> VSVideoConfig {
    var config = VSVideoConfig()
    config.streamID = streamID
    config.configEpoch = epoch
    config.codec = codec
    return config
}

private func videoHeader(
    streamID: UInt64,
    sessionEpoch: UInt64,
    configEpoch: UInt64,
    frameID: UInt64,
    codec: VSCodec = .h264,
    fragmentIndex: UInt32 = 0,
    fragmentCount: UInt32 = 1
) -> VSMediaPacketHeader {
    var header = VSMediaPacketHeader()
    header.streamID = streamID
    header.sessionEpoch = sessionEpoch
    header.configEpoch = configEpoch
    header.frameID = frameID
    header.codec = codec
    header.fragmentIndex = fragmentIndex
    header.fragmentCount = fragmentCount
    return header
}
