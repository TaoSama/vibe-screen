import { encodeUtf8 } from '../protocol/Utf8';

const IDENTITY_DOMAIN: string = 'vibescreen/identity/v1';
const ROTATION_DOMAIN: string = 'vibescreen/traffic-key-update/v1';
const RECORD_MAGIC: number = 0x56534352;
const RECORD_VERSION: number = 1;
const SESSION_ID_HASH_BYTES: number = 16;
const NONCE_BYTES: number = 12;
const GCM_TAG_BYTES: number = 16;
const RECORD_HEADER_BYTES: number = 4 + 1 + SESSION_ID_HASH_BYTES + 8 + 8 + 1 + 1 + NONCE_BYTES;
const LEGACY_MATERIAL_BYTES: number = 128;
const MATERIAL_BYTES: number = 256;
const PUBLIC_KEY_BYTES: number = 65;
const NEGOTIATION_VERSION: number = 1;
const REQUEST_MAGIC: number[] = [0x56, 0x53, 0x4c, 0x53];
const RESPONSE_MAGIC: number[] = [0x56, 0x53, 0x4c, 0x52];
const SECURE_RECORDS_REQUIRED: number = 1;
const LEGACY_FALLBACK_ALLOWED: number = 1 << 1;
const SECURE_RECORDS_ACCEPTED: number = 1;
const EXPLICIT_LEGACY_FALLBACK: number = 1 << 1;

export enum SecureRecordChannel { CONTROL = 1, MEDIA = 2, AUDIO = 3, BULK = 4 }
export enum SecureRecordSender { HOST = 1, DEVICE = 2 }
export enum SecureRecordProtectionState { ENCRYPTED = 'encrypted', EXPLICIT_LEGACY_FALLBACK = 'explicit_legacy_fallback' }

export interface ChannelRecordCrypto {
  sha256(value: Uint8Array): Uint8Array;
  hmacSha256(key: Uint8Array, value: Uint8Array): Uint8Array;
  hkdfSha256(input: Uint8Array, salt: Uint8Array, info: Uint8Array, length: number): Uint8Array;
  sealAes256Gcm(key: Uint8Array, nonce: Uint8Array, plaintext: Uint8Array, authenticatedHeader: Uint8Array): Uint8Array;
  openAes256Gcm(key: Uint8Array, nonce: Uint8Array, ciphertextAndTag: Uint8Array, authenticatedHeader: Uint8Array): Uint8Array;
}

export interface SecureRecordNegotiationRequest { publicKey: Uint8Array; allowLegacyFallback: boolean; }
export interface SecureRecordNegotiationResponse { publicKey: Uint8Array; encrypted: boolean; legacy: boolean; }

export class LanSecureRecordNegotiation {
  static readonly requestBytes: number = 4 + 1 + 1 + PUBLIC_KEY_BYTES;
  static readonly responseBytes: number = 4 + 1 + 1 + PUBLIC_KEY_BYTES;

  static encodeRequest(publicKey: Uint8Array, allowLegacyFallback: boolean): Uint8Array {
    if (publicKey.length !== PUBLIC_KEY_BYTES) throw new Error('Trusted LAN secure records require a P-256 public key');
    const flags: number = SECURE_RECORDS_REQUIRED | (allowLegacyFallback ? LEGACY_FALLBACK_ALLOWED : 0);
    return concat([new Uint8Array(REQUEST_MAGIC), new Uint8Array([NEGOTIATION_VERSION, flags]), publicKey]);
  }

  static decodeRequest(value: Uint8Array): SecureRecordNegotiationRequest {
    if (value.length !== LanSecureRecordNegotiation.requestBytes || !hasPrefix(value, REQUEST_MAGIC) || value[4] !== NEGOTIATION_VERSION) {
      throw new Error('Invalid trusted LAN secure-record request');
    }
    const flags: number = value[5];
    if ((flags & SECURE_RECORDS_REQUIRED) === 0) throw new Error('Trusted LAN secure-record request did not require encryption');
    return { publicKey: value.slice(6), allowLegacyFallback: (flags & LEGACY_FALLBACK_ALLOWED) !== 0 };
  }

