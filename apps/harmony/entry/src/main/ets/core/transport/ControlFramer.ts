const HEADER_LENGTH: number = 5;
export const MAX_FRAME_BYTES: number = 16 * 1024 * 1024;

export enum ProtocolChannel { CONTROL = 1, VIDEO = 2 }

export interface ProtocolFrame { channel: ProtocolChannel; payload: Uint8Array; }

export class ControlFramer {
  private buffered: Uint8Array = new Uint8Array();

  frame(channel: ProtocolChannel, payload: Uint8Array): Uint8Array {
    if (payload.length > MAX_FRAME_BYTES) throw new Error('Protocol frame exceeds limit');
    const framed: Uint8Array = new Uint8Array(HEADER_LENGTH + payload.length);
    framed[0] = channel;
    new DataView(framed.buffer).setUint32(1, payload.length, false);
    framed.set(payload, HEADER_LENGTH);
    return framed;
  }

  append(chunk: Uint8Array): ProtocolFrame[] {
    const combined: Uint8Array = new Uint8Array(this.buffered.length + chunk.length);
    combined.set(this.buffered);
    combined.set(chunk, this.buffered.length);
    const messages: ProtocolFrame[] = [];
    let offset: number = 0;
    while (combined.length - offset >= HEADER_LENGTH) {
      const channelValue: number = combined[offset];
      if (channelValue !== ProtocolChannel.CONTROL && channelValue !== ProtocolChannel.VIDEO) {
        this.buffered = new Uint8Array();
        throw new Error('Unknown Protocol v1 channel');
      }
      const length: number = new DataView(combined.buffer, combined.byteOffset + offset + 1, 4).getUint32(0, false);
      if (length > MAX_FRAME_BYTES) { this.buffered = new Uint8Array(); throw new Error('Invalid protocol frame length'); }
      if (combined.length - offset - HEADER_LENGTH < length) break;
      messages.push({ channel: channelValue as ProtocolChannel,
        payload: combined.slice(offset + HEADER_LENGTH, offset + HEADER_LENGTH + length) });
      offset += HEADER_LENGTH + length;
    }
    this.buffered = combined.slice(offset);
    return messages;
  }

  reset(): void { this.buffered = new Uint8Array(); }
}
