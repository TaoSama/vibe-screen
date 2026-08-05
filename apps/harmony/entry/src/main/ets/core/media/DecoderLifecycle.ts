export type DecoderLifecycleStage = 'configure' | 'set_output_surface' | 'prepare' | 'start' | 'ownership';
type DecoderSetupStage = 'configure' | 'set_output_surface' | 'prepare' | 'start';

export interface DecoderLifecycleOperations {
  configure(): Promise<void>;
  setOutputSurface(): Promise<void>;
  prepare(): Promise<void>;
  start(): Promise<void>;
  stop(): Promise<void>;
  release(): Promise<void>;
}

export interface DecoderCleanupTransition {
  detached: boolean;
  completion: Promise<void>;
}

/** Serializes candidate handoff so callers cannot bypass cleanup after detach. */
export class DecoderTransitionOwner<T> {
  private active: T | undefined;
  private pendingCleanup: Promise<void> | undefined;

  constructor(private cleanup: (candidate: T) => Promise<void>) {}

  install(candidate: T): void {
    if (this.active !== undefined || this.pendingCleanup !== undefined) {
      throw new Error('Decoder candidate installed before prior cleanup completed');
    }
    this.active = candidate;
  }

  current(): T | undefined { return this.active; }
  isCurrent(candidate: T): boolean { return this.active === candidate; }

  clearIfCurrent(candidate: T): boolean {
    if (this.active !== candidate) return false;
    this.active = undefined;
    return true;
  }

  detachAndCleanup(): DecoderCleanupTransition {
    const candidate: T | undefined = this.active;
    if (candidate === undefined) {
      return { detached: false, completion: this.pendingCleanup ?? Promise.resolve() };
    }
    this.active = undefined;
    let completion: Promise<void>;
    try { completion = this.cleanup(candidate); }
    catch (error) { completion = Promise.reject(error); }
    this.pendingCleanup = completion;
    const clear = (): void => { if (this.pendingCleanup === completion) this.pendingCleanup = undefined; };
    completion.then(clear, clear);
    return { detached: true, completion };
  }
}

class DecoderLifecycleSuperseded extends Error {
  constructor() { super('Decoder configuration superseded'); }
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

/** Owns every asynchronous setup and cleanup operation for one decoder instance. */
export class DecoderLifecycle {
  private stage: DecoderSetupStage = 'configure';
  private inFlight: Promise<void> | undefined;
  private cleanupPromise: Promise<string[]> | undefined;
  private cancellationRequested: boolean = false;
  private startInvoked: boolean = false;
  private setupFailed: boolean = false;

  constructor(private operations: DecoderLifecycleOperations) {}

  async initialize(): Promise<void> {
    try {
      await this.runStage('configure', (): Promise<void> => this.operations.configure());
      await this.runStage('set_output_surface', (): Promise<void> => this.operations.setOutputSurface());
      await this.runStage('prepare', (): Promise<void> => this.operations.prepare());
      await this.runStage('start', (): Promise<void> => this.operations.start());
    } catch (error) {
      const superseded: boolean = error instanceof DecoderLifecycleSuperseded;
      if (!superseded) this.setupFailed = true;
      const failedStage: DecoderLifecycleStage = superseded ? 'ownership' : this.stage;
      const cleanupFailures: string[] = await this.cancelAndCleanup();
      throw new DecoderLifecycleFailure(failedStage, this.errorMessage(error as Error), cleanupFailures);
    }
  }

  /** Atomically requests cancellation and returns the one cleanup operation for this instance. */
  cancelAndCleanup(): Promise<string[]> {
    this.cancellationRequested = true;
    if (this.cleanupPromise === undefined) this.cleanupPromise = this.cleanupWhenIdle();
    return this.cleanupPromise;
  }

  private async runStage(stage: DecoderSetupStage, operation: () => Promise<void>): Promise<void> {
    this.requireActive();
    this.stage = stage;
    if (stage === 'start') this.startInvoked = true;
    const pending: Promise<void> = operation().catch((error: Error) => {
      this.setupFailed = true;
      throw error;
    });
    this.inFlight = pending;
    try { await pending; }
    finally { if (this.inFlight === pending) this.inFlight = undefined; }
    this.requireActive();
  }

  private requireActive(): void {
    if (this.cancellationRequested) throw new DecoderLifecycleSuperseded();
  }

  private async cleanupWhenIdle(): Promise<string[]> {
    const pending: Promise<void> | undefined = this.inFlight;
    if (pending !== undefined) {
      try { await pending; }
      catch (_error) { /* initialize preserves the setup failure after cleanup */ }
    }
    const failures: string[] = [];
    if (this.startInvoked || this.setupFailed) {
      try { await this.operations.stop(); }
      catch (error) { failures.push(`stop: ${this.errorMessage(error as Error)}`); }
    }
    try { await this.operations.release(); }
    catch (error) { failures.push(`release: ${this.errorMessage(error as Error)}`); }
    return failures;
  }

  private errorMessage(error: Error): string { return error.message; }
}

/** Owns native creation before a decoder lifecycle can be attached. */
export class DecoderCandidateLease<T> {
  private creationPromise: Promise<T> | undefined;
  private lifecycle: DecoderLifecycle | undefined;
  private cancellationRequested: boolean = false;
  private cleanupPromise: Promise<void> | undefined;

  constructor(private createCandidate: () => Promise<T>, private releaseUninitialized: (candidate: T) => Promise<void>) {}

  start(): Promise<T> {
    if (this.creationPromise !== undefined) return this.creationPromise;
    try { this.creationPromise = this.createCandidate(); }
    catch (error) { this.creationPromise = Promise.reject(error); }
    return this.creationPromise;
  }

  canContinue(): boolean { return !this.cancellationRequested; }

  attachLifecycle(lifecycle: DecoderLifecycle): void {
    if (this.cancellationRequested) throw new Error('Decoder creation superseded');
    if (this.lifecycle !== undefined) throw new Error('Decoder lifecycle already attached');
    this.lifecycle = lifecycle;
  }

  cancelAndCleanup(): Promise<void> {
    this.cancellationRequested = true;
    if (this.cleanupPromise === undefined) this.cleanupPromise = this.cleanupWhenReady();
    return this.cleanupPromise;
  }

  private async cleanupWhenReady(): Promise<void> {
    const creation: Promise<T> | undefined = this.creationPromise;
    if (creation === undefined) throw new Error('Decoder cleanup requested before creation started');
    const candidate: T = await creation;
    const attached: DecoderLifecycle | undefined = this.lifecycle;
    if (attached === undefined) {
      await this.releaseUninitialized(candidate);
      return;
    }
    const failures: string[] = await attached.cancelAndCleanup();
    if (failures.length > 0) throw new Error(failures.join('; '));
  }
}
