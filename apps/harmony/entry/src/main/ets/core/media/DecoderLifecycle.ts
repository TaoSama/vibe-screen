export type DecoderLifecycleStage = 'configure' | 'set_output_surface' | 'prepare' | 'start' | 'ownership';

export interface DecoderLifecycleOperations {
  configure(): Promise<void>;
  setOutputSurface(): Promise<void>;
  prepare(): Promise<void>;
  start(): Promise<void>;
  stop(): Promise<void>;
  release(): Promise<void>;
}

export interface DecoderLifecycleOwnership {
  isCurrent(): boolean;
  /** Returns true only when this lifecycle detached and now owns cleanup. */
  claimForCleanup(): boolean;
}

export class DecoderLifecycleFailure extends Error {
  constructor(public stage: DecoderLifecycleStage, public primaryMessage: string,
    public cleanupFailures: string[]) {
    super(DecoderLifecycleFailure.describe(stage, primaryMessage, cleanupFailures));
    this.name = 'DecoderLifecycleFailure';
  }

  private static describe(stage: DecoderLifecycleStage, primaryMessage: string, cleanupFailures: string[]): string {
    const cleanup: string = cleanupFailures.length === 0 ? '' : `; cleanup ${cleanupFailures.join('; ')}`;
    return `Decoder lifecycle ${stage} failed: ${primaryMessage}${cleanup}`;
  }
}

/** Runs decoder setup transactionally once the candidate has been registered. */
export class DecoderLifecycle {
  static async initialize(operations: DecoderLifecycleOperations, ownership: DecoderLifecycleOwnership): Promise<void> {
    let stage: DecoderLifecycleStage = 'configure';
    try {
      await operations.configure(); this.requireCurrent(ownership);
      stage = 'set_output_surface';
      await operations.setOutputSurface(); this.requireCurrent(ownership);
      stage = 'prepare';
      await operations.prepare(); this.requireCurrent(ownership);
      stage = 'start';
      await operations.start(); this.requireCurrent(ownership);
    } catch (error) {
      if (!ownership.isCurrent()) stage = 'ownership';
      const cleanupFailures: string[] = ownership.claimForCleanup()
        ? await this.cleanup(operations) : [];
      throw new DecoderLifecycleFailure(stage, this.errorMessage(error as Error), cleanupFailures);
    }
  }

  private static requireCurrent(ownership: DecoderLifecycleOwnership): void {
    if (!ownership.isCurrent()) throw new Error('Decoder configuration superseded');
  }

  private static async cleanup(operations: DecoderLifecycleOperations): Promise<string[]> {
    const failures: string[] = [];
    try { await operations.stop(); }
    catch (error) { failures.push(`stop: ${this.errorMessage(error as Error)}`); }
    try { await operations.release(); }
    catch (error) { failures.push(`release: ${this.errorMessage(error as Error)}`); }
    return failures;
  }

  private static errorMessage(error: Error): string { return error.message; }
}
