import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { CoordinateMapper, Rotation } from '../.test-dist/input/CoordinateMapper.js';
import { ControllerInputMapper, MAXIMUM_ACTIVE_CONTROLLERS_REJECTION_REASON } from '../.test-dist/input/ControllerInputMapper.js';
import { PeripheralInputMapper } from '../.test-dist/input/PeripheralInputMapper.js';
import { StylusInputMapper } from '../.test-dist/input/StylusInputMapper.js';
import { FrameQueueState, LatestFrameQueue } from '../.test-dist/media/LatestFrameQueue.js';
import { MediaPacketParser } from '../.test-dist/media/MediaPacketParser.js';
import { AeadAlgorithm, Capability, Codec, ColorPrimaries, ControllerEventKind, InputPhase, KeyAgreementAlgorithm,
  MatrixCoefficients, SignatureAlgorithm, StylusContactState, StylusToolKind, TransferFunction,
  TransportKind } from '../.test-dist/protocol/ProtocolModels.js';
import { EnvelopePayloadField, ProtocolEncoder } from '../.test-dist/protocol/ProtocolEncoder.js';
import { ProtocolDecoder } from '../.test-dist/protocol/ProtocolDecoder.js';
import { MAX_PENDING_CONTROLS, OutboundControlWriter } from '../.test-dist/protocol/OutboundControlWriter.js';
import { ProtobufWriter } from '../.test-dist/protocol/ProtobufWriter.js';
import { decodeUtf8, encodeUtf8 } from '../.test-dist/protocol/Utf8.js';
import { ClientCapabilities, HARMONY_ADVERTISED_CAPABILITIES } from '../.test-dist/session/ClientCapabilities.js';
import { HeartbeatMonitor } from '../.test-dist/session/HeartbeatMonitor.js';
import { ProgressWatchdog } from '../.test-dist/session/ProgressWatchdog.js';
import { isSupportedVideoConfig, modifierWireMask, ProductSession, ProductSessionState } from '../.test-dist/session/ProductSession.js';
import { ReconnectPolicy } from '../.test-dist/session/ReconnectPolicy.js';
import { SessionState, SessionStateMachine } from '../.test-dist/session/SessionStateMachine.js';
import { CredentialLifecycle, PairingClient } from '../.test-dist/security/PairingSecurity.js';
import { ControlFramer, ProtocolChannel } from '../.test-dist/transport/ControlFramer.js';
import { ProtocolUpgrade } from '../.test-dist/transport/ProtocolUpgrade.js';

const fixtureRoot = '../../contracts/fixtures/messages/v1';
const fixture = (name) => new Uint8Array(readFileSync(`${fixtureRoot}/bin/${name}`));
const sessionId = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8]);
const encodeAction = (session, action, messageId = 100n) => new ProtocolEncoder().intent(
  ProtocolEncoder.metadata(messageId, session.outboundScope().sessionId, session.outboundScope().sessionEpoch), action.intent);
const finishVideoConfiguration = (session, configure) => {
  const response = session.completeVideoConfiguration(configure.token)[0];
  session.confirmSent(response.afterSend);
  return response;
};
const confirmStylus = (session, action) => {
  assert.deepEqual(action.afterSend, { kind: 'stylus' });
  session.confirmSent(action.afterSend);
  return action;
};
const confirmController = (session, action, messageId = undefined) => {
  assert.equal(action.afterSend?.kind, 'controller');
  if (action.onAssigned !== undefined) {
    assert.equal(action.onAssigned.kind, 'controllerConnect');
    session.confirmAssigned(action.onAssigned, messageId ?? action.afterSend.event.inputId + 100n, 1n);
  }
  session.confirmSent(action.afterSend);
  return action;
};
const confirmRequest = (session, action, messageId) => session.confirmAssigned(action.onAssigned, messageId, 1n);
const inputAckEnvelope = (messageId, correlationId, inputId, accepted = true,
  rejectionReason = MAXIMUM_ACTIVE_CONTROLLERS_REJECTION_REASON) => controlEnvelope(messageId, 64,
  new ProtobufWriter().uint64(1, inputId).bool(2, accepted).string(3, accepted ? '' : rejectionReason), true, correlationId);
const createStreamingSession = () => {
  const session = new ProductSession('harmony-test', 'Harmony test',
    [Capability.TOUCH, Capability.KEYBOARD, Capability.POINTER, Capability.TELEMETRY], [Codec.HEVC, Codec.H264]);
  confirmRequest(session, session.start(1n)[0], 1n); session.receive(fixture('host_hello.binpb'), 2n);
  const accepted = session.receive(fixture('session_accepted.binpb'), 3n);
  confirmRequest(session, accepted[1], 4n);
  confirmRequest(session, session.receive(fixture('list_displays_response.binpb'), 5n)[0], 6n);
  session.receive(fixture('start_display_response.binpb'), 7n);
  const configure = session.receive(fixture('video_config.binpb'), 8n)[0];
  finishVideoConfiguration(session, configure);
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
  const hello = session.start(1n)[0];
  assert.equal(hello.kind, 'send');
  confirmRequest(session, hello, 1n);
  assert.deepEqual(session.receive(fixture('host_hello.binpb'), 2n), []);
  const accepted = session.receive(fixture('session_accepted.binpb'), 3n);
  assert.deepEqual(accepted.map((action) => action.kind), ['heartbeat', 'send']);
  confirmRequest(session, accepted[1], 4n);
  const displays = session.receive(fixture('list_displays_response.binpb'), 5n);
  assert.equal(new ProtocolDecoder().envelope(encodeAction(session, displays[0])).payloadField, 42);
  confirmRequest(session, displays[0], 6n);
  assert.deepEqual(session.receive(fixture('start_display_response.binpb'), 7n), []);
  const configured = session.receive(fixture('video_config.binpb'), 8n);
  assert.equal(configured[0].kind, 'configureVideo');
  assert.equal(session.state(), ProductSessionState.CONFIGURING_VIDEO);
  assert.equal(configured[0].config.bitrateKbps, 12000);
  assert.equal(configured[0].config.colorDescription.bitDepth, 8);
  assert.deepEqual(new ProtocolEncoder().videoConfigResult(
    ProtocolEncoder.metadata(9n, sessionId, 7n, 1000000009n), 8n, configured[0].config, true, ''),
  fixture('video_config_result.binpb'));
  const response = finishVideoConfiguration(session, configured[0]);
  assert.equal(new ProtocolDecoder().envelope(encodeAction(session, response)).payloadField, 51);
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
  assert.deepEqual(session.acceptMedia({ ...packet, header: { ...packet.header, configEpoch: 2n, frameId: 1002n } }), []);
  assert.deepEqual(session.acceptMedia(packet), []);
  assert.throws(() => parser.parse(fixture('media_packet.bin').slice(0, -1)), /payload_length/);
});

test('video acceptance never exceeds the advertised decode envelope', () => {
  const base = { configEpoch: 1n, codec: Codec.HEVC, width: 1920, height: 1200,
    framesPerSecond: 60, bitrateKbps: 12000, streamId: 42n, rotationDegrees: 0 };
  assert.equal(isSupportedVideoConfig(base, 42n, 0n, [Codec.HEVC], new Set([Codec.HEVC])), true);
  assert.equal(isSupportedVideoConfig({ ...base, width: 1921 }, 42n, 0n, [Codec.HEVC], new Set([Codec.HEVC])), false);
  assert.equal(isSupportedVideoConfig({ ...base, framesPerSecond: 61 }, 42n, 0n, [Codec.HEVC], new Set([Codec.HEVC])), false);
  assert.equal(isSupportedVideoConfig({ ...base, framesPerSecond: 0 }, 42n, 0n, [Codec.HEVC], new Set([Codec.HEVC])), false);
  assert.equal(isSupportedVideoConfig({ ...base, colorDescription: { primaries: ColorPrimaries.BT709,
    transferFunction: TransferFunction.PQ, matrixCoefficients: MatrixCoefficients.BT709,
    fullRange: false, bitDepth: 10 } }, 42n, 0n, [Codec.HEVC], new Set([Codec.HEVC])), false);
});

test('negotiated capabilities must be a legal subset and gate optional input', () => {
  const capabilities = new ClientCapabilities(
    [Capability.TOUCH, Capability.KEYBOARD, Capability.POINTER], [Capability.TOUCH]);
  capabilities.acceptHost([Capability.TOUCH]);
  capabilities.acceptNegotiated([Capability.TOUCH]);
  assert.equal(capabilities.has(Capability.TOUCH), true);
  assert.equal(capabilities.has(Capability.KEYBOARD), false);
  assert.equal(capabilities.has(Capability.POINTER), false);
  assert.throws(() => capabilities.acceptNegotiated([Capability.TOUCH, Capability.KEYBOARD]), /invalid negotiated/);

  const session = new ProductSession('touch-only', 'Touch only', [Capability.TOUCH], [Codec.HEVC]);
  confirmRequest(session, session.start(1n)[0], 1n);
  session.receive(controlEnvelope(2n, 21, new ProtobufWriter().uint32(1, 1)
    .packedVarints(4, [Capability.TOUCH]).packedVarints(5, [Codec.HEVC]), false), 2n);
  assert.throws(() => session.receive(fixture('session_accepted.binpb'), 3n), /invalid negotiated/);
});

