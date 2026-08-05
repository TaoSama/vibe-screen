export interface TransportLease { id: number; }

export interface TransportReplacement { lease: TransportLease; superseded?: TransportLease; }

export interface TransportCloseClaim {
  detach: boolean;
  closeSocket: boolean;
  notification?: string;
}

interface LeaseState { claimed: boolean; }

export class TransportCloseOwner {
  private nextId: number = 1;
  private activeId: number = 0;
  private states: Map<number, LeaseState> = new Map();

  replace(): TransportReplacement {
    const superseded: TransportLease | undefined = this.activeId === 0 ? undefined : { id: this.activeId };
    const lease: TransportLease = { id: this.nextId++ };
    this.activeId = lease.id;
    this.states.set(lease.id, { claimed: false });
    return { lease, superseded };
  }

  isCurrent(lease: TransportLease): boolean {
    return this.activeId === lease.id && this.states.get(lease.id)?.claimed === false;
  }

  claim(lease: TransportLease, reason?: string, socketAlreadyClosed: boolean = false): TransportCloseClaim {
    const state: LeaseState | undefined = this.states.get(lease.id);
    if (state === undefined || state.claimed) return { detach: false, closeSocket: false };
    state.claimed = true;
    if (this.activeId === lease.id) this.activeId = 0;
    return { detach: true, closeSocket: !socketAlreadyClosed, notification: reason };
  }

  finish(lease: TransportLease): void {
    const state: LeaseState | undefined = this.states.get(lease.id);
    if (state?.claimed === true) this.states.delete(lease.id);
  }
}
