import { decodeUtf8 } from './Utf8';

export class ProtobufReader {
  private offset: number = 0;

  constructor(private bytes: Uint8Array) {}

  done(): boolean { return this.offset >= this.bytes.length; }

  varint(): bigint {
    let value: bigint = 0n;
    let shift: bigint = 0n;
    while (this.offset < this.bytes.length && shift <= 63n) {
      const current: number = this.bytes[this.offset++];
      if (shift === 63n && current > 1) throw new Error('Protobuf varint exceeds uint64');
      value |= BigInt(current & 0x7f) << shift;
      if ((current & 0x80) === 0) return value;
      shift += 7n;
    }
    throw new Error('Malformed protobuf varint');
  }

  tag(): number {
    const value: bigint = this.varint();
    if (value === 0n || value > 0xffffffffn) throw new Error('Invalid protobuf tag');
    return Number(value);
  }

  bytesField(): Uint8Array {
    const rawLength: bigint = this.varint();
    if (rawLength > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error('Protobuf length exceeds safe range');
    const length: number = Number(rawLength);
    if (this.offset + length > this.bytes.length) throw new Error('Malformed protobuf length');
    const value: Uint8Array = this.bytes.slice(this.offset, this.offset + length);
    this.offset += length;
    return value;
  }

  string(): string { return decodeUtf8(this.bytesField()); }

  remainingBytes(): Uint8Array {
    const value: Uint8Array = this.bytes.slice(this.offset);
    this.offset = this.bytes.length;
    return value;
  }

  fixed64(): number {
    this.requireAvailable(8);
    const value: number = new DataView(this.bytes.buffer, this.bytes.byteOffset + this.offset, 8).getFloat64(0, true);
    this.offset += 8;
    return value;
  }

  skip(wire: number): void {
    if (wire === 0) { this.varint(); return; }
    if (wire === 1) { this.requireAvailable(8); this.offset += 8; return; }
    if (wire === 2) { this.bytesField(); return; }
    if (wire === 5) { this.requireAvailable(4); this.offset += 4; return; }
    throw new Error('Unsupported protobuf wire type');
  }

  private requireAvailable(length: number): void {
    if (this.offset + length > this.bytes.length) throw new Error('Truncated protobuf field');
  }
}
