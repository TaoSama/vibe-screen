import { AeadAlgorithm, DeviceIdentity, KeyAgreementAlgorithm, PairingOffer, PairingRequest, PairingResult,
  SignatureAlgorithm } from '../protocol/ProtocolModels';
import { encodeUtf8 } from '../protocol/Utf8';

const REQUEST_DOMAIN: string = 'vibescreen/pairing-request/v1';
const RESULT_DOMAIN: string = 'vibescreen/pairing-result/v1';
const BOOTSTRAP_DOMAIN: string = 'vibescreen/pairing-bootstrap/v1';
const KEY_DOMAIN: string = 'vibescreen/pairing-session-keys/v1';
const CREDENTIAL_AAD: Uint8Array = utf8('vibescreen/device-credential/v1');
const HEX_PATTERN: RegExp = /^[0-9a-f]{64}$/;
const PAIRING_ID_PATTERN: RegExp = /^[0-9a-f]{32}$/;

export interface PairingEphemeralKey {
  publicKey: Uint8Array;
  derive(peerPublicKey: Uint8Array): Uint8Array;
  destroy(): void;
}

export interface PairingSigningIdentity {
  publicIdentity: DeviceIdentity;
  sign(digest: Uint8Array): Uint8Array;
}

export interface PairingCrypto {
  identity(): PairingSigningIdentity;
  ephemeral(): PairingEphemeralKey;
  sha256(value: Uint8Array): Uint8Array;
  hmacSha256(key: Uint8Array, value: Uint8Array): Uint8Array;
  hkdfSha256(secret: Uint8Array, salt: Uint8Array, info: Uint8Array, length: number): Uint8Array;
  verify(publicKey: Uint8Array, digest: Uint8Array, signature: Uint8Array): boolean;
  openAes256Gcm(key: Uint8Array, nonce: Uint8Array, ciphertext: Uint8Array, aad: Uint8Array): Uint8Array;
}

export interface PairingCompletion {
  credential: Uint8Array;
  deviceId: string;
  hostIdentity: DeviceIdentity;
  sessionKeyId: string;
  sessionKeyEpoch: bigint;
}

export class PendingPairing {
  private consumed: boolean = false;

  constructor(private offer: PairingOffer, readonly request: PairingRequest, private ephemeralKey: PairingEphemeralKey,
    private crypto: PairingCrypto) {}

  complete(result: PairingResult, nowUnixSeconds: bigint): PairingCompletion {
    if (this.consumed) throw new Error('Pairing offer was already consumed');
    this.consumed = true;
    let shared: Uint8Array | undefined;
    let keyMaterial: Uint8Array | undefined;
    try {
      if (nowUnixSeconds < 0n || nowUnixSeconds >= this.offer.expiresAtUnixSeconds || !result.accepted ||
        result.rejectionReason.length > 0 || result.deviceId !== this.request.deviceId ||
        result.deviceCredential.length > 0 || result.encryptedDeviceCredential.length < 16 ||
        result.credentialNonce.length !== 12 || result.hostProof.signature.length < 8 || result.hostProof.signature.length > 80 ||
        !HEX_PATTERN.test(result.sessionKeyId) || result.sessionKeyEpoch !== 1n) {
        throw new Error('Invalid PairingResult');
      }
      requireEqual(result.hostProof.challenge, this.offer.challenge, 'PairingResult challenge mismatch');
      requireEqual(result.hostProof.ephemeralPublicKey, this.offer.ephemeralPublicKey, 'PairingResult ephemeral key mismatch');
      const parts: Uint8Array[] = requestParts(this.offer, this.request);
      const resultDigest: Uint8Array = transcript(this.crypto, RESULT_DOMAIN, [...parts,
        result.encryptedDeviceCredential, result.credentialNonce, utf8(result.sessionKeyId), uint64(result.sessionKeyEpoch)]);
      if (!this.crypto.verify(this.offer.hostIdentity.signingPublicKey, resultDigest, result.hostProof.signature)) {
        throw new Error('Invalid PairingResult host proof');
      }
      shared = this.ephemeralKey.derive(this.offer.ephemeralPublicKey);
      const keyInfo: Uint8Array = transcript(this.crypto, KEY_DOMAIN, parts);
      keyMaterial = this.crypto.hkdfSha256(shared, this.offer.oneTimeCredential, keyInfo, 128);
      if (keyMaterial.length !== 128) throw new Error('Invalid derived session key material');
      const keyDigest: Uint8Array = this.crypto.sha256(concat([keyInfo, keyMaterial]));
      const derivedSessionKeyId: string = hex(this.crypto.sha256(keyDigest));
      if (result.sessionKeyId !== derivedSessionKeyId) throw new Error('PairingResult session key mismatch');
      const credentialKey: Uint8Array = keyMaterial.slice(0, 32);
      let credential: Uint8Array;
      try {
        credential = this.crypto.openAes256Gcm(credentialKey, result.credentialNonce,
          result.encryptedDeviceCredential, CREDENTIAL_AAD);
      } finally {
        credentialKey.fill(0);
      }
      if (credential.length !== 32) throw new Error('Invalid decrypted device credential');
      return { credential, deviceId: this.request.deviceId, hostIdentity: cloneIdentity(this.offer.hostIdentity), sessionKeyId: result.sessionKeyId,
        sessionKeyEpoch: result.sessionKeyEpoch };
    } finally {
      shared?.fill(0); keyMaterial?.fill(0);
      this.ephemeralKey.destroy();
      this.offer.oneTimeCredential.fill(0);
    }
  }

