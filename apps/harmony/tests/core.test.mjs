import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { CoordinateMapper, Rotation } from '../.test-dist/input/CoordinateMapper.js';
import { PeripheralInputMapper } from '../.test-dist/input/PeripheralInputMapper.js';
import { LatestFrameQueue } from '../.test-dist/media/LatestFrameQueue.js';
import { MediaPacketParser } from '../.test-dist/media/MediaPacketParser.js';
import { Capability, Codec, InputPhase, TransportKind } from '../.test-dist/protocol/ProtocolModels.js';
import { ProtocolEncoder } from '../.test-dist/protocol/ProtocolEncoder.js';
import { ProtocolDecoder } from '../.test-dist/protocol/ProtocolDecoder.js';
import { decodeUtf8, encodeUtf8 } from '../.test-dist/protocol/Utf8.js';
import { isSupportedVideoConfig, ProductSession, ProductSessionState } from '../.test-dist/session/ProductSession.js';
import { ReconnectPolicy } from '../.test-dist/session/ReconnectPolicy.js';
import { SessionState, SessionStateMachine } from '../.test-dist/session/SessionStateMachine.js';
import { ControlFramer, ProtocolChannel } from '../.test-dist/transport/ControlFramer.js';
import { ProtocolUpgrade } from '../.test-dist/transport/ProtocolUpgrade.js';

const fixtureRoot = '../../contracts/fixtures/messages/v1';
const fixture = (name) => new Uint8Array(readFileSync(`${fixtureRoot}/bin/${name}`));
const createStreamingSession = () => {
  const session = new ProductSession('harmony-test', 'Harmony test',
    [Capability.TOUCH, Capability.KEYBOARD, Capability.POINTER, Capability.TELEMETRY], [Codec.HEVC, Codec.H264]);
  session.start(1n); session.receive(fixture('host_hello.binpb'), 2n);
  session.receive(fixture('session_accepted.binpb'), 3n);
  session.receive(fixture('list_displays_response.binpb'), 5n);
  session.receive(fixture('start_display_response.binpb'), 7n);
  session.receive(fixture('video_config.binpb'), 8n);
  return session;
};

test('client hello preserves the historical Harmony golden vector', () => {
  const bytes = new ProtocolEncoder().clientHello(ProtocolEncoder.metadata(1n), {
    minimumProtocol: 1, maximumProtocol: 1, deviceId: 'protocol-golden', deviceName: 'Vibe Screen',
    capabilities: [Capability.TOUCH, Capability.KEYBOARD, Capability.POINTER],
    codecs: [Codec.H264, Codec.HEVC], transports: [TransportKind.LAN]
  });
  const expected = readFileSync('../../contracts/fixtures/client-hello-v1.hex', 'utf8').trim();
  assert.equal(Buffer.from(bytes).toString('hex'), expected);
});

test('full ClientHello encoder matches the shared formal fixture', () => {
  const bytes = new ProtocolEncoder().clientHello(ProtocolEncoder.metadata(1n, new Uint8Array(), 0n, 1000000001n), {
    minimumProtocol: 1, maximumProtocol: 1, deviceId: 'android-golden', deviceName: 'Golden Android',
    capabilities: [Capability.TOUCH, Capability.KEYBOARD, Capability.POINTER, Capability.TELEMETRY],
    codecs: [Codec.HEVC, Codec.H264], transports: [TransportKind.USB, TransportKind.LAN],
    resourceLimits: { maximumClients: 1, maximumDisplays: 1, maximumVideoStreams: 1 },
    videoDecodeCapabilities: [
      { codec: Codec.HEVC, maximumWidth: 1920, maximumHeight: 1200, maximumFramesPerSecond: 60, bitDepths: [8] },
      { codec: Codec.H264, maximumWidth: 1920, maximumHeight: 1200, maximumFramesPerSecond: 60, bitDepths: [8] }
    ], requiredCapabilities: [Capability.TOUCH]
  });
  assert.deepEqual(bytes, fixture('client_hello.binpb'));
});

test('empty ListDisplaysRequest remains present as a zero-length oneof message', () => {
  const bytes = new ProtocolEncoder().listDisplays(ProtocolEncoder.metadata(4n, new Uint8Array([1]), 7n));
  const decoded = new ProtocolDecoder().envelope(bytes);
  assert.equal(decoded.payloadField, 40);
  assert.equal(decoded.payload.length, 0);
});

