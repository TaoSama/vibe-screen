import { Capability, ClientHello, Codec, ColorDescription, DeviceIdentity, EnvelopeMetadata, InputTarget, KeyInput,
  NormalizedInput, PairingProof, PairingRequest, PROTOCOL_VERSION, ScrollInput, StylusInput, TransportKind, VideoConfig } from './ProtocolModels';
import { ProtobufWriter } from './ProtobufWriter';

export enum EnvelopePayloadField {
  CLIENT_HELLO = 20, PING = 24, PONG = 25, RESUME = 26, PAIRING_REQUEST = 31,
  LIST_DISPLAYS_REQUEST = 40, START_DISPLAY_REQUEST = 42, VIDEO_CONFIG_RESULT = 51,
  REQUEST_KEYFRAME = 52, TOUCH = 60, POINTER = 61, SCROLL = 62, KEY = 63, STYLUS = 65
}

export type OutboundControlIntent =
  | { kind: 'clientHello'; hello: ClientHello }
  | { kind: 'resume'; previousEpoch: bigint; lastMessageId: bigint }
  | { kind: 'pairingRequest'; request: PairingRequest; correlationId: bigint }
  | { kind: 'ping'; sequence: bigint }
  | { kind: 'pong'; sequence: bigint; correlationId: bigint }
  | { kind: 'listDisplays' }
  | { kind: 'startDisplay'; displayId: string }
  | { kind: 'videoConfigResult'; correlationId: bigint; config: VideoConfig; accepted: boolean; reason: string }
  | { kind: 'requestKeyframe'; streamId: bigint; reason: string }
  | { kind: 'touch'; event: NormalizedInput; target?: InputTarget }
  | { kind: 'pointer'; event: NormalizedInput; target?: InputTarget }
  | { kind: 'scroll'; event: ScrollInput }
  | { kind: 'key'; event: KeyInput }
  | { kind: 'stylus'; event: StylusInput; target?: InputTarget };

export class ProtocolEncoder {
  private envelope(metadata: EnvelopeMetadata, field: EnvelopePayloadField, payload: ProtobufWriter): Uint8Array {
    return new ProtobufWriter().uint32(1, metadata.protocolVersion).uint64(2, metadata.messageId)
      .uint64(3, metadata.correlationId).bytesField(4, metadata.sessionId).uint64(5, metadata.sessionEpoch)
      .uint64(6, metadata.sentAtMonotonicNs).message(field, payload).finish();
  }

  clientHello(metadata: EnvelopeMetadata, hello: ClientHello): Uint8Array {
    const range: ProtobufWriter = new ProtobufWriter().uint32(1, hello.minimumProtocol).uint32(2, hello.maximumProtocol);
    const payload: ProtobufWriter = new ProtobufWriter().message(1, range).string(2, hello.deviceId).string(3, hello.deviceName);
    const usesExtendedFields: boolean = hello.resourceLimits !== undefined || (hello.videoDecodeCapabilities?.length ?? 0) > 0 ||
      (hello.requiredCapabilities?.length ?? 0) > 0;
    this.repeatedEnums(payload, 4, hello.capabilities, usesExtendedFields);
    this.repeatedEnums(payload, 5, hello.codecs, usesExtendedFields);
    this.repeatedEnums(payload, 6, hello.transports, usesExtendedFields);
    if (hello.resourceLimits !== undefined) {
      const limits: ProtobufWriter = new ProtobufWriter().uint32(1, hello.resourceLimits.maximumClients)
        .uint32(2, hello.resourceLimits.maximumDisplays).uint32(3, hello.resourceLimits.maximumVideoStreams);
      payload.message(7, limits);
    }
    (hello.videoDecodeCapabilities ?? []).forEach((capability) => {
      payload.message(8, new ProtobufWriter().uint32(1, capability.codec).uint32(2, capability.maximumWidth)
        .uint32(3, capability.maximumHeight).uint32(4, capability.maximumFramesPerSecond)
        .packedVarints(5, capability.bitDepths));
    });
    payload.packedVarints(9, hello.requiredCapabilities ?? []);
    return this.envelope(metadata, EnvelopePayloadField.CLIENT_HELLO, payload);
  }

