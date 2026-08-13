import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { CoordinateMapper, Rotation } from '../.test-dist/input/CoordinateMapper.js';
import { AdvancedPeripheralInputMapper, ControllerSessionState, NEUTRAL_CONTROLLER_STATE
} from '../.test-dist/input/AdvancedPeripheralInputMapper.js';
import { PeripheralInputMapper } from '../.test-dist/input/PeripheralInputMapper.js';
import { FrameQueueState, LatestFrameQueue } from '../.test-dist/media/LatestFrameQueue.js';
import { MediaPacketParser } from '../.test-dist/media/MediaPacketParser.js';
import { Capability, Codec, ColorPrimaries, ControllerEventKind, InputPhase, MatrixCoefficients,
  StylusContactState, StylusToolKind, TransferFunction, TransportKind
} from '../.test-dist/protocol/ProtocolModels.js';
import { ProtocolEncoder } from '../.test-dist/protocol/ProtocolEncoder.js';
import { ProtocolDecoder } from '../.test-dist/protocol/ProtocolDecoder.js';
import { MAX_PENDING_CONTROLS, OutboundControlWriter } from '../.test-dist/protocol/OutboundControlWriter.js';
import { ProtobufWriter } from '../.test-dist/protocol/ProtobufWriter.js';
import { decodeUtf8, encodeUtf8 } from '../.test-dist/protocol/Utf8.js';
import { ClientCapabilities, HARMONY_ADVERTISED_CAPABILITIES
} from '../.test-dist/session/ClientCapabilities.js';
import { HeartbeatMonitor } from '../.test-dist/session/HeartbeatMonitor.js';
import { ProgressWatchdog } from '../.test-dist/session/ProgressWatchdog.js';
import { isSupportedVideoConfig, ProductSession, ProductSessionState } from '../.test-dist/session/ProductSession.js';
import { ReconnectPolicy } from '../.test-dist/session/ReconnectPolicy.js';
import { SessionState, SessionStateMachine } from '../.test-dist/session/SessionStateMachine.js';
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
const confirmRequest = (session, action, messageId) => session.confirmAssigned(action.onAssigned, messageId, 1n);
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
  assert.equal(HARMONY_ADVERTISED_CAPABILITIES.includes(Capability.STYLUS), true);
  assert.equal(HARMONY_ADVERTISED_CAPABILITIES.includes(Capability.STYLUS_EXTENDED), false);
  assert.equal(HARMONY_ADVERTISED_CAPABILITIES.includes(Capability.CONTROLLER), false);
  assert.throws(() => new ClientCapabilities([Capability.TOUCH, Capability.STYLUS_EXTENDED], [Capability.TOUCH]),
    /Invalid client capability/);
  const invalidHost = new ClientCapabilities([Capability.TOUCH, Capability.STYLUS,
    Capability.STYLUS_EXTENDED], [Capability.TOUCH]);
  assert.throws(() => invalidHost.acceptHost([Capability.TOUCH, Capability.STYLUS_EXTENDED]),
    /invalid capability dependencies/);
  invalidHost.acceptHost([Capability.TOUCH, Capability.STYLUS, Capability.STYLUS_EXTENDED]);
  assert.throws(() => invalidHost.acceptNegotiated([Capability.TOUCH, Capability.STYLUS_EXTENDED]),
    /invalid negotiated/);

  const session = new ProductSession('touch-only', 'Touch only', [Capability.TOUCH], [Codec.HEVC]);
  confirmRequest(session, session.start(1n)[0], 1n);
  session.receive(controlEnvelope(2n, 21, new ProtobufWriter().uint32(1, 1)
    .packedVarints(4, [Capability.TOUCH]).packedVarints(5, [Codec.HEVC]), false), 2n);
  assert.throws(() => session.receive(fixture('session_accepted.binpb'), 3n), /invalid negotiated/);
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

