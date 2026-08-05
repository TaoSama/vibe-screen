import { socket } from '@kit.NetworkKit';
import { ControlFramer, ProtocolChannel, ProtocolFrame } from '../core/transport/ControlFramer';
import { ProtocolUpgrade } from '../core/transport/ProtocolUpgrade';
import { TransportCloseClaim, TransportCloseOwner, TransportLease,
  TransportReplacement } from '../core/transport/TransportCloseOwner';

const CONNECT_TIMEOUT_MS: number = 5000;
const UPGRADE_TIMEOUT_MS: number = 1000;

export interface TransportListener {
  onConnected(): void;
  onControlMessage(payload: Uint8Array): void;
  onMediaMessage(payload: Uint8Array): void;
  onDisconnected(reason: string): void;
}

export class HarmonyTransport {
  private connection: socket.TCPSocket | undefined;
  private framer: ControlFramer = new ControlFramer();
  private upgrade: ProtocolUpgrade = new ProtocolUpgrade();
  private closeOwner: TransportCloseOwner = new TransportCloseOwner();
  private lease: TransportLease | undefined;
  private pendingLease: TransportLease | undefined;
  private upgraded: boolean = false;
  private upgradeTimer: number = -1;

  async connect(host: string, port: number, listener: TransportListener): Promise<void> {
    const replacement: TransportReplacement = this.closeOwner.replace();
    const owner: TransportLease = replacement.lease;
    const previous: socket.TCPSocket | undefined = this.connection;
    const previousLease: TransportLease | undefined = this.lease ?? replacement.superseded;
    this.pendingLease = owner;
    if (previous !== undefined && previousLease !== undefined) {
      await this.terminate(previousLease, previous, undefined, false);
    } else if (replacement.superseded !== undefined) {
      this.abandon(replacement.superseded);
    }
    if (!this.closeOwner.isCurrent(owner) || this.pendingLease?.id !== owner.id) return;

    const candidate: socket.TCPSocket = socket.constructTCPSocketInstance();
    this.connection = candidate; this.lease = owner; this.pendingLease = undefined;
    candidate.on('message', (info: socket.SocketMessageInfo) => {
      if (!this.isCurrent(owner, candidate)) return;
      try { this.receive(new Uint8Array(info.message), listener); }
      catch (error) {
        this.terminate(owner, candidate, (error as Error).message, false, listener);
      }
    });
    candidate.on('close', () => {
      this.terminate(owner, candidate, 'transport_closed', true, listener);
    });
    candidate.on('error', (error: Error) => {
      this.terminate(owner, candidate, error.message, false, listener);
    });

    try {
      await candidate.bind({ address: '0.0.0.0', port: 0 });
      if (!this.isCurrent(owner, candidate)) { await this.terminate(owner, candidate, undefined, false); return; }
      await candidate.connect({ address: { address: host, port }, timeout: CONNECT_TIMEOUT_MS });
      if (!this.isCurrent(owner, candidate)) { await this.terminate(owner, candidate, undefined, false); return; }
      await candidate.send({ data: this.upgrade.offer().buffer });
      if (!this.isCurrent(owner, candidate)) { await this.terminate(owner, candidate, undefined, false); return; }
      this.upgradeTimer = setTimeout(() => {
        if (!this.isCurrent(owner, candidate) || this.upgraded) return;
        this.terminate(owner, candidate, 'protocol_upgrade_timeout', false, listener);
      }, UPGRADE_TIMEOUT_MS);
    } catch (error) {
      try {
        const owned: boolean = await this.terminate(owner, candidate, undefined, false);
        if (!owned) return;
      }
      catch (closeError) { throw new Error(`${(error as Error).message}; close failed: ${(closeError as Error).message}`); }
      throw error;
    }
  }

  async sendControl(payload: Uint8Array): Promise<void> {
    const active: socket.TCPSocket | undefined = this.connection;
    if (active === undefined || !this.upgraded) throw new Error('Protocol v1 transport is not ready');
    const framed: Uint8Array = this.framer.frame(ProtocolChannel.CONTROL, payload);
    await active.send({ data: framed.buffer });
  }

  async close(): Promise<void> {
    const pending: TransportLease | undefined = this.pendingLease;
    if (pending !== undefined) this.abandon(pending);
    const active: socket.TCPSocket | undefined = this.connection;
    const owner: TransportLease | undefined = this.lease;
    if (active !== undefined && owner !== undefined) await this.terminate(owner, active, undefined, false);
  }

  private receive(chunk: Uint8Array, listener: TransportListener): void {
    let framedBytes: Uint8Array = chunk;
    if (!this.upgraded) {
      const remainder: Uint8Array | undefined = this.upgrade.append(chunk);
      if (remainder === undefined) return;
      this.upgraded = true;
      if (this.upgradeTimer >= 0) { clearTimeout(this.upgradeTimer); this.upgradeTimer = -1; }
      listener.onConnected(); framedBytes = remainder;
    }
    if (framedBytes.length === 0) return;
    this.framer.append(framedBytes).forEach((frame: ProtocolFrame) => {
      if (frame.channel === ProtocolChannel.CONTROL) listener.onControlMessage(frame.payload);
      else listener.onMediaMessage(frame.payload);
    });
  }

  private detachConnection(owner: TransportLease, candidate: socket.TCPSocket): void {
    if (this.pendingLease?.id === owner.id) this.pendingLease = undefined;
    if (this.lease?.id !== owner.id || this.connection !== candidate) return;
    this.connection = undefined; this.lease = undefined; this.upgraded = false;
    if (this.upgradeTimer >= 0) { clearTimeout(this.upgradeTimer); this.upgradeTimer = -1; }
    this.upgrade.reset(); this.framer.reset();
  }

  private abandon(owner: TransportLease): void {
    const claim: TransportCloseClaim = this.closeOwner.claim(owner, undefined, true);
    if (claim.detach) this.closeOwner.finish(owner);
    if (this.pendingLease?.id === owner.id) this.pendingLease = undefined;
  }

  private async terminate(owner: TransportLease, candidate: socket.TCPSocket, reason: string | undefined,
    socketAlreadyClosed: boolean, listener?: TransportListener): Promise<boolean> {
    const claim: TransportCloseClaim = this.closeOwner.claim(owner, reason, socketAlreadyClosed);
    if (!claim.detach) return false;
    this.detachConnection(owner, candidate);
    let notification: string | undefined = claim.notification;
    if (claim.closeSocket) {
      try { await candidate.close(); }
      catch (error) {
        const closeMessage: string = `transport_close_failed:${(error as Error).message}`;
        if (notification === undefined) { this.closeOwner.finish(owner); throw error; }
        notification = `${notification}; ${closeMessage}`;
      }
    }
    this.closeOwner.finish(owner);
    if (notification !== undefined) listener?.onDisconnected(notification);
    return true;
  }

  private isCurrent(owner: TransportLease, candidate: socket.TCPSocket): boolean {
    return this.closeOwner.isCurrent(owner) && this.lease?.id === owner.id && this.connection === candidate;
  }
}
