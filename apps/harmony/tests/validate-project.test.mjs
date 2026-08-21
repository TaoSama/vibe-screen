import test from 'node:test';
import assert from 'node:assert/strict';
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { validateProject } from '../scripts/validate-project.mjs';

const harmonyRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repositoryRoot = resolve(harmonyRoot, '../..');

function projectFixture(t) {
  const temporaryRoot = mkdtempSync(resolve(tmpdir(), 'vibe-screen-harmony-validator-'));
  const fixtureRepository = resolve(temporaryRoot, 'repository');
  const fixtureHarmony = resolve(fixtureRepository, 'apps/harmony');
  mkdirSync(resolve(fixtureRepository, 'apps'), { recursive: true });
  cpSync(harmonyRoot, fixtureHarmony, {
    recursive: true,
    filter: (source) => !['node_modules', '.test-dist', 'dist', 'build'].includes(source.split('/').at(-1))
  });
  cpSync(resolve(repositoryRoot, 'LICENSE'), resolve(fixtureRepository, 'LICENSE'));
  cpSync(resolve(repositoryRoot, 'THIRD_PARTY.md'), resolve(fixtureRepository, 'THIRD_PARTY.md'));
  t.after(() => rmSync(temporaryRoot, { recursive: true, force: true }));
  return { fixtureHarmony, fixtureRepository };
}

const validateFixture = (fixture) => validateProject(fixture.fixtureHarmony, fixture.fixtureRepository);
const overwrite = (fixture, relative, content) => writeFileSync(resolve(fixture.fixtureHarmony, relative), content);

test('semantic validator accepts the checked-in Harmony project', () => {
  assert.deepEqual(validateProject(harmonyRoot, repositoryRoot), []);
});

test('semantic validator rejects malformed JSON5 even when expected tokens remain', (t) => {
  const fixture = projectFixture(t);
  overwrite(fixture, 'AppScope/app.json5', "broken { app: { versionName: '0.1.0', icon: '$media:app_icon' }");
  assert(validateFixture(fixture).some((failure) => failure.includes('AppScope/app.json5: invalid JSON5')));
});

test('semantic validator rejects extra permissions', (t) => {
  const fixture = projectFixture(t);
  const path = resolve(fixture.fixtureHarmony, 'entry/src/main/module.json5');
  const source = readFileSync(path, 'utf8').replace(
    "{ name: 'ohos.permission.INTERNET' }",
    "{ name: 'ohos.permission.INTERNET' }, { name: 'ohos.permission.CAMERA' }"
  );
  writeFileSync(path, source);
  assert(validateFixture(fixture).some((failure) => failure.includes('permissions must be exactly')));
});

test('semantic validator rejects comment-only Hvigor and Makefile tokens', (t) => {
  const fixture = projectFixture(t);
  overwrite(fixture, 'hvigorfile.ts', "// import { appTasks } from '@ohos/hvigor-ohos-plugin';\n// export default { system: appTasks };\n");
  overwrite(fixture, 'Makefile', '.PHONY: release\n# ohpm assembleHap signed.hap\nrelease:\n\t@true\n');
  const failures = validateFixture(fixture);
  assert(failures.some((failure) => failure.includes('must import and export appTasks')));
  assert(failures.some((failure) => failure.includes('exact release assembleHap command')));
});

test('semantic validator rejects broken resource and pages references', (t) => {
  const fixture = projectFixture(t);
  const modulePath = resolve(fixture.fixtureHarmony, 'entry/src/main/module.json5');
  writeFileSync(modulePath, readFileSync(modulePath, 'utf8').replace('$string:module_desc', '$string:missing_desc'));
  overwrite(fixture, 'entry/src/main/resources/base/profile/main_pages.json', '{ "src": ["pages/Missing"] }\n');
  const failures = validateFixture(fixture);
  assert(failures.some((failure) => failure.includes('missing string resource missing_desc')));
  assert(failures.some((failure) => failure.includes('src must contain only pages/Index')));
});