  cancel(): void {
    if (this.consumed) return;
    this.consumed = true; this.ephemeralKey.destroy(); this.offer.oneTimeCredential.fill(0);
  }
}

export class PairingClient {
  constructor(private crypto: PairingCrypto) {}

  begin(offerValue: PairingOffer, deviceName: string, nowUnixSeconds: bigint): PendingPairing {
    const offer: PairingOffer = cloneOffer(offerValue); validateOffer(this.crypto, offer, nowUnixSeconds);
    if (utf8(deviceName).length < 1 || utf8(deviceName).length > 256) throw new Error('Invalid device name');
    const signing: PairingSigningIdentity = this.crypto.identity(); validateIdentity(this.crypto, signing.publicIdentity);
    const ephemeral: PairingEphemeralKey = this.crypto.ephemeral();
    try {
      if (ephemeral.publicKey.length !== 65) throw new Error('Invalid device ephemeral key');
      const request: PairingRequest = { offerId: offer.offerId.slice(), deviceId: signing.publicIdentity.deviceId,
        deviceName, devicePublicKey: signing.publicIdentity.signingPublicKey.slice(),
        deviceIdentity: cloneIdentity(signing.publicIdentity), proof: { challenge: offer.challenge.slice(),
          ephemeralPublicKey: ephemeral.publicKey.slice(), signature: new Uint8Array() }, bootstrapMac: new Uint8Array() };
      const parts: Uint8Array[] = requestParts(offer, request);
      request.proof.signature = signing.sign(transcript(this.crypto, REQUEST_DOMAIN, parts));
      if (request.proof.signature.length < 8 || request.proof.signature.length > 80) throw new Error('Invalid request signature');
      request.bootstrapMac = this.crypto.hmacSha256(offer.oneTimeCredential,
        transcript(this.crypto, BOOTSTRAP_DOMAIN, [...parts, request.proof.signature]));
      if (request.bootstrapMac.length !== 32) throw new Error('Invalid bootstrap MAC');
      return new PendingPairing(offer, request, ephemeral, this.crypto);
    } catch (error) {
      ephemeral.destroy(); offer.oneTimeCredential.fill(0); throw error;
    }
  }
}

export interface StoredCredential {
  version: number;
  pairingId: string;
  deviceId: string;
  hostIdentity: DeviceIdentity;
  credential: Uint8Array;
  sessionKeyId: string;
  sessionKeyEpoch: bigint;
  highestControlSequence: bigint;
  revoked: boolean;
  revocationReason: string;
}

export interface CredentialStore {
  load(): Promise<StoredCredential | undefined>;
  save(record: StoredCredential): Promise<void>;
}

export type StoredIdentityVerifier = (identity: DeviceIdentity) => boolean;

export class CredentialLifecycle {
  private generation: bigint = 1n;
  private record: StoredCredential | undefined;
  private admissionClosed: boolean = true;
  private operationTail: Promise<void> = Promise.resolve();

  constructor(private store: CredentialStore, private storedIdentityVerifier?: StoredIdentityVerifier) {}

  owner(): bigint { return this.generation; }

  supersede(): bigint { this.generation += 1n; this.admissionClosed = true; return this.generation; }

