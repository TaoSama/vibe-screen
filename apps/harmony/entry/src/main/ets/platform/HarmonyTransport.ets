import { socket } from '@kit.NetworkKit';
import { ControlFramer } from '../core/transport/ControlFramer';

export interface TransportListener {
  onConnected(): void;
  onControlMessage(payload: Uint8Array): void;
  onDisconnected(reason: string): void;
}

export class HarmonyTransport {
  private connection: socket.TCPSocket | undefined;
  private framer: ControlFramer = new ControlFramer();

  async connect(host: string, port: number, listener: TransportListener): Promise<void> {
    if (this.connection !== undefined) await this.close();
    const candidate: socket.TCPSocket = socket.constructTCPSocketInstance();
    candidate.on('message', (info: socket.SocketMessageInfo) => {
      const messages: Uint8Array[] = this.framer.append(new Uint8Array(info.message));
      messages.forEach((message: Uint8Array) => listener.onControlMessage(message));
    });
    candidate.on('close', () => listener.onDisconnected('transport_closed'));
    candidate.on('error', (error: Error) => listener.onDisconnected(error.message));
    await candidate.bind({ address: '0.0.0.0', port: 0 });
    await candidate.connect({ address: { address: host, port }, timeout: 5000 });
    this.connection = candidate;
    listener.onConnected();
  }

  async sendControl(payload: Uint8Array): Promise<void> {
    const active: socket.TCPSocket | undefined = this.connection;
    if (active === undefined) throw new Error('Transport is disconnected');
    const framed: Uint8Array = this.framer.frame(payload);
    await active.send({ data: framed.buffer });
  }

  async close(): Promise<void> {
    const active: socket.TCPSocket | undefined = this.connection;
    this.connection = undefined;
    this.framer.reset();
    if (active !== undefined) await active.close();
  }
}