test('controller capability 26 is advertised with a production encoder surface', () => {
  assert.equal(Capability.CONTROLLER, 26);
  assert.equal(HARMONY_ADVERTISED_CAPABILITIES.includes(Capability.CONTROLLER), true);
  assert.equal(EnvelopePayloadField.CONTROLLER, 66);
  assert.equal(typeof new ProtocolEncoder().controller, 'function');
});

test('controller capability has no additional capability dependency', () => {
  assert.doesNotThrow(() => new ClientCapabilities(
    [Capability.TOUCH, Capability.CONTROLLER], [Capability.TOUCH]));
});

test('controller negotiation rejects a capability the client did not offer', () => {
  const capabilities = new ClientCapabilities([Capability.TOUCH], [Capability.TOUCH]);
  capabilities.acceptHost([Capability.TOUCH, Capability.CONTROLLER]);
  assert.throws(() => capabilities.acceptNegotiated(
    [Capability.TOUCH, Capability.CONTROLLER]), /invalid negotiated capability set/);
});

test('USB HID modifier capability 27 preserves standard and legacy layouts', () => {
  assert.equal(Capability.USB_HID_MODIFIER_BYTE, 27);
  assert.equal(HARMONY_ADVERTISED_CAPABILITIES.includes(Capability.USB_HID_MODIFIER_BYTE), true);
  assert.equal(modifierWireMask(0x01, true), 0x01);
  assert.equal(modifierWireMask(0x02, true), 0x02);
  assert.equal(modifierWireMask(0x01, false), 0x02);
  assert.equal(modifierWireMask(0x02, false), 0x01);
  assert.equal(modifierWireMask(0x10, false), 0x02);
  assert.equal(modifierWireMask(0x20, false), 0x01);
  assert.equal(modifierWireMask(0xc0, false), 0x0c);
  assert.throws(() => modifierWireMask(0x100, false), /Invalid modifier byte/);
  const encoder = new ProtocolEncoder();
  const standardControl = { inputId: 102n, usbHidUsage: 4, pressed: true, modifierMask: 0x01,
    text: 'a', target: { displayId: 'display-main', streamId: 42n } };
  const legacyControl = { ...standardControl, inputId: 104n, modifierMask: 0x02 };
  assert.deepEqual(encoder.key(ProtocolEncoder.metadata(17n, sessionId, 7n, 1000000017n), standardControl),
    fixture('key_usb_hid_control.binpb'));
  assert.deepEqual(encoder.key(ProtocolEncoder.metadata(19n, sessionId, 7n, 1000000019n), legacyControl),
    fixture('key_legacy_control.binpb'));
  const dependencies = new ClientCapabilities(
    [Capability.TOUCH, Capability.KEYBOARD, Capability.USB_HID_MODIFIER_BYTE], [Capability.TOUCH]);
  assert.throws(() => dependencies.acceptHost(
    [Capability.TOUCH, Capability.USB_HID_MODIFIER_BYTE]), /required client capability/);
  dependencies.acceptHost([Capability.TOUCH, Capability.KEYBOARD, Capability.USB_HID_MODIFIER_BYTE]);
  assert.throws(() => dependencies.acceptNegotiated(
    [Capability.TOUCH, Capability.USB_HID_MODIFIER_BYTE]), /invalid negotiated capability set/);
});

test('product session suppresses unnegotiated pointer and keyboard input', () => {
  const session = touchOnlyStreamingSession();
  const input = { inputId: 1n, pointerId: 1, phase: InputPhase.BEGAN, x: 0.5, y: 0.5,
    pressure: 0.5, tiltX: 0, tiltY: 0, buttonMask: 0 };
  assert.equal(session.touch(input).intent.kind, 'touch');
  assert.throws(() => session.pointer(input), /was not negotiated/);
  assert.throws(() => session.scroll({ inputId: 2n, deltaX: 1, deltaY: 2 }), /was not negotiated/);
  assert.throws(() => session.key({ inputId: 3n, usbHidUsage: 4, pressed: true, modifierMask: 0, text: 'a' }),
    /was not negotiated/);
});

test('product session rejects non-finite and out-of-range input locally', () => {
  const session = createStreamingSession();
  const valid = { inputId: 1n, pointerId: 1, phase: InputPhase.BEGAN, x: 0.5, y: 0.5,
    pressure: 0.5, tiltX: 0, tiltY: 0, buttonMask: 0 };
  assert.equal(session.touch(valid).intent.kind, 'touch');
  assert.throws(() => session.touch({ ...valid, inputId: 2n, x: Number.NaN }), /Invalid normalized/);
  assert.throws(() => session.pointer({ ...valid, inputId: 3n, x: 1.1 }), /Invalid normalized/);
  assert.throws(() => session.scroll({ inputId: 4n, deltaX: Number.POSITIVE_INFINITY, deltaY: 0 }), /Invalid scroll/);
  assert.throws(() => session.key({ inputId: 5n, usbHidUsage: 0, pressed: true, modifierMask: 0, text: '' }),
    /Invalid keyboard/);
});

test('outbound writer keeps one send in flight and assigns ids at dequeue time', async () => {
  const sent = [];
  const releases = [];
  const writer = new OutboundControlWriter((bytes) => {
    sent.push(new ProtocolDecoder().envelope(bytes));
    return new Promise((resolve) => releases.push(resolve));
  }, () => 99n);
  const scope = { sessionId, sessionEpoch: 7n };
  const first = writer.enqueue({ kind: 'ping', sequence: 1n }, scope);
  const second = writer.enqueue({ kind: 'ping', sequence: 2n }, scope);
  const third = writer.enqueue({ kind: 'ping', sequence: 3n }, scope);
  assert.deepEqual(sent.map((value) => value.messageId), [1n]);
  releases.shift()(); await first;
  assert.deepEqual(sent.map((value) => value.messageId), [1n, 2n]);
  releases.shift()(); await second;
  assert.deepEqual(sent.map((value) => value.messageId), [1n, 2n, 3n]);
  releases.shift()(); await third;
});

test('outbound writer fails closed at a bounded backlog', async () => {
  const writer = new OutboundControlWriter(() => new Promise(() => {}), () => 1n);
  const scope = { sessionId, sessionEpoch: 7n };
  writer.enqueue({ kind: 'ping', sequence: 1n }, scope).catch(() => {});
  const queued = [];
  for (let index = 0; index < MAX_PENDING_CONTROLS; index += 1) {
    queued.push(writer.enqueue({ kind: 'ping', sequence: BigInt(index + 2) }, scope));
  }
  const overflow = writer.enqueue({ kind: 'pong', sequence: 1n, correlationId: 1n }, scope);
  await assert.rejects(overflow, /bounded capacity/);
  await Promise.all(queued.map((pending) => assert.rejects(pending, /bounded capacity/)));
});

test('protocol responses overtake input while gesture lifecycle stays FIFO', async () => {
  const sent = [];
  const releases = [];
  const writer = new OutboundControlWriter((bytes) => {
    sent.push(new ProtocolDecoder().envelope(bytes));
    return new Promise((resolve) => releases.push(resolve));
  }, () => 1n);
  const scope = { sessionId, sessionEpoch: 7n };
  const first = writer.enqueue({ kind: 'ping', sequence: 1n }, scope);
  const motion = writer.enqueue({ kind: 'pointer', event: { inputId: 2n, pointerId: 0,
    phase: InputPhase.CHANGED, x: 0.5, y: 0.5, pressure: 0, tiltX: 0, tiltY: 0, buttonMask: 0 } }, scope);
  const ended = writer.enqueue({ kind: 'pointer', event: { inputId: 3n, pointerId: 0,
    phase: InputPhase.ENDED, x: 0.5, y: 0.5, pressure: 0, tiltX: 0, tiltY: 0, buttonMask: 0 } }, scope);
  const pong = writer.enqueue({ kind: 'pong', sequence: 9n, correlationId: 8n }, scope);
  releases.shift()(); await first;
  assert.equal(sent[1].payloadField, 25);
  releases.shift()(); await pong;
  assert.equal(sent[2].payloadField, 61);
  releases.shift()(); const motionReceipt = await motion;
  assert.equal(motionReceipt.messageId, 3n);
  assert.equal(sent[3].payloadField, 61);
  releases.shift()(); const endedReceipt = await ended;
  assert.equal(endedReceipt.messageId, 4n);
  assert.deepEqual(sent.map((envelope) => envelope.messageId), [1n, 2n, 3n, 4n]);
});

test('delayed video result receives an id after intervening heartbeat traffic', async () => {
  const session = sessionAwaitingVideoConfiguration();
  const configure = session.receive(fixture('video_config.binpb'), 8n)[0];
  assert.equal(session.state(), ProductSessionState.CONFIGURING_VIDEO);
  const envelopes = [];
  const writer = new OutboundControlWriter(async (bytes) => { envelopes.push(new ProtocolDecoder().envelope(bytes)); }, () => 20n);
  const heartbeat = session.heartbeat(1n);
  const heartbeatReceipt = await writer.enqueue(heartbeat.intent, session.outboundScope(),
    (messageId, nowNs) => session.confirmAssigned(heartbeat.onAssigned, messageId, nowNs));
  const pongBytes = new ProtocolEncoder().pong({ ...ProtocolEncoder.metadata(50n, sessionId, 7n),
    correlationId: heartbeatReceipt.messageId }, 1n);
  session.receive(pongBytes, 21n);
  const result = session.completeVideoConfiguration(configure.token)[0];
  await writer.enqueue(result.intent, session.outboundScope());
  session.confirmSent(result.afterSend);
  assert.deepEqual(envelopes.map((value) => value.messageId), [1n, 2n]);
  assert.equal(envelopes[1].payloadField, 51);
  assert.equal(session.state(), ProductSessionState.STREAMING);
});

