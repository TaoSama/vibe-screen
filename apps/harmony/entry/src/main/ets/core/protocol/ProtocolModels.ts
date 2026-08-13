export const PROTOCOL_VERSION: number = 1;

export enum Codec { UNSPECIFIED = 0, H264 = 1, HEVC = 2, AV1 = 3 }
export enum TransportKind { UNSPECIFIED = 0, USB = 1, LAN = 2, INTERNET = 3 }
export enum Capability {
  UNSPECIFIED = 0, DISPLAY_MIRROR = 1, VIRTUAL_DISPLAY = 2, TOUCH = 3,
  KEYBOARD = 4, POINTER = 5, STYLUS = 6, TELEMETRY = 7, SESSION_RESUME = 8,
  STYLUS_EXTENDED = 25, CONTROLLER = 26
}
export enum InputPhase { UNSPECIFIED = 0, BEGAN = 1, CHANGED = 2, ENDED = 3, CANCELLED = 4 }
export enum StylusToolKind { UNSPECIFIED = 0, PEN = 1, ERASER = 2 }
export enum StylusContactState { UNSPECIFIED = 0, CONTACT = 1, PROXIMITY = 2 }
export enum ControllerEventKind { UNSPECIFIED = 0, CONNECTED = 1, STATE = 2, DISCONNECTED = 3 }
export enum ColorPrimaries { UNSPECIFIED = 0, BT709 = 1, DISPLAY_P3 = 2, BT2020 = 3 }
export enum TransferFunction { UNSPECIFIED = 0, SRGB = 1, BT709 = 2, PQ = 3, HLG = 4 }
export enum MatrixCoefficients { UNSPECIFIED = 0, BT709 = 1, BT2020_NON_CONSTANT = 2 }

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
export interface ColorDescription {
  primaries: ColorPrimaries;
  transferFunction: TransferFunction;
  matrixCoefficients: MatrixCoefficients;
  fullRange: boolean;
  bitDepth: number;
}
export interface VideoConfig { configEpoch: bigint; codec: Codec; width: number; height: number; framesPerSecond: number;
  bitrateKbps: number; streamId: bigint; rotationDegrees: number; colorDescription?: ColorDescription; }
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

export interface StylusInput {
  inputId: bigint;
  pointerId: number;
  phase: InputPhase;
  x: number;
  y: number;
  pressure: number;
  tiltXDegrees: number;
  tiltYDegrees: number;
  toolKind?: StylusToolKind;
  buttonMask?: number;
  contactState?: StylusContactState;
  target?: InputTarget;
}

export interface ControllerInput {
  inputId: bigint;
  controllerId: string;
  controllerEpoch: bigint;
  kind: ControllerEventKind;
  buttonMask: number;
  leftStickX: number;
  leftStickY: number;
  rightStickX: number;
  rightStickY: number;
  leftTrigger: number;
  rightTrigger: number;
  hatX: number;
  hatY: number;
  target?: InputTarget;
}

export interface ScrollInput { inputId: bigint; deltaX: number; deltaY: number; target?: InputTarget; }
export interface KeyInput { inputId: bigint; usbHidUsage: number; pressed: boolean; modifierMask: number; text: string; target?: InputTarget; }

export function defaultCapabilities(): Capability[] {
  return [Capability.DISPLAY_MIRROR, Capability.VIRTUAL_DISPLAY, Capability.TOUCH,
    Capability.KEYBOARD, Capability.POINTER, Capability.STYLUS, Capability.STYLUS_EXTENDED,
    Capability.CONTROLLER, Capability.TELEMETRY,
    Capability.SESSION_RESUME];
}
