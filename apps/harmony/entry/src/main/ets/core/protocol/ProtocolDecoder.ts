export interface SessionAcceptedMessage { sessionId: Uint8Array; sessionEpoch: bigint; heartbeatIntervalMs: number; }
export interface DecodedEnvelope { protocolVersion: number; payloadField: number; payload: Uint8Array; }

class Reader {
  private offset: number = 0;
  constructor(private bytes: Uint8Array) {}
  done(): boolean { return this.offset >= this.bytes.length; }
  varint(): bigint {
    let value: bigint = 0n;
    let shift: bigint = 0n;
    while (this.offset < this.bytes.length && shift <= 63n) {
      const current: number = this.bytes[this.offset++];
      value |= BigInt(current & 0x7f) << shift;
      if ((current & 0x80) === 0) return value;
      shift += 7n;
    }
    throw new Error('Malformed protobuf varint');
  }
  bytesField(): Uint8Array {
    const length: number = Number(this.varint());
    if (length < 0 || this.offset + length > this.bytes.length) throw new Error('Malformed protobuf length');
    const value: Uint8Array = this.bytes.slice(this.offset, this.offset + length);
    this.offset += length;
    return value;
  }
  skip(wire: number): void {
    if (wire === 0) { this.varint(); return; }
    if (wire === 1) { this.offset += 8; return; }
    if (wire === 2) { this.bytesField(); return; }
    if (wire === 5) { this.offset += 4; return; }
    throw new Error('Unsupported protobuf wire type');
  }
}

export class ProtocolDecoder {
  envelope(bytes: Uint8Array): DecodedEnvelope {
    const reader: Reader = new Reader(bytes);
    let version: number = 0;
    let payloadField: number = 0;
    let payload: Uint8Array = new Uint8Array();
    while (!reader.done()) {
      const tag: number = Number(reader.varint());
      const field: number = tag >>> 3;
      const wire: number = tag & 7;
      if (field === 1 && wire === 0) version = Number(reader.varint());
      else if (field >= 20 && wire === 2) { payloadField = field; payload = reader.bytesField(); }
      else reader.skip(wire);
    }
    return { protocolVersion: version, payloadField, payload };
  }

  sessionAccepted(payload: Uint8Array): SessionAcceptedMessage {
    const reader: Reader = new Reader(payload);
    let sessionId: Uint8Array = new Uint8Array();
    let epoch: bigint = 0n;
    let heartbeat: number = 0;
    while (!reader.done()) {
      const tag: number = Number(reader.varint());
      const field: number = tag >>> 3;
      const wire: number = tag & 7;
      if (field === 1 && wire === 2) sessionId = reader.bytesField();
      else if (field === 2 && wire === 0) epoch = reader.varint();
      else if (field === 3 && wire === 0) heartbeat = Number(reader.varint());
      else reader.skip(wire);
    }
    if (sessionId.length === 0 || epoch === 0n) throw new Error('Invalid SessionAccepted');
    return { sessionId, sessionEpoch: epoch, heartbeatIntervalMs: heartbeat };
  }
}
