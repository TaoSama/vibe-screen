import { Codec, ColorDescription, ColorPrimaries, DisplayDescriptor, HostHello, MatrixCoefficients,
  MediaPacketHeader, SessionAccepted, TransferFunction, VideoConfig } from './ProtocolModels';
import { ProtobufReader } from './ProtobufReader';

export interface DecodedEnvelope {
  protocolVersion: number;
  messageId: bigint;
  correlationId: bigint;
  sessionId: Uint8Array;
  sessionEpoch: bigint;
  payloadField: number;
  payload: Uint8Array;
}

export interface StartDisplayResponse { accepted: boolean; streamId: bigint; rejectionReason: string; displayId: string; }
export interface FailureMessage { reason: string; message: string; retryable: boolean; }
export interface DisplayChange { display: DisplayDescriptor; rotationDegrees: number; }
export interface DisconnectNotice { reason: string; mayResume: boolean; }

export class ProtocolDecoder {
  envelope(bytes: Uint8Array): DecodedEnvelope {
    const reader: ProtobufReader = new ProtobufReader(bytes);
    let version: number = 0;
    let messageId: bigint = 0n;
    let correlationId: bigint = 0n;
    let sessionId: Uint8Array = new Uint8Array();
    let sessionEpoch: bigint = 0n;
    let payloadField: number = 0;
    let payload: Uint8Array = new Uint8Array();
    while (!reader.done()) {
      const tag: number = reader.tag();
      const field: number = tag >>> 3;
      const wire: number = tag & 7;
      if (field === 1 && wire === 0) version = Number(reader.varint());
      else if (field === 2 && wire === 0) messageId = reader.varint();
      else if (field === 3 && wire === 0) correlationId = reader.varint();
      else if (field === 4 && wire === 2) sessionId = reader.bytesField();
      else if (field === 5 && wire === 0) sessionEpoch = reader.varint();
      else if (field >= 20 && wire === 2) {
        if (payloadField !== 0) throw new Error('Protocol envelope has multiple payloads');
        payloadField = field; payload = reader.bytesField();
      }
      else reader.skip(wire);
    }
    if (payloadField === 0) throw new Error('Protocol envelope has no payload');
    return { protocolVersion: version, messageId, correlationId, sessionId, sessionEpoch, payloadField, payload };
  }

  hostHello(payload: Uint8Array): HostHello {
    const reader: ProtobufReader = new ProtobufReader(payload);
    const message: HostHello = { selectedProtocol: 0, capabilities: [], codecs: [] };
    while (!reader.done()) {
      const tag: number = reader.tag(); const field: number = tag >>> 3; const wire: number = tag & 7;
      if (field === 1 && wire === 0) message.selectedProtocol = Number(reader.varint());
      else if (field === 4 && wire === 0) message.capabilities.push(Number(reader.varint()));
      else if (field === 5 && wire === 0) message.codecs.push(Number(reader.varint()));
      else if ((field === 4 || field === 5) && wire === 2) this.readPackedEnums(reader.bytesField(), field === 4 ? message.capabilities : message.codecs);
      else reader.skip(wire);
    }
    return message;
  }

  sessionAccepted(payload: Uint8Array): SessionAccepted {
    const reader: ProtobufReader = new ProtobufReader(payload);
    const message: SessionAccepted = { sessionId: new Uint8Array(), sessionEpoch: 0n, heartbeatIntervalMs: 0, negotiatedCapabilities: [] };
    while (!reader.done()) {
      const tag: number = reader.tag(); const field: number = tag >>> 3; const wire: number = tag & 7;
      if (field === 1 && wire === 2) message.sessionId = reader.bytesField();
      else if (field === 2 && wire === 0) message.sessionEpoch = reader.varint();
      else if (field === 3 && wire === 0) message.heartbeatIntervalMs = Number(reader.varint());
      else if (field === 4 && wire === 0) message.negotiatedCapabilities.push(Number(reader.varint()));
      else if (field === 4 && wire === 2) this.readPackedEnums(reader.bytesField(), message.negotiatedCapabilities);
      else reader.skip(wire);
    }
    if (message.sessionId.length === 0 || message.sessionEpoch === 0n) throw new Error('Invalid SessionAccepted');
    return message;
  }

