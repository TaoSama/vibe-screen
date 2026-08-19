import { ControllerEventKind, ControllerInput } from '../protocol/ProtocolModels';

export const MAX_ACTIVE_CONTROLLERS: number = 4;
export const MAXIMUM_ACTIVE_CONTROLLERS_REJECTION_REASON: string = 'maximum_active_controllers_exceeded';

const MAX_CONTROLLER_ID_BYTES: number = 128;
const MAX_UINT64: bigint = 0xffffffffffffffffn;
const DEFINED_BUTTON_MASK: number = 0x1fff;

export interface HarmonyControllerSample {
  controllerId: string;
  controllerEpoch: bigint;
  kind: ControllerEventKind;
  buttonMask?: number;
  leftStickX?: number;
  leftStickY?: number;
  rightStickX?: number;
  rightStickY?: number;
  leftTrigger?: number;
  rightTrigger?: number;
  hatX?: number;
  hatY?: number;
}

export interface ControllerAdmissionResult {
  accepted: boolean;
  rejectionReason: string;
}

export class ControllerInputMapper {
  validate(event: ControllerInput): void {
    if (event.inputId <= 0n || event.inputId > MAX_UINT64) throw new Error('Controller inputId must be a positive uint64');
    this.validateIdentity(event.controllerId, event.controllerEpoch);
    if (!this.isValidKind(event.kind)) throw new Error('Controller kind must be CONNECTED, STATE, or DISCONNECTED');
    if (!Number.isInteger(event.buttonMask) || event.buttonMask < 0 || (event.buttonMask & ~DEFINED_BUTTON_MASK) !== 0) {
      throw new Error('Controller button bits 13-31 are reserved');
    }
    for (const value of [event.leftStickX, event.leftStickY, event.rightStickX, event.rightStickY]) {
      if (!Number.isFinite(value) || value < -1 || value > 1) {
        throw new Error('Controller stick axes must be finite and in [-1, 1]');
      }
    }
    for (const value of [event.leftTrigger, event.rightTrigger]) {
      if (!Number.isFinite(value) || value < 0 || value > 1) {
        throw new Error('Controller triggers must be finite and in [0, 1]');
      }
    }
    for (const value of [event.hatX, event.hatY]) {
      if (!Number.isInteger(value) || ![-1, 0, 1].includes(value)) {
        throw new Error('Controller hat axes must each be -1, 0, or 1');
      }
    }
    if ((event.kind === ControllerEventKind.CONNECTED || event.kind === ControllerEventKind.DISCONNECTED) &&
      !this.isNeutral(event)) {
      throw new Error('Controller lifecycle markers must be neutral');
    }
  }

  map(inputId: bigint, sample: HarmonyControllerSample): ControllerInput {
    const event: ControllerInput = {
      inputId,
      controllerId: sample.controllerId,
      controllerEpoch: sample.controllerEpoch,
      kind: sample.kind,
      buttonMask: sample.buttonMask ?? 0,
      leftStickX: sample.leftStickX ?? 0,
      leftStickY: sample.leftStickY ?? 0,
      rightStickX: sample.rightStickX ?? 0,
      rightStickY: sample.rightStickY ?? 0,
      leftTrigger: sample.leftTrigger ?? 0,
      rightTrigger: sample.rightTrigger ?? 0,
      hatX: sample.hatX ?? 0,
      hatY: sample.hatY ?? 0
    };
    this.validate(event);
    return event;
  }

  neutralDisconnect(inputId: bigint, active: ControllerInput): ControllerInput {
    const event: ControllerInput = {
      inputId,
      controllerId: active.controllerId,
      controllerEpoch: active.controllerEpoch,
      kind: ControllerEventKind.DISCONNECTED,
      buttonMask: 0,
      leftStickX: 0,
      leftStickY: 0,
      rightStickX: 0,
      rightStickY: 0,
      leftTrigger: 0,
      rightTrigger: 0,
      hatX: 0,
      hatY: 0,
      target: active.target
    };
    this.validate(event);
    return event;
  }

  private validateIdentity(controllerId: string, controllerEpoch: bigint): void {
    if (controllerId.length === 0) throw new Error('Controller id must be non-empty');
    if (this.utf8ByteLength(controllerId) > MAX_CONTROLLER_ID_BYTES) {
      throw new Error('Controller id must encode to at most 128 UTF-8 bytes');
    }
    if (controllerEpoch <= 0n || controllerEpoch > MAX_UINT64) throw new Error('Controller epoch must be a positive uint64');
  }

  private isValidKind(kind: ControllerEventKind): boolean {
    return kind === ControllerEventKind.CONNECTED || kind === ControllerEventKind.STATE ||
      kind === ControllerEventKind.DISCONNECTED;
  }

  private isNeutral(event: ControllerInput): boolean {
    return event.buttonMask === 0 && event.leftStickX === 0 && event.leftStickY === 0 && event.rightStickX === 0 &&
      event.rightStickY === 0 && event.leftTrigger === 0 && event.rightTrigger === 0 && event.hatX === 0 &&
      event.hatY === 0;
  }

  private utf8ByteLength(value: string): number {
    let bytes: number = 0;
    for (let index = 0; index < value.length; index += 1) {
      const code: number = value.charCodeAt(index);
      if (code <= 0x7f) bytes += 1;
      else if (code <= 0x7ff) bytes += 2;
      else if (code >= 0xd800 && code <= 0xdbff && index + 1 < value.length) {
        const next: number = value.charCodeAt(index + 1);
        if (next >= 0xdc00 && next <= 0xdfff) { bytes += 4; index += 1; }
        else bytes += 3;
      } else bytes += 3;
    }
    return bytes;
  }
}