test('portable UTF-8 codec does not depend on browser globals', () => {
  const value = '鸿蒙 · Vibe Screen 🖥️';
  assert.equal(decodeUtf8(encodeUtf8(value)), value);
  assert.equal(decodeUtf8(new Uint8Array([0xc0, 0xaf])), '�');
});

test('formal control fixtures drive the product session through video configuration', () => {
  const session = new ProductSession('harmony-test', 'Harmony test',
    [Capability.TOUCH, Capability.KEYBOARD, Capability.POINTER, Capability.TELEMETRY], [Codec.HEVC, Codec.H264]);
  assert.equal(session.start(1n)[0].kind, 'send');
  assert.deepEqual(session.receive(fixture('host_hello.binpb'), 2n), []);
  const accepted = session.receive(fixture('session_accepted.binpb'), 3n);
  assert.deepEqual(accepted.map((action) => action.kind), ['heartbeat', 'send']);
  const displays = session.receive(fixture('list_displays_response.binpb'), 5n);
  assert.equal(new ProtocolDecoder().envelope(displays[0].bytes).payloadField, 42);
  assert.deepEqual(session.receive(fixture('start_display_response.binpb'), 7n), []);
  const configured = session.receive(fixture('video_config.binpb'), 8n);
  assert.equal(configured[0].kind, 'configureVideo');
  assert.equal(new ProtocolDecoder().envelope(configured[0].acceptedResponse).payloadField, 51);
  assert.equal(session.state(), ProductSessionState.STREAMING);
  assert.deepEqual(session.receive(fixture('display_changed.binpb'), 14n), [
    { kind: 'displayChanged', width: 1080, height: 1920, rotationDegrees: 270 }
  ]);
});

test('media parser matches formal Annex-B fixture and session filters stale epochs', () => {
  const parser = new MediaPacketParser();
  const packet = parser.parse(fixture('media_packet.bin'));
  assert.equal(packet.header.streamId, 42n);
  assert.equal(packet.header.sessionEpoch, 7n);
  assert.equal(packet.header.codec, Codec.HEVC);
  assert.equal(Buffer.from(packet.payload).toString('hex'), '0000000140010c01ff00aa55');
  const session = createStreamingSession();
  assert.equal(session.acceptMedia(packet)[0].kind, 'media');
  assert.deepEqual(session.acceptMedia({ ...packet, header: { ...packet.header, sessionEpoch: 6n, frameId: 1002n } }), []);
  assert.throws(() => session.acceptMedia({ ...packet, header: { ...packet.header, sessionEpoch: 8n, frameId: 1002n } }), /future/);
  assert.deepEqual(session.acceptMedia(packet), []);
  assert.throws(() => parser.parse(fixture('media_packet.bin').slice(0, -1)), /payload_length/);
});

test('video acceptance never exceeds the advertised decode envelope', () => {
  const base = { configEpoch: 1n, codec: Codec.HEVC, width: 1920, height: 1200,
    framesPerSecond: 60, streamId: 42n, rotationDegrees: 0 };
  assert.equal(isSupportedVideoConfig(base, 42n, 0n, [Codec.HEVC], new Set([Codec.HEVC])), true);
  assert.equal(isSupportedVideoConfig({ ...base, width: 1921 }, 42n, 0n, [Codec.HEVC], new Set([Codec.HEVC])), false);
  assert.equal(isSupportedVideoConfig({ ...base, framesPerSecond: 61 }, 42n, 0n, [Codec.HEVC], new Set([Codec.HEVC])), false);
  assert.equal(isSupportedVideoConfig({ ...base, framesPerSecond: 0 }, 42n, 0n, [Codec.HEVC], new Set([Codec.HEVC])), false);
});

test('touch encoder matches the shared target-aware fixture', () => {
  const bytes = new ProtocolEncoder().touch(ProtocolEncoder.metadata(10n,
    new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8]), 7n, 1000000010n), {
      inputId: 100n, pointerId: 1, phase: InputPhase.BEGAN, x: 0.25, y: 0.75,
      pressure: 0.5, tiltX: 0, tiltY: 0, buttonMask: 0
    }, { displayId: 'display-main', streamId: 42n });
  assert.deepEqual(bytes, fixture('touch.binpb'));
});

test('upgrade parser accepts split acknowledgement and returns coalesced frame bytes', () => {
  const upgrade = new ProtocolUpgrade();
  assert.deepEqual([...upgrade.offer()], [0x0d]);
  assert.equal(upgrade.append(new Uint8Array([0x0d])), undefined);
  assert.deepEqual([...upgrade.append(new Uint8Array([0x01, 0xaa, 0xbb]))], [0xaa, 0xbb]);
  assert.throws(() => new ProtocolUpgrade().append(new Uint8Array([0x0d, 0x02])), /acknowledge/);
});