test('decoder configuration rejection returns to video negotiation after its result is sent', () => {
  const session = sessionAwaitingVideoConfiguration();
  const configure = session.receive(fixture('video_config.binpb'), 8n)[0];
  const response = session.completeVideoConfiguration(configure.token, false, 'decoder_configuration_failed')[0];
  assert.equal(response.intent.kind, 'videoConfigResult');
  assert.equal(response.intent.accepted, false);
  session.confirmSent(response.afterSend);
  assert.equal(session.state(), ProductSessionState.AWAITING_VIDEO);
});

test('heartbeat monitor requires matching Pong correlation and times out deterministically', () => {
  const monitor = new HeartbeatMonitor();
  monitor.configure(1000);
  monitor.reserve(9n);
  monitor.sent(9n, 41n, 100n);
  assert.equal(monitor.acceptPong(9n, 40n), false);
  assert.equal(monitor.acceptPong(8n, 41n), false);
  assert.equal(monitor.timedOut(3000000099n), false);
  assert.equal(monitor.timedOut(3000000100n), true);
  assert.equal(monitor.acceptPong(9n, 41n), true);
  assert.equal(monitor.timedOut(4000000000n), false);
});

test('progress watchdog ignores same-state Pong traffic and resets per video configuration', () => {
  const watchdog = new ProgressWatchdog();
  assert.equal(watchdog.shouldRearm(ProductSessionState.AWAITING_VIDEO, ProductSessionState.AWAITING_VIDEO), false);
  assert.equal(watchdog.shouldRearm(ProductSessionState.STARTING_DISPLAY, ProductSessionState.AWAITING_VIDEO), true);
  watchdog.configurationStarted();
  assert.equal(watchdog.delayMs(ProductSessionState.STREAMING), 5000);
  assert.equal(watchdog.deadlineAction(ProductSessionState.STREAMING, false), 'requestKeyframe');
  assert.equal(watchdog.deadlineAction(ProductSessionState.STREAMING, false), 'requestKeyframe');
  assert.equal(watchdog.deadlineAction(ProductSessionState.STREAMING, false), 'reconnect');
  watchdog.configurationStarted();
  assert.equal(watchdog.deadlineAction(ProductSessionState.STREAMING, false), 'requestKeyframe');
  assert.equal(watchdog.deadlineAction(ProductSessionState.STREAMING, true), 'none');
});

test('session responses must correlate to the request that opened their state', () => {
  const session = new ProductSession('correlation-test', 'Correlation test',
    [Capability.TOUCH], [Codec.HEVC]);
  confirmRequest(session, session.start(1n)[0], 1n);
  const host = new ProtobufWriter().uint32(1, 1).packedVarints(4, [Capability.TOUCH]).packedVarints(5, [Codec.HEVC]);
  assert.throws(() => session.receive(controlEnvelope(2n, 21, host, false, 99n), 2n), /correlation/);
});

test('writer failure rejects queued controls and closes the writer', async () => {
  const failure = new Error('socket failed');
  const writer = new OutboundControlWriter(async () => { throw failure; }, () => 1n);
  const scope = { sessionId, sessionEpoch: 7n };
  const first = writer.enqueue({ kind: 'ping', sequence: 1n }, scope);
  const second = writer.enqueue({ kind: 'ping', sequence: 2n }, scope);
  await assert.rejects(first, /socket failed/);
  await assert.rejects(second, /socket failed/);
  await assert.rejects(writer.enqueue({ kind: 'ping', sequence: 3n }, scope), /socket failed/);
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
  assert.equal(queue.reset(1n).requestKeyframe, true);
  assert.equal(queue.offer(frame(1n, 2n, true)).accepted, false);
  assert.equal(queue.depth(), 0); assert.equal(queue.droppedCount(), 1);
  const mapped = new CoordinateMapper().map(60, 120, { left: 10, top: 20, width: 100, height: 200, rotation: Rotation.DEG_90 });
  assert.deepEqual(mapped, { x: 0.5, y: 0.5 });
  const state = new SessionStateMachine(); state.beginConnect(); state.transportReady(); state.accept(7n);
  assert.equal(state.state(), SessionState.STREAMING); assert.equal(state.acceptsEpoch(6n), false);
  const policy = new ReconnectPolicy(); assert.equal(policy.delayMs(0, 0.5), 250); assert.equal(policy.delayMs(20, 0.5), 8000);
});

test('resume result advances epoch and rejected or malformed results fail closed', () => {
  const negotiated = [Capability.TOUCH, Capability.SESSION_RESUME];
  const original = sessionAwaitingVideoConfiguration(negotiated,
    [Capability.TOUCH, Capability.SESSION_RESUME]);
  const configure = original.receive(fixture('video_config.binpb'), 8n)[0]; finishVideoConfiguration(original, configure);
  const snapshot = original.resumableSnapshot(19n);
  assert.equal(snapshot.nextOutboundMessageId, 19n);

  const resumed = new ProductSession('harmony-test', 'Harmony test',
    [Capability.TOUCH, Capability.SESSION_RESUME], [Codec.HEVC, Codec.H264]);
  const request = resumed.start(10n, snapshot)[0];
  assert.equal(request.intent.kind, 'resume'); confirmRequest(resumed, request, 19n);
  const accepted = new ProtobufWriter().bool(1, true).uint64(2, 8n);
  const resultEnvelope = new ProtobufWriter().uint32(1, 1).uint64(2, 16n).uint64(3, 19n)
    .bytesField(4, sessionId).uint64(5, 8n).message(27, accepted).finish();
  const actions = resumed.receive(resultEnvelope, 11n);
  assert.equal(resumed.epoch(), 8n); assert.equal(resumed.state(), ProductSessionState.SELECTING_DISPLAY);
  assert.deepEqual(actions.map((action) => action.kind), ['heartbeat', 'send']);
  assert.throws(() => resumed.receive(resultEnvelope, 12n), /metadata/);

  const rejected = new ProductSession('harmony-test', 'Harmony test',
    [Capability.TOUCH, Capability.SESSION_RESUME], [Codec.HEVC, Codec.H264]);
  const rejectedRequest = rejected.start(10n, snapshot)[0]; confirmRequest(rejected, rejectedRequest, 19n);
  const rejection = new ProtobufWriter().string(3, 'expired');
  const rejectedEnvelope = new ProtobufWriter().uint32(1, 1).uint64(2, 16n).uint64(3, 19n)
    .bytesField(4, sessionId).uint64(5, 7n).message(27, rejection).finish();
  assert.deepEqual(rejected.receive(rejectedEnvelope, 11n),
    [{ kind: 'disconnect', reason: 'resume_rejected:expired', retryable: true }]);
  assert.equal(rejected.state(), ProductSessionState.CLOSED);

  const wrongCorrelation = new ProductSession('harmony-test', 'Harmony test', negotiated, [Codec.HEVC, Codec.H264]);
  const wrongRequest = wrongCorrelation.start(10n, snapshot)[0]; confirmRequest(wrongCorrelation, wrongRequest, 19n);
  const uncorrelatedEnvelope = new ProtobufWriter().uint32(1, 1).uint64(2, 16n).uint64(3, 18n)
    .bytesField(4, sessionId).uint64(5, 8n).message(27, accepted).finish();
  assert.throws(() => wrongCorrelation.receive(uncorrelatedEnvelope, 11n), /correlation/);

  const unexpectedPayload = new ProductSession('harmony-test', 'Harmony test', negotiated, [Codec.HEVC, Codec.H264]);
  const unexpectedRequest = unexpectedPayload.start(10n, snapshot)[0]; confirmRequest(unexpectedPayload, unexpectedRequest, 19n);
  const ping = new ProtobufWriter().uint64(1, 1n);
  const pingEnvelope = new ProtobufWriter().uint32(1, 1).uint64(2, 16n).bytesField(4, sessionId)
    .uint64(5, 7n).message(24, ping).finish();
  assert.throws(() => unexpectedPayload.receive(pingEnvelope, 11n), /Only ResumeSessionResult/);
});

