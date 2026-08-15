import { InputPhase, StylusContactState, StylusInput, StylusToolKind } from '../protocol/ProtocolModels';

const MAX_TILT_DEGREES: number = 90;
const MAX_UINT32: number = 0xffffffff;
const MAX_UINT64: bigint = 0xffffffffffffffffn;
const STYLUS_PRIMARY_BUTTON: number = 1 << 0;
const STYLUS_SECONDARY_BUTTON: number = 1 << 1;
const STYLUS_BUTTON_MASK: number = STYLUS_PRIMARY_BUTTON | STYLUS_SECONDARY_BUTTON;

export type StylusRoute = 'touch' | 'stylus' | 'suppress';

export interface HarmonyStylusSample {
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
}

function isFiniteNumber(value: number): boolean {
  return typeof value === 'number' && Number.isFinite(value);
}

function isSafeNonNegativeInteger(value: number): boolean {
  return Number.isSafeInteger(value) && value >= 0 && value <= MAX_UINT32;
}

function isValidPhase(value: InputPhase): boolean {
  return value === InputPhase.BEGAN || value === InputPhase.CHANGED || value === InputPhase.ENDED ||
    value === InputPhase.CANCELLED;
}

export class StylusInputMapper {
  route(sample: HarmonyStylusSample, stylus: boolean, extended: boolean): StylusRoute {
    this.validateSampleNumbers(sample);
    const toolKind: StylusToolKind = sample.toolKind ?? StylusToolKind.PEN;
    const contactState: StylusContactState = sample.contactState ?? StylusContactState.CONTACT;
    if (toolKind !== StylusToolKind.PEN && toolKind !== StylusToolKind.ERASER) return 'suppress';
    if (contactState !== StylusContactState.CONTACT && contactState !== StylusContactState.PROXIMITY) return 'suppress';
    const baseSafe: boolean = toolKind === StylusToolKind.PEN && contactState === StylusContactState.CONTACT &&
      (sample.buttonMask ?? 0) === 0;
    if (!stylus) return baseSafe ? 'touch' : 'suppress';
    return extended || baseSafe ? 'stylus' : 'suppress';
  }

  map(inputId: bigint, sample: HarmonyStylusSample, extended: boolean): StylusInput {
    if (inputId <= 0n || inputId > MAX_UINT64) throw new Error('Stylus inputId must be a positive uint64');
    this.validateSampleNumbers(sample);
    const buttonMask: number = sample.buttonMask ?? 0;
    if (sample.toolKind !== undefined && sample.toolKind !== StylusToolKind.PEN &&
      sample.toolKind !== StylusToolKind.ERASER) {
      throw new Error('Stylus toolKind must be PEN or ERASER');
    }
    if (sample.contactState !== undefined && sample.contactState !== StylusContactState.CONTACT &&
      sample.contactState !== StylusContactState.PROXIMITY) {
      throw new Error('Stylus contactState must be CONTACT or PROXIMITY');
    }
    const hasExtendedSemantics: boolean = sample.toolKind === StylusToolKind.ERASER ||
      sample.contactState === StylusContactState.PROXIMITY || buttonMask !== 0;
    if (!extended && hasExtendedSemantics) {
      throw new Error('Extended stylus semantics require STYLUS_EXTENDED');
    }

    const isTerminal: boolean = sample.phase === InputPhase.ENDED || sample.phase === InputPhase.CANCELLED;
    const isProximity: boolean = sample.contactState === StylusContactState.PROXIMITY;
    const pressure: number = isTerminal || isProximity ? 0 : sample.pressure;

    const event: StylusInput = {
      inputId,
      pointerId: sample.pointerId,
      phase: sample.phase,
      x: sample.x,
      y: sample.y,
      pressure,
      tiltXDegrees: sample.tiltXDegrees,
      tiltYDegrees: sample.tiltYDegrees
    };

    if (extended) {
      event.toolKind = sample.toolKind ?? StylusToolKind.PEN;
      event.buttonMask = buttonMask;
      event.contactState = sample.contactState ?? StylusContactState.CONTACT;
    }

    return event;
  }