  displays(payload: Uint8Array): DisplayDescriptor[] {
    const reader: ProtobufReader = new ProtobufReader(payload); const displays: DisplayDescriptor[] = [];
    while (!reader.done()) {
      const tag: number = reader.tag(); const field: number = tag >>> 3; const wire: number = tag & 7;
      if (field === 1 && wire === 2) displays.push(this.display(reader.bytesField())); else reader.skip(wire);
    }
    return displays;
  }

  startDisplayResponse(payload: Uint8Array): StartDisplayResponse {
    const reader: ProtobufReader = new ProtobufReader(payload);
    const response: StartDisplayResponse = { accepted: false, streamId: 0n, rejectionReason: '', displayId: '' };
    while (!reader.done()) {
      const tag: number = reader.tag(); const field: number = tag >>> 3; const wire: number = tag & 7;
      if (field === 1 && wire === 0) response.accepted = reader.varint() !== 0n;
      else if (field === 2 && wire === 2) response.displayId = this.display(reader.bytesField()).displayId;
      else if (field === 3 && wire === 2) response.rejectionReason = reader.string();
      else if (field === 4 && wire === 0) response.streamId = reader.varint();
      else reader.skip(wire);
    }
    return response;
  }

  videoConfig(payload: Uint8Array): VideoConfig {
    const reader: ProtobufReader = new ProtobufReader(payload);
    const config: VideoConfig = { configEpoch: 0n, codec: Codec.UNSPECIFIED, width: 0, height: 0,
      framesPerSecond: 0, bitrateKbps: 0, streamId: 0n, rotationDegrees: 0 };
    while (!reader.done()) {
      const tag: number = reader.tag(); const field: number = tag >>> 3; const wire: number = tag & 7;
      if (field === 1 && wire === 0) config.configEpoch = reader.varint();
      else if (field === 2 && wire === 0) config.codec = Number(reader.varint());
      else if (field === 3 && wire === 2) [config.width, config.height] = this.dimensions(reader.bytesField());
      else if (field === 4 && wire === 0) config.framesPerSecond = Number(reader.varint());
      else if (field === 5 && wire === 0) config.bitrateKbps = Number(reader.varint());
      else if (field === 6 && wire === 0) config.streamId = reader.varint();
      else if (field === 7 && wire === 2) config.colorDescription = this.colorDescription(reader.bytesField());
      else if (field === 8 && wire === 0) config.rotationDegrees = Number(reader.varint());
      else reader.skip(wire);
    }
    return config;
  }

  disconnectNotice(payload: Uint8Array): DisconnectNotice {
    const reader: ProtobufReader = new ProtobufReader(payload);
    const notice: DisconnectNotice = { reason: '', mayResume: false };
    while (!reader.done()) {
      const tag: number = reader.tag(); const field: number = tag >>> 3; const wire: number = tag & 7;
      if (field === 1 && wire === 2) notice.reason = reader.string();
      else if (field === 2 && wire === 0) notice.mayResume = reader.varint() !== 0n;
      else reader.skip(wire);
    }
    return notice;
  }

  private colorDescription(payload: Uint8Array): ColorDescription {
    const reader: ProtobufReader = new ProtobufReader(payload);
    const color: ColorDescription = { primaries: ColorPrimaries.UNSPECIFIED,
      transferFunction: TransferFunction.UNSPECIFIED, matrixCoefficients: MatrixCoefficients.UNSPECIFIED,
      fullRange: false, bitDepth: 0 };
    while (!reader.done()) {
      const tag: number = reader.tag(); const field: number = tag >>> 3; const wire: number = tag & 7;
      if (wire !== 0) { reader.skip(wire); continue; }
      const value: bigint = reader.varint();
      if (field === 1) color.primaries = Number(value);
      else if (field === 2) color.transferFunction = Number(value);
      else if (field === 3) color.matrixCoefficients = Number(value);
      else if (field === 4) color.fullRange = value !== 0n;
      else if (field === 5) color.bitDepth = Number(value);
    }
    return color;
  }