test('semantic validator rejects package version drift', (t) => {
  const fixture = projectFixture(t);
  const packagePath = resolve(fixture.fixtureHarmony, 'package.json');
  writeFileSync(packagePath, readFileSync(packagePath, 'utf8').replace('"version": "0.1.0"', '"version": "0.2.0"'));
  assert(validateFixture(fixture).some((failure) => failure.includes('package versions must both be 0.1.0')));
});

test('semantic validator rejects removal of the ArkUI stylus route', (t) => {
  const fixture = projectFixture(t);
  const pagePath = resolve(fixture.fixtureHarmony, 'entry/src/main/ets/pages/Index.ets');
  const source = readFileSync(pagePath, 'utf8');
  const modified = source.replace('sessionRuntime.sendStylus({', 'sessionRuntime.sendTouch({');
  assert.notEqual(modified, source);
  writeFileSync(pagePath, modified);
  assert(validateFixture(fixture).some((failure) =>
    failure.includes('Index.handleTouch() must call sessionRuntime.sendStylus()')));
});

test('semantic validator rejects stylus pressure read from TouchObject', (t) => {
  const fixture = projectFixture(t);
  const pagePath = resolve(fixture.fixtureHarmony, 'entry/src/main/ets/pages/Index.ets');
  const source = readFileSync(pagePath, 'utf8');
  const modified = source.replace('pressure: event.pressure', 'pressure: touch.pressure');
  assert.notEqual(modified, source);
  writeFileSync(pagePath, modified);
  assert(validateFixture(fixture).some((failure) =>
    failure.includes('must source stylus pressure from TouchEvent event.pressure')));
});

test('semantic validator rejects dropping ordinary TouchEvent pressure', (t) => {
  const fixture = projectFixture(t);
  const pagePath = resolve(fixture.fixtureHarmony, 'entry/src/main/ets/pages/Index.ets');
  const source = readFileSync(pagePath, 'utf8');
  const modified = source.replace(
    'this.viewportWidth, this.viewportHeight, this.rotation, event.pressure);',
    'this.viewportWidth, this.viewportHeight, this.rotation, 0);');
  assert.notEqual(modified, source);
  writeFileSync(pagePath, modified);
  assert(validateFixture(fixture).some((failure) =>
    failure.includes('must preserve TouchEvent event.pressure for ordinary touch input')));
});

test('semantic validator rejects closing an explicit disconnect before active input release', (t) => {
  const fixture = projectFixture(t);
  const controllerPath = resolve(fixture.fixtureHarmony,
    'entry/src/main/ets/platform/HarmonySessionController.ets');
  const source = readFileSync(controllerPath, 'utf8');
  const disconnectStart = source.indexOf('  async disconnect(): Promise<void> {');
  const disconnectEnd = source.indexOf('\n  setSurface(', disconnectStart);
  assert(disconnectStart >= 0 && disconnectEnd > disconnectStart);
  const disconnect = source.slice(disconnectStart, disconnectEnd);
  const release = '    const releaseFailures: CleanupFailure[] = await this.releaseActiveInputs();\n' +
    '    if (owner !== this.operationGeneration) return;\n' +
    '    this.session?.close(); this.closeWriter();';
  const modifiedDisconnect = disconnect.replace(release,
    '    this.session?.close(); this.closeWriter();\n' +
    '    const releaseFailures: CleanupFailure[] = await this.releaseActiveInputs();\n' +
    '    if (owner !== this.operationGeneration) return;');
  assert.notEqual(modifiedDisconnect, disconnect);
  const modified = source.slice(0, disconnectStart) + modifiedDisconnect + source.slice(disconnectEnd);
  writeFileSync(controllerPath, modified);
  assert(validateFixture(fixture).some((failure) =>
    failure.includes('disconnect() must release active inputs before closing the writer')));
});

