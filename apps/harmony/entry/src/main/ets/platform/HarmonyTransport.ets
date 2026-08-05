import { socket } from '@kit.NetworkKit';
import { ControlFramer, ProtocolChannel, ProtocolFrame } from '../core/transport/ControlFramer';
import { ProtocolUpgrade } from '../core/transport/ProtocolUpgrade';

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
  private generation: number = 0;
  private upgraded: boolean = false;
  private upgradeTimer: number = -1;

  async connect(host: string, port: number, listener: TransportListener): Promise<void> {
    const owner: number = ++this.generation;
    const previous: socket.TCPSocket | undefined = this.detachConnection();
    if (previous !== undefined) await previous.close();
    if (owner !== this.generation) return;

    const candidate: socket.TCPSocket = socket.constructTCPSocketInstance();
    this.connection = candidate;
    candidate.on('message', (info: socket.SocketMessageInfo) => {
      if (!this.isCurrent(owner, candidate)) return;
      try { this.receive(new Uint8Array(info.message), listener); }
      catch (error) {
        listener.onDisconnected((error as Error).message);
        this.closeOwned(owner, candidate).catch((closeError: Error) =>
          listener.onDisconnected(`transport_close_failed:${closeError.message}`));
      }
    });
    candidate.on('close', () => {
      if (!this.isCurrent(owner, candidate)) return;
      this.generation += 1; this.detachConnection();
      listener.onDisconnected('transport_closed');
    });
    candidate.on('error', (error: Error) => {
      if (this.isCurrent(owner, candidate)) listener.onDisconnected(error.message);
    });

    try {
      await candidate.bind({ address: '0.0.0.0', port: 0 });
      if (!this.isCurrent(owner, candidate)) { await candidate.close(); return; }
      await candidate.connect({ address: { address: host, port }, timeout: CONNECT_TIMEOUT_MS });
      if (!this.isCurrent(owner, candidate)) { await candidate.close(); return; }
      await candidate.send({ data: this.upgrade.offer().buffer });
      if (!this.isCurrent(owner, candidate)) { await candidate.close(); return; }
      this.upgradeTimer = setTimeout(() => {
        if (!this.isCurrent(owner, candidate) || this.upgraded) return;
        listener.onDisconnected('protocol_upgrade_timeout');
        this.closeOwned(owner, candidate).catch((error: Error) =>
          listener.onDisconnected(`transport_close_failed:${error.message}`));
      }, UPGRADE_TIMEOUT_MS);
    } catch (error) {
      try { await this.closeOwned(owner, candidate); }
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
    this.generation += 1;
    const active: socket.TCPSocket | undefined = this.detachConnection();
    if (active !== undefined) await active.close();
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

  private detachConnection(): socket.TCPSocket | undefined {
    const active: socket.TCPSocket | undefined = this.connection;
    this.connection = undefined; this.upgraded = false;
    if (this.upgradeTimer >= 0) { clearTimeout(this.upgradeTimer); this.upgradeTimer = -1; }
    this.upgrade.reset(); this.framer.reset();
    return active;
  }

  private async closeOwned(owner: number, candidate: socket.TCPSocket): Promise<void> {
    if (this.isCurrent(owner, candidate)) { this.generation += 1; this.detachConnection(); }
    await candidate.close();
  }

  private isCurrent(owner: number, candidate: socket.TCPSocket): boolean {
    return owner === this.generation && this.connection === candidate;
  }
}
