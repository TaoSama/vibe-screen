import { ControllerEventKind, ControllerInput, InputPhase, StylusContactState, StylusInput,
  StylusToolKind } from '../protocol/ProtocolModels';
import { encodeUtf8 } from '../protocol/Utf8';

export const STYLUS_BUTTON_MASK: number = 0x03;
export const CONTROLLER_BUTTON_MASK: number = 0x1fff;

export interface HarmonyStylusSample {
  pointerId: number;
  phase: InputPhase;
  x: number;
  y: number;
  pressure: number;
  tiltXDegrees: number;
  tiltYDegrees: number;
  toolKind: StylusToolKind;
  buttonMask: number;
  contactState: StylusContactState;
}

export interface ControllerFullState {
  buttonMask: number;
  leftStickX: number;
  leftStickY: number;
  rightStickX: number;
  rightStickY: number;
  leftTrigger: number;
  rightTrigger: number;
  hatX: number;
  hatY: number;
}

export interface ControllerLifecycleSample extends ControllerFullState {
  controllerId: string;
  controllerEpoch: bigint;
  kind: ControllerEventKind;
}

export const NEUTRAL_CONTROLLER_STATE: ControllerFullState = {
  buttonMask: 0, leftStickX: 0, leftStickY: 0, rightStickX: 0, rightStickY: 0,
  leftTrigger: 0, rightTrigger: 0, hatX: 0, hatY: 0
};

/** Converts ArkUI/native-XComponent values without allowing invalid wire state. */
export class AdvancedPeripheralInputMapper {
  stylus(inputId: bigint, sample: HarmonyStylusSample, extended: boolean): StylusInput {
    const terminal: boolean = sample.phase === InputPhase.ENDED || sample.phase === InputPhase.CANCELLED;
    const pressure: number = terminal || sample.contactState === StylusContactState.PROXIMITY ? 0 : sample.pressure;
    const event: StylusInput = {
      inputId, pointerId: sample.pointerId, phase: sample.phase, x: sample.x, y: sample.y,
      pressure, tiltXDegrees: sample.tiltXDegrees, tiltYDegrees: sample.tiltYDegrees
    };
    if (extended) {
      event.toolKind = sample.toolKind;
      event.buttonMask = sample.buttonMask;
      event.contactState = sample.contactState;
    }
    this.validateStylus(event, extended);
    return event;
  }

  controller(inputId: bigint, sample: ControllerLifecycleSample): ControllerInput {
    const event: ControllerInput = { inputId, ...sample };
    this.validateController(event);
    return event;
  }

  stableControllerId(deviceId: number): string {
    if (!Number.isSafeInteger(deviceId) || deviceId < 0) throw new Error('Invalid ArkUI controller device id');
    return `harmony-${deviceId.toString(16)}`;
  }

  validateStylus(event: StylusInput, extended: boolean): void {
    const validPhase: boolean = event.phase === InputPhase.BEGAN || event.phase === InputPhase.CHANGED ||
      event.phase === InputPhase.ENDED || event.phase === InputPhase.CANCELLED;
    const terminal: boolean = event.phase === InputPhase.ENDED || event.phase === InputPhase.CANCELLED;
    if (event.inputId <= 0n || !Number.isInteger(event.pointerId) || event.pointerId < 0 || !validPhase ||
      !this.unit(event.x) || !this.unit(event.y) || !this.unit(event.pressure) ||
      !this.tilt(event.tiltXDegrees) || !this.tilt(event.tiltYDegrees) ||
      Math.hypot(event.tiltXDegrees, event.tiltYDegrees) > 90 || (terminal && event.pressure !== 0)) {
      throw new Error('Invalid stylus input');
    }
    if (extended) {
      if ((event.toolKind !== StylusToolKind.PEN && event.toolKind !== StylusToolKind.ERASER) ||
        (event.contactState !== StylusContactState.CONTACT && event.contactState !== StylusContactState.PROXIMITY) ||
        !Number.isInteger(event.buttonMask) || (event.buttonMask! & ~STYLUS_BUTTON_MASK) !== 0 ||
        (event.contactState === StylusContactState.PROXIMITY && event.pressure !== 0)) {
        throw new Error('Invalid extended stylus input');
      }
    } else if (event.toolKind !== undefined || event.contactState !== undefined || (event.buttonMask ?? 0) !== 0) {
      throw new Error('Extended stylus fields require STYLUS_EXTENDED');
    }
  }