test('semantic validator rejects taking a resume snapshot before active input release', (t) => {
  const fixture = projectFixture(t);
  const controllerPath = resolve(fixture.fixtureHarmony,
    'entry/src/main/ets/platform/HarmonySessionController.ets');
  const source = readFileSync(controllerPath, 'utf8');
  const release = '    const releaseFailures: CleanupFailure[] = await this.releaseActiveInputs();\n' +
    '    if (owner !== this.operationGeneration) return;\n' +
    '    const nextMessageId: bigint | undefined = this.controlWriter?.nextMessageIdValue();';
  const modified = source.replace(release,
    '    const nextMessageId: bigint | undefined = this.controlWriter?.nextMessageIdValue();\n' +
    '    const releaseFailures: CleanupFailure[] = await this.releaseActiveInputs();\n' +
    '    if (owner !== this.operationGeneration) return;');
  assert.notEqual(modified, source);
  writeFileSync(controllerPath, modified);
  assert(validateFixture(fixture).some((failure) =>
    failure.includes('onBackground() must release active inputs before taking the resume snapshot')));
});

for (const [receiver, methodName] of [
  ['writer', 'beginRelease'],
  ['writer', 'awaitReleaseDrain'],
  ['active', 'completeStylusRelease'],
  ['active', 'completeControllerRelease']
]) {
  test(`semantic validator rejects removal of ${receiver}.${methodName}() from active input release`, (t) => {
    const fixture = projectFixture(t);
    const controllerPath = resolve(fixture.fixtureHarmony,
      'entry/src/main/ets/platform/HarmonySessionController.ets');
    const source = readFileSync(controllerPath, 'utf8');
    const modified = source.replace(`${receiver}.${methodName}()`, 'void 0');
    assert.notEqual(modified, source);
    writeFileSync(controllerPath, modified);
    assert(validateFixture(fixture).some((failure) =>
      failure.includes(`releaseActiveInputs() must call ${receiver}.${methodName}()`)));
  });
}

test('semantic validator rejects unconfirmed active input release sends', (t) => {
  const fixture = projectFixture(t);
  const controllerPath = resolve(fixture.fixtureHarmony,
    'entry/src/main/ets/platform/HarmonySessionController.ets');
  const source = readFileSync(controllerPath, 'utf8');
  const modified = source.replace(
    'if (action.afterSend !== undefined) active.confirmSent(action.afterSend);',
    'void action.afterSend;');
  assert.notEqual(modified, source);
  writeFileSync(controllerPath, modified);
  assert(validateFixture(fixture).some((failure) =>
    failure.includes('releaseActiveInputs() must call active.confirmSent()')));
});

test('semantic validator rejects dropping controller release from active input cleanup', (t) => {
  const fixture = projectFixture(t);
  const controllerPath = resolve(fixture.fixtureHarmony,
    'entry/src/main/ets/platform/HarmonySessionController.ets');
  const source = readFileSync(controllerPath, 'utf8');
  const modified = source.replace('...active.releaseControllerInputs(() => this.nextInputId++)', '');
  assert.notEqual(modified, source);
  writeFileSync(controllerPath, modified);
  assert(validateFixture(fixture).some((failure) =>
    failure.includes('releaseActiveInputs() must call active.releaseControllerInputs()')));
});

test('semantic validator rejects dropping pending controller send cancellation', (t) => {
  const fixture = projectFixture(t);
  const controllerPath = resolve(fixture.fixtureHarmony,
    'entry/src/main/ets/platform/HarmonySessionController.ets');
  const source = readFileSync(controllerPath, 'utf8');
  const modified = source.replaceAll('active.cancelControllerSend(action.afterSend.event)', 'void action.afterSend.event');
  assert.notEqual(modified, source);
  writeFileSync(controllerPath, modified);
  assert(validateFixture(fixture).some((failure) =>
    failure.includes('sendAction() must call active.cancelControllerSend()')));
});

test('semantic validator rejects a missing controller capability guard', (t) => {
  const fixture = projectFixture(t);
  const controllerPath = resolve(fixture.fixtureHarmony,
    'entry/src/main/ets/platform/HarmonySessionController.ets');
  const source = readFileSync(controllerPath, 'utf8').replace('!active.canSend(Capability.CONTROLLER)', 'false');
  assert.notEqual(source, readFileSync(controllerPath, 'utf8'));
  writeFileSync(controllerPath, source);
  assert(validateFixture(fixture).some((failure) =>
    failure.includes('sendController() must use a dominating CONTROLLER early-return guard')));
});

