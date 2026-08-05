export const PROTOCOL_VERSION: number = 1;

export enum Codec { UNSPECIFIED = 0, H264 = 1, HEVC = 2, AV1 = 3 }
export enum TransportKind { UNSPECIFIED = 0, USB = 1, LAN = 2, INTERNET = 3 }
export enum Capability {
  UNSPECIFIED = 0, DISPLAY_MIRROR = 1, VIRTUAL_DISPLAY = 2, TOUCH = 3,
  KEYBOARD = 4, POINTER = 5, STYLUS = 6, TELEMETRY = 7, SESSION_RESUME = 8
}
export enum InputPhase { UNSPECIFIED = 0, BEGAN = 1, CHANGED = 2, ENDED = 3, CANCELLED = 4 }

export interface EnvelopeMetadata {
  protocolVersion: number;
  messageId: bigint;
  correlationId: bigint;
  sessionId: Uint8Array;
  sessionEpoch: bigint;
  sentAtMonotonicNs: bigint;
}

export interface ClientHello {
  minimumProtocol: number;
  maximumProtocol: number;
  deviceId: string;
  deviceName: string;
  capabilities: Capability[];
  codecs: Codec[];
  transports: TransportKind[];
  requiredCapabilities?: Capability[];
  resourceLimits?: ResourceLimits;
  videoDecodeCapabilities?: VideoDecodeCapability[];
}

export interface ResourceLimits { maximumClients: number; maximumDisplays: number; maximumVideoStreams: number; }
export interface VideoDecodeCapability { codec: Codec; maximumWidth: number; maximumHeight: number; maximumFramesPerSecond: number; bitDepths: number[]; }
export interface HostHello { selectedProtocol: number; capabilities: Capability[]; codecs: Codec[]; }
export interface SessionAccepted { sessionId: Uint8Array; sessionEpoch: bigint; heartbeatIntervalMs: number; negotiatedCapabilities: Capability[]; }
export interface DisplayDescriptor { displayId: string; name: string; width: number; height: number; scaleFactor: number; primary: boolean; }
export interface VideoConfig { configEpoch: bigint; codec: Codec; width: number; height: number; framesPerSecond: number; streamId: bigint; rotationDegrees: number; }
export interface InputTarget { displayId: string; streamId: bigint; }

export interface MediaPacketHeader {
  streamId: bigint;
  sessionEpoch: bigint;
  configEpoch: bigint;
  frameId: bigint;
  fragmentIndex: number;
  fragmentCount: number;
  captureTimestampNs: bigint;
  keyframe: boolean;
  codec: Codec;
  payloadLength: number;
}

export interface NormalizedInput {
  inputId: bigint;
  pointerId: number;
  phase: InputPhase;
  x: number;
  y: number;
  pressure: number;
  tiltX: number;
  tiltY: number;
  buttonMask: number;
}

export interface ScrollInput { inputId: bigint; deltaX: number; deltaY: number; target?: InputTarget; }
export interface KeyInput { inputId: bigint; usbHidUsage: number; pressed: boolean; modifierMask: number; text: string; target?: InputTarget; }

export function defaultCapabilities(): Capability[] {
  return [Capability.DISPLAY_MIRROR, Capability.VIRTUAL_DISPLAY, Capability.TOUCH,
    Capability.KEYBOARD, Capability.POINTER, Capability.STYLUS, Capability.TELEMETRY,
    Capability.SESSION_RESUME];
}
