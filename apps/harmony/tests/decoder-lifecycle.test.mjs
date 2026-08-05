import test from 'node:test';
import assert from 'node:assert/strict';
import { DecoderCandidateLease, DecoderLifecycle, DecoderLifecycleFailure,
  DecoderTransitionOwner } from '../.test-dist/media/DecoderLifecycle.js';

const stages = ['configure', 'set_output_surface', 'prepare', 'start'];

const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((resolveValue, rejectValue) => { resolve = resolveValue; reject = rejectValue; });
  return { promise, resolve, reject };
};

const waitFor = async (predicate) => {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (predicate()) return;
    await Promise.resolve();
  }
  assert.fail('deferred lifecycle stage was not reached');
};

const failureHarness = (failureStage, cleanupFailures = []) => {
  const calls = [];
  const operation = (name) => async () => {
    calls.push(name);
    if (name === failureStage || cleanupFailures.includes(name)) throw new Error(`${name} boom`);
  };
  return {
    calls,
    lifecycle: new DecoderLifecycle({
      configure: operation('configure'), setOutputSurface: operation('set_output_surface'),
      prepare: operation('prepare'), start: operation('start'), stop: operation('stop'), release: operation('release')
    })
  };
};

for (const stage of stages) {
  test(`decoder lifecycle cleans a registered candidate when ${stage} fails`, async () => {
    const target = failureHarness(stage);
    await assert.rejects(target.lifecycle.initialize(), (error) => {
      assert.ok(error instanceof DecoderLifecycleFailure);
      assert.equal(error.stage, stage);
      assert.equal(error.primaryMessage, `${stage} boom`);
      assert.deepEqual(error.cleanupFailures, []);
      return true;
    });
    assert.deepEqual(target.calls.slice(-2), ['stop', 'release']);
  });
}

test('decoder lifecycle preserves the setup failure and every cleanup failure', async () => {
  const target = failureHarness('prepare', ['stop', 'release']);
  await assert.rejects(target.lifecycle.initialize(), (error) => {
    assert.ok(error instanceof DecoderLifecycleFailure);
    assert.equal(error.primaryMessage, 'prepare boom');
    assert.deepEqual(error.cleanupFailures, ['stop: stop boom', 'release: release boom']);
    assert.match(error.message, /prepare boom; cleanup stop: stop boom; release: release boom/);
    return true;
  });
  assert.deepEqual(target.calls.slice(-2), ['stop', 'release']);
});

const cancellationHarness = (pendingStage) => {
  const gate = deferred();
  const calls = [];
  let operationInFlight = false;
  const operation = (name) => async () => {
    calls.push(name);
    if (name !== pendingStage) return;
    operationInFlight = true;
    try { await gate.promise; }
    finally { operationInFlight = false; }
  };
  const cleanup = (name) => async () => {
    assert.equal(operationInFlight, false, `${name} raced ${pendingStage}`);
    calls.push(name);
  };
  const lifecycle = new DecoderLifecycle({
    configure: operation('configure'), setOutputSurface: operation('set_output_surface'),
    prepare: operation('prepare'), start: operation('start'), stop: cleanup('stop'), release: cleanup('release')
  });
  const candidate = { name: 'old', lifecycle };
  const owner = new DecoderTransitionOwner(async (detached) => {
    const failures = await detached.lifecycle.cancelAndCleanup();
    if (failures.length > 0) throw new Error(failures.join('; '));
  });
  owner.install(candidate);
  return {
    gate,
    calls,
    candidate,
    lifecycle,
    owner
  };
};