test('semantic validator rejects a disconnected production capability gate', (t) => {
  const fixture = projectFixture(t);
  const controllerPath = resolve(fixture.fixtureHarmony,
    'entry/src/main/ets/platform/HarmonySessionController.ets');
  const source = readFileSync(controllerPath, 'utf8')
    .replace('!active.canSend(Capability.TOUCH)', 'false')
    .concat('\nfunction deadCapabilityGate(active: ProductSession): boolean { return active.canSend(Capability.TOUCH); }\n');
  writeFileSync(controllerPath, source);
  assert(validateFixture(fixture).some((failure) =>
    failure.includes('sendTouch() must use a dominating TOUCH early-return guard')));
});

test('semantic validator rejects a capability call hidden in method-local short-circuit dead code', (t) => {
  const fixture = projectFixture(t);
  const controllerPath = resolve(fixture.fixtureHarmony,
    'entry/src/main/ets/platform/HarmonySessionController.ets');
  const source = readFileSync(controllerPath, 'utf8').replace(
    '!active.canSend(Capability.TOUCH)', 'false && !active.canSend(Capability.TOUCH)');
  writeFileSync(controllerPath, source);
  assert(validateFixture(fixture).some((failure) =>
    failure.includes('sendTouch() must use a dominating TOUCH early-return guard')));
});

test('semantic validator rejects a capability guard neutralized by a constant-false right operand', (t) => {
  const fixture = projectFixture(t);
  const controllerPath = resolve(fixture.fixtureHarmony,
    'entry/src/main/ets/platform/HarmonySessionController.ets');
  const source = readFileSync(controllerPath, 'utf8').replace(
    '!active.canSend(Capability.TOUCH)', '(!active.canSend(Capability.TOUCH) && false)');
  writeFileSync(controllerPath, source);
  assert(validateFixture(fixture).some((failure) =>
    failure.includes('sendTouch() must use a dominating TOUCH early-return guard')));
});

test('semantic validator rejects a capability guard placed after the protected send', (t) => {
  const fixture = projectFixture(t);
  const controllerPath = resolve(fixture.fixtureHarmony,
    'entry/src/main/ets/platform/HarmonySessionController.ets');
  const source = readFileSync(controllerPath, 'utf8')
    .replace('!active.canSend(Capability.TOUCH)', 'false')
    .replace('    this.applyActions([active.touch(event)], this.operationGeneration);',
      '    this.applyActions([active.touch(event)], this.operationGeneration);\n' +
      '    if (!active.canSend(Capability.TOUCH)) return;');
  writeFileSync(controllerPath, source);
  assert(validateFixture(fixture).some((failure) =>
    failure.includes('sendTouch() must use a dominating TOUCH early-return guard')));
});

test('semantic validator rejects capability guard and send after an always-true return', (t) => {
  const fixture = projectFixture(t);
  const controllerPath = resolve(fixture.fixtureHarmony,
    'entry/src/main/ets/platform/HarmonySessionController.ets');
  const active = '    const active: ProductSession | undefined = this.session;';
  const source = readFileSync(controllerPath, 'utf8').replace(active, `    if (true) return;\n${active}`);
  writeFileSync(controllerPath, source);
  assert(validateFixture(fixture).some((failure) =>
    failure.includes('sendTouch() must use a dominating TOUCH early-return guard')));
});

test('semantic validator rejects TypeScript and ArkTS shell parse diagnostics', (t) => {
  const fixture = projectFixture(t);
  const controllerPath = resolve(fixture.fixtureHarmony,
    'entry/src/main/ets/platform/HarmonySessionController.ets');
  writeFileSync(controllerPath, `${readFileSync(controllerPath, 'utf8')}\nfunction brokenController( {\n`);
  const pagePath = resolve(fixture.fixtureHarmony, 'entry/src/main/ets/pages/Index.ets');
  writeFileSync(pagePath, readFileSync(pagePath, 'utf8').replace('  @Builder', '  private brokenPage(: void {}\n\n  @Builder'));
  const failures = validateFixture(fixture);
  assert(failures.some((failure) => failure.includes('HarmonySessionController.ets') && failure.includes('portable parse error')));
  assert(failures.some((failure) => failure.includes('Index.ets') && failure.includes('portable parse error')));
});