test('pairing request/result is single-use and credential replay/revoke is durable', async () => {
  const digest = (_value) => new Uint8Array(32);
  const devicePublic = new Uint8Array(65).fill(7); devicePublic[0] = 4;
  const hostPublic = new Uint8Array(65).fill(9); hostPublic[0] = 4;
  const toHex = (value) => [...value].map((byte) => byte.toString(16).padStart(2, '0')).join('');
  let destroyed = 0;
  const crypto = {
    identity: () => ({ publicIdentity: { deviceId: 'device', keyId: toHex(digest(devicePublic)), keyEpoch: 1n,
      signatureAlgorithm: SignatureAlgorithm.ECDSA_P256_SHA256, signingPublicKey: devicePublic }, sign: (value) => value }),
    ephemeral: () => ({ publicKey: new Uint8Array(65).fill(5), derive: () => new Uint8Array(32).fill(6),
      destroy: () => { destroyed += 1; } }),
    sha256: digest, hmacSha256: (_key, value) => digest(value),
    hkdfSha256: (_secret, _salt, _info, length) => new Uint8Array(length).fill(3), verify: () => true,
    openAes256Gcm: () => new Uint8Array(32).fill(4)
  };
  const offer = { offerId: new Uint8Array(16).fill(1), oneTimeCredential: new Uint8Array(32).fill(2),
    expiresAtUnixSeconds: 200n, hostPublicKey: hostPublic, hostIdentity: { deviceId: 'host',
      keyId: toHex(digest(hostPublic)), keyEpoch: 1n, signatureAlgorithm: SignatureAlgorithm.ECDSA_P256_SHA256,
      signingPublicKey: hostPublic }, challenge: new Uint8Array(32).fill(3), ephemeralPublicKey: new Uint8Array(65).fill(4),
    signatureAlgorithms: [SignatureAlgorithm.ECDSA_P256_SHA256], keyAgreementAlgorithms: [KeyAgreementAlgorithm.ECDH_P256],
    aeadAlgorithms: [AeadAlgorithm.AES_256_GCM] };
  const pending = new PairingClient(crypto).begin(offer, 'Harmony tablet', 100n);
  assert.equal(pending.request.bootstrapMac.length, 32);
  const encoded = new ProtocolEncoder().pairingRequest(ProtocolEncoder.metadata(1n), pending.request);
  assert.equal(new ProtocolDecoder().envelope(encoded).payloadField, 31);
  const pairingResult = { accepted: true, deviceId: 'device', deviceCredential: new Uint8Array(),
    rejectionReason: '', hostProof: { challenge: offer.challenge, ephemeralPublicKey: offer.ephemeralPublicKey,
      signature: new Uint8Array(32) }, encryptedDeviceCredential: new Uint8Array(48), credentialNonce: new Uint8Array(12),
    sessionKeyId: '0'.repeat(64), sessionKeyEpoch: 1n };
  const completion = pending.complete(pairingResult, 150n);
  assert.equal(completion.credential.length, 32); assert.equal(destroyed, 1);
  assert.throws(() => pending.complete(pairingResult, 150n), /already consumed/);

  const expiredPending = new PairingClient(crypto).begin(offer, 'Harmony tablet', 100n);
  assert.throws(() => expiredPending.complete(pairingResult, 200n), /Invalid PairingResult/);

  const writes = []; const store = { load: async () => undefined,
    save: async (record) => { writes.push({ ...record, credential: record.credential.slice() }); } };
  const lifecycle = new CredentialLifecycle(store); const owner = lifecycle.owner();
  await lifecycle.install(owner, 'b'.repeat(32), completion);
  assert.equal(lifecycle.authorize().credential.length, 32);
  await lifecycle.acceptAuthenticatedControlSequence(2n);
  await assert.rejects(lifecycle.acceptAuthenticatedControlSequence(2n), /Replayed/);
  await lifecycle.revoke('device', 'user_revoked');
  assert.throws(() => lifecycle.authorize(), /No authorized/);
  assert.equal(writes.at(-1).credential.length, 0); assert.equal(writes.at(-1).revoked, true);
});

test('superseded or failed credential writes cannot revive or retain pairing secrets', async () => {
  let releaseFirstSave;
  let markSaveStarted;
  const firstSaveStarted = new Promise((resolve) => { markSaveStarted = resolve; });
  const firstSaveGate = new Promise((resolve) => { releaseFirstSave = resolve; });
  const writes = [];
  let first = true;
  const store = { load: async () => undefined, save: async (record) => {
    if (first) { first = false; markSaveStarted(); await firstSaveGate; }
    writes.push({ ...record, credential: record.credential.slice() });
  } };
  const identity = { deviceId: 'host', keyId: 'a'.repeat(64), keyEpoch: 1n,
    signatureAlgorithm: SignatureAlgorithm.ECDSA_P256_SHA256, signingPublicKey: new Uint8Array(65) };
  const lifecycle = new CredentialLifecycle(store);
  const completion = { credential: new Uint8Array(32).fill(7), deviceId: 'device', hostIdentity: identity,
    sessionKeyId: 'b'.repeat(64), sessionKeyEpoch: 1n };
  const install = lifecycle.install(lifecycle.owner(), 'c'.repeat(32), completion);
  await firstSaveStarted; lifecycle.supersede(); releaseFirstSave();
  await assert.rejects(install, /superseded/);
  assert.equal(completion.credential.every((byte) => byte === 0), true);
  assert.equal(writes.at(-1).revoked, true); assert.equal(writes.at(-1).credential.length, 0);
  assert.throws(() => lifecycle.authorize(), /No authorized/);

  const failedSecret = new Uint8Array(32).fill(8);
  const failed = new CredentialLifecycle({ load: async () => undefined, save: async () => { throw new Error('disk full'); } });
  await assert.rejects(failed.install(failed.owner(), 'd'.repeat(32), { ...completion, credential: failedSecret }), /disk full/);
  assert.equal(failedSecret.every((byte) => byte === 0), true);

  const oldRecord = { version: 1, pairingId: 'e'.repeat(32), deviceId: 'device', hostIdentity: identity,
    credential: new Uint8Array(32).fill(9), sessionKeyId: 'f'.repeat(64), sessionKeyEpoch: 1n,
    highestControlSequence: 0n, revoked: false, revocationReason: '' };
  const replacing = new CredentialLifecycle({ load: async () => oldRecord,
    save: async () => { throw new Error('uncertain write'); } }, () => true);
  await replacing.restore(); const replacementOwner = replacing.owner();
  const replacement = { ...completion, credential: new Uint8Array(32).fill(10) };
  await assert.rejects(replacing.install(replacementOwner, 'a'.repeat(32), replacement), /uncertain write/);
  assert.throws(() => replacing.authorize(), /No authorized/);

  let releaseLoad;
  let markLoadStarted;
  const loadStarted = new Promise((resolve) => { markLoadStarted = resolve; });
  const loadGate = new Promise((resolve) => { releaseLoad = resolve; });
  const restoredRecord = { version: 1, pairingId: 'e'.repeat(32), deviceId: 'device', hostIdentity: identity,
    credential: new Uint8Array(32).fill(9), sessionKeyId: 'f'.repeat(64), sessionKeyEpoch: 1n,
    highestControlSequence: 0n, revoked: false, revocationReason: '' };
  const restoring = new CredentialLifecycle({ load: async () => { markLoadStarted(); await loadGate; return restoredRecord; },
    save: async () => {} }, () => true);
  const restore = restoring.restore();
  await loadStarted; restoring.supersede(); releaseLoad(); await restore;
  assert.throws(() => restoring.authorize(), /No authorized/);

  const unverified = new CredentialLifecycle({ load: async () => restoredRecord, save: async () => {} });
  await assert.rejects(unverified.restore(), /Stored host identity cannot be verified/);

  let releaseSequenceSave;
  let markSequenceSaveStarted;
  const sequenceSaveStarted = new Promise((resolve) => { markSequenceSaveStarted = resolve; });
  const sequenceSaveGate = new Promise((resolve) => { releaseSequenceSave = resolve; });
  const concurrentWrites = [];
  let blockNextSave = true;
  const concurrent = new CredentialLifecycle({ load: async () => restoredRecord, save: async (record) => {
    if (blockNextSave) { blockNextSave = false; markSequenceSaveStarted(); await sequenceSaveGate; }
    concurrentWrites.push({ ...record, credential: record.credential.slice() });
  } }, () => true);
  await concurrent.restore();
  const sequenceUpdate = concurrent.acceptAuthenticatedControlSequence(1n);
  await sequenceSaveStarted;
  const revocation = concurrent.revoke('device', 'user_revoked');
  const replacementSecret = new Uint8Array(32).fill(10);
  const replacementInstall = concurrent.install(concurrent.owner(), 'a'.repeat(32),
    { ...completion, credential: replacementSecret });
  releaseSequenceSave();
  await assert.rejects(sequenceUpdate, /superseded/);
  await assert.rejects(revocation, /superseded/);
  await replacementInstall;
  assert.equal(concurrentWrites.some((record) => record.revoked), false);
  assert.equal(concurrent.authorize().credential.every((byte) => byte === 10), true);
});

function controlEnvelope(messageId, payloadField, payload, sessionScoped = true, correlationId = 1n) {
  const envelope = new ProtobufWriter().uint32(1, 1).uint64(2, messageId).uint64(3, correlationId);
  if (sessionScoped) envelope.bytesField(4, sessionId).uint64(5, 7n);
  return envelope.message(payloadField, payload).finish();
}

function touchOnlyStreamingSession() {
  const session = sessionAwaitingVideoConfiguration([Capability.TOUCH]);
  const configure = session.receive(fixture('video_config.binpb'), 8n)[0];
  finishVideoConfiguration(session, configure);
  return session;
}

