import test from 'node:test';
import assert from 'node:assert/strict';
import { DecoderLifecycle, DecoderLifecycleFailure } from '../.test-dist/media/DecoderLifecycle.js';

const stages = ['configure', 'set_output_surface', 'prepare', 'start'];

const harness = (failureStage, cleanupFailures = []) => {
  const calls = [];
  let current = true;
  const operation = (name) => async () => {
    calls.push(name);
    if (name === failureStage || cleanupFailures.includes(name)) throw new Error(`${name} boom`);
  };
  return {
    calls,
    operations: {
      configure: operation('configure'), setOutputSurface: operation('set_output_surface'),
      prepare: operation('prepare'), start: operation('start'), stop: operation('stop'), release: operation('release')
    },
    ownership: {
      isCurrent: () => current,
      claimForCleanup: () => { if (!current) return false; current = false; calls.push('detach'); return true; }
    },
    current: () => current
  };
};

for (const stage of stages) {
  test(`decoder lifecycle cleans a registered candidate when ${stage} fails`, async () => {
    const target = harness(stage);
    await assert.rejects(DecoderLifecycle.initialize(target.operations, target.ownership), (error) => {
      assert.ok(error instanceof DecoderLifecycleFailure);
      assert.equal(error.stage, stage);
      assert.equal(error.primaryMessage, `${stage} boom`);
      assert.deepEqual(error.cleanupFailures, []);
      return true;
    });
    assert.equal(target.current(), false);
    assert.deepEqual(target.calls.slice(-3), ['detach', 'stop', 'release']);
  });
}

test('decoder lifecycle preserves the setup failure and every cleanup failure', async () => {
  const target = harness('prepare', ['stop', 'release']);
  await assert.rejects(DecoderLifecycle.initialize(target.operations, target.ownership), (error) => {
    assert.ok(error instanceof DecoderLifecycleFailure);
    assert.equal(error.primaryMessage, 'prepare boom');
    assert.deepEqual(error.cleanupFailures, ['stop: stop boom', 'release: release boom']);
    assert.match(error.message, /prepare boom; cleanup stop: stop boom; release: release boom/);
    return true;
  });
  assert.deepEqual(target.calls.slice(-3), ['detach', 'stop', 'release']);
});

test('superseded setup never detaches or cleans the replacement owner', async () => {
  const calls = [];
  let current = true;
  const operations = {
    configure: async () => { calls.push('configure'); current = false; },
    setOutputSurface: async () => { calls.push('set_output_surface'); },
    prepare: async () => { calls.push('prepare'); }, start: async () => { calls.push('start'); },
    stop: async () => { calls.push('stop'); }, release: async () => { calls.push('release'); }
  };
  const ownership = { isCurrent: () => current, claimForCleanup: () => { calls.push('claim'); return false; } };
  await assert.rejects(DecoderLifecycle.initialize(operations, ownership), (error) => {
    assert.ok(error instanceof DecoderLifecycleFailure); assert.equal(error.stage, 'ownership'); return true;
  });
  assert.deepEqual(calls, ['configure', 'claim']);
});