  async restore(): Promise<void> {
    const owner: bigint = this.supersede();
    await this.serialized(async () => {
      const restored: StoredCredential | undefined = await this.store.load();
      if (restored !== undefined) validateStoredCredential(restored);
      if (restored !== undefined && !restored.revoked &&
        (this.storedIdentityVerifier === undefined || !this.storedIdentityVerifier(restored.hostIdentity))) {
        throw new Error('Stored host identity cannot be verified');
      }
      if (owner !== this.generation) {
        this.record = undefined; this.admissionClosed = true; return;
      }
      this.record = restored === undefined ? undefined : cloneRecord(restored);
      this.admissionClosed = restored === undefined || restored.revoked;
    });
  }

  async install(owner: bigint, pairingId: string, completion: PairingCompletion): Promise<void> {
    if (owner !== this.generation) { completion.credential.fill(0); throw new Error('Stale pairing completion'); }
    const installationOwner: bigint = this.supersede();
    try {
      await this.serialized(async () => {
        if (installationOwner !== this.generation || !PAIRING_ID_PATTERN.test(pairingId)) {
          throw new Error('Stale pairing completion');
        }
        const next: StoredCredential = { version: 1, pairingId, deviceId: completion.deviceId,
          hostIdentity: cloneIdentity(completion.hostIdentity), credential: completion.credential.slice(),
          sessionKeyId: completion.sessionKeyId, sessionKeyEpoch: completion.sessionKeyEpoch,
          highestControlSequence: 0n, revoked: false, revocationReason: '' };
        validateStoredCredential(next); await this.store.save(next);
        if (installationOwner !== this.generation) {
          const tombstone: StoredCredential = { ...next, credential: new Uint8Array(), revoked: true,
            revocationReason: 'superseded_pairing_completion' };
          await this.store.save(tombstone); this.record = cloneRecord(tombstone);
          throw new Error('Pairing completion was superseded');
        }
        this.record = cloneRecord(next); this.admissionClosed = false;
      });
    } finally {
      completion.credential.fill(0);
    }
  }

  authorize(): StoredCredential {
    if (this.admissionClosed || this.record === undefined || this.record.revoked) {
      throw new Error('No authorized pairing credential');
    }
    return cloneRecord(this.record);
  }

  async acceptAuthenticatedControlSequence(sequence: bigint): Promise<void> {
    const owner: bigint = this.generation;
    await this.serialized(async () => {
      if (owner !== this.generation) throw new Error('Credential lifecycle was superseded');
      const current: StoredCredential = this.authorize();
      if (sequence <= current.highestControlSequence) throw new Error('Replayed control record');
      const next: StoredCredential = { ...current, highestControlSequence: sequence };
      await this.store.save(next);
      if (owner !== this.generation) throw new Error('Credential lifecycle was superseded');
      this.record = cloneRecord(next);
    });
  }

  async revoke(deviceId: string, reason: string): Promise<void> {
    const current: StoredCredential = this.authorize();
    if (deviceId !== current.deviceId || reason.length === 0) throw new Error('Invalid revocation');
    this.supersede();
    const tombstone: StoredCredential = { ...current, credential: new Uint8Array(), revoked: true, revocationReason: reason };
    await this.serialized(async () => { await this.store.save(tombstone); this.record = cloneRecord(tombstone); });
  }

  private async serialized<T>(operation: () => Promise<T>): Promise<T> {
    const predecessor: Promise<void> = this.operationTail;
    let release: () => void = () => {};
    this.operationTail = new Promise<void>((resolve: () => void) => { release = resolve; });
    await predecessor;
    try { return await operation(); }
    finally { release(); }
  }
}

function validateOffer(crypto: PairingCrypto, offer: PairingOffer, now: bigint): void {
  if (offer.offerId.length !== 16 || offer.oneTimeCredential.length !== 32 || offer.challenge.length !== 32 ||
    offer.expiresAtUnixSeconds <= now || offer.hostPublicKey.length !== 65 || offer.ephemeralPublicKey.length !== 65 ||
    offer.signatureAlgorithms.length !== 1 || offer.signatureAlgorithms[0] !== SignatureAlgorithm.ECDSA_P256_SHA256 ||
    offer.keyAgreementAlgorithms.length !== 1 || offer.keyAgreementAlgorithms[0] !== KeyAgreementAlgorithm.ECDH_P256 ||
    offer.aeadAlgorithms.length !== 1 || offer.aeadAlgorithms[0] !== AeadAlgorithm.AES_256_GCM) {
    throw new Error('Invalid or expired PairingOffer');
  }
  validateIdentity(crypto, offer.hostIdentity);
  requireEqual(offer.hostPublicKey, offer.hostIdentity.signingPublicKey, 'Host public key mismatch');
}

