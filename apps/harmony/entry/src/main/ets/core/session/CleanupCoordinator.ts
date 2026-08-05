export interface CleanupFailure {
  operation: string;
  message: string;
}

export interface CleanupOperation {
  name: string;
  run: () => Promise<void>;
}

export async function runAllCleanup(operations: CleanupOperation[]): Promise<CleanupFailure[]> {
  const results: CleanupFailure[][] = await Promise.all(operations.map(async (operation: CleanupOperation) => {
    try {
      await operation.run();
      return [];
    } catch (error) {
      const failure: Error = error instanceof Error ? error : new Error('Cleanup operation failed');
      return [{ operation: operation.name, message: failure.message }];
    }
  }));
  return results.flat();
}

export function describeCleanupFailures(failures: CleanupFailure[]): string {
  return failures.map((failure: CleanupFailure) => `${failure.operation}: ${failure.message}`).join('; ');
}
