import { ProtocolDecoder } from '../protocol/ProtocolDecoder';
import { MediaPacketHeader } from '../protocol/ProtocolModels';
import { ProtobufReader } from '../protocol/ProtobufReader';

export interface MediaPacket { header: MediaPacketHeader; payload: Uint8Array; }

export class MediaPacketParser {
  constructor(private decoder: ProtocolDecoder = new ProtocolDecoder()) {}

  parse(packet: Uint8Array): MediaPacket {
    const reader: ProtobufReader = new ProtobufReader(packet);
    const headerBytes: Uint8Array = reader.bytesField();
    const payload: Uint8Array = reader.remainingBytes();
    const header: MediaPacketHeader = this.decoder.mediaHeader(headerBytes);
    if (header.payloadLength !== payload.length) throw new Error('Media payload_length mismatch');
    if (payload.length === 0) throw new Error('Media payload is empty');
    return { header, payload };
  }
}
