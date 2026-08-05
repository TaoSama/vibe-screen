const UPGRADE_OFFER: number = 0x0d;
const UPGRADE_VERSION: number = 0x01;

export class ProtocolUpgrade {
  private buffered: Uint8Array = new Uint8Array();

  offer(): Uint8Array { return new Uint8Array([UPGRADE_OFFER]); }

  append(bytes: Uint8Array): Uint8Array | undefined {
    const combined: Uint8Array = new Uint8Array(this.buffered.length + bytes.length);
    combined.set(this.buffered); combined.set(bytes, this.buffered.length);
    if (combined.length < 2) { this.buffered = combined; return undefined; }
    if (combined[0] !== UPGRADE_OFFER || combined[1] !== UPGRADE_VERSION) throw new Error('Host did not acknowledge Protocol v1');
    this.buffered = new Uint8Array();
    return combined.slice(2);
  }

  reset(): void { this.buffered = new Uint8Array(); }
}
