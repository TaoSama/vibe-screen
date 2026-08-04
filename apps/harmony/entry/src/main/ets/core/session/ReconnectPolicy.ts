const BASE_DELAY_MS: number = 250;
const MAX_DELAY_MS: number = 8000;
const JITTER_RATIO: number = 0.2;

export class ReconnectPolicy {
  delayMs(attempt: number, randomUnit: number = Math.random()): number {
    const exponent: number = Math.min(Math.max(attempt, 0), 8);
    const base: number = Math.min(BASE_DELAY_MS * Math.pow(2, exponent), MAX_DELAY_MS);
    const jitter: number = base * JITTER_RATIO * (Math.min(Math.max(randomUnit, 0), 1) * 2 - 1);
    return Math.round(base + jitter);
  }
}