  validateController(event: ControllerInput): void {
    const lifecycle: boolean = event.kind === ControllerEventKind.CONNECTED || event.kind === ControllerEventKind.DISCONNECTED;
    const validKind: boolean = lifecycle || event.kind === ControllerEventKind.STATE;
    const idBytes: number = encodeUtf8(event.controllerId).length;
    const sticks: number[] = [event.leftStickX, event.leftStickY, event.rightStickX, event.rightStickY];
    const triggers: number[] = [event.leftTrigger, event.rightTrigger];
    if (event.inputId <= 0n || idBytes < 1 || idBytes > 128 || event.controllerEpoch <= 0n || !validKind ||
      !Number.isInteger(event.buttonMask) || (event.buttonMask & ~CONTROLLER_BUTTON_MASK) !== 0 ||
      !sticks.every((value: number) => Number.isFinite(value) && value >= -1 && value <= 1) ||
      !triggers.every((value: number) => this.unit(value)) || ![-1, 0, 1].includes(event.hatX) ||
      ![-1, 0, 1].includes(event.hatY) || (lifecycle && !this.isNeutral(event))) {
      throw new Error('Invalid controller input');
    }
  }

  private unit(value: number): boolean { return Number.isFinite(value) && value >= 0 && value <= 1; }
  private tilt(value: number): boolean { return Number.isFinite(value) && value >= -90 && value <= 90; }
  private isNeutral(event: ControllerFullState): boolean {
    return event.buttonMask === 0 && event.leftStickX === 0 && event.leftStickY === 0 &&
      event.rightStickX === 0 && event.rightStickY === 0 && event.leftTrigger === 0 &&
      event.rightTrigger === 0 && event.hatX === 0 && event.hatY === 0;
  }
}

/** Owns attachment epochs and always emits complete controller snapshots. */
export class ControllerSessionState {
  private readonly epochs: Map<string, bigint> = new Map();
  private readonly active: Map<string, { epoch: bigint; state: ControllerFullState }> = new Map();

  connect(controllerId: string): ControllerLifecycleSample[] {
    if (this.active.has(controllerId)) return [];
    const epoch: bigint = (this.epochs.get(controllerId) ?? 0n) + 1n;
    this.epochs.set(controllerId, epoch);
    this.active.set(controllerId, { epoch, state: { ...NEUTRAL_CONTROLLER_STATE } });
    return [this.sample(controllerId, epoch, ControllerEventKind.CONNECTED, NEUTRAL_CONTROLLER_STATE),
      ...this.fullStateSamples()];
  }

  update(controllerId: string, state: ControllerFullState): ControllerLifecycleSample[] {
    const prefix: ControllerLifecycleSample[] = this.connect(controllerId);
    const active = this.active.get(controllerId)!;
    active.state = { ...state };
    return [...prefix, ...this.fullStateSamples()];
  }

  disconnect(controllerId: string): ControllerLifecycleSample[] {
    const active = this.active.get(controllerId);
    if (active === undefined) return [];
    this.active.delete(controllerId);
    return [this.sample(controllerId, active.epoch, ControllerEventKind.STATE, NEUTRAL_CONTROLLER_STATE),
      this.sample(controllerId, active.epoch, ControllerEventKind.DISCONNECTED, NEUTRAL_CONTROLLER_STATE),
      ...this.fullStateSamples()];
  }

  releaseAll(): ControllerLifecycleSample[] {
    const samples: ControllerLifecycleSample[] = [];
    [...this.active.keys()].sort().forEach((controllerId: string) => samples.push(...this.disconnect(controllerId)));
    return samples;
  }

  resetSession(): void { this.active.clear(); this.epochs.clear(); }

  private fullStateSamples(): ControllerLifecycleSample[] {
    return [...this.active.entries()].sort(([left], [right]) => left.localeCompare(right))
      .map(([id, active]) => this.sample(id, active.epoch, ControllerEventKind.STATE, active.state));
  }

  private sample(controllerId: string, controllerEpoch: bigint, kind: ControllerEventKind,
    state: ControllerFullState): ControllerLifecycleSample {
    return { controllerId, controllerEpoch, kind, ...state };
  }
}