  intent(metadata: EnvelopeMetadata, intent: OutboundControlIntent): Uint8Array {
    if (intent.kind === 'clientHello') return this.clientHello(metadata, intent.hello);
    if (intent.kind === 'resume') return this.resume(metadata, intent.previousEpoch, intent.lastMessageId);
    if (intent.kind === 'pairingRequest') return this.pairingRequest({ ...metadata, correlationId: intent.correlationId }, intent.request);
    if (intent.kind === 'ping') return this.ping(metadata, intent.sequence);
    if (intent.kind === 'pong') return this.pong({ ...metadata, correlationId: intent.correlationId }, intent.sequence);
    if (intent.kind === 'listDisplays') return this.listDisplays(metadata);
    if (intent.kind === 'startDisplay') return this.startDisplay(metadata, intent.displayId);
    if (intent.kind === 'videoConfigResult') return this.videoConfigResult(metadata, intent.correlationId,
      intent.config, intent.accepted, intent.reason);
    if (intent.kind === 'requestKeyframe') return this.requestKeyframe(metadata, intent.streamId, intent.reason);
    if (intent.kind === 'touch') return this.touch(metadata, intent.event, intent.target);
    if (intent.kind === 'pointer') return this.pointer(metadata, intent.event, intent.target);
    if (intent.kind === 'scroll') return this.scroll(metadata, intent.event);
    if (intent.kind === 'key') return this.key(metadata, intent.event);
    return this.stylus(metadata, intent.event, intent.target);
  }

  ping(metadata: EnvelopeMetadata, sequence: bigint): Uint8Array {
    return this.envelope(metadata, EnvelopePayloadField.PING, new ProtobufWriter().uint64(1, sequence));
  }

  pong(metadata: EnvelopeMetadata, sequence: bigint): Uint8Array {
    return this.envelope(metadata, EnvelopePayloadField.PONG, new ProtobufWriter().uint64(1, sequence));
  }

  resume(metadata: EnvelopeMetadata, previousEpoch: bigint, lastMessageId: bigint): Uint8Array {
    const payload: ProtobufWriter = new ProtobufWriter().bytesField(1, metadata.sessionId)
      .uint64(2, previousEpoch).uint64(3, lastMessageId);
    return this.envelope(metadata, EnvelopePayloadField.RESUME, payload);
  }

  pairingRequest(metadata: EnvelopeMetadata, request: PairingRequest): Uint8Array {
    const payload: ProtobufWriter = new ProtobufWriter().bytesField(1, request.offerId).string(2, request.deviceId)
      .string(3, request.deviceName).bytesField(4, request.devicePublicKey)
      .message(5, this.deviceIdentity(request.deviceIdentity)).message(6, this.pairingProof(request.proof))
      .bytesField(7, request.bootstrapMac);
    return this.envelope(metadata, EnvelopePayloadField.PAIRING_REQUEST, payload);
  }

  listDisplays(metadata: EnvelopeMetadata): Uint8Array {
    return this.envelope(metadata, EnvelopePayloadField.LIST_DISPLAYS_REQUEST, new ProtobufWriter());
  }

  startDisplay(metadata: EnvelopeMetadata, displayId: string): Uint8Array {
    const payload: ProtobufWriter = new ProtobufWriter().uint32(1, 3).string(2, displayId);
    return this.envelope(metadata, EnvelopePayloadField.START_DISPLAY_REQUEST, payload);
  }

  videoConfigResult(metadata: EnvelopeMetadata, correlationId: bigint, config: VideoConfig,
    accepted: boolean, reason: string): Uint8Array {
    const correlated: EnvelopeMetadata = { ...metadata, correlationId };
    const payload: ProtobufWriter = new ProtobufWriter().uint64(1, config.configEpoch).bool(2, accepted)
      .string(3, reason).uint64(4, config.streamId);
    if (accepted && config.colorDescription !== undefined) payload.message(5, this.colorDescription(config.colorDescription));
    return this.envelope(correlated, EnvelopePayloadField.VIDEO_CONFIG_RESULT, payload);
  }

  requestKeyframe(metadata: EnvelopeMetadata, streamId: bigint, reason: string): Uint8Array {
    return this.envelope(metadata, EnvelopePayloadField.REQUEST_KEYFRAME,
      new ProtobufWriter().uint64(1, streamId).string(2, reason.slice(0, 128)));
  }

  touch(metadata: EnvelopeMetadata, event: NormalizedInput, target?: InputTarget): Uint8Array {
    const point: ProtobufWriter = new ProtobufWriter().fixed64(1, event.x).fixed64(2, event.y);
    const payload: ProtobufWriter = new ProtobufWriter().uint64(1, event.inputId).uint32(2, event.pointerId)
      .uint32(3, event.phase).message(4, point).fixed64(5, event.pressure);
    if (target !== undefined) payload.message(6, this.inputTarget(target));
    return this.envelope(metadata, EnvelopePayloadField.TOUCH, payload);
  }