  static encodeResponse(publicKey: Uint8Array, encrypted: boolean, explicitLegacyFallback: boolean): Uint8Array {
    if (publicKey.length !== PUBLIC_KEY_BYTES) throw new Error('Trusted LAN secure records require a P-256 public key');
    if (encrypted === explicitLegacyFallback) throw new Error('Trusted LAN response must choose encrypted or explicit legacy');
    const flags: number = encrypted ? SECURE_RECORDS_ACCEPTED : EXPLICIT_LEGACY_FALLBACK;
    return concat([new Uint8Array(RESPONSE_MAGIC), new Uint8Array([NEGOTIATION_VERSION, flags]), publicKey]);
  }

  static decodeResponse(value: Uint8Array): SecureRecordNegotiationResponse {
    if (value.length !== LanSecureRecordNegotiation.responseBytes || !hasPrefix(value, RESPONSE_MAGIC) || value[4] !== NEGOTIATION_VERSION) {
      throw new Error('Invalid trusted LAN secure-record response');
    }
    const flags: number = value[5];
    const encrypted: boolean = (flags & SECURE_RECORDS_ACCEPTED) !== 0;
    const legacy: boolean = (flags & EXPLICIT_LEGACY_FALLBACK) !== 0;
    if (encrypted === legacy) throw new Error('Trusted LAN response did not choose one protection mode');
    return { publicKey: value.slice(6), encrypted, legacy };
  }

  static requireEncryptedResponse(value: Uint8Array): SecureRecordNegotiationResponse {
    const decoded: SecureRecordNegotiationResponse = LanSecureRecordNegotiation.decodeResponse(value);
    if (decoded.legacy) throw new Error('Trusted LAN plaintext fallback was not explicitly allowed');
    return decoded;
  }
}

export class SessionTrafficKeys {
  constructor(readonly keyId: string, readonly keyEpoch: bigint, readonly hostControl: Uint8Array,
    readonly deviceControl: Uint8Array, readonly hostMedia: Uint8Array, readonly deviceMedia: Uint8Array,
    readonly hostAudio: Uint8Array, readonly deviceAudio: Uint8Array, readonly hostBulk: Uint8Array,
    readonly deviceBulk: Uint8Array) {}

  key(channel: SecureRecordChannel, sender: SecureRecordSender): Uint8Array {
    if (channel === SecureRecordChannel.CONTROL && sender === SecureRecordSender.HOST) return this.hostControl;
    if (channel === SecureRecordChannel.CONTROL && sender === SecureRecordSender.DEVICE) return this.deviceControl;
    if (channel === SecureRecordChannel.MEDIA && sender === SecureRecordSender.HOST) return this.hostMedia;
    if (channel === SecureRecordChannel.MEDIA && sender === SecureRecordSender.DEVICE) return this.deviceMedia;
    if (channel === SecureRecordChannel.AUDIO && sender === SecureRecordSender.HOST) return this.hostAudio;
    if (channel === SecureRecordChannel.AUDIO && sender === SecureRecordSender.DEVICE) return this.deviceAudio;
    if (channel === SecureRecordChannel.BULK && sender === SecureRecordSender.HOST) return this.hostBulk;
    if (channel === SecureRecordChannel.BULK && sender === SecureRecordSender.DEVICE) return this.deviceBulk;
    throw new Error('Invalid secure-record key selector');
  }

  material(): Uint8Array {
    return concat([this.hostControl, this.deviceControl, this.hostMedia, this.deviceMedia,
      this.hostAudio, this.deviceAudio, this.hostBulk, this.deviceBulk]);
  }

  legacyMaterial(): Uint8Array { return concat([this.hostControl, this.deviceControl, this.hostMedia, this.deviceMedia]); }

