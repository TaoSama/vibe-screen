import test from 'node:test';
import assert from 'node:assert/strict';
import { createCipheriv, createDecipheriv, createHash, createHmac } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { ChannelRecordSession, InMemoryNonceStore, LanSecureRecordNegotiation, SecureRecordChannel,
  SecureRecordSender, TrafficKeyDerivation, hex, nonce, trustedLanSessionIdentifier,
  trustedLanTranscriptContext } from '../.test-dist/security/ChannelRecordSecurity.js';

const fixture = JSON.parse(readFileSync('../../contracts/fixtures/security/v1/channel-records.json', 'utf8'));

const nodeCrypto = {
  sha256: (value) => new Uint8Array(createHash('sha256').update(value).digest()),
  hmacSha256: (key, value) => new Uint8Array(createHmac('sha256', key).update(value).digest()),
  hkdfSha256: (input, salt, info, length) => hkdfSha256(input, salt, info, length),
  sealAes256Gcm: (key, iv, plaintext, authenticatedHeader) => {
    const cipher = createCipheriv('aes-256-gcm', key, iv, { authTagLength: 16 });
    cipher.setAAD(authenticatedHeader);
    return new Uint8Array(Buffer.concat([cipher.update(plaintext), cipher.final(), cipher.getAuthTag()]));
  },
  openAes256Gcm: (key, iv, ciphertextAndTag, authenticatedHeader) => {
    if (ciphertextAndTag.length < 16) throw new Error('missing_tag');
    const decipher = createDecipheriv('aes-256-gcm', key, iv, { authTagLength: 16 });
    decipher.setAAD(authenticatedHeader);
    decipher.setAuthTag(ciphertextAndTag.slice(ciphertextAndTag.length - 16));
    return new Uint8Array(Buffer.concat([decipher.update(ciphertextAndTag.slice(0, -16)), decipher.final()]));
  }
};

test('Harmony channel record fixture matches the Host and Android AES-256-GCM contract', () => {
  const initial = deriveFixtureKeys();
  assert.equal(initial.keyId, fixture.initial.key_id);
  assert.equal(hex(initial.material()), fixture.initial.keys);
  assert.equal(new Set(keySlices(initial).map(hex)).size, 8);

  const rotated = TrafficKeyDerivation.rotate(nodeCrypto, initial, 2n, bytes(fixture.input.rotation_nonce));
  assert.equal(rotated.keyId, fixture.rotated.key_id);
  assert.equal(hex(rotated.material()), fixture.rotated.keys);
  assert.equal(new Set(keySlices(rotated).map(hex)).size, 8);

  const host = fixtureSession(SecureRecordSender.HOST, deriveFixtureKeys());
  const device = fixtureSession(SecureRecordSender.DEVICE, deriveFixtureKeys());
  for (const item of [
    { name: 'host_control', channel: SecureRecordChannel.CONTROL, sender: host, receiver: device },
    { name: 'device_media', channel: SecureRecordChannel.MEDIA, sender: device, receiver: host },
    { name: 'host_audio', channel: SecureRecordChannel.AUDIO, sender: host, receiver: device },
    { name: 'device_bulk', channel: SecureRecordChannel.BULK, sender: device, receiver: host }
  ]) {
    const record = fixture.records[item.name];
    assert.equal(hex(item.sender.seal(item.channel, bytes(record.payload))), record.record);
    assert.deepEqual(item.receiver.open(item.channel, bytes(record.record)), bytes(record.payload));
  }
});