function sessionAwaitingVideoConfiguration(negotiated = [Capability.TOUCH, Capability.KEYBOARD,
  Capability.POINTER, Capability.TELEMETRY], offered = [Capability.TOUCH, Capability.KEYBOARD,
  Capability.POINTER, Capability.TELEMETRY]) {
  const session = new ProductSession('harmony-test', 'Harmony test',
    offered, [Codec.HEVC, Codec.H264]);
  confirmRequest(session, session.start(1n)[0], 1n);
  const host = new ProtobufWriter().uint32(1, 1).packedVarints(4, offered).packedVarints(5, [Codec.HEVC, Codec.H264]);
  session.receive(controlEnvelope(2n, 21, host, false), 2n);
  const accepted = new ProtobufWriter().bytesField(1, sessionId).uint64(2, 7n).uint32(3, 1000)
    .packedVarints(4, negotiated);
  const acceptedActions = session.receive(controlEnvelope(3n, 22, accepted), 3n);
  confirmRequest(session, acceptedActions[1], 4n);
  confirmRequest(session, session.receive(fixture('list_displays_response.binpb'), 5n)[0], 6n);
  session.receive(fixture('start_display_response.binpb'), 7n);
  return session;
}

const frame = (frameId, epoch = 1n, keyframe = false) => ({
  frameId, epoch, timestampNs: frameId, keyframe, payload: new Uint8Array([Number(frameId)])
});

test('decoder ingress waits for one keyframe request and preserves a pending keyframe', () => {
  const queue = new LatestFrameQueue();
  assert.equal(queue.reset(1n).requestKeyframe, true);
  assert.equal(queue.offer(frame(1n)).requestKeyframe, false);
  assert.equal(queue.offer(frame(2n)).requestKeyframe, false);
  assert.equal(queue.offer(frame(3n, 1n, true)).accepted, true);
  assert.equal(queue.offer(frame(4n)).accepted, false);
  assert.equal(queue.state(), FrameQueueState.KEYFRAME_PENDING);
  assert.equal(queue.beginPush().frameId, 3n);
  assert.equal(queue.beginPush(), undefined);
  queue.completePush(true);
  assert.equal(queue.state(), FrameQueueState.DECODABLE);
});

test('decoder ingress only recovers after keyframe push succeeds', () => {
  const queue = new LatestFrameQueue(); queue.reset(1n);
  queue.offer(frame(10n, 1n, true)); assert.equal(queue.beginPush().frameId, 10n);
  assert.equal(queue.offer(frame(11n)).accepted, true);
  assert.equal(queue.state(), FrameQueueState.KEYFRAME_PENDING);
  assert.equal(queue.beginPush(), undefined);
  queue.completePush(true);
  assert.equal(queue.state(), FrameQueueState.DECODABLE);
  assert.equal(queue.beginPush().frameId, 11n);
  assert.equal(queue.offer(frame(12n)).accepted, true);
  const failed = queue.completePush(false);
  assert.equal(failed.requestKeyframe, true);
  assert.equal(queue.state(), FrameQueueState.WAITING_FOR_KEYFRAME);
  assert.equal(queue.offer(frame(13n)).requestKeyframe, false);
  queue.offer(frame(14n, 1n, true)); queue.beginPush(); queue.completePush(true);
  assert.equal(queue.state(), FrameQueueState.DECODABLE);
});

test('delta reference loss clears the capacity-one backlog and requests one refresh', () => {
  const queue = new LatestFrameQueue(); queue.reset(1n);
  queue.offer(frame(1n, 1n, true)); queue.beginPush(); queue.completePush(true);
  assert.equal(queue.offer(frame(2n)).accepted, true);
  const overflow = queue.offer(frame(3n));
  assert.deepEqual(overflow, { accepted: false, dropped: 2, requestKeyframe: true });
  assert.equal(queue.depth(), 0);
  assert.equal(queue.offer(frame(4n)).requestKeyframe, false);

  const gap = new LatestFrameQueue(); gap.reset(1n);
  gap.offer(frame(10n, 1n, true)); gap.beginPush(); gap.completePush(true);
  assert.deepEqual(gap.offer(frame(12n)), { accepted: false, dropped: 1, requestKeyframe: true });
  assert.equal(gap.state(), FrameQueueState.WAITING_FOR_KEYFRAME);
});

test('push failure and reset discard dependent work and re-arm refresh requests', () => {
  const queue = new LatestFrameQueue(); queue.reset(1n);
  queue.offer(frame(1n, 1n, true)); queue.beginPush();
  const failure = queue.completePush(false);
  assert.equal(failure.requestKeyframe, true);
  assert.equal(queue.state(), FrameQueueState.WAITING_FOR_KEYFRAME);
  queue.offer(frame(2n, 1n, true)); queue.beginPush(); queue.completePush(true);
  const reset = queue.reset(2n);
  assert.equal(reset.requestKeyframe, true);
  assert.equal(queue.offer(frame(3n, 1n, true)).accepted, false);
  assert.equal(queue.offer(frame(1n, 2n)).requestKeyframe, false);
});

test('stylus encoder matches the shared base and extended formal fixtures', () => {
  const base = new ProtocolEncoder().stylus(ProtocolEncoder.metadata(15n,
    new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8]), 7n, 1000000015n), {
      inputId: 101n, pointerId: 7, phase: InputPhase.CHANGED, x: 0.125, y: 0.875,
      pressure: 0.625, tiltXDegrees: -12.5, tiltYDegrees: 28.75
    }, { displayId: 'display-main', streamId: 42n });
  assert.deepEqual(base, fixture('stylus.binpb'));

  const extended = new ProtocolEncoder().stylus(ProtocolEncoder.metadata(16n,
    new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8]), 7n, 1000000016n), {
      inputId: 102n, pointerId: 8, phase: InputPhase.CHANGED, x: 0.75, y: 0.25,
      pressure: 0.0, tiltXDegrees: 10.0, tiltYDegrees: -20.0,
      toolKind: StylusToolKind.ERASER, buttonMask: 3, contactState: StylusContactState.PROXIMITY
    }, { displayId: 'display-main', streamId: 42n });
  assert.deepEqual(extended, fixture('stylus_extended.binpb'));
});

test('controller encoder matches formal lifecycle and state fixtures', () => {
  const encoder = new ProtocolEncoder();
  const target = { displayId: 'display-main', streamId: 42n };
  assert.deepEqual(encoder.controller(ProtocolEncoder.metadata(21n, sessionId, 7n, 1000000021n), {
    inputId: 103n, controllerId: 'controller-xbox-1', controllerEpoch: 1n, kind: ControllerEventKind.CONNECTED,
    buttonMask: 0, leftStickX: 0, leftStickY: 0, rightStickX: 0, rightStickY: 0, leftTrigger: 0,
    rightTrigger: 0, hatX: 0, hatY: 0
  }, target), fixture('controller_connected.binpb'));
  assert.deepEqual(encoder.controller(ProtocolEncoder.metadata(22n, sessionId, 7n, 1000000022n), {
    inputId: 104n, controllerId: 'controller-xbox-1', controllerEpoch: 1n, kind: ControllerEventKind.STATE,
    buttonMask: 4101, leftStickX: -0.75, leftStickY: 0.5, rightStickX: 0.25, rightStickY: -0.125,
    leftTrigger: 0.375, rightTrigger: 0.875, hatX: 1, hatY: -1
  }, target), fixture('controller_state.binpb'));
  assert.deepEqual(encoder.controller(ProtocolEncoder.metadata(23n, sessionId, 7n, 1000000023n), {
    inputId: 105n, controllerId: 'controller-xbox-1', controllerEpoch: 1n, kind: ControllerEventKind.DISCONNECTED,
    buttonMask: 0, leftStickX: 0, leftStickY: 0, rightStickX: 0, rightStickY: 0, leftTrigger: 0,
    rightTrigger: 0, hatX: 0, hatY: 0
  }, target), fixture('controller_disconnected.binpb'));
});

test('controller mapper rejects invalid scalar fields and neutral lifecycle violations', () => {
  const mapper = new ControllerInputMapper();
  const valid = { controllerId: 'controller-1', controllerEpoch: 1n, kind: ControllerEventKind.STATE };
  assert.throws(() => mapper.map(0n, valid), /inputId/);
  assert.throws(() => mapper.map(1n, { ...valid, controllerId: '' }), /id must be non-empty/);
  assert.throws(() => mapper.map(1n, { ...valid, controllerId: '手'.repeat(43) }), /at most 128/);
  assert.throws(() => mapper.map(1n, { ...valid, controllerEpoch: 0n }), /epoch/);
  assert.throws(() => mapper.map(1n, { ...valid, kind: ControllerEventKind.UNSPECIFIED }), /kind/);
  assert.throws(() => mapper.map(1n, { ...valid, buttonMask: 0x2000 }), /button bits/);
  assert.throws(() => mapper.map(1n, { ...valid, leftStickX: 1.1 }), /stick axes/);
  assert.throws(() => mapper.map(1n, { ...valid, rightTrigger: Number.NaN }), /triggers/);
  assert.throws(() => mapper.map(1n, { ...valid, hatY: 2 }), /hat axes/);
  assert.throws(() => mapper.map(1n, { ...valid, kind: ControllerEventKind.CONNECTED, buttonMask: 1 }), /neutral/);
  const neutral = mapper.neutralDisconnect(2n, mapper.map(1n, { ...valid, buttonMask: 1, hatX: -1 }));
  assert.equal(neutral.kind, ControllerEventKind.DISCONNECTED);
  assert.equal(neutral.buttonMask, 0);
  assert.equal(neutral.hatX, 0);
});