for (const takeover of ['configure supersede', 'release']) {
  for (const stage of stages) {
    test(`${takeover} waits for the ${stage} await window and cleans the candidate once`, async () => {
      const target = cancellationHarness(stage);
      const initialization = target.lifecycle.initialize().catch((error) => {
        target.owner.clearIfCurrent(target.candidate);
        throw error;
      });
      await waitFor(() => target.calls.includes(stage));

      const handoff = target.owner.detachAndCleanup();
      assert.equal(handoff.detached, true);
      assert.strictEqual(target.owner.detachAndCleanup().completion, handoff.completion);
      assert.equal(target.calls.includes('stop'), false);
      assert.equal(target.calls.includes('release'), false);

      target.gate.resolve();
      await handoff.completion;
      const replacement = { name: 'replacement' };
      if (takeover === 'configure supersede') target.owner.install(replacement);
      await assert.rejects(initialization, (error) => {
        assert.ok(error instanceof DecoderLifecycleFailure);
        assert.equal(error.stage, 'ownership');
        return true;
      });

      const stageIndex = stages.indexOf(stage);
      for (const laterStage of stages.slice(stageIndex + 1)) assert.equal(target.calls.includes(laterStage), false);
      assert.equal(target.calls.filter((call) => call === 'release').length, 1);
      assert.equal(target.calls.filter((call) => call === 'stop').length, stage === 'start' ? 1 : 0);
      if (stage === 'start') assert.deepEqual(target.calls.slice(-2), ['stop', 'release']);
      assert.strictEqual(target.owner.current(), takeover === 'configure supersede' ? replacement : undefined);
    });
  }
}

for (const stage of stages) {
  test(`cancellation racing a rejecting ${stage} still performs one stop before release`, async () => {
    const target = cancellationHarness(stage);
    const initialization = target.lifecycle.initialize();
    await waitFor(() => target.calls.includes(stage));
    const initializationFailure = assert.rejects(initialization, (error) => {
      assert.ok(error instanceof DecoderLifecycleFailure);
      assert.equal(error.stage, stage);
      assert.equal(error.primaryMessage, `${stage} uncertain`);
      return true;
    });
    const cleanup = target.owner.detachAndCleanup().completion;
    target.gate.reject(new Error(`${stage} uncertain`));

    await cleanup;
    await initializationFailure;
    assert.deepEqual(target.calls.slice(-2), ['stop', 'release']);
    assert.equal(target.calls.filter((call) => call === 'stop').length, 1);
    assert.equal(target.calls.filter((call) => call === 'release').length, 1);
  });
}

test('an old continuation cannot clear a replacement candidate after cleanup handoff', async () => {
  const target = cancellationHarness('start');
  const replacement = { name: 'replacement' };
  const initialization = target.lifecycle.initialize().catch((error) => {
    target.owner.clearIfCurrent(target.candidate);
    throw error;
  });
  await waitFor(() => target.calls.includes('start'));

  const cleanup = target.owner.detachAndCleanup().completion;
  target.gate.resolve();
  await cleanup;
  target.owner.install(replacement);
  await assert.rejects(initialization, /Decoder configuration superseded/);

  assert.strictEqual(target.owner.current(), replacement);
  assert.equal(target.calls.filter((call) => call === 'stop').length, 1);
  assert.equal(target.calls.filter((call) => call === 'release').length, 1);
});

test('a third configure or release cannot bypass a detached candidate cleanup', async () => {
  const target = cancellationHarness('prepare');
  const initialization = target.lifecycle.initialize().catch((error) => {
    target.owner.clearIfCurrent(target.candidate);
    throw error;
  });
  await waitFor(() => target.calls.includes('prepare'));

  const secondConfigure = target.owner.detachAndCleanup();
  const thirdRelease = target.owner.detachAndCleanup();
  assert.strictEqual(thirdRelease.completion, secondConfigure.completion);
  assert.throws(() => target.owner.install({ name: 'too-early' }), /prior cleanup completed/);
  assert.equal(target.calls.includes('release'), false);

  target.gate.resolve();
  await thirdRelease.completion;
  assert.equal(target.calls.filter((call) => call === 'release').length, 1);
  target.owner.install({ name: 'after-cleanup' });
  await assert.rejects(initialization, /Decoder configuration superseded/);
  assert.equal(target.owner.current().name, 'after-cleanup');
});

