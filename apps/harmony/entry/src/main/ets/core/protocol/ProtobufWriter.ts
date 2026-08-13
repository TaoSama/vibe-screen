import { encodeUtf8 } from './Utf8';

const WIRE_VARINT: number = 0;
const WIRE_FIXED64: number = 1;
const WIRE_LENGTH_DELIMITED: number = 2;

export class ProtobufWriter {
  private bytes: number[] = [];

  private writeTag(fieldNumber: number, wireType: number): void {
    this.writeVarint(BigInt((fieldNumber << 3) | wireType));
  }

  writeVarint(value: bigint): void {
    let remaining: bigint = value;
    while (remaining > 0x7fn) {
      this.bytes.push(Number(remaining & 0x7fn) | 0x80);
      remaining >>= 7n;
    }
    this.bytes.push(Number(remaining));
  }

  uint32(fieldNumber: number, value: number): ProtobufWriter {
    if (value !== 0) { this.writeTag(fieldNumber, WIRE_VARINT); this.writeVarint(BigInt(value)); }
    return this;
  }

  uint64(fieldNumber: number, value: bigint): ProtobufWriter {
    if (value !== 0n) { this.writeTag(fieldNumber, WIRE_VARINT); this.writeVarint(value); }
    return this;
  }

  sint32(fieldNumber: number, value: number): ProtobufWriter {
    if (!Number.isInteger(value) || value < -0x80000000 || value > 0x7fffffff) {
      throw new Error('sint32 value is outside the supported range');
    }
    const encoded: number = ((value << 1) ^ (value >> 31)) >>> 0;
    return this.uint32(fieldNumber, encoded);
  }

  bool(fieldNumber: number, value: boolean): ProtobufWriter {
    return this.uint32(fieldNumber, value ? 1 : 0);
  }

  fixed64(fieldNumber: number, value: number): ProtobufWriter {
    if (value === 0) return this;
    this.writeTag(fieldNumber, WIRE_FIXED64);
    const buffer: ArrayBuffer = new ArrayBuffer(8);
    new DataView(buffer).setFloat64(0, value, true);
    this.raw(new Uint8Array(buffer));
    return this;
  }

  string(fieldNumber: number, value: string): ProtobufWriter {
    if (value.length > 0) this.bytesField(fieldNumber, encodeUtf8(value));
    return this;
  }

  bytesField(fieldNumber: number, value: Uint8Array): ProtobufWriter {
    if (value.length > 0) {
      this.writeTag(fieldNumber, WIRE_LENGTH_DELIMITED);
      this.writeVarint(BigInt(value.length));
      this.raw(value);
    }
    return this;
  }

  message(fieldNumber: number, writer: ProtobufWriter): ProtobufWriter {
    const value: Uint8Array = writer.finish();
    this.writeTag(fieldNumber, WIRE_LENGTH_DELIMITED);
    this.writeVarint(BigInt(value.length));
    return this.raw(value);
  }

  packedVarints(fieldNumber: number, values: number[]): ProtobufWriter {
    const packed: ProtobufWriter = new ProtobufWriter();
    values.forEach((value: number) => packed.writeVarint(BigInt(value)));
    return this.bytesField(fieldNumber, packed.finish());
  }

  raw(value: Uint8Array): ProtobufWriter {
    for (let index: number = 0; index < value.length; index += 1) this.bytes.push(value[index]);
    return this;
  }

  finish(): Uint8Array { return new Uint8Array(this.bytes); }
}