test('Harmony advertised capabilities omit stylus extended and its dependency fails closed', () => {
  assert.equal(HARMONY_ADVERTISED_CAPABILITIES.includes(Capability.STYLUS_EXTENDED), false);
  assert.equal(HARMONY_ADVERTISED_CAPABILITIES.includes(Capability.STYLUS), true);

  assert.throws(() => new ClientCapabilities([Capability.TOUCH, Capability.STYLUS_EXTENDED], [Capability.TOUCH]),
    /Invalid client capability declaration/);

  const hostMissingBase = new ClientCapabilities([Capability.TOUCH, Capability.STYLUS], [Capability.TOUCH]);
  assert.throws(() => hostMissingBase.acceptHost([Capability.TOUCH, Capability.STYLUS_EXTENDED]),
    /Host lacks a required client capability/);

  const negotiatedMissingBase = new ClientCapabilities(
    [Capability.TOUCH, Capability.STYLUS, Capability.STYLUS_EXTENDED], [Capability.TOUCH]);
  negotiatedMissingBase.acceptHost([Capability.TOUCH, Capability.STYLUS, Capability.STYLUS_EXTENDED]);
  assert.throws(() => negotiatedMissingBase.acceptNegotiated([Capability.TOUCH, Capability.STYLUS_EXTENDED]),
    /invalid negotiated capability set/);

  const restoreMissingBase = new ClientCapabilities(
    [Capability.TOUCH, Capability.STYLUS, Capability.STYLUS_EXTENDED], [Capability.TOUCH]);
  assert.throws(() => restoreMissingBase.restore(
    [Capability.TOUCH, Capability.STYLUS_EXTENDED], [Capability.TOUCH, Capability.STYLUS_EXTENDED]),
    /Host lacks a required client capability/);
});

test('stylus mapper routes contacting pen through touch or stylus and suppresses extended-only semantics', () => {
  const mapper = new StylusInputMapper();
  const contactingPen = {
    pointerId: 1, phase: InputPhase.BEGAN, x: 0.5, y: 0.5, pressure: 0.5,
    tiltXDegrees: 0, tiltYDegrees: 0, toolKind: StylusToolKind.PEN,
    contactState: StylusContactState.CONTACT
  };

  assert.equal(mapper.route(contactingPen, false, false), 'touch');
  assert.equal(mapper.route(contactingPen, true, false), 'stylus');
  assert.equal(mapper.route({ ...contactingPen, toolKind: undefined, contactState: undefined }, false, false), 'touch');
  assert.equal(mapper.route({ ...contactingPen, toolKind: undefined, contactState: undefined }, true, false), 'stylus');

  const eraser = { ...contactingPen, toolKind: StylusToolKind.ERASER };
  assert.equal(mapper.route(eraser, true, false), 'suppress');
  assert.equal(mapper.route(eraser, true, true), 'stylus');

  const proximity = { ...contactingPen, contactState: StylusContactState.PROXIMITY };
  assert.equal(mapper.route(proximity, true, false), 'suppress');
  assert.equal(mapper.route(proximity, true, true), 'stylus');

  const buttoned = { ...contactingPen, buttonMask: 1 };
  assert.equal(mapper.route(buttoned, true, false), 'suppress');
  assert.equal(mapper.route(buttoned, true, true), 'stylus');

  assert.equal(mapper.route({ ...contactingPen, toolKind: StylusToolKind.UNSPECIFIED }, true, true), 'suppress');
});

test('stylus mapper rejects illegal phase, id, pointer, coordinates, pressure, tilt and hypot', () => {
  const mapper = new StylusInputMapper();
  const valid = {
    pointerId: 1, phase: InputPhase.BEGAN, x: 0.5, y: 0.5, pressure: 0.5,
    tiltXDegrees: 0, tiltYDegrees: 0
  };

  assert.throws(() => mapper.map(0n, valid, false), /inputId must be a positive uint64/);
  assert.throws(() => mapper.map(-1n, valid, false), /inputId must be a positive uint64/);
  assert.throws(() => mapper.map(0x10000000000000000n, valid, false), /inputId must be a positive uint64/);
  assert.throws(() => mapper.map(1n, { ...valid, pointerId: -1 }, false), /pointerId/);
  assert.throws(() => mapper.map(1n, { ...valid, pointerId: 1.5 }, false), /pointerId/);
  assert.throws(() => mapper.map(1n, { ...valid, pointerId: 0x100000000 }, false), /pointerId/);
  assert.throws(() => mapper.map(1n, { ...valid, phase: InputPhase.UNSPECIFIED }, false), /phase/);
  assert.throws(() => mapper.map(1n, { ...valid, phase: InputPhase.CANCELLED + 1 }, false), /phase/);
  assert.throws(() => mapper.map(1n, { ...valid, x: -0.1 }, false), /x must be/);
  assert.throws(() => mapper.map(1n, { ...valid, x: 1.1 }, false), /x must be/);
  assert.throws(() => mapper.map(1n, { ...valid, x: Number.NaN }, false), /x must be/);
  assert.throws(() => mapper.map(1n, { ...valid, y: 2 }, false), /y must be/);
  assert.throws(() => mapper.map(1n, { ...valid, pressure: 1.5 }, false), /pressure/);
  assert.throws(() => mapper.map(1n, { ...valid, tiltXDegrees: 91 }, false), /tiltX/);
  assert.throws(() => mapper.map(1n, { ...valid, tiltYDegrees: -91 }, false), /tiltY/);
  assert.throws(() => mapper.map(1n, { ...valid, tiltXDegrees: 70, tiltYDegrees: 70 }, false), /tilt vector magnitude/);
  assert.throws(() => mapper.map(1n, { ...valid, toolKind: 3 }, false), /toolKind must be PEN or ERASER/);
  assert.throws(() => mapper.map(1n, { ...valid, contactState: 3 }, false), /contactState must be CONTACT or PROXIMITY/);
  assert.throws(() => mapper.map(1n, { ...valid, toolKind: StylusToolKind.ERASER }, false), /require STYLUS_EXTENDED/);
  assert.throws(() => mapper.map(1n, { ...valid, contactState: StylusContactState.PROXIMITY }, false), /require STYLUS_EXTENDED/);
  assert.throws(() => mapper.map(1n, { ...valid, buttonMask: 1 }, false), /require STYLUS_EXTENDED/);
  assert.throws(() => mapper.map(1n, { ...valid, buttonMask: 1.5 }, true), /buttonMask/);
  assert.throws(() => mapper.map(1n, { ...valid, buttonMask: 0x100000000 }, true), /buttonMask/);

  const terminal = mapper.map(1n, { ...valid, phase: InputPhase.ENDED, pressure: 0.5 }, false);
  assert.equal(terminal.pressure, 0);
  const proximitySample = mapper.map(1n, { ...valid, contactState: StylusContactState.PROXIMITY, pressure: 0.5 }, true);
  assert.equal(proximitySample.pressure, 0);
});

test('stylus mapper validate rejects reserved extended enum, button and proximity values', () => {
  const mapper = new StylusInputMapper();
  const baseEvent = {
    inputId: 1n, pointerId: 1, phase: InputPhase.CHANGED, x: 0.5, y: 0.5,
    pressure: 0.5, tiltXDegrees: 0, tiltYDegrees: 0
  };

  assert.throws(() => mapper.validate({ ...baseEvent, toolKind: StylusToolKind.PEN }, false), /toolKind must be omitted/);
  assert.throws(() => mapper.validate({ ...baseEvent, buttonMask: 0 }, false), /buttonMask must be omitted/);
  assert.throws(() => mapper.validate({ ...baseEvent, contactState: StylusContactState.CONTACT }, false), /contactState must be omitted/);

  assert.throws(() => mapper.validate({ ...baseEvent, toolKind: 3, buttonMask: 0,
    contactState: StylusContactState.CONTACT }, true), /toolKind must be PEN or ERASER/);
  assert.throws(() => mapper.validate({ ...baseEvent, toolKind: StylusToolKind.PEN, buttonMask: 4,
    contactState: StylusContactState.CONTACT }, true), /buttonMask may only contain bits 0 and 1/);
  assert.throws(() => mapper.validate({ ...baseEvent, toolKind: StylusToolKind.PEN, buttonMask: 0,
    contactState: 3 }, true), /contactState must be CONTACT or PROXIMITY/);
  assert.throws(() => mapper.validate({ ...baseEvent, toolKind: StylusToolKind.PEN, buttonMask: 0,
    contactState: StylusContactState.PROXIMITY, pressure: 0.1 }, true), /PROXIMITY samples must have zero pressure/);

  mapper.validate({ ...baseEvent, toolKind: StylusToolKind.ERASER, buttonMask: 3,
    contactState: StylusContactState.PROXIMITY, pressure: 0 }, true);
});

test('product session gates stylus on negotiated base and extended capabilities', () => {
  const noStylus = createStreamingSessionWithCapabilities([Capability.TOUCH], [Capability.TOUCH]);
  assert.throws(() => noStylus.stylus({ inputId: 1n, pointerId: 1, phase: InputPhase.BEGAN,
    x: 0.5, y: 0.5, pressure: 0.5, tiltXDegrees: 0, tiltYDegrees: 0 }), /was not negotiated/);

  const baseOnly = createStreamingSessionWithCapabilities(
    [Capability.TOUCH, Capability.STYLUS], [Capability.TOUCH, Capability.STYLUS]);
  const baseEvent = { inputId: 1n, pointerId: 1, phase: InputPhase.BEGAN, x: 0.5, y: 0.5,
    pressure: 0.5, tiltXDegrees: 0, tiltYDegrees: 0 };
  assert.equal(confirmStylus(baseOnly, baseOnly.stylus(baseEvent)).intent.kind, 'stylus');
  assert.throws(() => baseOnly.stylus({ ...baseEvent, inputId: 2n, toolKind: StylusToolKind.ERASER }),
    /was not negotiated/);

  const both = createStreamingSessionWithCapabilities(
    [Capability.TOUCH, Capability.STYLUS, Capability.STYLUS_EXTENDED],
    [Capability.TOUCH, Capability.STYLUS, Capability.STYLUS_EXTENDED]);
  const extended = both.stylus({ ...baseEvent, inputId: 2n, pointerId: 2, toolKind: StylusToolKind.ERASER,
    buttonMask: 1, contactState: StylusContactState.CONTACT });
  assert.equal(confirmStylus(both, extended).intent.kind, 'stylus');
});

