import test from 'node:test';
import assert from 'node:assert/strict';
import { TransportCloseOwner } from '../.test-dist/transport/TransportCloseOwner.js';

class CloseHarness {
  owner = new TransportCloseOwner();
  active = undefined;
  closeCount = new Map();
  detachCount = new Map();
  notifications = [];

  connect() {
    const replacement = this.owner.replace();
    if (replacement.superseded !== undefined) this.terminate(replacement.superseded);
    this.active = replacement.lease;
    return replacement.lease;
  }

  terminate(lease, reason = undefined, socketAlreadyClosed = false) {
    const claim = this.owner.claim(lease, reason, socketAlreadyClosed);
    if (!claim.detach) return claim;
    this.detachCount.set(lease.id, (this.detachCount.get(lease.id) ?? 0) + 1);
    if (claim.closeSocket) this.closeCount.set(lease.id, (this.closeCount.get(lease.id) ?? 0) + 1);
    if (claim.notification !== undefined) this.notifications.push(claim.notification);
    this.owner.finish(lease);
    return claim;
  }
}

test('connect supersede gives the old socket one silent close owner', () => {
  const harness = new CloseHarness();
  const first = harness.connect();
  const second = harness.connect();
  harness.terminate(first, 'stale_error');
  harness.terminate(first, 'transport_closed', true);
  assert.equal(harness.closeCount.get(first.id), 1);
  assert.equal(harness.detachCount.get(first.id), 1);
  assert.deepEqual(harness.notifications, []);
  assert.equal(harness.owner.isCurrent(first), false);
  assert.equal(harness.owner.isCurrent(second), true);
});

test('a third connect and controller close cancel pending superseded leases', () => {
  const owner = new TransportCloseOwner();
  const first = owner.replace().lease;
  const secondReplacement = owner.replace();
  assert.equal(secondReplacement.superseded.id, first.id);
  assert.equal(owner.claim(first, undefined, false).closeSocket, true);
  owner.finish(first);

  const thirdReplacement = owner.replace();
  assert.equal(thirdReplacement.superseded.id, secondReplacement.lease.id);
  assert.equal(owner.claim(secondReplacement.lease, undefined, true).detach, true);
  owner.finish(secondReplacement.lease);
  assert.equal(owner.isCurrent(thirdReplacement.lease), true);

  assert.equal(owner.claim(thirdReplacement.lease, undefined, true).detach, true);
  owner.finish(thirdReplacement.lease);
  assert.equal(owner.isCurrent(thirdReplacement.lease), false);
  assert.equal(owner.claim(thirdReplacement.lease, 'late_error').detach, false);
});

test('controller close racing socket close never double-closes or notifies', () => {
  const controllerWins = new CloseHarness();
  const first = controllerWins.connect();
  controllerWins.terminate(first);
  controllerWins.terminate(first, 'transport_closed', true);
  assert.equal(controllerWins.closeCount.get(first.id), 1);
  assert.deepEqual(controllerWins.notifications, []);

  const socketWins = new CloseHarness();
  const second = socketWins.connect();
  socketWins.terminate(second, 'transport_closed', true);
  socketWins.terminate(second);
  assert.equal(socketWins.closeCount.get(second.id) ?? 0, 0);
  assert.deepEqual(socketWins.notifications, ['transport_closed']);
});

test('error and upgrade timeout races have deterministic first-cause ownership', () => {
  for (const [firstReason, secondReason] of [
    ['socket_error', 'protocol_upgrade_timeout'],
    ['protocol_upgrade_timeout', 'socket_error']
  ]) {
    const harness = new CloseHarness();
    const lease = harness.connect();
    harness.terminate(lease, firstReason);
    harness.terminate(lease, secondReason);
    harness.terminate(lease, 'transport_closed', true);
    assert.equal(harness.closeCount.get(lease.id), 1);
    assert.equal(harness.detachCount.get(lease.id), 1);
    assert.deepEqual(harness.notifications, [firstReason]);
  }
});

test('parse failure owns detach, close and the only disconnect notification', () => {
  const harness = new CloseHarness();
  const lease = harness.connect();
  harness.terminate(lease, 'Unknown protocol channel 9');
  harness.terminate(lease, 'protocol_upgrade_timeout');
  harness.terminate(lease, 'transport_closed', true);
  assert.equal(harness.closeCount.get(lease.id), 1);
  assert.equal(harness.detachCount.get(lease.id), 1);
  assert.deepEqual(harness.notifications, ['Unknown protocol channel 9']);
});