test('channel framer preserves identity across split and coalesced frames', () => {
  const framer = new ControlFramer();
  const one = framer.frame(ProtocolChannel.CONTROL, new Uint8Array([1, 2]));
  const two = framer.frame(ProtocolChannel.VIDEO, new Uint8Array([3]));
  assert.deepEqual(framer.append(one.slice(0, 4)), []);
  const joined = new Uint8Array(one.length - 4 + two.length);
  joined.set(one.slice(4)); joined.set(two, one.length - 4);
  assert.deepEqual(framer.append(joined).map((value) => [value.channel, [...value.payload]]), [[1, [1, 2]], [2, [3]]]);
  assert.throws(() => new ControlFramer().append(new Uint8Array([9, 0, 0, 0, 0])), /Unknown/);
});

test('session decoder ignores additive unknown fields and rejects truncated fixed fields', () => {
  const payload = new Uint8Array([0x0a, 0x02, 0xaa, 0xbb, 0x10, 0x07, 0x18, 0xe8, 0x07, 0x98, 0x06, 0x01]);
  const decoded = new ProtocolDecoder().sessionAccepted(payload);
  assert.equal(decoded.sessionEpoch, 7n);
  assert.throws(() => new ProtocolDecoder().sessionAccepted(new Uint8Array([0x09, 0x01])), /Truncated/);
  assert.throws(() => new ProtocolDecoder().envelope(new Uint8Array([0x00])), /tag/);
  assert.throws(() => new ProtocolDecoder().envelope(new Uint8Array([0x80, 0x80, 0x80, 0x80, 0x80,
    0x80, 0x80, 0x80, 0x80, 0x02])), /uint64/);
  assert.throws(() => new ProtocolDecoder().envelope(new Uint8Array([0x08, 0x01, 0xa2, 0x01, 0x00, 0xaa, 0x01, 0x00])), /multiple/);
});

test('input codecs use distinct envelope fields and stable HID mapping', () => {
  const encoder = new ProtocolEncoder();
  const metadata = ProtocolEncoder.metadata(9n, new Uint8Array([1]), 2n);
  const input = { inputId: 1n, pointerId: 2, phase: 2, x: 0.2, y: 0.4, pressure: 0.5, tiltX: 0, tiltY: 0, buttonMask: 1 };
  assert.equal(new ProtocolDecoder().envelope(encoder.pointer(metadata, input)).payloadField, 61);
  assert.equal(new ProtocolDecoder().envelope(encoder.scroll(metadata, { inputId: 2n, deltaX: 1, deltaY: -2 })).payloadField, 62);
  assert.equal(new ProtocolDecoder().envelope(encoder.key(metadata, { inputId: 3n, usbHidUsage: 4, pressed: true, modifierMask: 0, text: 'a' })).payloadField, 63);
  assert.equal(new PeripheralInputMapper().usbHidUsage('a'), 0x04);
  assert.equal(new PeripheralInputMapper().usbHidUsage('ArrowRight'), 0x4f);
  assert.equal(new PeripheralInputMapper().buttonMask(1), 2);
});

test('queue, geometry, session epoch and reconnect policies remain bounded', () => {
  const queue = new LatestFrameQueue();
  queue.offer({ frameId: 1n, epoch: 1n, timestampNs: 1n, keyframe: true, payload: new Uint8Array([1]) });
  queue.offer({ frameId: 2n, epoch: 2n, timestampNs: 2n, keyframe: false, payload: new Uint8Array([2]) });
  assert.equal(queue.poll(1n), undefined); assert.equal(queue.droppedCount(), 2);
  const mapped = new CoordinateMapper().map(60, 120, { left: 10, top: 20, width: 100, height: 200, rotation: Rotation.DEG_90 });
  assert.deepEqual(mapped, { x: 0.5, y: 0.5 });
  const state = new SessionStateMachine(); state.beginConnect(); state.transportReady(); state.accept(7n);
  assert.equal(state.state(), SessionState.STREAMING); assert.equal(state.acceptsEpoch(6n), false);
  const policy = new ReconnectPolicy(); assert.equal(policy.delayMs(0, 0.5), 250); assert.equal(policy.delayMs(20, 0.5), 8000);
});