test('replay, relabel, wrong key, stale epoch, and tamper fail closed', () => {
  const host = fixtureSession(SecureRecordSender.HOST, deriveFixtureKeys());
  const device = fixtureSession(SecureRecordSender.DEVICE, deriveFixtureKeys());
  const wrongKeyDevice = fixtureSession(SecureRecordSender.DEVICE, TrafficKeyDerivation.initial(
    nodeCrypto, new Uint8Array(32).fill(8), new Uint8Array(32).fill(8), new Uint8Array(32).fill(8)));
  const staleEpochDevice = new ChannelRecordSession({ sessionId: fixture.session.id, sessionEpoch: 8n,
    localRole: SecureRecordSender.DEVICE, initialKeys: deriveFixtureKeys(), crypto: nodeCrypto,
    reserveNonce: new InMemoryNonceStore().reserve.bind(new InMemoryNonceStore()) });
  const record = host.seal(SecureRecordChannel.MEDIA, new Uint8Array([7]));
  const tampered = record.slice();
  tampered[tampered.length - 1] ^= 1;

  assert.deepEqual(device.open(SecureRecordChannel.MEDIA, record), new Uint8Array([7]));
  assert.equal(device.open(SecureRecordChannel.MEDIA, record), undefined);
  assert.equal(device.open(SecureRecordChannel.CONTROL, record), undefined);
  assert.equal(wrongKeyDevice.open(SecureRecordChannel.MEDIA, record), undefined);
  assert.equal(staleEpochDevice.open(SecureRecordChannel.MEDIA, record), undefined);
  assert.equal(fixtureSession(SecureRecordSender.DEVICE, deriveFixtureKeys()).open(SecureRecordChannel.MEDIA, tampered), undefined);
});

test('nonce reuse with a different payload fails closed after the first record', () => {
  const host = fixtureSession(SecureRecordSender.HOST, deriveFixtureKeys());
  const device = fixtureSession(SecureRecordSender.DEVICE, deriveFixtureKeys());
  const first = host.seal(SecureRecordChannel.CONTROL, new Uint8Array([1]));
  const reusedNonce = host.seal(SecureRecordChannel.CONTROL, new Uint8Array([2]));

  assert.notEqual(hex(first), hex(reusedNonce));
  assert.deepEqual(device.open(SecureRecordChannel.CONTROL, first), new Uint8Array([1]));
  assert.equal(device.open(SecureRecordChannel.CONTROL, reusedNonce), undefined);
});

test('nonce validation fails before sealing and closed sessions reject use', () => {
  for (const invalidNonce of [new Uint8Array([0, 0, 0, 3]), nonce(SecureRecordChannel.BULK, 1n), nonce(SecureRecordChannel.AUDIO, 0n)]) {
    const session = new ChannelRecordSession({ sessionId: 'nonce-test', sessionEpoch: 1n, localRole: SecureRecordSender.HOST,
      initialKeys: TrafficKeyDerivation.initial(nodeCrypto, new Uint8Array(32).fill(3), new Uint8Array(32).fill(3), new Uint8Array(32).fill(3)),
      crypto: nodeCrypto, reserveNonce: () => invalidNonce });
    assert.throws(() => session.seal(SecureRecordChannel.AUDIO, new Uint8Array([1])), /invalid nonce/);
  }

  const session = fixtureSession(SecureRecordSender.HOST, deriveFixtureKeys());
  session.close();
  assert.throws(() => session.seal(SecureRecordChannel.CONTROL, new Uint8Array([1])), /closed/);
  assert.equal(session.open(SecureRecordChannel.MEDIA, bytes(fixture.records.device_media.record)), undefined);
});

test('invalid sender and channel values fail closed at runtime', () => {
  const keys = deriveFixtureKeys();
  assert.throws(() => keys.key(SecureRecordChannel.CONTROL, 9), /Invalid secure-record key selector/);
  assert.throws(() => keys.key(9, SecureRecordSender.DEVICE), /Invalid secure-record key selector/);
  const nonceStore = new InMemoryNonceStore();
  assert.throws(() => nonceStore.reserve(9, SecureRecordSender.DEVICE, 1n), /nonce inputs must be valid/);
  assert.throws(() => nonceStore.reserve(SecureRecordChannel.CONTROL, 9, 1n), /nonce inputs must be valid/);
  assert.throws(() => new ChannelRecordSession({ sessionId: 'invalid-role', sessionEpoch: 1n, localRole: 9,
    initialKeys: keys, crypto: nodeCrypto, reserveNonce: new InMemoryNonceStore().reserve.bind(new InMemoryNonceStore()) }),
  /Invalid local secure-record sender/);

  const host = fixtureSession(SecureRecordSender.HOST, deriveFixtureKeys());
  assert.throws(() => host.seal(9, new Uint8Array([1])), /Invalid secure-record channel/);
  assert.equal(host.open(9, bytes(fixture.records.device_media.record)), undefined);
});

