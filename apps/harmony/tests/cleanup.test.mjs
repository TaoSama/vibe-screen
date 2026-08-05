import test from 'node:test';
import assert from 'node:assert/strict';
import cleanupModule from '../.test-dist/session/CleanupCoordinator.js';

const { describeCleanupFailures, runAllCleanup } = cleanupModule;

test('cleanup runs every operation and reports every failure', async () => {
  const calls = [];
  const failures = await runAllCleanup([
    { name: 'transport', run: async () => { calls.push('transport'); throw new Error('close failed'); } },
    { name: 'decoder', run: async () => { calls.push('decoder'); throw new Error('release failed'); } }
  ]);
  assert.deepEqual(calls.sort(), ['decoder', 'transport']);
  assert.deepEqual(failures, [
    { operation: 'transport', message: 'close failed' },
    { operation: 'decoder', message: 'release failed' }
  ]);
  assert.equal(describeCleanupFailures(failures), 'transport: close failed; decoder: release failed');
});

test('cleanup success does not hide a sibling failure', async () => {
  const failures = await runAllCleanup([
    { name: 'transport', run: async () => {} },
    { name: 'decoder', run: async () => { throw 'release failed'; } }
  ]);
  assert.deepEqual(failures, [{ operation: 'decoder', message: 'Cleanup operation failed' }]);
});