test('product session gates controller input on negotiated capability and Host ack', () => {
  const noController = createStreamingSessionWithCapabilities([Capability.TOUCH], [Capability.TOUCH]);
  assert.throws(() => noController.controller({ inputId: 1n, controllerId: 'pad-1', controllerEpoch: 1n,
    kind: ControllerEventKind.CONNECTED, buttonMask: 0, leftStickX: 0, leftStickY: 0, rightStickX: 0,
    rightStickY: 0, leftTrigger: 0, rightTrigger: 0, hatX: 0, hatY: 0 }), /was not negotiated/);

  const session = createStreamingSessionWithCapabilities([Capability.TOUCH, Capability.CONTROLLER],
    [Capability.TOUCH, Capability.CONTROLLER]);
  const connected = session.controller({ inputId: 1n, controllerId: 'pad-1', controllerEpoch: 1n,
    kind: ControllerEventKind.CONNECTED, buttonMask: 0, leftStickX: 0, leftStickY: 0, rightStickX: 0,
    rightStickY: 0, leftTrigger: 0, rightTrigger: 0, hatX: 0, hatY: 0 });
  assert.equal(connected.intent.kind, 'controller');
  confirmController(session, connected, 30n);
  assert.throws(() => session.controller({ inputId: 2n, controllerId: 'pad-1', controllerEpoch: 1n,
    kind: ControllerEventKind.STATE, buttonMask: 1, leftStickX: 0, leftStickY: 0, rightStickX: 0,
    rightStickY: 0, leftTrigger: 0, rightTrigger: 0, hatX: 0, hatY: 0 }), /Invalid controller lifecycle/);
  session.receive(inputAckEnvelope(31n, 30n, 1n), 31n);
  const state = session.controller({ inputId: 3n, controllerId: 'pad-1', controllerEpoch: 1n,
    kind: ControllerEventKind.STATE, buttonMask: 1, leftStickX: -0.25, leftStickY: 0.5, rightStickX: 0,
    rightStickY: 0, leftTrigger: 0.25, rightTrigger: 0, hatX: 1, hatY: -1 });
  assert.equal(confirmController(session, state).intent.event.hatY, -1);
});

test('product session controller release sends neutral disconnect and blocks resume until written', () => {
  const session = createStreamingSessionWithCapabilities(
    [Capability.TOUCH, Capability.CONTROLLER, Capability.SESSION_RESUME],
    [Capability.TOUCH, Capability.CONTROLLER, Capability.SESSION_RESUME]);
  assert.notEqual(session.resumableSnapshot(20n), undefined);
  const connected = session.controller({ inputId: 1n, controllerId: 'pad-1', controllerEpoch: 1n,
    kind: ControllerEventKind.CONNECTED, buttonMask: 0, leftStickX: 0, leftStickY: 0, rightStickX: 0,
    rightStickY: 0, leftTrigger: 0, rightTrigger: 0, hatX: 0, hatY: 0 });
  confirmController(session, connected, 40n);
  assert.equal(session.resumableSnapshot(21n), undefined);
  session.receive(inputAckEnvelope(41n, 40n, 1n), 41n);
  assert.equal(session.resumableSnapshot(22n), undefined);
  confirmController(session, session.controller({ inputId: 2n, controllerId: 'pad-1', controllerEpoch: 1n,
    kind: ControllerEventKind.STATE, buttonMask: 4101, leftStickX: -0.75, leftStickY: 0.5, rightStickX: 0.25,
    rightStickY: -0.125, leftTrigger: 0.375, rightTrigger: 0.875, hatX: 1, hatY: -1 }));
  const releases = session.releaseControllerInputs(() => 10n);
  assert.equal(releases.length, 1);
  assert.equal(releases[0].intent.event.kind, ControllerEventKind.DISCONNECTED);
  assert.equal(releases[0].intent.event.buttonMask, 0);
  assert.equal(releases[0].intent.event.leftStickX, 0);
  assert.equal(releases[0].intent.event.rightTrigger, 0);
  assert.equal(releases[0].intent.event.hatX, 0);
  assert.equal(session.resumableSnapshot(23n), undefined);
  assert.throws(() => session.completeControllerRelease(), /incomplete/);
  assert.throws(() => session.controller({ inputId: 11n, controllerId: 'pad-1', controllerEpoch: 1n,
    kind: ControllerEventKind.STATE, buttonMask: 0, leftStickX: 0, leftStickY: 0, rightStickX: 0,
    rightStickY: 0, leftTrigger: 0, rightTrigger: 0, hatX: 0, hatY: 0 }), /Controller input is closing/);
  confirmController(session, releases[0]);
  session.completeControllerRelease();
  assert.notEqual(session.resumableSnapshot(23n), undefined);
});

test('product session enforces controller lifecycle bounds and rejected ack cleanup', () => {
  const session = createStreamingSessionWithCapabilities([Capability.TOUCH, Capability.CONTROLLER],
    [Capability.TOUCH, Capability.CONTROLLER]);
  const connect = (id, inputId, messageId) => {
    const action = session.controller({ inputId: BigInt(inputId), controllerId: id, controllerEpoch: 1n,
      kind: ControllerEventKind.CONNECTED, buttonMask: 0, leftStickX: 0, leftStickY: 0, rightStickX: 0,
      rightStickY: 0, leftTrigger: 0, rightTrigger: 0, hatX: 0, hatY: 0 });
    confirmController(session, action, BigInt(messageId));
    session.receive(inputAckEnvelope(BigInt(messageId + 100), BigInt(messageId), BigInt(inputId)), BigInt(messageId + 100));
  };
  connect('pad-1', 1, 51); connect('pad-2', 2, 52); connect('pad-3', 3, 53); connect('pad-4', 4, 54);
  assert.throws(() => session.controller({ inputId: 5n, controllerId: 'pad-5', controllerEpoch: 1n,
    kind: ControllerEventKind.CONNECTED, buttonMask: 0, leftStickX: 0, leftStickY: 0, rightStickX: 0,
    rightStickY: 0, leftTrigger: 0, rightTrigger: 0, hatX: 0, hatY: 0 }),
  new RegExp(MAXIMUM_ACTIVE_CONTROLLERS_REJECTION_REASON));
  assert.throws(() => session.controller({ inputId: 4n, controllerId: 'pad-1', controllerEpoch: 1n,
    kind: ControllerEventKind.STATE, buttonMask: 0, leftStickX: 0, leftStickY: 0, rightStickX: 0,
    rightStickY: 0, leftTrigger: 0, rightTrigger: 0, hatX: 0, hatY: 0 }), /strictly increase/);
});

test('cancelled pending controller connect releases admission state', () => {
  const session = createStreamingSessionWithCapabilities(
    [Capability.TOUCH, Capability.CONTROLLER, Capability.SESSION_RESUME],
    [Capability.TOUCH, Capability.CONTROLLER, Capability.SESSION_RESUME]);
  const connected = session.controller({ inputId: 1n, controllerId: 'pad-1', controllerEpoch: 1n,
    kind: ControllerEventKind.CONNECTED, buttonMask: 0, leftStickX: 0, leftStickY: 0, rightStickX: 0,
    rightStickY: 0, leftTrigger: 0, rightTrigger: 0, hatX: 0, hatY: 0 });
  confirmController(session, connected, 70n);
  assert.equal(session.resumableSnapshot(71n), undefined);
  session.cancelControllerSend(connected.afterSend.event);
  assert.doesNotThrow(() => session.completeControllerRelease());
  assert.notEqual(session.resumableSnapshot(71n), undefined);
});

