const HEADER_LENGTH: number = 4;
const MAX_CONTROL_MESSAGE_BYTES: number = 1024 * 1024;

export class ControlFramer {
  private buffered: Uint8Array = new Uint8Array();

  frame(payload: Uint8Array): Uint8Array {
    if (payload.length > MAX_CONTROL_MESSAGE_BYTES) throw new Error('Control message exceeds limit');
    const framed: Uint8Array = new Uint8Array(HEADER_LENGTH + payload.length);
    new DataView(framed.buffer).setUint32(0, payload.length, false);
    framed.set(payload, HEADER_LENGTH);
    return framed;
  }

  append(chunk: Uint8Array): Uint8Array[] {
    const combined: Uint8Array = new Uint8Array(this.buffered.length + chunk.length);
    combined.set(this.buffered);
    combined.set(chunk, this.buffered.length);
    const messages: Uint8Array[] = [];
    let offset: number = 0;
    while (combined.length - offset >= HEADER_LENGTH) {
      const length: number = new DataView(combined.buffer, combined.byteOffset + offset, HEADER_LENGTH).getUint32(0, false);
      if (length > MAX_CONTROL_MESSAGE_BYTES) { this.buffered = new Uint8Array(); throw new Error('Invalid control message length'); }
      if (combined.length - offset - HEADER_LENGTH < length) break;
      messages.push(combined.slice(offset + HEADER_LENGTH, offset + HEADER_LENGTH + length));
      offset += HEADER_LENGTH + length;
    }
    this.buffered = combined.slice(offset);
    return messages;
  }

  reset(): void { this.buffered = new Uint8Array(); }
}