  close(): void {
    [this.hostControl, this.deviceControl, this.hostMedia, this.deviceMedia,
      this.hostAudio, this.deviceAudio, this.hostBulk, this.deviceBulk].forEach((key: Uint8Array) => key.fill(0));
  }
}

export class TrafficKeyDerivation {
  static initial(crypto: ChannelRecordCrypto, sharedSecret: Uint8Array, bootstrapSecret: Uint8Array, context: Uint8Array): SessionTrafficKeys {
    if (sharedSecret.length === 0 || bootstrapSecret.length !== 32 || context.length !== 32) {
      throw new Error('Initial key derivation requires a shared secret, 32-byte bootstrap secret, and 32-byte transcript context');
    }
    const material: Uint8Array = crypto.hkdfSha256(sharedSecret, bootstrapSecret, context, MATERIAL_BYTES);
    try { return TrafficKeyDerivation.split(crypto, material, context, 1n); }
    finally { material.fill(0); }
  }

  static rotate(crypto: ChannelRecordCrypto, current: SessionTrafficKeys, nextEpoch: bigint, updateNonce: Uint8Array): SessionTrafficKeys {
    if (current.keyEpoch <= 0n || nextEpoch !== current.keyEpoch + 1n || current.keyId.length === 0 || updateNonce.length < 16) {
      throw new Error('Traffic-key rotation must advance exactly one epoch and use at least 16 nonce bytes');
    }
    const context: Uint8Array = securityTranscript(crypto, ROTATION_DOMAIN, [
      encodeUtf8(current.keyId), uint64(current.keyEpoch), uint64(nextEpoch), updateNonce
    ]);
    const legacyMaterial: Uint8Array = current.legacyMaterial();
    const material: Uint8Array = crypto.hkdfSha256(legacyMaterial, updateNonce, context, MATERIAL_BYTES);
    try { return TrafficKeyDerivation.split(crypto, material, context, nextEpoch); }
    finally { context.fill(0); legacyMaterial.fill(0); material.fill(0); }
  }

  private static split(crypto: ChannelRecordCrypto, material: Uint8Array, context: Uint8Array, keyEpoch: bigint): SessionTrafficKeys {
    if (material.length !== MATERIAL_BYTES) throw new Error('Invalid traffic key material length');
    const legacyMaterial: Uint8Array = material.slice(0, LEGACY_MATERIAL_BYTES);
    const firstDigest: Uint8Array = crypto.sha256(concat([context, legacyMaterial]));
    const keyId: string = hex(crypto.sha256(firstDigest));
    firstDigest.fill(0); legacyMaterial.fill(0);
    return new SessionTrafficKeys(keyId, keyEpoch, material.slice(0, 32), material.slice(32, 64),
      material.slice(64, 96), material.slice(96, 128), material.slice(128, 160), material.slice(160, 192),
      material.slice(192, 224), material.slice(224, 256));
  }
}

export interface ChannelRecordSessionOptions {
  sessionId: string;
  sessionEpoch: bigint;
  localRole: SecureRecordSender;
  initialKeys: SessionTrafficKeys;
  crypto: ChannelRecordCrypto;
  reserveNonce: (channel: SecureRecordChannel, sender: SecureRecordSender, keyEpoch: bigint) => Uint8Array;
  withActiveSessionEpoch?: (sessionEpoch: bigint, operation: () => Uint8Array | undefined) => Uint8Array | undefined;
  rotateKeys?: (current: SessionTrafficKeys, updateNonce: Uint8Array) => SessionTrafficKeys;
}

export class ChannelRecordSession {
  static readonly recordOverhead: number = RECORD_HEADER_BYTES + GCM_TAG_BYTES;
  readonly sessionEpoch: bigint;
  private sessionIdHash: Uint8Array;
  private keys: SessionTrafficKeys | undefined;
  private replay: Map<SecureRecordChannel, ReplayWindow> = new Map();
  private readonly withActiveSessionEpoch: (sessionEpoch: bigint, operation: () => Uint8Array | undefined) => Uint8Array | undefined;
  private readonly rotateKeys: (current: SessionTrafficKeys, updateNonce: Uint8Array) => SessionTrafficKeys;

