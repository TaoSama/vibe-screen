import { Capability, ClientHello, Codec, EnvelopeMetadata, KeyInput, NormalizedInput, PROTOCOL_VERSION, ScrollInput, TransportKind } from './ProtocolModels';
import { ProtobufWriter } from './ProtobufWriter';

export enum EnvelopePayloadField { CLIENT_HELLO = 20, PING = 24, PONG = 25, RESUME = 26, TOUCH = 60, POINTER = 61, SCROLL = 62, KEY = 63 }

export class ProtocolEncoder {
  private envelope(metadata: EnvelopeMetadata, field: EnvelopePayloadField, payload: ProtobufWriter): Uint8Array {
    return new ProtobufWriter()
      .uint32(1, metadata.protocolVersion)
      .uint64(2, metadata.messageId)
      .uint64(3, metadata.correlationId)
      .bytesField(4, metadata.sessionId)
      .uint64(5, metadata.sessionEpoch)
      .uint64(6, metadata.sentAtMonotonicNs)
      .message(field, payload)
      .finish();
  }

  clientHello(metadata: EnvelopeMetadata, hello: ClientHello): Uint8Array {
    const range: ProtobufWriter = new ProtobufWriter().uint32(1, hello.minimumProtocol).uint32(2, hello.maximumProtocol);
    const payload: ProtobufWriter = new ProtobufWriter().message(1, range).string(2, hello.deviceId).string(3, hello.deviceName);
    hello.capabilities.forEach((capability: Capability) => payload.uint32(4, capability));
    hello.codecs.forEach((codec: Codec) => payload.uint32(5, codec));
    hello.transports.forEach((transport: TransportKind) => payload.uint32(6, transport));
    return this.envelope(metadata, EnvelopePayloadField.CLIENT_HELLO, payload);
  }

  ping(metadata: EnvelopeMetadata, sequence: bigint): Uint8Array {
    return this.envelope(metadata, EnvelopePayloadField.PING, new ProtobufWriter().uint64(1, sequence));
  }

  resume(metadata: EnvelopeMetadata, previousEpoch: bigint, lastMessageId: bigint): Uint8Array {
    const payload: ProtobufWriter = new ProtobufWriter().bytesField(1, metadata.sessionId)
      .uint64(2, previousEpoch).uint64(3, lastMessageId);
    return this.envelope(metadata, EnvelopePayloadField.RESUME, payload);
  }

  touch(metadata: EnvelopeMetadata, event: NormalizedInput): Uint8Array {
    const point: ProtobufWriter = new ProtobufWriter().fixed64(1, event.x).fixed64(2, event.y);
    const payload: ProtobufWriter = new ProtobufWriter().uint64(1, event.inputId).uint32(2, event.pointerId)
      .uint32(3, event.phase).message(4, point).fixed64(5, event.pressure);
    return this.envelope(metadata, EnvelopePayloadField.TOUCH, payload);
  }

  pointer(metadata: EnvelopeMetadata, event: NormalizedInput): Uint8Array {
    const point: ProtobufWriter = new ProtobufWriter().fixed64(1, event.x).fixed64(2, event.y);
    const payload: ProtobufWriter = new ProtobufWriter().uint64(1, event.inputId).uint32(2, event.phase)
      .message(3, point).uint32(4, event.buttonMask);
    return this.envelope(metadata, EnvelopePayloadField.POINTER, payload);
  }

  scroll(metadata: EnvelopeMetadata, event: ScrollInput): Uint8Array {
    const payload: ProtobufWriter = new ProtobufWriter().uint64(1, event.inputId)
      .fixed64(2, event.deltaX).fixed64(3, event.deltaY);
    return this.envelope(metadata, EnvelopePayloadField.SCROLL, payload);
  }

  key(metadata: EnvelopeMetadata, event: KeyInput): Uint8Array {
    const payload: ProtobufWriter = new ProtobufWriter().uint64(1, event.inputId).uint32(2, event.usbHidUsage)
      .bool(3, event.pressed).uint32(4, event.modifierMask).string(5, event.text);
    return this.envelope(metadata, EnvelopePayloadField.KEY, payload);
  }

  static metadata(messageId: bigint, sessionId: Uint8Array = new Uint8Array(), sessionEpoch: bigint = 0n,
    sentAtMonotonicNs: bigint = 0n): EnvelopeMetadata {
    return { protocolVersion: PROTOCOL_VERSION, messageId, correlationId: 0n, sessionId,
      sessionEpoch, sentAtMonotonicNs };
  }
}