  validate(event: StylusInput, extended: boolean): void {
    if (event.inputId <= 0n || event.inputId > MAX_UINT64) {
      throw new Error('Stylus inputId must be a positive uint64');
    }
    if (!isSafeNonNegativeInteger(event.pointerId)) {
      throw new Error('Stylus pointerId must be a safe non-negative integer');
    }
    if (!isValidPhase(event.phase)) {
      throw new Error('Stylus phase must be BEGAN, CHANGED, ENDED, or CANCELLED');
    }
    if (!isFiniteNumber(event.x) || event.x < 0 || event.x > 1) {
      throw new Error('Stylus x must be finite and in [0, 1]');
    }
    if (!isFiniteNumber(event.y) || event.y < 0 || event.y > 1) {
      throw new Error('Stylus y must be finite and in [0, 1]');
    }
    if (!isFiniteNumber(event.pressure) || event.pressure < 0 || event.pressure > 1) {
      throw new Error('Stylus pressure must be finite and in [0, 1]');
    }
    const isTerminal: boolean = event.phase === InputPhase.ENDED || event.phase === InputPhase.CANCELLED;
    if (isTerminal && event.pressure !== 0) {
      throw new Error('Stylus pressure must be 0 for ENDED or CANCELLED phase');
    }
    if (!isFiniteNumber(event.tiltXDegrees) || event.tiltXDegrees < -MAX_TILT_DEGREES ||
      event.tiltXDegrees > MAX_TILT_DEGREES) {
      throw new Error('Stylus tiltX must be finite and in [-90, 90]');
    }
    if (!isFiniteNumber(event.tiltYDegrees) || event.tiltYDegrees < -MAX_TILT_DEGREES ||
      event.tiltYDegrees > MAX_TILT_DEGREES) {
      throw new Error('Stylus tiltY must be finite and in [-90, 90]');
    }
    if (Math.hypot(event.tiltXDegrees, event.tiltYDegrees) > MAX_TILT_DEGREES + 1e-6) {
      throw new Error('Stylus tilt vector magnitude must not exceed 90 degrees');
    }

    if (!extended) {
      if (event.toolKind !== undefined) throw new Error('Stylus toolKind must be omitted without extended capability');
      if (event.buttonMask !== undefined) throw new Error('Stylus buttonMask must be omitted without extended capability');
      if (event.contactState !== undefined) throw new Error('Stylus contactState must be omitted without extended capability');
      return;
    }

    if (event.toolKind !== StylusToolKind.PEN && event.toolKind !== StylusToolKind.ERASER) {
      throw new Error('Stylus toolKind must be PEN or ERASER when extended');
    }
    const buttonMask: number = event.buttonMask ?? 0;
    if (!Number.isInteger(buttonMask) || buttonMask < 0 || buttonMask > STYLUS_BUTTON_MASK) {
      throw new Error('Stylus buttonMask may only contain bits 0 and 1');
    }
    if (event.contactState !== StylusContactState.CONTACT &&
      event.contactState !== StylusContactState.PROXIMITY) {
      throw new Error('Stylus contactState must be CONTACT or PROXIMITY when extended');
    }
    if (event.contactState === StylusContactState.PROXIMITY && event.pressure !== 0) {
      throw new Error('Stylus PROXIMITY samples must have zero pressure');
    }
  }

  private validateSampleNumbers(sample: HarmonyStylusSample): void {
    if (!isSafeNonNegativeInteger(sample.pointerId)) {
      throw new Error('Stylus pointerId must be a uint32');
    }
    if (!isValidPhase(sample.phase)) {
      throw new Error('Stylus phase must be BEGAN, CHANGED, ENDED, or CANCELLED');
    }
    if (!isFiniteNumber(sample.x) || sample.x < 0 || sample.x > 1) {
      throw new Error('Stylus x must be finite and in [0, 1]');
    }
    if (!isFiniteNumber(sample.y) || sample.y < 0 || sample.y > 1) {
      throw new Error('Stylus y must be finite and in [0, 1]');
    }
    if (!isFiniteNumber(sample.pressure) || sample.pressure < 0 || sample.pressure > 1) {
      throw new Error('Stylus pressure must be finite and in [0, 1]');
    }
    if (!isFiniteNumber(sample.tiltXDegrees) || sample.tiltXDegrees < -MAX_TILT_DEGREES ||
      sample.tiltXDegrees > MAX_TILT_DEGREES) {
      throw new Error('Stylus tiltX must be finite and in [-90, 90]');
    }
    if (!isFiniteNumber(sample.tiltYDegrees) || sample.tiltYDegrees < -MAX_TILT_DEGREES ||
      sample.tiltYDegrees > MAX_TILT_DEGREES) {
      throw new Error('Stylus tiltY must be finite and in [-90, 90]');
    }
    if (Math.hypot(sample.tiltXDegrees, sample.tiltYDegrees) > MAX_TILT_DEGREES + 1e-6) {
      throw new Error('Stylus tilt vector magnitude must not exceed 90 degrees');
    }
    const buttonMask: number = sample.buttonMask ?? 0;
    if (!Number.isInteger(buttonMask) || buttonMask < 0 || buttonMask > STYLUS_BUTTON_MASK) {
      throw new Error('Stylus buttonMask may only contain bits 0 and 1');
    }
  }
}