test('product session gates advanced input and releases active state neutrally', () => {
  const unavailable = createStreamingSession();
  const stylus = { inputId: 1n, pointerId: 7, phase: InputPhase.BEGAN, x: 0.5, y: 0.5,
    pressure: 0.5, tiltXDegrees: 0, tiltYDegrees: 0 };
  assert.throws(() => unavailable.stylus(stylus), /was not negotiated/);

  const session = advancedStreamingSession();
  assert.equal(session.stylus({ ...stylus, toolKind: StylusToolKind.PEN, buttonMask: 1,
    contactState: StylusContactState.CONTACT }).intent.kind, 'stylus');
  assert.equal(session.controller({ inputId: 2n, controllerId: 'pad-1', controllerEpoch: 1n,
    kind: ControllerEventKind.CONNECTED, ...NEUTRAL_CONTROLLER_STATE }).intent.kind, 'controller');
  let next = 10n;
  const releases = session.releaseAdvancedInputs(() => next++).map((action) => action.intent);
  assert.deepEqual(releases.map((intent) => intent.kind), ['stylus', 'controller', 'controller']);
  assert.equal(releases[0].event.phase, InputPhase.CANCELLED);
  assert.equal(releases[0].event.pressure, 0);
  assert.equal(releases[0].event.contactState, StylusContactState.CONTACT);
  assert.equal(releases[1].event.kind, ControllerEventKind.STATE);
  assert.equal(releases[2].event.kind, ControllerEventKind.DISCONNECTED);
  assert.deepEqual(session.releaseAdvancedInputs(() => next++), []);
  assert.throws(() => session.controller({ inputId: 13n, controllerId: 'pad-1', controllerEpoch: 1n,
    kind: ControllerEventKind.CONNECTED, ...NEUTRAL_CONTROLLER_STATE }), /Invalid controller attach/);
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

test('advanced release reserve bypasses a full ordinary backlog and sends first', async () => {
  const sent = [];
  const releases = [];
  const writer = new OutboundControlWriter((bytes) => {
    sent.push(new ProtocolDecoder().envelope(bytes));
    return new Promise((resolve) => releases.push(resolve));
  }, () => 1n);
  const scope = { sessionId, sessionEpoch: 7n };
  const active = writer.enqueue({ kind: 'ping', sequence: 1n }, scope);
  const queued = [];
  for (let index = 0; index < MAX_PENDING_CONTROLS; index += 1) {
    queued.push(writer.enqueue({ kind: 'pointer', event: { inputId: BigInt(index + 1), pointerId: 0,
      phase: InputPhase.CHANGED, x: 0.5, y: 0.5, pressure: 0, tiltX: 0, tiltY: 0, buttonMask: 0 } }, scope));
  }
  const release = writer.enqueueRelease({ kind: 'stylus', event: { inputId: 999n, pointerId: 1,
    phase: InputPhase.CANCELLED, x: 0.5, y: 0.5, pressure: 0, tiltXDegrees: 0, tiltYDegrees: 0 } }, scope);
  const disconnect = writer.enqueueRelease({ kind: 'controller', event: { inputId: 1000n,
    controllerId: 'pad-1', controllerEpoch: 1n, kind: ControllerEventKind.DISCONNECTED,
    ...NEUTRAL_CONTROLLER_STATE } }, scope);
  releases.shift()(); await active;
  assert.equal(sent[1].payloadField, 65);
  releases.shift()(); await release;
  assert.equal(sent[2].payloadField, 66);
  releases.shift()(); await disconnect;
  assert.equal(sent[3].payloadField, 61);
  writer.close();
  await Promise.all(queued.map((pending) => assert.rejects(pending)));
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

test('advanced input codecs match shared Protocol v1 golden fixtures', () => {
  const encoder = new ProtocolEncoder();
  const target = { displayId: 'display-main', streamId: 42n };
  assert.deepEqual(encoder.stylus(ProtocolEncoder.metadata(16n, sessionId, 7n, 1000000016n), {
    inputId: 102n, pointerId: 8, phase: InputPhase.CHANGED, x: 0.75, y: 0.25, pressure: 0,
    tiltXDegrees: 10, tiltYDegrees: -20, target, toolKind: StylusToolKind.ERASER,
    buttonMask: 3, contactState: StylusContactState.PROXIMITY
  }), fixture('stylus_extended.binpb'));
  const controller = { controllerId: 'controller-xbox-1', controllerEpoch: 1n, target,
    ...NEUTRAL_CONTROLLER_STATE };
  assert.deepEqual(encoder.controller(ProtocolEncoder.metadata(17n, sessionId, 7n, 1000000017n), {
    inputId: 103n, kind: ControllerEventKind.CONNECTED, ...controller
  }), fixture('controller_connected.binpb'));
  assert.deepEqual(encoder.controller(ProtocolEncoder.metadata(18n, sessionId, 7n, 1000000018n), {
    inputId: 104n, kind: ControllerEventKind.STATE, ...controller, buttonMask: 4101,
    leftStickX: -0.75, leftStickY: 0.5, rightStickX: 0.25, rightStickY: -0.125,
    leftTrigger: 0.375, rightTrigger: 0.875, hatX: 1, hatY: -1
  }), fixture('controller_state.binpb'));
  assert.deepEqual(encoder.controller(ProtocolEncoder.metadata(19n, sessionId, 7n, 1000000019n), {
    inputId: 105n, kind: ControllerEventKind.DISCONNECTED, ...controller
  }), fixture('controller_disconnected.binpb'));
});

test('advanced input mapper validates stylus and emits full controller snapshots', () => {
  const mapper = new AdvancedPeripheralInputMapper();
  const stylus = mapper.stylus(1n, { pointerId: 7, phase: InputPhase.CHANGED, x: 0.5, y: 0.25,
    pressure: 0.8, tiltXDegrees: 10, tiltYDegrees: -20, toolKind: StylusToolKind.PEN,
    buttonMask: 1, contactState: StylusContactState.CONTACT }, true);
  assert.equal(stylus.pressure, 0.8);
  assert.equal(mapper.stableControllerId(31), 'harmony-1f');
  assert.throws(() => mapper.stylus(2n, { ...stylus, inputId: undefined, buttonMask: 4 }, true),
    /Invalid extended stylus/);
  const baseSample = { pointerId: 7, phase: InputPhase.CHANGED, x: 0.5, y: 0.25, pressure: 0.8,
    tiltXDegrees: 10, tiltYDegrees: -20, toolKind: StylusToolKind.PEN, buttonMask: 0,
    contactState: StylusContactState.CONTACT };
  assert.equal(mapper.routeStylus(baseSample, false, false), 'touch');
  assert.equal(mapper.routeStylus({ ...baseSample, toolKind: StylusToolKind.ERASER }, false, false), 'suppress');
  assert.equal(mapper.routeStylus({ ...baseSample, contactState: StylusContactState.PROXIMITY }, true, false), 'suppress');
  assert.equal(mapper.routeStylus({ ...baseSample, buttonMask: 1 }, true, false), 'suppress');
  assert.equal(mapper.routeStylus({ ...baseSample, buttonMask: 1 }, true, true), 'stylus');

  const controllers = new ControllerSessionState();
  assert.deepEqual(controllers.connect('pad-b').map((event) => [event.controllerId, event.kind]),
    [['pad-b', ControllerEventKind.CONNECTED]]);
  const update = controllers.update('pad-a', { ...NEUTRAL_CONTROLLER_STATE, leftStickX: 0.5 });
  assert.deepEqual(update.map((event) => [event.controllerId, event.kind]), [
    ['pad-a', ControllerEventKind.CONNECTED], ['pad-a', ControllerEventKind.STATE]
  ]);
  assert.equal(update.at(-1).leftStickX, 0.5);
  assert.deepEqual(controllers.update('pad-b', { ...NEUTRAL_CONTROLLER_STATE, rightTrigger: 0.75 })
    .map((event) => event.controllerId), ['pad-b']);
  const released = controllers.releaseAll();
  assert.equal(released.filter((event) => event.kind === ControllerEventKind.DISCONNECTED).length, 2);
  assert.equal(controllers.connect('pad-a')[0].controllerEpoch, 2n);
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

function advancedStreamingSession() {
  const capabilities = [Capability.TOUCH, Capability.STYLUS, Capability.STYLUS_EXTENDED, Capability.CONTROLLER];
  const session = new ProductSession('harmony-test', 'Harmony test', capabilities, [Codec.HEVC, Codec.H264]);
  confirmRequest(session, session.start(1n)[0], 1n);
  const host = new ProtobufWriter().uint32(1, 1).packedVarints(4, capabilities)
    .packedVarints(5, [Codec.HEVC, Codec.H264]);
  session.receive(controlEnvelope(2n, 21, host, false), 2n);
  const accepted = new ProtobufWriter().bytesField(1, sessionId).uint64(2, 7n).uint32(3, 1000)
    .packedVarints(4, capabilities);
  const acceptedActions = session.receive(controlEnvelope(3n, 22, accepted), 3n);
  confirmRequest(session, acceptedActions[1], 4n);
  confirmRequest(session, session.receive(fixture('list_displays_response.binpb'), 5n)[0], 6n);
  session.receive(fixture('start_display_response.binpb'), 7n);
  finishVideoConfiguration(session, session.receive(fixture('video_config.binpb'), 8n)[0]);
  return session;
}

function sessionAwaitingVideoConfiguration(negotiated = [Capability.TOUCH, Capability.KEYBOARD,
  Capability.POINTER, Capability.TELEMETRY]) {
  const session = new ProductSession('harmony-test', 'Harmony test',
    [Capability.TOUCH, Capability.KEYBOARD, Capability.POINTER, Capability.TELEMETRY], [Codec.HEVC, Codec.H264]);
  confirmRequest(session, session.start(1n)[0], 1n);
  session.receive(fixture('host_hello.binpb'), 2n);
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