function validateIdentity(crypto: PairingCrypto, identity: DeviceIdentity): void {
  if (identity.deviceId.length === 0 || !HEX_PATTERN.test(identity.keyId) || identity.keyEpoch <= 0n ||
    identity.signatureAlgorithm !== SignatureAlgorithm.ECDSA_P256_SHA256 || identity.signingPublicKey.length !== 65 ||
    hex(crypto.sha256(identity.signingPublicKey)) !== identity.keyId) throw new Error('Invalid device identity');
}

function requestParts(offer: PairingOffer, request: PairingRequest): Uint8Array[] {
  return [offer.offerId, offer.challenge, offer.hostIdentity.signingPublicKey, offer.ephemeralPublicKey,
    request.deviceIdentity.signingPublicKey, request.proof.ephemeralPublicKey, utf8(request.deviceIdentity.deviceId),
    uint64(request.deviceIdentity.keyEpoch)];
}

function transcript(crypto: PairingCrypto, domain: string, parts: Uint8Array[]): Uint8Array {
  return crypto.sha256(concat([lengthPrefix(utf8('vibescreen/identity/v1')), lengthPrefix(utf8(domain)),
    ...parts.map((part: Uint8Array) => lengthPrefix(part))]));
}

function lengthPrefix(value: Uint8Array): Uint8Array { return concat([uint64(BigInt(value.length)), value]); }
function uint64(value: bigint): Uint8Array {
  if (value < 0n || value > 0xffffffffffffffffn) throw new Error('Invalid uint64');
  const result: Uint8Array = new Uint8Array(8); let remaining: bigint = value;
  for (let index: number = 7; index >= 0; index -= 1) { result[index] = Number(remaining & 0xffn); remaining >>= 8n; }
  return result;
}
function utf8(value: string): Uint8Array { return encodeUtf8(value); }
function concat(values: Uint8Array[]): Uint8Array {
  const result: Uint8Array = new Uint8Array(values.reduce((sum: number, value: Uint8Array) => sum + value.length, 0));
  let offset: number = 0; values.forEach((value: Uint8Array) => { result.set(value, offset); offset += value.length; }); return result;
}
function hex(value: Uint8Array): string { return [...value].map((byte: number) => byte.toString(16).padStart(2, '0')).join(''); }
function requireEqual(left: Uint8Array, right: Uint8Array, message: string): void {
  let difference: number = left.length ^ right.length;
  const length: number = Math.max(left.length, right.length);
  for (let index: number = 0; index < length; index += 1) difference |= (left[index] ?? 0) ^ (right[index] ?? 0);
  if (difference !== 0) throw new Error(message);
}
function cloneIdentity(value: DeviceIdentity): DeviceIdentity { return { ...value, signingPublicKey: value.signingPublicKey.slice() }; }
function cloneOffer(value: PairingOffer): PairingOffer { return { ...value, offerId: value.offerId.slice(),
  oneTimeCredential: value.oneTimeCredential.slice(), hostPublicKey: value.hostPublicKey.slice(),
  hostIdentity: cloneIdentity(value.hostIdentity), challenge: value.challenge.slice(), ephemeralPublicKey: value.ephemeralPublicKey.slice(),
  signatureAlgorithms: [...value.signatureAlgorithms], keyAgreementAlgorithms: [...value.keyAgreementAlgorithms],
  aeadAlgorithms: [...value.aeadAlgorithms] }; }
function cloneRecord(value: StoredCredential): StoredCredential { return { ...value, hostIdentity: cloneIdentity(value.hostIdentity),
  credential: value.credential.slice() }; }
function validateStoredCredential(value: StoredCredential): void {
  if (value.version !== 1 || !PAIRING_ID_PATTERN.test(value.pairingId) || value.deviceId.length === 0 ||
    value.hostIdentity.deviceId.length === 0 || !HEX_PATTERN.test(value.hostIdentity.keyId) ||
    value.hostIdentity.keyEpoch <= 0n || value.hostIdentity.signatureAlgorithm !== SignatureAlgorithm.ECDSA_P256_SHA256 ||
    value.hostIdentity.signingPublicKey.length !== 65 ||
    !HEX_PATTERN.test(value.sessionKeyId) || value.sessionKeyEpoch <= 0n || value.highestControlSequence < 0n ||
    (value.revoked ? value.credential.length !== 0 || value.revocationReason.length === 0 : value.credential.length !== 32)) {
    throw new Error('Invalid stored pairing credential');
  }
}