  constructor(private options: ChannelRecordSessionOptions) {
    if (options.sessionId.length === 0) throw new Error('Session ID must not be blank');
    if (options.sessionEpoch <= 0n || options.initialKeys.keyEpoch <= 0n) throw new Error('Session and key epochs must be positive');
    if (!isSender(options.localRole)) throw new Error('Invalid local secure-record sender');
    this.sessionEpoch = options.sessionEpoch;
    this.keys = options.initialKeys;
    this.sessionIdHash = options.crypto.sha256(encodeUtf8(options.sessionId)).slice(0, SESSION_ID_HASH_BYTES);
    this.withActiveSessionEpoch = options.withActiveSessionEpoch ?? ((_epoch, operation) => operation());
    this.rotateKeys = options.rotateKeys ?? ((current: SessionTrafficKeys, updateNonce: Uint8Array) =>
      TrafficKeyDerivation.rotate(options.crypto, current, current.keyEpoch + 1n, updateNonce));
  }

  seal(channel: SecureRecordChannel, payload: Uint8Array): Uint8Array {
    const keys: SessionTrafficKeys | undefined = this.keys;
    if (keys === undefined) throw new Error('Session packet cipher is closed');
    if (!isRecordChannel(channel)) throw new Error('Invalid secure-record channel');
    const sealed: Uint8Array | undefined = this.withActiveSessionEpoch(this.sessionEpoch, () => {
      const nonceValue: Uint8Array = this.options.reserveNonce(channel, this.options.localRole, keys.keyEpoch);
      if (nonceValue.length !== NONCE_BYTES || uint32(nonceValue, 0) !== channel || uint64From(nonceValue, 4) <= 0n) {
        throw new Error('Durable nonce allocator returned an invalid nonce');
      }
      const header: Uint8Array = this.header(keys.keyEpoch, this.options.localRole, channel, nonceValue);
      return concat([header, this.options.crypto.sealAes256Gcm(keys.key(channel, this.options.localRole), nonceValue, payload, header)]);
    });
    if (sealed === undefined) throw new Error('Active session seal returned no record');
    return sealed;
  }

  open(channel: SecureRecordChannel, record: Uint8Array): Uint8Array | undefined {
    const keys: SessionTrafficKeys | undefined = this.keys;
    if (!isRecordChannel(channel)) return undefined;
    if (keys === undefined || record.length < RECORD_HEADER_BYTES + GCM_TAG_BYTES) return undefined;
    try {
      return this.withActiveSessionEpoch(this.sessionEpoch, () => {
        const headerBytes: Uint8Array = record.slice(0, RECORD_HEADER_BYTES);
        const header: DecodedHeader | undefined = this.decodeHeader(headerBytes);
        if (header === undefined || !equals(header.sessionHash, this.sessionIdHash) || header.sessionEpoch !== this.sessionEpoch ||
          header.keyEpoch !== keys.keyEpoch || header.sender !== remote(this.options.localRole) || header.channel !== channel ||
          uint32(header.nonce, 0) !== channel) return undefined;
        const sequence: bigint = uint64From(header.nonce, 4);
        const window: ReplayWindow = this.replay.get(channel) ?? new ReplayWindow(channel === SecureRecordChannel.CONTROL || channel === SecureRecordChannel.BULK);
        if (!window.canAccept(sequence)) return undefined;
        const plaintext: Uint8Array = this.options.crypto.openAes256Gcm(keys.key(channel, header.sender),
          header.nonce, record.slice(RECORD_HEADER_BYTES), headerBytes);
        window.commit(sequence); this.replay.set(channel, window);
        return plaintext;
      });
    } catch (_error) { return undefined; }
  }

  openDeclaredChannel(record: Uint8Array): Uint8Array | undefined {
    const channel: SecureRecordChannel | undefined = ChannelRecordSession.declaredChannel(record);
    return channel === undefined ? undefined : this.open(channel, record);
  }