test('active epoch callback prevents stale session use without exposing plaintext', () => {
  let reservations = 0;
  const host = new ChannelRecordSession({ sessionId: fixture.session.id, sessionEpoch: BigInt(fixture.session.epoch),
    localRole: SecureRecordSender.HOST, initialKeys: deriveFixtureKeys(), crypto: nodeCrypto,
    reserveNonce: (channel, sender, keyEpoch) => { reservations += 1; return nonce(channel, BigInt(sender) + keyEpoch); },
    withActiveSessionEpoch: (epoch, operation) => epoch === 10n ? operation() : undefined });
  assert.throws(() => host.seal(SecureRecordChannel.CONTROL, new Uint8Array([1])), /Active session seal returned no record/);
  assert.equal(reservations, 0);

  const device = new ChannelRecordSession({ sessionId: fixture.session.id, sessionEpoch: BigInt(fixture.session.epoch),
    localRole: SecureRecordSender.DEVICE, initialKeys: deriveFixtureKeys(), crypto: nodeCrypto,
    reserveNonce: new InMemoryNonceStore().reserve.bind(new InMemoryNonceStore()),
    withActiveSessionEpoch: () => { throw new Error('stale_epoch'); } });
  assert.equal(device.open(SecureRecordChannel.CONTROL, bytes(fixture.records.host_control.record)), undefined);
});

test('legacy fallback is explicit and rejected by the secure verifier path', () => {
  const publicKey = new Uint8Array(65).fill(4);
  publicKey[0] = 4;
  assert.throws(() => LanSecureRecordNegotiation.encodeResponse(publicKey, false, false), /choose encrypted or explicit legacy/);
  assert.throws(() => LanSecureRecordNegotiation.encodeResponse(publicKey, true, true), /choose encrypted or explicit legacy/);

  const request = LanSecureRecordNegotiation.decodeRequest(LanSecureRecordNegotiation.encodeRequest(publicKey, false));
  assert.equal(request.allowLegacyFallback, false);
  const legacy = LanSecureRecordNegotiation.encodeResponse(publicKey, false, true);
  assert.deepEqual(LanSecureRecordNegotiation.decodeResponse(legacy), { publicKey, encrypted: false, legacy: true });
  assert.throws(() => LanSecureRecordNegotiation.requireEncryptedResponse(legacy), /plaintext fallback/);
});

test('audio accepts bounded reordering while bulk remains strictly ordered', () => {
  const host = counterSession(SecureRecordSender.HOST);
  const device = counterSession(SecureRecordSender.DEVICE);
  const audioOne = host.seal(SecureRecordChannel.AUDIO, new Uint8Array([1]));
  const audioTwo = host.seal(SecureRecordChannel.AUDIO, new Uint8Array([2]));
  const bulkOne = host.seal(SecureRecordChannel.BULK, new Uint8Array([3]));
  const bulkTwo = host.seal(SecureRecordChannel.BULK, new Uint8Array([4]));

  assert.deepEqual(device.open(SecureRecordChannel.AUDIO, audioTwo), new Uint8Array([2]));
  assert.deepEqual(device.open(SecureRecordChannel.AUDIO, audioOne), new Uint8Array([1]));
  assert.equal(device.open(SecureRecordChannel.AUDIO, audioTwo), undefined);
  assert.deepEqual(device.open(SecureRecordChannel.BULK, bulkTwo), new Uint8Array([4]));
  assert.equal(device.open(SecureRecordChannel.BULK, bulkOne), undefined);
});

