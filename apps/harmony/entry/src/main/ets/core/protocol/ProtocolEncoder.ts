import { Capability, ClientHello, Codec, EnvelopeMetadata, InputTarget, KeyInput, NormalizedInput,
  PROTOCOL_VERSION, ScrollInput, TransportKind, VideoConfig } from './ProtocolModels';
import { ProtobufWriter } from './ProtobufWriter';

export enum EnvelopePayloadField {
  CLIENT_HELLO = 20, PING = 24, PONG = 25, RESUME = 26,
  LIST_DISPLAYS_REQUEST = 40, START_DISPLAY_REQUEST = 42, VIDEO_CONFIG_RESULT = 51,
  REQUEST_KEYFRAME = 52, TOUCH = 60, POINTER = 61, SCROLL = 62, KEY = 63
}

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

  static metadata(messageId: bigint, sessionId: Uint8Array = new Uint8Array(), sessionEpoch: bigint = 0n,
    sentAtMonotonicNs: bigint = 0n): EnvelopeMetadata {
    return { protocolVersion: PROTOCOL_VERSION, messageId, correlationId: 0n, sessionId, sessionEpoch, sentAtMonotonicNs };
  }

  private inputTarget(target: InputTarget): ProtobufWriter {
    return new ProtobufWriter().string(1, target.displayId).uint64(2, target.streamId);
  }

  private repeatedEnums(writer: ProtobufWriter, field: number, values: number[], packed: boolean): void {
    if (packed) writer.packedVarints(field, values);
    else values.forEach((value: number) => writer.uint32(field, value));
  }
}