  rotateTrafficKeys(updateNonce: Uint8Array): void {
    const current: SessionTrafficKeys | undefined = this.keys;
    if (current === undefined) throw new Error('Session packet cipher is closed');
    const replacement: SessionTrafficKeys = this.rotateKeys(current, updateNonce);
    this.keys = replacement; this.replay.clear(); current.close();
  }

  close(): void {
    this.keys?.close(); this.keys = undefined; this.replay.clear(); this.sessionIdHash.fill(0);
  }

  static declaredChannel(record: Uint8Array): SecureRecordChannel | undefined {
    if (record.length < RECORD_HEADER_BYTES + GCM_TAG_BYTES || uint32(record, 0) !== RECORD_MAGIC || record[4] !== RECORD_VERSION) return undefined;
    const channel: number = record[38];
    return isRecordChannel(channel) ? channel : undefined;
  }

  private header(keyEpoch: bigint, sender: SecureRecordSender, channel: SecureRecordChannel, nonceValue: Uint8Array): Uint8Array {
    const header: Uint8Array = new Uint8Array(RECORD_HEADER_BYTES);
    writeUint32(header, 0, RECORD_MAGIC); header[4] = RECORD_VERSION; header.set(this.sessionIdHash, 5);
    writeUint64(header, 21, this.sessionEpoch); writeUint64(header, 29, keyEpoch); header[37] = sender; header[38] = channel; header.set(nonceValue, 39);
    return header;
  }

  private decodeHeader(header: Uint8Array): DecodedHeader | undefined {
    if (header.length !== RECORD_HEADER_BYTES || uint32(header, 0) !== RECORD_MAGIC || header[4] !== RECORD_VERSION ||
      !isSender(header[37]) || !isRecordChannel(header[38])) return undefined;
    return { sessionHash: header.slice(5, 21), sessionEpoch: uint64From(header, 21), keyEpoch: uint64From(header, 29),
      sender: header[37], channel: header[38], nonce: header.slice(39, 51) };
  }
}

export class InMemoryNonceStore {
  private counters: Map<string, bigint> = new Map();

  reserve(channel: SecureRecordChannel, sender: SecureRecordSender, keyEpoch: bigint): Uint8Array {
    if (!isRecordChannel(channel) || !isSender(sender) || keyEpoch <= 0n) throw new Error('LAN secure record nonce inputs must be valid');
    const key: string = String(channel) + ':' + String(sender) + ':' + keyEpoch.toString();
    const next: bigint = (this.counters.get(key) ?? 0n) + 1n;
    this.counters.set(key, next);
    return nonce(channel, next);
  }
}

export function trustedLanSessionIdentifier(crypto: ChannelRecordCrypto, hostPublicKey: Uint8Array, devicePublicKey: Uint8Array): string {
  return hex(crypto.sha256(concat([encodeUtf8('vibescreen/trusted-lan-session/v1'), hostPublicKey, devicePublicKey])));
}

export function trustedLanTranscriptContext(crypto: ChannelRecordCrypto, sessionIdentifier: string, hostPublicKey: Uint8Array,
  devicePublicKey: Uint8Array): Uint8Array {
  return securityTranscript(crypto, 'vibescreen/trusted-lan-records/v1', [encodeUtf8(sessionIdentifier), hostPublicKey, devicePublicKey]);
}

export function nonce(channel: SecureRecordChannel, sequence: bigint): Uint8Array {
  const value: Uint8Array = new Uint8Array(NONCE_BYTES);
  writeUint32(value, 0, channel); writeUint64(value, 4, sequence); return value;
}

export function hex(value: Uint8Array): string { return [...value].map((byte: number) => byte.toString(16).padStart(2, '0')).join(''); }