  mediaHeader(payload: Uint8Array): MediaPacketHeader {
    const reader: ProtobufReader = new ProtobufReader(payload);
    const header: MediaPacketHeader = { streamId: 0n, sessionEpoch: 0n, configEpoch: 0n, frameId: 0n,
      fragmentIndex: 0, fragmentCount: 0, captureTimestampNs: 0n, keyframe: false, codec: Codec.UNSPECIFIED, payloadLength: 0 };
    while (!reader.done()) {
      const tag: number = reader.tag(); const field: number = tag >>> 3; const wire: number = tag & 7;
      if (wire !== 0) { reader.skip(wire); continue; }
      const value: bigint = reader.varint();
      if (field === 1) header.streamId = value; else if (field === 2) header.sessionEpoch = value;
      else if (field === 3) header.configEpoch = value; else if (field === 4) header.frameId = value;
      else if (field === 5) header.fragmentIndex = Number(value); else if (field === 6) header.fragmentCount = Number(value);
      else if (field === 7) header.captureTimestampNs = value; else if (field === 8) header.keyframe = value !== 0n;
      else if (field === 9) header.codec = Number(value); else if (field === 10) header.payloadLength = Number(value);
    }
    return header;
  }

  displayChanged(payload: Uint8Array): DisplayChange {
    const reader: ProtobufReader = new ProtobufReader(payload);
    let display: DisplayDescriptor | undefined; let rotationDegrees: number = 0;
    while (!reader.done()) {
      const tag: number = reader.tag(); const field: number = tag >>> 3; const wire: number = tag & 7;
      if (field === 1 && wire === 2) display = this.display(reader.bytesField());
      else if (field === 2 && wire === 0) rotationDegrees = Number(reader.varint());
      else reader.skip(wire);
    }
    if (display === undefined) throw new Error('DisplayChanged has no display');
    return { display, rotationDegrees };
  }

  sequence(payload: Uint8Array): bigint {
    const reader: ProtobufReader = new ProtobufReader(payload);
    while (!reader.done()) { const tag: number = reader.tag(); if ((tag >>> 3) === 1 && (tag & 7) === 0) return reader.varint(); reader.skip(tag & 7); }
    return 0n;
  }

  failure(payload: Uint8Array, protocolError: boolean): FailureMessage {
    const reader: ProtobufReader = new ProtobufReader(payload); const result: FailureMessage = { reason: '', message: '', retryable: false };
    while (!reader.done()) {
      const tag: number = reader.tag(); const field: number = tag >>> 3; const wire: number = tag & 7;
      if (protocolError && field === 1 && wire === 0) result.reason = `protocol_error_${reader.varint()}`;
      else if (!protocolError && field === 1 && wire === 2) result.reason = reader.string();
      else if (field === 2 && wire === 2) result.message = reader.string();
      else if (field === 3 && wire === 0) result.retryable = reader.varint() !== 0n;
      else reader.skip(wire);
    }
    return result;
  }

  private display(payload: Uint8Array): DisplayDescriptor {
    const reader: ProtobufReader = new ProtobufReader(payload);
    const display: DisplayDescriptor = { displayId: '', name: '', width: 0, height: 0, scaleFactor: 0, primary: false };
    while (!reader.done()) {
      const tag: number = reader.tag(); const field: number = tag >>> 3; const wire: number = tag & 7;
      if (field === 1 && wire === 2) display.displayId = reader.string(); else if (field === 2 && wire === 2) display.name = reader.string();
      else if (field === 3 && wire === 2) [display.width, display.height] = this.dimensions(reader.bytesField());
      else if (field === 4 && wire === 1) display.scaleFactor = reader.fixed64(); else if (field === 5 && wire === 0) display.primary = reader.varint() !== 0n;
      else reader.skip(wire);
    }
    return display;
  }

  private dimensions(payload: Uint8Array): [number, number] {
    const reader: ProtobufReader = new ProtobufReader(payload); let width: number = 0; let height: number = 0;
    while (!reader.done()) { const tag: number = reader.tag(); const field: number = tag >>> 3; const wire: number = tag & 7;
      if (field === 1 && wire === 0) width = Number(reader.varint()); else if (field === 2 && wire === 0) height = Number(reader.varint()); else reader.skip(wire); }
    return [width, height];
  }

  private readPackedEnums(payload: Uint8Array, destination: number[]): void {
    const packed: ProtobufReader = new ProtobufReader(payload); while (!packed.done()) destination.push(Number(packed.varint()));
  }
}