  pointer(metadata: EnvelopeMetadata, event: NormalizedInput, target?: InputTarget): Uint8Array {
    const point: ProtobufWriter = new ProtobufWriter().fixed64(1, event.x).fixed64(2, event.y);
    const payload: ProtobufWriter = new ProtobufWriter().uint64(1, event.inputId).uint32(2, event.phase)
      .message(3, point).uint32(4, event.buttonMask);
    if (target !== undefined) payload.message(5, this.inputTarget(target));
    return this.envelope(metadata, EnvelopePayloadField.POINTER, payload);
  }

  scroll(metadata: EnvelopeMetadata, event: ScrollInput): Uint8Array {
    const payload: ProtobufWriter = new ProtobufWriter().uint64(1, event.inputId)
      .fixed64(2, event.deltaX).fixed64(3, event.deltaY);
    if (event.target !== undefined) payload.message(4, this.inputTarget(event.target));
    return this.envelope(metadata, EnvelopePayloadField.SCROLL, payload);
  }

  key(metadata: EnvelopeMetadata, event: KeyInput): Uint8Array {
    const payload: ProtobufWriter = new ProtobufWriter().uint64(1, event.inputId).uint32(2, event.usbHidUsage)
      .bool(3, event.pressed).uint32(4, event.modifierMask).string(5, event.text);
    if (event.target !== undefined) payload.message(6, this.inputTarget(event.target));
    return this.envelope(metadata, EnvelopePayloadField.KEY, payload);
  }

  stylus(metadata: EnvelopeMetadata, event: StylusInput, target?: InputTarget): Uint8Array {
    const point: ProtobufWriter = new ProtobufWriter().fixed64(1, event.x).fixed64(2, event.y);
    const payload: ProtobufWriter = new ProtobufWriter().uint64(1, event.inputId).uint32(2, event.pointerId)
      .uint32(3, event.phase).message(4, point).fixed64(5, event.pressure)
      .fixed64(6, event.tiltXDegrees).fixed64(7, event.tiltYDegrees);
    const resolvedTarget: InputTarget | undefined = target ?? event.target;
    if (resolvedTarget !== undefined) payload.message(8, this.inputTarget(resolvedTarget));
    const extended: boolean = event.toolKind !== undefined || event.buttonMask !== undefined ||
      event.contactState !== undefined;
    if (extended) {
      if (event.toolKind !== undefined) payload.uint32(9, event.toolKind);
      if (event.buttonMask !== undefined) payload.uint32(10, event.buttonMask);
      if (event.contactState !== undefined) payload.uint32(11, event.contactState);
    }
    return this.envelope(metadata, EnvelopePayloadField.STYLUS, payload);
  }

  static metadata(messageId: bigint, sessionId: Uint8Array = new Uint8Array(), sessionEpoch: bigint = 0n,
    sentAtMonotonicNs: bigint = 0n): EnvelopeMetadata {
    return { protocolVersion: PROTOCOL_VERSION, messageId, correlationId: 0n, sessionId, sessionEpoch, sentAtMonotonicNs };
  }

  private inputTarget(target: InputTarget): ProtobufWriter {
    return new ProtobufWriter().string(1, target.displayId).uint64(2, target.streamId);
  }

  private colorDescription(color: ColorDescription): ProtobufWriter {
    return new ProtobufWriter().uint32(1, color.primaries).uint32(2, color.transferFunction)
      .uint32(3, color.matrixCoefficients).bool(4, color.fullRange).uint32(5, color.bitDepth);
  }

  private deviceIdentity(identity: DeviceIdentity): ProtobufWriter {
    return new ProtobufWriter().string(1, identity.deviceId).string(2, identity.keyId).uint64(3, identity.keyEpoch)
      .uint32(4, identity.signatureAlgorithm).bytesField(5, identity.signingPublicKey);
  }

  private pairingProof(proof: PairingProof): ProtobufWriter {
    return new ProtobufWriter().bytesField(1, proof.challenge).bytesField(2, proof.ephemeralPublicKey)
      .bytesField(3, proof.signature);
  }

  private repeatedEnums(writer: ProtobufWriter, field: number, values: number[], packed: boolean): void {
    if (packed) writer.packedVarints(field, values);
    else values.forEach((value: number) => writer.uint32(field, value));
  }
}