function securityTranscript(crypto: ChannelRecordCrypto, domain: string, parts: Uint8Array[]): Uint8Array {
  return crypto.sha256(concat([lengthPrefix(encodeUtf8(IDENTITY_DOMAIN)), lengthPrefix(encodeUtf8(domain)),
    ...parts.map((part: Uint8Array) => lengthPrefix(part))]));
}

function lengthPrefix(value: Uint8Array): Uint8Array { return concat([uint64(value.length), value]); }
function uint64(value: number | bigint): Uint8Array { const result: Uint8Array = new Uint8Array(8); writeUint64(result, 0, BigInt(value)); return result; }
function uint32(value: Uint8Array, offset: number): number { return ((value[offset] << 24) | (value[offset + 1] << 16) | (value[offset + 2] << 8) | value[offset + 3]) >>> 0; }
function uint64From(value: Uint8Array, offset: number): bigint {
  let result: bigint = 0n;
  for (let index: number = 0; index < 8; index += 1) result = (result << 8n) | BigInt(value[offset + index]);
  return result;
}
function writeUint32(value: Uint8Array, offset: number, input: number): void {
  value[offset] = (input >>> 24) & 0xff; value[offset + 1] = (input >>> 16) & 0xff;
  value[offset + 2] = (input >>> 8) & 0xff; value[offset + 3] = input & 0xff;
}
function writeUint64(value: Uint8Array, offset: number, input: bigint): void {
  if (input < 0n || input > 0xffffffffffffffffn) throw new Error('Invalid uint64');
  let remaining: bigint = input;
  for (let index: number = 7; index >= 0; index -= 1) { value[offset + index] = Number(remaining & 0xffn); remaining >>= 8n; }
}
function concat(values: Uint8Array[]): Uint8Array {
  const result: Uint8Array = new Uint8Array(values.reduce((sum: number, value: Uint8Array) => sum + value.length, 0));
  let offset: number = 0; values.forEach((value: Uint8Array) => { result.set(value, offset); offset += value.length; }); return result;
}
function equals(left: Uint8Array, right: Uint8Array): boolean {
  let difference: number = left.length ^ right.length;
  const length: number = Math.max(left.length, right.length);
  for (let index: number = 0; index < length; index += 1) difference |= (left[index] ?? 0) ^ (right[index] ?? 0);
  return difference === 0;
}
function hasPrefix(value: Uint8Array, prefix: number[]): boolean { return prefix.every((byte: number, index: number) => value[index] === byte); }
function isRecordChannel(value: number): value is SecureRecordChannel { return value >= SecureRecordChannel.CONTROL && value <= SecureRecordChannel.BULK; }
function isSender(value: number): value is SecureRecordSender { return value === SecureRecordSender.HOST || value === SecureRecordSender.DEVICE; }
function remote(value: SecureRecordSender): SecureRecordSender { return value === SecureRecordSender.HOST ? SecureRecordSender.DEVICE : SecureRecordSender.HOST; }

interface DecodedHeader {
  sessionHash: Uint8Array;
  sessionEpoch: bigint;
  keyEpoch: bigint;
  sender: SecureRecordSender;
  channel: SecureRecordChannel;
  nonce: Uint8Array;
}

class ReplayWindow {
  private highest: bigint = 0n;
  private bitmap: bigint = 0n;

  constructor(private strictlyOrdered: boolean) {}

  canAccept(sequence: bigint): boolean {
    if (sequence <= 0n) return false;
    if (this.strictlyOrdered) return sequence > this.highest;
    if (sequence > this.highest) return true;
    const distance: bigint = this.highest - sequence;
    return distance < 64n && (this.bitmap & (1n << distance)) === 0n;
  }

  commit(sequence: bigint): void {
    if (!this.canAccept(sequence)) throw new Error('Replay sequence was committed twice');
    if (sequence > this.highest) {
      const shift: bigint = sequence - this.highest;
      this.bitmap = shift >= 64n ? 1n : (this.bitmap << shift) | 1n;
      this.highest = sequence;
    } else {
      this.bitmap |= 1n << (this.highest - sequence);
    }
  }
}
