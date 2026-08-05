import { Capability } from '../protocol/ProtocolModels';

export const HARMONY_ADVERTISED_CAPABILITIES: Capability[] = [
  Capability.TOUCH, Capability.KEYBOARD, Capability.POINTER, Capability.STYLUS
];
export const HARMONY_REQUIRED_CAPABILITIES: Capability[] = [Capability.TOUCH];

export class ClientCapabilities {
  private readonly offered: Set<number>;
  private readonly required: Set<number>;
  private host: Set<number> = new Set();
  private negotiated: Set<number> = new Set();

  constructor(offered: Capability[], required: Capability[]) {
    this.offered = new Set(offered);
    this.required = new Set(required);
    if (this.offered.has(Capability.UNSPECIFIED) || !this.isSubset(this.required, this.offered)) {
      throw new Error('Invalid client capability declaration');
    }
  }

  acceptHost(capabilities: Capability[]): void {
    this.host = new Set(capabilities);
    if (!this.isSubset(this.required, this.host)) throw new Error('Host lacks a required client capability');
    this.negotiated.clear();
  }

  acceptNegotiated(capabilities: Capability[]): void {
    const accepted: Set<number> = new Set(capabilities);
    if (accepted.has(Capability.UNSPECIFIED) || !this.isSubset(accepted, this.offered) ||
      !this.isSubset(accepted, this.host) || !this.isSubset(this.required, accepted)) {
      throw new Error('Host returned an invalid negotiated capability set');
    }
    this.negotiated = accepted;
  }

  has(capability: Capability): boolean { return this.negotiated.has(capability); }

  values(): Capability[] { return [...this.negotiated] as Capability[]; }

  reset(): void { this.host.clear(); this.negotiated.clear(); }

  private isSubset(left: Set<number>, right: Set<number>): boolean {
    for (const capability of left) if (!right.has(capability)) return false;
    return true;
  }
}
