import { ProductSessionState } from './ProductSession';

const SESSION_PROGRESS_TIMEOUT_MS: number = 10000;
const FIRST_FRAME_TIMEOUT_MS: number = 5000;
const MAX_FIRST_FRAME_REQUESTS: number = 2;

export type ProgressDeadlineAction = 'none' | 'requestKeyframe' | 'reconnect';

export class ProgressWatchdog {
  private firstFrameRequests: number = 0;

  shouldRearm(previous: ProductSessionState, current: ProductSessionState): boolean {
    return previous !== current;
  }

  configurationStarted(): void { this.firstFrameRequests = 0; }

  delayMs(state: ProductSessionState): number {
    return state === ProductSessionState.STREAMING ? FIRST_FRAME_TIMEOUT_MS : SESSION_PROGRESS_TIMEOUT_MS;
  }

  deadlineAction(state: ProductSessionState, renderedFirstFrame: boolean): ProgressDeadlineAction {
    if (renderedFirstFrame || state === ProductSessionState.CLOSED) return 'none';
    if (state === ProductSessionState.STREAMING && this.firstFrameRequests < MAX_FIRST_FRAME_REQUESTS) {
      this.firstFrameRequests += 1;
      return 'requestKeyframe';
    }
    return 'reconnect';
  }
}
