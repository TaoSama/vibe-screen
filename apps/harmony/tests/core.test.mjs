import test from 'node:test';
import assert from 'node:assert/strict';
import { CoordinateMapper, Rotation } from '../.test-dist/input/CoordinateMapper.js';
import { LatestFrameQueue } from '../.test-dist/media/LatestFrameQueue.js';
import { Codec, defaultCapabilities, TransportKind } from '../.test-dist/protocol/ProtocolModels.js';
import { ProtocolEncoder } from '../.test-dist/protocol/ProtocolEncoder.js';
import { ProtocolDecoder } from '../.test-dist/protocol/ProtocolDecoder.js';
import { ReconnectPolicy } from '../.test-dist/session/ReconnectPolicy.js';
import { SessionState, SessionStateMachine } from '../.test-dist/session/SessionStateMachine.js';
import { ControlFramer } from '../.test-dist/transport/ControlFramer.js';

test('client hello uses Protocol v1 golden prefix', () => {
  const bytes = new ProtocolEncoder().clientHello(ProtocolEncoder.metadata(1n), {
    minimumProtocol: 1, maximumProtocol: 1, deviceId: 'matepad-mini', deviceName: 'MatePad Mini',
    capabilities: defaultCapabilities(), codecs: [Codec.HEVC, Codec.H264], transports: [TransportKind.LAN]
  });
  assert.equal(bytes[0], 0x08);
  assert.equal(bytes[1], 0x01);
  assert.ok(bytes.includes(0xa2));
});

test('session accepted decoder ignores unknown fields', () => {
  const payload = new Uint8Array([0x0a, 0x02, 0xaa, 0xbb, 0x10, 0x07, 0x18, 0xe8, 0x07, 0x98, 0x06, 0x01]);
  const decoded = new ProtocolDecoder().sessionAccepted(payload);
  assert.deepEqual([...decoded.sessionId], [0xaa, 0xbb]);
  assert.equal(decoded.sessionEpoch, 7n);
  assert.equal(decoded.heartbeatIntervalMs, 1000);
});

test('touch, pointer, scroll and key use distinct envelope fields', () => {
  const encoder = new ProtocolEncoder();
  const metadata = ProtocolEncoder.metadata(9n, new Uint8Array([1]), 2n);
  const input = { inputId: 1n, pointerId: 2, phase: 2, x: 0.2, y: 0.4, pressure: 0.5, tiltX: 0, tiltY: 0, buttonMask: 1 };
  assert.equal(new ProtocolDecoder().envelope(encoder.touch(metadata, input)).payloadField, 60);
  assert.equal(new ProtocolDecoder().envelope(encoder.pointer(metadata, input)).payloadField, 61);
  assert.equal(new ProtocolDecoder().envelope(encoder.scroll(metadata, { inputId: 2n, deltaX: 1, deltaY: -2 })).payloadField, 62);
  assert.equal(new ProtocolDecoder().envelope(encoder.key(metadata, { inputId: 3n, usbHidUsage: 4, pressed: true, modifierMask: 0, text: 'a' })).payloadField, 63);
});

test('framer preserves split and coalesced messages', () => {
  const framer = new ControlFramer();
  const one = framer.frame(new Uint8Array([1, 2]));
  const two = framer.frame(new Uint8Array([3]));
  assert.deepEqual(framer.append(one.slice(0, 3)), []);
  const joined = new Uint8Array(one.length - 3 + two.length);
  joined.set(one.slice(3)); joined.set(two, one.length - 3);
  assert.deepEqual(framer.append(joined).map(value => [...value]), [[1, 2], [3]]);
});

test('session rejects stale epochs', () => {
  const session = new SessionStateMachine();
  session.beginConnect(); session.transportReady(); session.accept(7n);
  assert.equal(session.state(), SessionState.STREAMING);
  assert.equal(session.acceptsEpoch(6n), false);
  assert.equal(session.acceptsEpoch(7n), true);
});

test('latest-frame queue is bounded and filters old epochs', () => {
  const queue = new LatestFrameQueue();
  queue.offer({ frameId: 1n, epoch: 1n, keyframe: true, payload: new Uint8Array([1]) });
  queue.offer({ frameId: 2n, epoch: 2n, keyframe: false, payload: new Uint8Array([2]) });
  assert.equal(queue.depth(), 1);
  assert.equal(queue.poll(1n), undefined);
  assert.equal(queue.droppedCount(), 2);
});

test('coordinate mapper handles rotation and letterbox offsets', () => {
  const mapped = new CoordinateMapper().map(60, 120, { left: 10, top: 20, width: 100, height: 200, rotation: Rotation.DEG_90 });
  assert.deepEqual(mapped, { x: 0.5, y: 0.5 });
});

test('reconnect backoff is capped and deterministic with injected jitter', () => {
  const policy = new ReconnectPolicy();
  assert.equal(policy.delayMs(0, 0.5), 250);
  assert.equal(policy.delayMs(20, 0.5), 8000);
});