test('product session enforces stylus lifecycle and release cancels active inputs', () => {
  const session = createStreamingSessionWithCapabilities(
    [Capability.TOUCH, Capability.STYLUS, Capability.STYLUS_EXTENDED],
    [Capability.TOUCH, Capability.STYLUS, Capability.STYLUS_EXTENDED]);
  const base = { pointerId: 1, phase: InputPhase.BEGAN, x: 0.5, y: 0.5,
    pressure: 0.5, tiltXDegrees: 0, tiltYDegrees: 0 };

  assert.throws(() => session.stylus({ ...base, inputId: 1n, phase: InputPhase.CHANGED }), /Invalid stylus lifecycle/);
  assert.throws(() => session.stylus({ ...base, inputId: 1n, phase: InputPhase.ENDED, pressure: 0 }), /Invalid stylus lifecycle/);

  const began = session.stylus({ ...base, inputId: 1n });
  assert.equal(confirmStylus(session, began).intent.kind, 'stylus');
  assert.throws(() => session.stylus({ ...base, inputId: 2n }), /Invalid stylus lifecycle/);
  assert.throws(() => session.stylus({ ...base, inputId: 2n, pointerId: 2 }), /Invalid stylus lifecycle/);
  const changed = session.stylus({ ...base, inputId: 3n, phase: InputPhase.CHANGED });
  assert.equal(confirmStylus(session, changed).intent.kind, 'stylus');
  const ended = session.stylus({ ...base, inputId: 4n, phase: InputPhase.ENDED, pressure: 0 });
  assert.equal(confirmStylus(session, ended).intent.kind, 'stylus');
  assert.throws(() => session.stylus({ ...base, inputId: 5n, phase: InputPhase.CHANGED }), /Invalid stylus lifecycle/);

  confirmStylus(session, session.stylus({ ...base, inputId: 10n, pointerId: 5, toolKind: StylusToolKind.ERASER,
    buttonMask: 1, contactState: StylusContactState.PROXIMITY, pressure: 0 }));
  assert.throws(() => session.stylus({ ...base, inputId: 11n, pointerId: 5, phase: InputPhase.CHANGED,
    toolKind: StylusToolKind.PEN, buttonMask: 1, contactState: StylusContactState.PROXIMITY, pressure: 0 }),
  /Invalid stylus lifecycle/);
  assert.throws(() => session.stylus({ ...base, inputId: 12n, pointerId: 5, phase: InputPhase.CHANGED,
    toolKind: StylusToolKind.ERASER, buttonMask: 1, contactState: StylusContactState.CONTACT }),
  /Invalid stylus lifecycle/);
  let nextId = 100n;
  const releases = session.releaseStylusInputs(() => nextId++);
  assert.equal(releases.length, 1);
  assert.equal(releases[0].intent.event.pointerId, 5);
  assert.equal(releases[0].intent.event.phase, InputPhase.CANCELLED);
  assert.equal(releases[0].intent.event.pressure, 0);
  assert.equal(releases[0].intent.event.toolKind, StylusToolKind.ERASER);
  assert.equal(releases[0].intent.event.buttonMask, 0);
  assert.equal(releases[0].intent.event.contactState, StylusContactState.PROXIMITY);
  assert.throws(() => session.completeStylusRelease(), /incomplete/);
  assert.throws(() => session.stylus({ ...base, inputId: 200n, pointerId: 5, phase: InputPhase.CHANGED }),
    /Stylus input is closing/);
  confirmStylus(session, releases[0]);
  session.completeStylusRelease();

  assert.throws(() => session.stylus({ ...base, inputId: 201n, pointerId: 5, phase: InputPhase.CHANGED }),
    /Invalid stylus lifecycle/);
});

test('product session releaseStylusInputs clears state outside streaming and is idempotent', () => {
  const session = createStreamingSessionWithCapabilities(
    [Capability.TOUCH, Capability.STYLUS], [Capability.TOUCH, Capability.STYLUS]);
  confirmStylus(session, session.stylus({ inputId: 1n, pointerId: 1, phase: InputPhase.BEGAN, x: 0.5, y: 0.5,
    pressure: 0.5, tiltXDegrees: 0, tiltYDegrees: 0 }));
  session.close();
  assert.deepEqual(session.releaseStylusInputs(() => 9n), []);
});

test('stylus terminal send must be confirmed before resume is allowed', () => {
  const session = createStreamingSessionWithCapabilities(
    [Capability.TOUCH, Capability.STYLUS, Capability.SESSION_RESUME],
    [Capability.TOUCH, Capability.STYLUS, Capability.SESSION_RESUME]);
  const began = session.stylus({ inputId: 1n, pointerId: 1, phase: InputPhase.BEGAN, x: 0.5, y: 0.5,
    pressure: 0.5, tiltXDegrees: 0, tiltYDegrees: 0 });
  confirmStylus(session, began);
  const ended = session.stylus({ inputId: 2n, pointerId: 1, phase: InputPhase.ENDED, x: 0.5, y: 0.5,
    pressure: 0, tiltXDegrees: 0, tiltYDegrees: 0 });
  assert.equal(session.resumableSnapshot(20n), undefined);
  confirmStylus(session, ended);
  assert.notEqual(session.resumableSnapshot(20n), undefined);
});

test('active stylus state disables resume until its release is written', () => {
  const session = createStreamingSessionWithCapabilities(
    [Capability.TOUCH, Capability.STYLUS, Capability.SESSION_RESUME],
    [Capability.TOUCH, Capability.STYLUS, Capability.SESSION_RESUME]);
  assert.notEqual(session.resumableSnapshot(20n), undefined);
  const began = session.stylus({ inputId: 1n, pointerId: 1, phase: InputPhase.BEGAN, x: 0.5, y: 0.5,
    pressure: 0.5, tiltXDegrees: 0, tiltYDegrees: 0 });
  assert.equal(session.resumableSnapshot(20n), undefined);
  confirmStylus(session, began);
  const release = session.releaseStylusInputs(() => 2n);
  assert.equal(release.length, 1);
  assert.equal(session.resumableSnapshot(21n), undefined);
  assert.throws(() => session.completeStylusRelease(), /incomplete/);
  confirmStylus(session, release[0]);
  session.completeStylusRelease();
  assert.notEqual(session.resumableSnapshot(21n), undefined);
});

test('outbound release preserves queued stylus state and drops unrelated traffic', async () => {
  const sent = [];
  const releases = [];
  const writer = new OutboundControlWriter((bytes) => {
    sent.push(new ProtocolDecoder().envelope(bytes));
    return new Promise((resolve) => releases.push(resolve));
  }, () => 1n);
  const scope = { sessionId, sessionEpoch: 7n };

  const inFlight = writer.enqueue({ kind: 'pointer', event: { inputId: 1n, pointerId: 0,
    phase: InputPhase.BEGAN, x: 0.5, y: 0.5, pressure: 0, tiltX: 0, tiltY: 0, buttonMask: 0 } }, scope);
  const queuedStylus = writer.enqueue({ kind: 'stylus', event: { inputId: 2n, pointerId: 7,
    phase: InputPhase.BEGAN, x: 0.5, y: 0.5, pressure: 0.5, tiltXDegrees: 0, tiltYDegrees: 0 } }, scope);
  const critical = writer.enqueue({ kind: 'ping', sequence: 1n }, scope);
  writer.beginRelease();
  const release = writer.enqueueRelease({ kind: 'stylus', event: { inputId: 3n, pointerId: 7,
    phase: InputPhase.CANCELLED, x: 0.5, y: 0.5, pressure: 0, tiltXDegrees: 0, tiltYDegrees: 0 } }, scope);
  const trailing = writer.enqueue({ kind: 'pointer', event: { inputId: 4n, pointerId: 0,
    phase: InputPhase.ENDED, x: 0.5, y: 0.5, pressure: 0, tiltX: 0, tiltY: 0, buttonMask: 0 } }, scope);
  await assert.rejects(critical, /releasing/);
  await assert.rejects(trailing, /releasing/);

  assert.equal(sent.length, 1);
  assert.equal(sent[0].payloadField, 61);

  releases.shift()(); await inFlight;
  assert.equal(sent[1].payloadField, 65);

  releases.shift()(); await queuedStylus;
  assert.equal(sent[2].payloadField, 65);

  releases.shift()(); await release;
  await writer.awaitReleaseDrain();
  assert.deepEqual(sent.map((envelope) => envelope.messageId), [1n, 2n, 3n]);
});

test('outbound writer assigns consecutive message ids starting from the configured first id', async () => {
  const sent = [];
  const releases = [];
  const writer = new OutboundControlWriter((bytes) => {
    sent.push(new ProtocolDecoder().envelope(bytes));
    return new Promise((resolve) => releases.push(resolve));
  }, () => 1n, 7n);
  const scope = { sessionId, sessionEpoch: 7n };

  const first = writer.enqueue({ kind: 'ping', sequence: 1n }, scope);
  releases.shift()(); await first;
  const second = writer.enqueue({ kind: 'pong', sequence: 1n, correlationId: 7n }, scope);
  releases.shift()(); await second;

  assert.deepEqual(sent.map((envelope) => envelope.messageId), [7n, 8n]);
  assert.equal(writer.nextMessageIdValue(), 9n);
});

function createStreamingSessionWithCapabilities(offered, negotiated) {
  const session = new ProductSession('harmony-test', 'Harmony test', offered, [Codec.HEVC, Codec.H264]);
  confirmRequest(session, session.start(1n)[0], 1n);
  const host = new ProtobufWriter().uint32(1, 1).packedVarints(4, offered).packedVarints(5, [Codec.HEVC, Codec.H264]);
  session.receive(controlEnvelope(2n, 21, host, false), 2n);
  const accepted = new ProtobufWriter().bytesField(1, sessionId).uint64(2, 7n).uint32(3, 1000)
    .packedVarints(4, negotiated);
  const acceptedActions = session.receive(controlEnvelope(3n, 22, accepted), 3n);
  confirmRequest(session, acceptedActions[1], 4n);
  confirmRequest(session, session.receive(fixture('list_displays_response.binpb'), 5n)[0], 6n);
  session.receive(fixture('start_display_response.binpb'), 7n);
  const configure = session.receive(fixture('video_config.binpb'), 8n)[0];
  finishVideoConfiguration(session, configure);
  return session;
}