const creationHarness = (releaseFailure = false) => {
  const gate = deferred();
  const calls = [];
  let creationInFlight = false;
  const resource = { name: 'native-decoder' };
  const lease = new DecoderCandidateLease(async () => {
    calls.push('create');
    creationInFlight = true;
    try { await gate.promise; }
    finally { creationInFlight = false; }
    return resource;
  }, async (candidate) => {
    assert.strictEqual(candidate, resource);
    assert.equal(creationInFlight, false, 'release raced native create');
    calls.push('release-uninitialized');
    if (releaseFailure) throw new Error('uninitialized release failed');
  });
  const candidate = { name: 'creating', lease };
  const owner = new DecoderTransitionOwner(async (detached) => detached.lease.cancelAndCleanup());
  owner.install(candidate);
  const configure = async () => {
    await lease.start();
    if (!lease.canContinue()) {
      await lease.cancelAndCleanup();
      throw new Error('Decoder creation superseded');
    }
    calls.push('setup');
  };
  return { gate, calls, candidate, configure, lease, owner };
};

for (const takeover of ['configure supersede', 'release']) {
  test(`${takeover} waits for native decoder creation before one uninitialized release`, async () => {
    const target = creationHarness();
    const configuration = target.configure();
    await waitFor(() => target.calls.includes('create'));
    const configurationFailure = assert.rejects(configuration, /Decoder creation superseded/);

    const handoff = target.owner.detachAndCleanup();
    assert.strictEqual(target.owner.detachAndCleanup().completion, handoff.completion);
    assert.deepEqual(target.calls, ['create']);
    target.gate.resolve();

    await handoff.completion;
    await configurationFailure;
    assert.deepEqual(target.calls, ['create', 'release-uninitialized']);
    assert.equal(target.owner.current(), undefined);
  });
}

test('A-B-C create handoff blocks a third caller until native creation cleanup settles', async () => {
  const target = creationHarness();
  const configuration = target.configure();
  await waitFor(() => target.calls.includes('create'));
  const configurationFailure = assert.rejects(configuration, /Decoder creation superseded/);

  const secondConfigure = target.owner.detachAndCleanup();
  const thirdRelease = target.owner.detachAndCleanup();
  assert.strictEqual(thirdRelease.completion, secondConfigure.completion);
  assert.throws(() => target.owner.install({ name: 'too-early' }), /prior cleanup completed/);
  assert.deepEqual(target.calls, ['create']);

  target.gate.resolve();
  await thirdRelease.completion;
  await configurationFailure;
  const replacementLease = new DecoderCandidateLease(async () => {
    target.calls.push('create-replacement');
    return { name: 'replacement-native' };
  }, async () => { target.calls.push('release-replacement'); });
  target.owner.install({ name: 'replacement', lease: replacementLease });
  await replacementLease.start();
  assert.deepEqual(target.calls, ['create', 'release-uninitialized', 'create-replacement']);
});

test('native creation failure rejects both configure and every cleanup waiter', async () => {
  const target = creationHarness();
  const configuration = target.configure();
  await waitFor(() => target.calls.includes('create'));
  const configurationFailure = assert.rejects(configuration, /native create failed/);
  const cleanupFailure = assert.rejects(target.owner.detachAndCleanup().completion, /native create failed/);

  target.gate.reject(new Error('native create failed'));
  await Promise.all([configurationFailure, cleanupFailure]);
  assert.deepEqual(target.calls, ['create']);
  assert.equal(target.owner.current(), undefined);
});

test('uninitialized release failure is visible to superseded configure and cleanup waiter', async () => {
  const target = creationHarness(true);
  const configuration = target.configure();
  await waitFor(() => target.calls.includes('create'));
  const configurationFailure = assert.rejects(configuration, /uninitialized release failed/);
  const cleanupFailure = assert.rejects(target.owner.detachAndCleanup().completion, /uninitialized release failed/);

  target.gate.resolve();
  await Promise.all([configurationFailure, cleanupFailure]);
  assert.deepEqual(target.calls, ['create', 'release-uninitialized']);
});