test('semantic validator rejects removal of atomic Asset Store update wiring', (t) => {
  const fixture = projectFixture(t);
  const storePath = resolve(fixture.fixtureHarmony, 'entry/src/main/ets/platform/PairingStore.ets');
  writeFileSync(storePath, readFileSync(storePath, 'utf8').replaceAll('asset.update', 'asset.add'));
  assert(validateFixture(fixture).some((failure) => failure.includes('PairingStore.upsert() must call asset.update()')));
});

test('semantic validator rejects removal of the authenticated record open path', (t) => {
  const fixture = projectFixture(t);
  const recordPath = resolve(fixture.fixtureHarmony,
    'entry/src/main/ets/core/security/ChannelRecordSecurity.ts');
  const source = readFileSync(recordPath, 'utf8');
  const modified = source.replace('this.options.crypto.openAes256Gcm', 'this.options.crypto.sha256');
  assert.notEqual(modified, source);
  writeFileSync(recordPath, modified);
  assert(validateFixture(fixture).some((failure) =>
    failure.includes('ChannelRecordSession.open() must call this.options.crypto.openAes256Gcm()')));
});

test('semantic validator rejects removal of the bounded control backlog', (t) => {
  const fixture = projectFixture(t);
  const writerPath = resolve(fixture.fixtureHarmony,
    'entry/src/main/ets/core/protocol/OutboundControlWriter.ts');
  writeFileSync(writerPath, readFileSync(writerPath, 'utf8').replaceAll('MAX_PENDING_CONTROLS', 'UNBOUNDED_CONTROLS'));
  assert(validateFixture(fixture).some((failure) =>
    failure.includes('enqueue() must use a reachable MAX_PENDING_CONTROLS fail-closed guard')));
});

test('semantic validator rejects a queue limit hidden in method-local constant-false control flow', (t) => {
  const fixture = projectFixture(t);
  const writerPath = resolve(fixture.fixtureHarmony,
    'entry/src/main/ets/core/protocol/OutboundControlWriter.ts');
  const source = readFileSync(writerPath, 'utf8').replace(
    'if (this.queuedCount() >= MAX_PENDING_CONTROLS)',
    'if (false && this.queuedCount() >= MAX_PENDING_CONTROLS)');
  writeFileSync(writerPath, source);
  assert(validateFixture(fixture).some((failure) =>
    failure.includes('enqueue() must use a reachable MAX_PENDING_CONTROLS fail-closed guard')));
});

test('semantic validator rejects a queue guard neutralized inside a wider condition', (t) => {
  const fixture = projectFixture(t);
  const writerPath = resolve(fixture.fixtureHarmony,
    'entry/src/main/ets/core/protocol/OutboundControlWriter.ts');
  const source = readFileSync(writerPath, 'utf8').replace(
    'this.queuedCount() >= MAX_PENDING_CONTROLS',
    '((this.queuedCount() >= MAX_PENDING_CONTROLS && false) || this.failure !== undefined)');
  writeFileSync(writerPath, source);
  assert(validateFixture(fixture).some((failure) =>
    failure.includes('enqueue() must use a reachable MAX_PENDING_CONTROLS fail-closed guard')));
});

test('semantic validator rejects queue guard after an always-true throw', (t) => {
  const fixture = projectFixture(t);
  const writerPath = resolve(fixture.fixtureHarmony,
    'entry/src/main/ets/core/protocol/OutboundControlWriter.ts');
  const guard = '    if (this.queuedCount() >= MAX_PENDING_CONTROLS) {';
  const source = readFileSync(writerPath, 'utf8').replace(
    guard, `    if (true) throw new Error('terminal');\n${guard}`);
  writeFileSync(writerPath, source);
  assert(validateFixture(fixture).some((failure) =>
    failure.includes('enqueue() must use a reachable MAX_PENDING_CONTROLS fail-closed guard')));
});