test('rotation resets replay state and declared-channel dispatch opens rotated records', () => {
  const initialHostKeys = deriveFixtureKeys();
  const initialDeviceKeys = deriveFixtureKeys();
  const oldHostControl = initialHostKeys.hostControl;
  const oldDeviceControl = initialDeviceKeys.deviceControl;
  const host = fixtureSession(SecureRecordSender.HOST, initialHostKeys);
  const device = fixtureSession(SecureRecordSender.DEVICE, initialDeviceKeys);

  const first = host.seal(SecureRecordChannel.CONTROL, new Uint8Array([1]));
  assert.equal(ChannelRecordSession.declaredChannel(first), SecureRecordChannel.CONTROL);
  assert.deepEqual(device.openDeclaredChannel(first), new Uint8Array([1]));
  assert.equal(device.openDeclaredChannel(first), undefined);

  host.rotateTrafficKeys(bytes(fixture.input.rotation_nonce));
  device.rotateTrafficKeys(bytes(fixture.input.rotation_nonce));
  assert(oldHostControl.every((byte) => byte === 0));
  assert(oldDeviceControl.every((byte) => byte === 0));
  assert.equal(device.openDeclaredChannel(first), undefined);

  const rotated = host.seal(SecureRecordChannel.CONTROL, new Uint8Array([2]));
  assert.equal(ChannelRecordSession.declaredChannel(rotated), SecureRecordChannel.CONTROL);
  assert.deepEqual(device.openDeclaredChannel(rotated), new Uint8Array([2]));
});

test('trusted LAN session identifier and transcript context are stable and role ordered', () => {
  const hostPublic = new Uint8Array(65).fill(1);
  const devicePublic = new Uint8Array(65).fill(2);
  hostPublic[0] = 4;
  devicePublic[0] = 4;

  const sessionId = trustedLanSessionIdentifier(nodeCrypto, hostPublic, devicePublic);
  const swappedSessionId = trustedLanSessionIdentifier(nodeCrypto, devicePublic, hostPublic);
  assert.equal(sessionId, trustedLanSessionIdentifier(nodeCrypto, hostPublic, devicePublic));
  assert.notEqual(sessionId, swappedSessionId);

  const context = trustedLanTranscriptContext(nodeCrypto, sessionId, hostPublic, devicePublic);
  const swappedContext = trustedLanTranscriptContext(nodeCrypto, sessionId, devicePublic, hostPublic);
  assert.equal(context.length, 32);
  assert.equal(hex(context), hex(trustedLanTranscriptContext(nodeCrypto, sessionId, hostPublic, devicePublic)));
  assert.notEqual(hex(context), hex(swappedContext));
});

function fixtureSession(localRole, initialKeys) {
  return new ChannelRecordSession({ sessionId: fixture.session.id, sessionEpoch: BigInt(fixture.session.epoch),
    localRole, initialKeys, crypto: nodeCrypto, reserveNonce: (_channel) => nonce(_channel, 1n) });
}

function counterSession(localRole) {
  const store = new InMemoryNonceStore();
  return new ChannelRecordSession({ sessionId: 'counter-session', sessionEpoch: 9n, localRole,
    initialKeys: TrafficKeyDerivation.initial(nodeCrypto, new Uint8Array(32).fill(3), new Uint8Array(32).fill(3), new Uint8Array(32).fill(3)),
    crypto: nodeCrypto, reserveNonce: store.reserve.bind(store) });
}

function deriveFixtureKeys() {
  return TrafficKeyDerivation.initial(nodeCrypto, bytes(fixture.input.shared_secret), bytes(fixture.input.bootstrap_secret), bytes(fixture.input.context));
}

function keySlices(keys) {
  return [keys.hostControl, keys.deviceControl, keys.hostMedia, keys.deviceMedia, keys.hostAudio, keys.deviceAudio, keys.hostBulk, keys.deviceBulk];
}

function bytes(value) { return new Uint8Array(Buffer.from(value, 'hex')); }

function hkdfSha256(input, salt, info, length) {
  const prk = createHmac('sha256', salt).update(input).digest();
  const blocks = [];
  let previous = Buffer.alloc(0);
  let offset = 0;
  for (let counter = 1; offset < length; counter += 1) {
    previous = createHmac('sha256', prk).update(previous).update(info).update(Buffer.from([counter])).digest();
    blocks.push(previous);
    offset += previous.length;
  }
  return new Uint8Array(Buffer.concat(blocks).subarray(0, length));
}
